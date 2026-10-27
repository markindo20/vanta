"""Package manager (client-side) for Vanta."""
import os, sys, shutil, subprocess, urllib.request, tarfile, io, re, stat, hashlib

VENDOR = 'vendor'
MANIFEST = 'vanta.toml'
LOCK = 'vanta.lock'

def _rmtree(path):
    """Remove a directory tree deterministically, including read-only VCS files."""
    if not os.path.exists(path):
        return

    def _on_error(func, filepath, exc_info):
        try:
            os.chmod(filepath, stat.S_IWRITE)
        except OSError:
            pass
        try:
            func(filepath)
        except OSError:
            pass

    shutil.rmtree(path, onerror=_on_error)



def read_toml(path):
    result = {}
    current = None
    try:
        with open(path, encoding='utf-8') as f:
            lines = f.readlines()
    except OSError:
        return result
    import re as _re
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        m = _re.match(r'^\[(.+?)\]\s*$', line)
        if m:
            name = m.group(1).strip()
            inner = result
            for part in name.split('.'):
                inner = inner.setdefault(part, {})
            current = inner
            continue
        if '=' in line:
            key, _, val = line.partition('=')
            key = key.strip()
            val = val.strip()
            if val.startswith('{') and val.endswith('}'):
                inner = val[1:-1].strip()
                d = {}
                for piece in inner.split(','):
                    piece = piece.strip()
                    if not piece or '=' not in piece:
                        continue
                    k, _, v = piece.partition('=')
                    d[k.strip()] = _parse_scalar(v.strip())
                (current if current is not None else result)[key] = d
            else:
                (current if current is not None else result)[key] = _parse_scalar(val)
    return result


def _parse_scalar(val):
    val = val.strip()
    if val.startswith('"') and val.endswith('"'):
        return val[1:-1]
    if val.startswith("'") and val.endswith("'"):
        return val[1:-1]
    if val.lower() in ('true', 'false'):
        return val.lower() == 'true'
    try:
        return int(val)
    except ValueError:
        pass
    try:
        return float(val)
    except ValueError:
        pass
    if val.startswith('[') and val.endswith(']'):
        inner = val[1:-1].strip()
        out = []
        for piece in inner.split(','):
            piece = piece.strip()
            if not piece:
                continue
            out.append(_parse_scalar(piece))
        return out
    return val


def write_toml(path, data):
    lines = []
    pkg = data.get('package', {}) or {}
    if pkg:
        lines.append('[package]')
        for k, v in pkg.items():
            lines.append(f'{k} = {_emit_scalar(v)}')
        lines.append('')
    deps = data.get('dependencies', {}) or data.get('deps', {}) or {}
    if deps:
        lines.append('[dependencies]')
        for k, v in deps.items():
            if isinstance(v, dict):
                inner = ', '.join(f'{kk} = {_emit_scalar(vv)}' for kk, vv in v.items())
                lines.append(f'{k} = {{ {inner} }}')
            else:
                lines.append(f'{k} = {_emit_scalar(v)}')
        lines.append('')
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))


def _emit_scalar(v):
    if isinstance(v, bool):
        return 'true' if v else 'false'
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, list):
        return '[' + ', '.join(_emit_scalar(x) for x in v) + ']'
    if isinstance(v, dict):
        inner = ', '.join(f'{k} = {_emit_scalar(vv)}' for k, vv in v.items())
        return '{ ' + inner + ' }'
    return '"' + str(v).replace('"', '\\"') + '"'


def read_lock(path=LOCK):
    if not os.path.exists(path):
        return {'packages': {}}
    data = read_toml(path)
    if 'packages' not in data:
        data['packages'] = {}
    return data


def write_lock(lock, path=LOCK):
    pkgmap = lock.get('packages', {}) or {}
    lines = []
    for name, info in pkgmap.items():
        lines.append(f'[packages.{name}]')
        for k, v in (info or {}).items():
            lines.append(f'{k} = {_emit_scalar(v)}')
        lines.append('')
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))


def _read_manifest(path=MANIFEST):
    if not os.path.exists(path):
        return {}
    return read_toml(path)


def _is_url(s):
    return s.startswith('http://') or s.startswith('https://') or s.startswith('git@') or s.startswith('git:')


def _safe_target(dest, name):
    """Resolve *name* under *dest*, refusing anything that escapes it.

    Package names and archive members are untrusted input: a name such as
    ``../evil`` or an absolute path must never be able to write outside the
    vendor directory or the extraction root.
    """
    base = os.path.realpath(os.path.abspath(dest))
    target = os.path.realpath(os.path.abspath(os.path.join(dest, name)))
    try:
        inside = os.path.commonpath([base, target]) == base
    except ValueError:
        inside = False
    if not inside or target == base:
        raise RuntimeError(f'unsafe package path {name!r}')
    return target


def _safe_extract_tar(tf, target):
    """Extract *tf* into *target* without following hostile entries.

    ``tarfile.extractall`` trusts member names and link targets.  Python 3.12
    added ``filter='data'``, but Vanta supports Python 3.10+, so validate each
    member ourselves.  Only regular files and directories are accepted;
    absolute paths, drive-qualified paths, ``..`` components, symlinks, and
    hardlinks are rejected before anything is written.
    """
    base = os.path.realpath(os.path.abspath(target))
    os.makedirs(base, exist_ok=True)
    for member in tf.getmembers():
        raw = member.name.replace('\\', '/')
        if (raw.startswith('/') or raw.startswith('//')
                or re.match(r'^[A-Za-z]:', raw)):
            raise RuntimeError(
                f'unsafe archive member {member.name!r}: absolute path')
        parts = [part for part in raw.split('/') if part not in ('', '.')]
        if '..' in parts:
            raise RuntimeError(
                f'unsafe archive member {member.name!r}: parent traversal')
        if member.issym() or member.islnk():
            raise RuntimeError(
                f'unsafe archive member {member.name!r}: links are not allowed')
        if not (member.isfile() or member.isdir()):
            raise RuntimeError(
                f'unsafe archive member {member.name!r}: unsupported entry type')
        if not parts:
            if member.isdir():
                continue
            raise RuntimeError(
                f'unsafe archive member {member.name!r}: empty path')
        destination = os.path.join(base, *parts)
        if not _safe_target(base, os.path.join(*parts)):
            raise RuntimeError(
                f'unsafe archive member {member.name!r}: escapes extraction root')
        if member.isdir():
            os.makedirs(destination, exist_ok=True)
            continue
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        source = tf.extractfile(member)
        if source is None:
            raise RuntimeError(
                f'unsafe archive member {member.name!r}: missing contents')
        with source, open(destination, 'wb') as out:
            shutil.copyfileobj(source, out)


def _split_git_ref(source, ref=None):
    """Split an optional git ref from a source and fragment."""
    src = source[len('git+'):] if source.startswith('git+') else source
    if ref is not None:
        return src.split('#', 1)[0], ref.strip()
    if '#' in src:
        base, _, fragment = src.partition('#')
        for part in fragment.split('&'):
            if part.startswith('tag=') or part.startswith('ref='):
                return base, part.split('=', 1)[1].strip()
    return src, ''


def fetch_source(source, dest, name, ref=None):
    os.makedirs(dest, exist_ok=True)
    target = _safe_target(dest, name)
    if os.path.exists(target):
        _rmtree(target)
    if os.path.exists(source) and os.path.isdir(source):
        shutil.copytree(source, target)
        return ''
    src, requested_ref = _split_git_ref(source, ref)
    if (src.startswith('https://') or src.startswith('http://') or
            src.startswith('git@') or src.startswith('git:') or
            source.startswith('git+')):
        try:
            subprocess.run(['git', 'clone', src, target], check=True,
                           capture_output=True, text=True)
        except Exception as exc:
            raise RuntimeError(f'could not clone {src}: {exc}')
        if requested_ref:
            # A normal clone exposes branch refs as remotes/origin/<ref>, so
            # try several common spellings before declaring the ref invalid.
            candidates = [requested_ref, 'origin/' + requested_ref,
                          'refs/remotes/origin/' + requested_ref]
            checked_out = False
            for candidate in candidates:
                try:
                    subprocess.run(['git', '-C', target, 'checkout',
                                    '--detach', candidate], check=True,
                                   capture_output=True, text=True)
                    checked_out = True
                    break
                except Exception:
                    continue
            if not checked_out:
                _rmtree(target)
                raise RuntimeError(
                    f'could not checkout {requested_ref!r}')
                _rmtree(target)
                raise RuntimeError(f'could not checkout {requested_ref!r}: {exc}')
        try:
            out = subprocess.run(['git', '-C', target, 'rev-parse', 'HEAD'],
                                 capture_output=True, text=True).stdout.strip()
            return out
        except Exception:
            return ''
    raise RuntimeError(f'source not found or not a URL/path: {source}')



def _manifest_dep_source(spec):
    if isinstance(spec, str):
        return spec
    if isinstance(spec, dict):
        if 'registry' in spec:
            version = spec.get('registry')
            return 'registry:' + str(version or 'latest')
        if 'git' in spec:
            source = str(spec.get('git') or '')
            ref = str(spec.get('tag') or spec.get('ref') or '').strip()
            if ref:
                kind = 'tag' if spec.get('tag') else 'ref'
                return source + '#' + kind + '=' + ref
            return source
        if 'path' in spec:
            return spec['path']
        if 'src' in spec:
            return spec['src']
    return str(spec)


def _registry_base():
    return os.environ.get('VANTA_REGISTRY', '').strip()


def fetch_from_registry(name, version_spec, dest, target_name=None):
    target_name = target_name or name
    base = _registry_base()
    if not base:
        raise RuntimeError('VANTA_REGISTRY not set; cannot resolve bare package name')
    if base.startswith('http://') or base.startswith('https://'):
        try:
            url = base.rstrip('/') + '/' + name + '/' + (version_spec or 'latest') + '/source.tar.gz'
            target = _safe_target(dest, target_name)
            data = urllib.request.urlopen(url).read()
            tf = tarfile.open(fileobj=__import__('io').BytesIO(data), mode='r:gz')
            _rmtree(target)
            os.makedirs(target)
            _safe_extract_tar(tf, target)
            return ''
        except Exception as exc:
            if isinstance(exc, RuntimeError) and 'unsafe ' in str(exc):
                raise
            raise RuntimeError(f'registry fetch failed for {name}: {exc}')
    cand = _safe_target(base, os.path.join(name, version_spec or ''))
    if os.path.isdir(cand):
        return fetch_source(cand, dest, target_name)
    reg_tmp = os.path.join(dest, '.regbase_tmp')
    try:
        fetch_source(base, dest, '.regbase_tmp')
        cand2 = _safe_target(reg_tmp, os.path.join(name, version_spec or ''))
        if os.path.isdir(cand2):
            r = fetch_source(cand2, dest, target_name)
            _rmtree(reg_tmp)
            return r
        _rmtree(reg_tmp)
    except Exception:
        pass
    raise RuntimeError(f'registry base does not contain {name}/{version_spec}')


def _read_transitive_deps(dest_path):
    p = os.path.join(dest_path, MANIFEST)
    if not os.path.exists(p):
        return {}
    return read_toml(p).get('dependencies', {}) or {}


def _installed_git_commit(path):
    """Return HEAD for a downloaded git checkout, or an empty string."""
    git_dir = os.path.join(path, '.git')
    if not os.path.lexists(git_dir):
        return ''
    try:
        result = subprocess.run(
            ['git', '-C', path, 'rev-parse', 'HEAD'],
            check=True, capture_output=True, text=True)
    except Exception:
        return ''
    return result.stdout.strip()


def _tree_digest(root):
    """Return a deterministic SHA-256 of a dependency directory tree.

    The digest covers sorted file paths and their byte contents. A digest can
    therefore detect partial installations, manual edits, and mismatched
    vendored trees without assuming anything about the dependency's source
    backend.
    """
    root = os.path.abspath(root)
    if not os.path.isdir(root):
        return ''
    root_real = os.path.realpath(root)
    hasher = hashlib.sha256()
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = sorted(dirs)
        for name in sorted(files):
            full = os.path.join(dirpath, name)
            if os.path.islink(full):
                raise RuntimeError(f'unsafe archive member {name!r}: symlink')
            if os.path.realpath(full) != os.path.realpath(full):
                pass
            real = os.path.realpath(full)
            if os.path.commonpath([root_real, real]) != root_real:
                raise RuntimeError(f'unsafe dependency path {name!r}')
            rel = os.path.relpath(full, root).replace(os.sep, '/')
            digest_file(full, hasher, rel)
    return hasher.hexdigest()


def digest_file(full, hasher, rel):
    hasher.update(f'file:{rel}\n'.encode('utf-8'))
    with open(full, 'rb') as f:
        data = f.read()
    hasher.update(str(len(data)).encode('ascii'))
    hasher.update(b':')
    hasher.update(data)


def _installed_git_commit(path):
    """Return HEAD for a downloaded git checkout, or an empty string."""
    git_dir = os.path.join(path, '.git')
    if not os.path.lexists(git_dir):
        return ''
    try:
        result = subprocess.run(
            ['git', '-C', path, 'rev-parse', 'HEAD'],
            check=True, capture_output=True, text=True)
    except Exception:
        return ''
    return result.stdout.strip()

def _sources_compatible(dep_name, spec, locked_source):
    source = str(locked_source or '').strip()
    if not source:
        return True
    if isinstance(spec, str):
        return source == spec.strip()
    if not isinstance(spec, dict):
        return source == str(spec).strip()

    if 'git' in spec:
        expected_base = str(spec.get('git') or '').strip()
        locked_base = source.partition('#')[0].strip()
        if locked_base != expected_base:
            return False
        expected_ref = str(spec.get('tag') or spec.get('ref') or '').strip()
        fragment = source.partition('#')[2].strip() if '#' in source else ''
        if fragment.startswith('tag=') or fragment.startswith('ref='):
            fragment = fragment.split('=', 1)[1].strip()
        if expected_ref and fragment and expected_ref != fragment:
            return False
        return True

    if 'registry' in spec:
        expected_version = str(spec.get('registry') or '').strip()
        locked_portion = source[len('registry:'):].strip() if source.startswith('registry:') else source
        locked_version = locked_portion.split('@', 1)[-1].strip()
        return (not expected_version or locked_version == expected_version or
                (expected_version == 'latest' and locked_version in ('', 'latest')))

    expected = str(spec.get('path') if 'path' in spec else spec.get('src')
                   if 'src' in spec else '')
    return source == expected.strip()


# ---------- Commands ----------

def cmd_pm_init(args):
    if os.path.exists(MANIFEST):
        print(f'{MANIFEST} already exists')
        return 0
    name = getattr(args, 'name', None) or os.path.basename(os.getcwd()) or 'project'
    data = {'package': {'name': name, 'version': '0.1.0'}, 'dependencies': {}}
    write_toml(MANIFEST, data)
    print(f'created {MANIFEST}')
    return 0


def cmd_pm_add(args):
    sources = list(getattr(args, 'sources', None) or [])
    name_opt = getattr(args, 'name', None)
    dest = getattr(args, 'dest', None) or VENDOR
    if not sources:
        sys.stderr.write('error: pm add needs at least one source/name\n')
        return 1
    manifest = _read_manifest()
    manifest.setdefault('package', {'name': os.path.basename(os.getcwd()) or 'project', 'version': '0.1.0'})
    manifest.setdefault('dependencies', {})
    lock = read_lock()
    lock.setdefault('packages', {})
    rc_total = 0
    for src in sources:
        dep_name = name_opt or os.path.basename(src.rstrip('/\\') or '') or 'dep'
        # registry name form: name@version
        is_registry_name = (not os.path.exists(src) and not _is_url(src) and not src.startswith('git+') and not src.startswith('registry:'))
        if is_registry_name:
            ver = ''
            if '@' in src:
                dep_name, _, ver = src.partition('@')
            try:
                commit = fetch_from_registry(dep_name, ver, dest, dep_name)
                manifest['dependencies'][dep_name] = {'registry': (ver or 'latest')}
                src = 'registry:' + dep_name + (('@' + ver) if ver else '')
            except RuntimeError as exc:
                sys.stderr.write(f'error: {exc}\n')
                rc_total = 1
                continue
        else:
            tag = ''
            base_src = src
            if '#' in src:
                base_src, _, frag = src.partition('#')
                for part in frag.split('&'):
                    if part.startswith('tag=') or part.startswith('ref='):
                        tag = part.split('=', 1)[1]
            try:
                commit = fetch_source(base_src, dest, dep_name, tag)
            except RuntimeError as exc:
                sys.stderr.write(f'error: {exc}\n')
                rc_total = 1
                continue
            if tag:
                manifest['dependencies'][dep_name] = {'git': base_src, 'tag': tag}
            else:
                manifest['dependencies'][dep_name] = src
        lock['packages'][dep_name] = {
            'source': src, 'path': os.path.join(dest, dep_name),
            'commit': commit,
            'sha256': _tree_digest(os.path.join(dest, dep_name))}
        write_lock(lock)
        dep_manifest = os.path.join(dest, dep_name, MANIFEST)
        if os.path.exists(dep_manifest):
            dep_m = read_toml(dep_manifest)
            for dname, dspec in (dep_m.get('dependencies') or {}).items():
                manifest['dependencies'].setdefault(dname, dspec)
        print(f'added {dep_name} -> {os.path.join(dest, dep_name)}')
    write_toml(MANIFEST, manifest)
    print('manifest ' + MANIFEST)
    return rc_total


def cmd_pm_remove(args):
    names = list(getattr(args, 'names', None) or [])
    if not names:
        names = list(getattr(args, 'sources', None) or [])
    if not names:
        sys.stderr.write('error: pm remove needs a name\n')
        return 1
    manifest = _read_manifest()
    deps = manifest.get('dependencies', {}) or {}
    lock = read_lock()
    lock.setdefault('packages', {})
    rc = 0
    for name in names:
        try:
            target = _safe_target(VENDOR, name)
        except RuntimeError as exc:
            sys.stderr.write(f'error: {exc}\n')
            rc = 1
            continue
        if name in deps:
            del deps[name]
        if name in lock.get('packages', {}):
            del lock['packages'][name]
        if os.path.exists(target):
            _rmtree(target)
        print(f'removed {name}')
    manifest['dependencies'] = deps
    write_toml(MANIFEST, manifest)
    write_lock(lock)
    return rc


def cmd_pm_list(args):
    manifest = _read_manifest()
    deps = manifest.get('dependencies', {}) or {}
    if not deps:
        print('no dependencies')
        return 0
    for name, spec in deps.items():
        print(f'{name}: {spec}')
    return 0


def cmd_pm_install(args):
    manifest = _read_manifest()
    deps = manifest.get('dependencies', {}) or {}
    dest = getattr(args, 'dest', None) or VENDOR
    if not deps:
        print('nothing to install')
        write_lock({'packages': {}})
        return 0
    lock = read_lock()
    lock.setdefault('packages', {})
    failures = 0
    pending = list(deps.items())
    seen = set()
    while pending:
        name, spec = pending.pop(0)
        if name in seen:
            continue
        seen.add(name)
        try:
            target = _safe_target(dest, name)
        except RuntimeError as exc:
            sys.stderr.write(f'error: {exc}\n')
            failures += 1
            continue
        src = _manifest_dep_source(spec)
        ref = ''
        if isinstance(spec, dict):
            ref = str(spec.get('tag') or spec.get('ref') or '')
        locked_entry = lock.get('packages', {}).get(name, {}) or {}
        locked_source = str(locked_entry.get('source') or '').strip()
        locked_commit = str(locked_entry.get('commit') or '').strip()
        locked_digest = str(locked_entry.get('sha256') or '').strip()

        if locked_entry and not _sources_compatible(name, spec, locked_source):
            sys.stderr.write(
                f'source mismatch for {name}: manifest has {src!r}, '
                f'lockfile has {locked_source!r}\n')
            failures += 1
            continue

        # Leave a checked-out tree untouched unless lockfile says a different
        # revision is needed. This makes a clean install reproducible from
        # .vanta.lock instead of only from the mutable manifest source.
        if os.path.exists(target):
            current_commit = _installed_git_commit(target)
            current_digest = _tree_digest(target)
            if (not src.startswith('registry:')
                    and locked_commit
                    and current_commit
                    and current_commit != locked_commit):
                _rmtree(target)
            elif locked_digest and current_digest != locked_digest:
                sys.stderr.write(
                    ('checksum mismatch for %s: installed tree %r != %r\n' % (name, current_digest, locked_digest)))
                failures += 1
                continue
            else:
                print(f'already present: {name}')
                dep_manifest = os.path.join(target, MANIFEST)
                if os.path.exists(dep_manifest):
                    dep_m = read_toml(dep_manifest)
                    for dname, dspec in (dep_m.get('dependencies') or {}).items():
                        manifest.setdefault('dependencies', {}).setdefault(dname, dspec)
                        if dname not in seen:
                            pending.append((dname, dspec))
                continue
        try:
            if src.startswith('registry:'):
                r = fetch_from_registry(name, src[len('registry:'):], dest, name)
                commit = r if not isinstance(r, tuple) else (r[0] if r else '')
            else:
                fetch_ref = locked_commit or ref
                commit = fetch_source(src, dest, name, fetch_ref)
        except RuntimeError as exc:
            sys.stderr.write(f'error: {exc}\n')
            failures += 1
            continue
        lock['packages'][name] = {
            'source': src, 'path': target,
            'commit': commit or locked_commit,
            'sha256': _tree_digest(target) or locked_digest}
        dep_manifest = os.path.join(target, MANIFEST)
        if os.path.exists(dep_manifest):
            dep_m = read_toml(dep_manifest)
            for dname, dspec in (dep_m.get('dependencies') or {}).items():
                manifest.setdefault('dependencies', {}).setdefault(dname, dspec)
                if dname not in seen:
                    pending.append((dname, dspec))
    write_toml(MANIFEST, manifest)
    write_lock(lock)
    print('installed; lockfile ' + LOCK)
    return 1 if failures else 0


def cmd_pm_lock(args):
    manifest = _read_manifest()
    lock = read_lock()
    lock.setdefault('packages', {})
    for name, spec in (manifest.get('dependencies') or {}).items():
        installed_target = os.path.join(VENDOR, name)
        source = _manifest_dep_source(spec)
        entry = lock['packages'].get(name, {}) or {}
        # Existing pins belong to the same manifest source. If the manifest
        # changes, reset all exact-install identity instead of retaining stale
        # commit information.
        if str(entry.get('source') or '').strip() != source:
            entry = {}
        if os.path.isdir(installed_target):
            git_dir = os.path.join(installed_target, '.git')
            if os.path.lexists(git_dir):
                try:
                    entry['commit'] = subprocess.run(
                        ['git', '-C', installed_target, 'rev-parse', 'HEAD'],
                        check=True, capture_output=True, text=True).stdout.strip()
                except Exception:
                    entry['commit'] = entry.get('commit', '')
            entry['sha256'] = _tree_digest(installed_target)
        else:
            entry.setdefault('commit', '')
            entry.setdefault('sha256', '')
        entry['source'] = source
        entry['path'] = installed_target
        lock['packages'][name] = entry
    write_lock(lock)
    print('locked')
    return 0


def cmd_pm_check(args):
    manifest = _read_manifest()
    deps = manifest.get('dependencies', {}) or {}
    lock = read_lock()
    lock.setdefault('packages', {})
    ok = True
    for name, spec in deps.items():
        expected_source = _manifest_dep_source(spec)
        target = os.path.join(VENDOR, name)
        if not os.path.isdir(target):
            sys.stderr.write(f'missing: {name}\n')
            ok = False
            continue
        entry = lock['packages'].get(name, {}) or {}
        if entry:
            locked_source = str(entry.get('source') or '').strip()
            if locked_source and not _sources_compatible(name, spec, locked_source):
                sys.stderr.write(
                    f'source mismatch for {name}: manifest {expected_source!r}, '
                    f'lockfile {locked_source!r}\n')
                ok = False
                continue
            locked_commit = str(entry.get('commit') or '').strip()
            locked_digest = str(entry.get('sha256') or '').strip()
            current_commit = ''
            git_dir = os.path.join(target, '.git')
            if os.path.lexists(git_dir):
                try:
                    current_commit = subprocess.run(
                        ['git', '-C', target, 'rev-parse', 'HEAD'],
                        check=True, capture_output=True, text=True
                    ).stdout.strip()
                except Exception:
                    current_commit = ''
            if locked_commit and current_commit and current_commit != locked_commit:
                sys.stderr.write(
                    f'commit mismatch for {name}: installed {current_commit!r}, '
                    f'lockfile {locked_commit!r}\n')
                ok = False
                continue
            if locked_digest:
                current_digest = _tree_digest(target)
                if current_digest != locked_digest:
                    sys.stderr.write(
                        f'checksum mismatch for {name}: installed tree '
                        f'{current_digest!r} != {locked_digest!r}\n')
                    ok = False
                    continue
    if ok:
        print('all dependencies present')
    return 0 if ok else 1


def cmd_pm(args):
    sub = getattr(args, 'pm_command', None)
    dispatch = {
        'init': cmd_pm_init,
        'add': cmd_pm_add,
        'install': cmd_pm_install,
        'remove': cmd_pm_remove,
        'list': cmd_pm_list,
        'lock': cmd_pm_lock,
        'check': cmd_pm_check,
    }
    fn = dispatch.get(sub)
    if fn is None:
        sys.stderr.write('usage: vanta pm (init|add|install|remove|list|lock|check)\n')
        return 1
    return fn(args)
