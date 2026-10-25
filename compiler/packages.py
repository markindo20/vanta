"""Package manager (client-side) for Vanta."""
import os, sys, shutil, subprocess, urllib.request, tarfile, io, re

VENDOR = 'vendor'
MANIFEST = 'vanta.toml'
LOCK = 'vanta.lock'


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


def fetch_source(source, dest, name):
    os.makedirs(dest, exist_ok=True)
    target = os.path.join(dest, name)
    if os.path.exists(target):
        shutil.rmtree(target, ignore_errors=True)
    if os.path.exists(source) and os.path.isdir(source):
        shutil.copytree(source, target)
        return ''
    src = source[len('git+'):] if source.startswith('git+') else source
    if src.startswith('https://') or src.startswith('http://') or src.startswith('git@') or src.startswith('git:'):
        try:
            subprocess.run(['git', 'clone', '--depth', '1', src, target], check=True,
                           capture_output=True, text=True)
        except Exception as exc:
            raise RuntimeError(f'could not clone {src}: {exc}')
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
        if 'git' in spec:
            return spec['git']
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
            target = os.path.join(dest, target_name)
            os.makedirs(target, exist_ok=True)
            data = urllib.request.urlopen(url).read()
            tf = tarfile.open(fileobj=__import__('io').BytesIO(data), mode='r:gz')
            shutil.rmtree(target, ignore_errors=True)
            os.makedirs(target)
            tf.extractall(target)
            return ''
        except Exception as exc:
            raise RuntimeError(f'registry fetch failed for {name}: {exc}')
    cand = os.path.join(base, name, version_spec or '')
    if os.path.isdir(cand):
        return fetch_source(cand, dest, target_name)
    reg_tmp = os.path.join(dest, '.regbase_tmp')
    try:
        fetch_source(base, dest, '.regbase_tmp')
        cand2 = os.path.join(reg_tmp, name, version_spec or '')
        if os.path.isdir(cand2):
            r = fetch_source(cand2, dest, target_name)
            shutil.rmtree(reg_tmp, ignore_errors=True)
            return r
        shutil.rmtree(reg_tmp, ignore_errors=True)
    except Exception:
        pass
    raise RuntimeError(f'registry base does not contain {name}/{version_spec}')


def _read_transitive_deps(dest_path):
    p = os.path.join(dest_path, MANIFEST)
    if not os.path.exists(p):
        return {}
    return read_toml(p).get('dependencies', {}) or {}


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
                commit = fetch_source(src, dest, dep_name)
            except RuntimeError as exc:
                sys.stderr.write(f'error: {exc}\n')
                rc_total = 1
                continue
            if tag:
                manifest['dependencies'][dep_name] = {'git': base_src, 'tag': tag}
            else:
                manifest['dependencies'][dep_name] = src
        lock['packages'][dep_name] = {'source': src, 'path': os.path.join(dest, dep_name), 'commit': commit}
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
    for name in names:
        if name in deps:
            del deps[name]
        if name in lock.get('packages', {}):
            del lock['packages'][name]
        target = os.path.join(VENDOR, name)
        if os.path.exists(target):
            shutil.rmtree(target, ignore_errors=True)
        print(f'removed {name}')
    manifest['dependencies'] = deps
    write_toml(MANIFEST, manifest)
    write_lock(lock)
    return 0


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
    for name, spec in list(deps.items()):
        target = os.path.join(dest, name)
        if os.path.exists(target):
            print(f'already present: {name}')
            continue
        src = _manifest_dep_source(spec)
        try:
            if src.startswith('registry:'):
                r = fetch_from_registry(name, src[len('registry:'):], dest, name)
                commit = r if not isinstance(r, tuple) else (r[0] if r else '')
            else:
                commit = fetch_source(src, dest, name)
        except RuntimeError as exc:
            sys.stderr.write(f'error: {exc}\n')
            failures += 1
            continue
        lock['packages'][name] = {'source': src, 'path': target, 'commit': commit}
        dep_manifest = os.path.join(target, MANIFEST)
        if os.path.exists(dep_manifest):
            dep_m = read_toml(dep_manifest)
            for dname, dspec in (dep_m.get('dependencies') or {}).items():
                manifest.setdefault('dependencies', {}).setdefault(dname, dspec)
                deps[dname] = dspec
    write_toml(MANIFEST, manifest)
    write_lock(lock)
    print('installed; lockfile ' + LOCK)
    return 1 if failures else 0


def cmd_pm_lock(args):
    manifest = _read_manifest()
    lock = read_lock()
    lock.setdefault('packages', {})
    for name, spec in (manifest.get('dependencies') or {}).items():
        lock['packages'].setdefault(name, {'source': _manifest_dep_source(spec), 'path': os.path.join(VENDOR, name), 'commit': ''})
    write_lock(lock)
    print('locked')
    return 0


def cmd_pm_check(args):
    manifest = _read_manifest()
    ok = True
    for name, spec in (manifest.get('dependencies') or {}).items():
        if not os.path.isdir(os.path.join(VENDOR, name)):
            sys.stderr.write(f'missing: {name}\n')
            ok = False
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
