import io
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import unittest
from contextlib import redirect_stderr, redirect_stdout
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from compiler.packages import (
    MANIFEST, LOCK, VENDOR, _rmtree,
    _read_manifest, read_toml, write_toml,
    read_lock, write_lock,
    _tree_digest, _installed_git_commit,
    cmd_pm, fetch_source,
)


def make_args(**kwargs):
    return SimpleNamespace(**kwargs)


def _git(cwd, *args):
    subprocess.run(['git', '-C', cwd, *args],
                   check=True, capture_output=True, text=True)


class PackageVerificationTests(unittest.TestCase):
    def setUp(self):
        if shutil.which('git') is None:
            self.skipTest('git not available')
        self._old_cwd = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        os.chdir(self._tmp.name)

    def tearDown(self):
        os.chdir(self._old_cwd)
        self._tmp.cleanup()

    def _write(self, path, content):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8', newline='\n') as f:
            f.write(content)

    def _make_git_repo(self, path, commits):
        os.makedirs(path, exist_ok=True)
        _git(path, 'init', '-q', '-b', 'main')
        _git(path, 'config', 'user.email', 'test@example.invalid')
        _git(path, 'config', 'user.name', 'Package Verification Tests')
        for files, message, tag in commits:
            for rel, content in files.items():
                self._write(os.path.join(path, rel), content)
            _git(path, 'add', '-A')
            _git(path, 'commit', '-q', '-m', message)
            if tag:
                _git(path, 'tag', '-f', tag)
        return path

    def _rev_parse(self, repo, ref='HEAD'):
        out = subprocess.run(
            ['git', '-C', repo, 'rev-parse', ref],
            check=True, capture_output=True, text=True)
        return out.stdout.strip()

    def _git_source(self, repo, ref=''):
        source = 'git+' + repo
        if ref:
            source += '#' + ref
        return source

    def _env(self, key, value):
        old = os.environ.get(key)
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
        return old

    def test_git_tag_add_records_selected_commit(self):
        repo = os.path.join(self._tmp.name, 'tagrepo')
        self._make_git_repo(repo, [
            ({'vanta.toml': '[package]\nname = "tagdep"\n',
              'lib.vnt': 'func main() -> void: print_i32(1)\n'}, 'v1', 'v1'),
            ({'vanta.toml': '[package]\nname = "tagdep"\n',
              'lib.vnt': 'func main() -> void: print_i32(2)\n'}, 'v2', 'v2'),
        ])

        commit_v1 = self._rev_parse(repo, 'v1')
        cmd_pm(make_args(pm_command='init', name='project'))
        rc = cmd_pm(make_args(
            pm_command='add', sources=[self._git_source(repo, 'tag=v1')],
            name='tagrepo', dest=None))
        self.assertEqual(rc, 0)

        lock = read_lock()
        self.assertEqual(lock['packages']['tagrepo']['commit'], commit_v1)
        self.assertEqual(
            open(os.path.join(VENDOR, 'tagrepo', 'lib.vnt'), encoding='utf-8').read(),
            'func main() -> void: print_i32(1)\n')

    def test_git_tag_re_resolution_updates_lock_and_files(self):
        repo = os.path.join(self._tmp.name, 'tagrepo')
        self._make_git_repo(repo, [
            ({'vanta.toml': '[package]\nname = "tagdep"\n',
              'lib.vnt': 'func main() -> void: print_i32(1)\n'}, 'v1', 'v1'),
            ({'vanta.toml': '[package]\nname = "tagdep"\n',
              'lib.vnt': 'func main() -> void: print_i32(2)\n'}, 'v2', 'v2'),
        ])

        cmd_pm(make_args(pm_command='init', name='project'))
        rc = cmd_pm(make_args(
            pm_command='add', sources=[self._git_source(repo, 'tag=v1')],
            name='tagrepo', dest=None))
        self.assertEqual(rc, 0)
        old_commit = read_lock()['packages']['tagrepo']['commit']

        # Move the tag to simulate a republished/ref changed backend.
        _git(repo, 'tag', '-f', 'v1', 'v2')
        new_commit = self._rev_parse(repo, 'v1')

        # With the recorded commit left intact, install must replay that exact
        # revision even after the mutable tag moves.
        if os.path.isdir(VENDOR):
            _rmtree(VENDOR)

        rc = cmd_pm(make_args(pm_command='install', dest=None))
        self.assertEqual(rc, 0)
        self.assertEqual(read_lock()['packages']['tagrepo']['commit'],
                         old_commit)
        self.assertEqual(
            open(os.path.join(VENDOR, 'tagrepo', 'lib.vnt'), encoding='utf-8').read(),
            'func main() -> void: print_i32(1)\n')

        # Clearing the lock's commit lets the manifest tag resolve anew.
        locked = read_lock()['packages']['tagrepo']
        locked['commit'] = ''
        lock = read_lock()
        lock['packages']['tagrepo'] = locked
        write_lock(lock)

        if os.path.isdir(VENDOR):
            _rmtree(VENDOR)

        rc = cmd_pm(make_args(pm_command='install', dest=None))
        self.assertEqual(rc, 0)
        self.assertEqual(read_lock()['packages']['tagrepo']['commit'],
                         new_commit)
        self.assertEqual(
            open(os.path.join(VENDOR, 'tagrepo', 'lib.vnt'), encoding='utf-8').read(),
            'func main() -> void: print_i32(2)\n')

    def test_git_branch_re_resolution_reports_backend_failure_for_unknown_ref(self):
        repo = os.path.join(self._tmp.name, 'branchedrepo')
        self._make_git_repo(repo, [
            ({'vanta.toml': '[package]\nname = "branchdep"\n',
              'lib.vnt': 'func main() -> void: print_i32(1)\n'}, 'initial', ''),
        ])

        cmd_pm(make_args(pm_command='init', name='project'))
        rc = cmd_pm(make_args(
            pm_command='add',
            sources=[self._git_source(repo, 'ref=does-not-exist')],
            name='tagrepo', dest=None))
        self.assertEqual(rc, 1)
        self.assertFalse(os.path.exists(os.path.join(VENDOR, 'branchedrepo')))
        self.assertNotIn('branchedrepo', _read_manifest().get('dependencies', {}))

    def test_git_transitive_install_and_nested_manifest_resolution(self):
        child = os.path.join(self._tmp.name, 'childrepo')
        parent = os.path.join(self._tmp.name, 'parentrepo')
        self._make_git_repo(child, [
            ({'vanta.toml': '[package]\nname = "childdep"\nversion = "1.0.0"\n',
              'lib.vnt': 'func main() -> void: print_i32(2)\n'}, 'child v1', 'v1'),
        ])
        self._make_git_repo(parent, [
            ({'vanta.toml': ('[package]\nname = "parentdep"\nversion = "1.0.0"\n'
                             '[dependencies]\n'
                             'childdep = { git = "%s", tag = "v1" }\n'
                             % self._git_source(child, '')),
              'lib.vnt': 'func main() -> void: print_i32(1)\n'}, 'parent v1', 'v1'),
        ])

        cmd_pm(make_args(pm_command='init', name='project'))
        manifest = _read_manifest()
        manifest['dependencies'] = {
            'parentdep': {'git': self._git_source(parent, ''),
                          'tag': 'v1'},
        }
        write_toml(MANIFEST, manifest)

        rc = cmd_pm(make_args(pm_command='install', dest=None))
        self.assertEqual(rc, 0)
        self.assertTrue(os.path.exists(os.path.join(VENDOR, 'parentdep', 'lib.vnt')))
        self.assertTrue(os.path.exists(os.path.join(VENDOR, 'childdep', 'lib.vnt')))
        self.assertIn('childdep', _read_manifest()['dependencies'])
        self.assertEqual(
            read_lock()['packages']['parentdep']['commit'],
            self._rev_parse(parent, 'v1'))
        self.assertEqual(
            read_lock()['packages']['childdep']['commit'],
            self._rev_parse(child, 'v1'))

    def test_backend_failure_returns_deterministic_error_and_no_partial_install(self):
        cmd_pm(make_args(pm_command='init', name='project'))
        manifest = _read_manifest()
        manifest['dependencies'] = {'ghost': './does-not-exist'}
        write_toml(MANIFEST, manifest)

        rc = cmd_pm(make_args(pm_command='install', dest=None))
        self.assertEqual(rc, 1)
        self.assertFalse(os.path.exists(os.path.join(VENDOR, 'ghost')))

    def test_registry_backend_failure_is_reported(self):
        cmd_pm(make_args(pm_command='init', name='project'))
        old = self._env('VANTA_REGISTRY', None)
        try:
            rc = cmd_pm(make_args(
                pm_command='add', sources=['missingdep@1.0.0'], names=[],
                dest=None))
        finally:
            self._env('VANTA_REGISTRY', old)
        self.assertEqual(rc, 1)
        self.assertNotIn('missingdep', _read_manifest().get('dependencies', {}))

    def test_install_missing_vendor_dependency_returns_failure(self):
        cmd_pm(make_args(pm_command='init', name='project'))
        manifest = _read_manifest()
        manifest['dependencies'] = {'ghost': './ghost'}
        write_toml(MANIFEST, manifest)

        rc = cmd_pm(make_args(pm_command='install', dest=None))
        self.assertEqual(rc, 1)

    def test_corrupt_registry_backend_is_reported_and_clean(self):
        cmd_pm(make_args(pm_command='init', name='project'))
        root = os.path.join(self._tmp.name, 'bad-registry')
        pkg_dir = os.path.join(root, 'baddep', '1.0.0')
        os.makedirs(pkg_dir, exist_ok=True)
        with open(os.path.join(pkg_dir, 'source.tar.gz'), 'wb') as f:
            f.write(b'not a valid gzip archive')

        handler = SimpleHTTPRequestHandler
        import functools
        directory_handler = functools.partial(handler, directory=root)
        server = ThreadingHTTPServer(('127.0.0.1', 0), directory_handler)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        old = self._env('VANTA_REGISTRY', 'http://127.0.0.1:%d' % port)
        try:
            rc = cmd_pm(make_args(
                pm_command='add', sources=['baddep@1.0.0'], names=[],
                dest=None))
        finally:
            self._env('VANTA_REGISTRY', old)
            server.shutdown()
            server.shutdown()
            server.server_close()
        self.assertEqual(rc, 1)
        self.assertFalse(os.path.exists(os.path.join(VENDOR, 'baddep')))



    def test_pm_install_uses_recorded_lock_commit(self):
        repo = os.path.join(self._tmp.name, 'lockedrepo')
        self._make_git_repo(repo, [
            ({'vanta.toml': '[package]\nname = "lockdep"\n',
              'lib.vnt': 'func main() -> void: print_i32(1)\n'}, 'commit 1', 'v1'),
            ({'vanta.toml': '[package]\nname = "lockdep"\n',
              'lib.vnt': 'func main() -> void: print_i32(2)\n'}, 'commit 2', 'v2'),
        ])

        commit_one = self._rev_parse(repo, 'v1')

        cmd_pm(make_args(pm_command='init', name='project'))
        rc = cmd_pm(make_args(
            pm_command='add', sources=[self._git_source(repo, 'tag=v1')],
            name='lockdep'))
        self.assertEqual(rc, 0)
        self.assertEqual(read_lock()['packages']['lockdep']['commit'],
                         commit_one)

        # Republish the movable tag while leaving the recorded commit in place.
        _git(repo, 'tag', '-f', 'v1', 'v2')

        if os.path.isdir(VENDOR):
            _rmtree(VENDOR)

        rc = cmd_pm(make_args(pm_command='install', dest=None))
        self.assertEqual(rc, 0)
        self.assertEqual(read_lock()['packages']['lockdep']['commit'],
                         commit_one)
        self.assertEqual(
            open(os.path.join(VENDOR, 'lockdep', 'lib.vnt'),
                 encoding='utf-8').read(),
            'func main() -> void: print_i32(1)\n')

        locked_entry = read_lock()['packages']['lockdep']
        locked_entry['commit'] = ''

        lock = read_lock()
        lock['packages']['lockdep'] = locked_entry
        write_lock(lock)

        if os.path.isdir(VENDOR):
            _rmtree(VENDOR)

        rc = cmd_pm(make_args(pm_command='install', dest=None))
        self.assertEqual(rc, 0)
        self.assertEqual(
            open(os.path.join(VENDOR, 'lockdep', 'lib.vnt'),
                 encoding='utf-8').read(),
            'func main() -> void: print_i32(2)\n')

    def test_package_check_reports_source_drift_and_checksum_mismatch(self):
        repository = os.path.join(self._tmp.name, 'driftrepo')
        self._make_git_repo(repository, [
            ({'vanta.toml': '[package]\nname = "driftpkg"\n',
              'lib.vnt': 'func answer() -> i32:\n    return 1\n'}, 'first', 'v1'),
            ({'vanta.toml': '[package]\nname = "driftpkg"\n',
              'lib.vnt': 'func answer() -> i32:\n    return 2\n'}, 'second', 'v2'),
        ])
        first_commit = self._rev_parse(repository, 'v1')

        cmd_pm(make_args(pm_command='init', name='driftcheck'))
        src = self._git_source(repository, 'tag=v1')
        self.assertEqual(cmd_pm(make_args(pm_command='add', sources=[src],
                                         name='driftpkg')), 0)

        baseline = _read_manifest()
        baseline_lock = read_lock()

        cleared = read_lock()['packages']['driftpkg']
        cleared['commit'] = ''
        cleared_lock = read_lock()
        cleared_lock['packages']['driftpkg'] = cleared
        write_lock(cleared_lock)
        self.assertEqual(cmd_pm(make_args(pm_command='check')), 0)
        write_lock(baseline_lock)

        drifted_manifest = _read_manifest()
        drifted_manifest['dependencies'] = {'driftpkg': {'git': 'https://example.invalid/driftpkg.git',
                                                         'tag': 'v1'}}
        write_toml(MANIFEST, drifted_manifest)
        self.assertEqual(cmd_pm(make_args(pm_command='check')), 1)
        write_toml(MANIFEST, baseline)

        manifest_only = _read_manifest()
        manifest_only['dependencies'] = {'driftpkg': {'git': repository, 'tag': 'v2'}}
        write_toml(MANIFEST, manifest_only)
        self.assertEqual(cmd_pm(make_args(pm_command='check')), 1)
        write_toml(MANIFEST, baseline)

        lock = baseline_lock
        lock['packages']['driftpkg']['commit'] = 'deadbeef'
        write_lock(lock)
        self.assertEqual(cmd_pm(make_args(pm_command='check')), 1)
        write_lock(baseline_lock)

        extra = os.path.join(VENDOR, 'driftpkg', 'extra.txt')
        with open(extra, 'w', encoding='utf-8') as f:
            f.write('tampered')
        self.assertEqual(cmd_pm(make_args(pm_command='check')), 1)
        self.assertEqual(cmd_pm(make_args(pm_command='install', dest=None)), 1)
        write_lock(baseline_lock)

    def test_package_lock_missing_commit_and_checksum(self):
        self._make_git_repo(os.path.join(self._tmp.name, 'minimalrepo'), [
            ({'vanta.toml': '[package]\nname = "minimalpkg"\n',
              'lib.vnt': 'func answer() -> i32:\n    return 1\n'},
             'only commit', 'v1'),
        ])
        repository = os.path.join(self._tmp.name, 'minimalrepo')
        cmd_pm(make_args(pm_command='init', name='project'))
        src = self._git_source(repository, 'tag=v1')
        self.assertEqual(cmd_pm(make_args(pm_command='add', sources=[src],
                                         name='minimalpkg')), 0)

        legacy = read_lock()
        legacy['packages']['minimalpkg'] = {
            'source': legacy['packages']['minimalpkg'].get(
                'source', 'git+' + repository + '#tag=v1'),
            'path': legacy['packages']['minimalpkg'].get(
                'path', os.path.join(VENDOR, 'minimalpkg')),
            'commit': '',
            'sha256': '',
        }
        write_lock(legacy)
        self.assertEqual(cmd_pm(make_args(pm_command='check')), 0)
        if os.path.isdir(VENDOR):
            _rmtree(VENDOR)
        self.assertEqual(cmd_pm(make_args(pm_command='install', dest=None)), 0)
        self.assertEqual(
            open(os.path.join(VENDOR, 'minimalpkg', 'lib.vnt'),
                 encoding='utf-8').read(),
            'func answer() -> i32:\n    return 1\n')

    def _run_pm(self, **kwargs):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = cmd_pm(make_args(**kwargs))
        return rc, out.getvalue(), err.getvalue()

    def test_locked_branch_commit_replays_moved_branch(self):
        repo = os.path.join(self._tmp.name, 'branchrepo')
        self._make_git_repo(repo, [
            ({'vanta.toml': '[package]\nname = "branchdep"\n',
              'lib.vnt': 'func answer() -> i32:\n    return 1\n'},
             'branch commit', ''),
        ])
        locked_commit = self._rev_parse(repo, 'main')

        cmd_pm(make_args(pm_command='init', name='project'))
        rc = cmd_pm(make_args(pm_command='add',
                              sources=[self._git_source(repo, 'ref=main')],
                              name='branchdep', dest=None))
        self.assertEqual(rc, 0)
        self.assertEqual(read_lock()['packages']['branchdep']['commit'],
                         locked_commit)

        # Move the mutable branch forward while the lock keeps the old head.
        with open(os.path.join(repo, 'lib.vnt'), 'a', encoding='utf-8') as f:
            f.write('func second() -> i32:\n    return 2\n')
        _git(repo, 'add', '-A')
        _git(repo, 'commit', '-q', '-m', 'branch commit 2')
        self.assertNotEqual(self._rev_parse(repo, 'main'), locked_commit)

        if os.path.isdir(VENDOR):
            _rmtree(VENDOR)
        rc = cmd_pm(make_args(pm_command='install', dest=None))
        self.assertEqual(rc, 0)
        self.assertEqual(read_lock()['packages']['branchdep']['commit'],
                         locked_commit)
        installed = os.path.join(VENDOR, 'branchdep', 'lib.vnt')
        self.assertEqual(open(installed, encoding='utf-8').read(),
                         'func answer() -> i32:\n    return 1\n')

        # The moved branch does not re-resolve without an explicit pm add.
        rc, out, err = self._run_pm(pm_command='check')
        self.assertEqual(rc, 0)
        self.assertEqual(out, 'all dependencies present\n')

    def test_install_reports_exact_drift_and_checksum_text(self):
        repo = os.path.join(self._tmp.name, 'driftrepo2')
        self._make_git_repo(repo, [
            ({'vanta.toml': '[package]\nname = "drift2pkg"\n',
              'lib.vnt': 'func answer() -> i32:\n    return 1\n'}, 'v1', 'v1'),
            ({'vanta.toml': '[package]\nname = "drift2pkg"\n',
              'lib.vnt': 'func answer() -> i32:\n    return 2\n'}, 'v2', 'v2'),
        ])
        cmd_pm(make_args(pm_command='init', name='project'))
        self.assertEqual(cmd_pm(make_args(
            pm_command='add', sources=[self._git_source(repo, 'tag=v1')],
            name='drift2pkg', dest=None)), 0)
        baseline_lock = read_lock()
        baseline_manifest = _read_manifest()
        locked_source = baseline_lock['packages']['drift2pkg']['source']

        # Manifest tag drift with a healthy vendor present: install refuses
        # with the exact message and leaves the vendor tree untouched.
        drifted = _read_manifest()
        drifted['dependencies'] = {'drift2pkg': {'git': 'git+' + repo,
                                                 'tag': 'v2'}}
        write_toml(MANIFEST, drifted)
        manifest_src = 'git+' + repo + '#tag=v2'
        rc, out, err = self._run_pm(pm_command='install', dest=None)
        self.assertEqual(rc, 1)
        self.assertEqual(
            err,
            f'source mismatch for drift2pkg: manifest has {manifest_src!r}, '
            f'lockfile has {locked_source!r}\n')
        self.assertEqual(out, 'installed; lockfile vanta.lock\n')
        installed = os.path.join(VENDOR, 'drift2pkg', 'lib.vnt')
        self.assertEqual(
            open(installed, encoding='utf-8').read(),
            'func answer() -> i32:\n    return 1\n')
        self.assertEqual(
            read_lock()['packages']['drift2pkg']['source'], locked_source)
        write_toml(MANIFEST, baseline_manifest)

        # Checksum mismatch on a tampered vendor tree is reported with the
        # exact installed/locked digests.
        with open(installed, 'a', encoding='utf-8') as f:
            f.write('func extra() -> void:\n    return\n')
        changed_digest = _tree_digest(os.path.join(VENDOR, 'drift2pkg'))
        locked_digest = baseline_lock['packages']['drift2pkg']['sha256']
        self.assertNotEqual(changed_digest, locked_digest)
        rc, out, err = self._run_pm(pm_command='install', dest=None)
        self.assertEqual(rc, 1)
        self.assertEqual(
            err,
            f'checksum mismatch for drift2pkg: installed tree '
            f'{changed_digest!r} != {locked_digest!r}\n')

        # Restoring the content restores `already present` behavior.
        with open(installed, 'w', encoding='utf-8', newline='\n') as f:
            f.write('func answer() -> i32:\n    return 1\n')
        rc, out, err = self._run_pm(pm_command='install', dest=None)
        self.assertEqual(rc, 0, msg=(out, err))
        self.assertIn('already present: drift2pkg\n', out)

    def test_check_reports_exact_missing_commit_and_checksum_text(self):
        repo = os.path.join(self._tmp.name, 'checkrepo')
        self._make_git_repo(repo, [
            ({'vanta.toml': '[package]\nname = "checkpkg"\n',
              'lib.vnt': 'func answer() -> i32:\n    return 1\n'}, 'v1', 'v1'),
        ])
        cmd_pm(make_args(pm_command='init', name='project'))
        self.assertEqual(cmd_pm(make_args(
            pm_command='add', sources=[self._git_source(repo, 'tag=v1')],
            name='checkpkg', dest=None)), 0)
        baseline_lock = read_lock()

        # Missing vendor tree.
        _rmtree(os.path.join(VENDOR, 'checkpkg'))
        rc, out, err = self._run_pm(pm_command='check')
        self.assertEqual(rc, 1)
        self.assertEqual(err, 'missing: checkpkg\n')
        self.assertEqual(out, '')
        rc = cmd_pm(make_args(pm_command='install', dest=None))
        self.assertEqual(rc, 0)

        # Stale commit in the lock: exact installed/locked revisions.
        current_commit = _installed_git_commit(os.path.join(VENDOR, 'checkpkg'))
        self.assertEqual(current_commit, self._rev_parse(repo, 'v1'))
        lock = read_lock()
        lock['packages']['checkpkg']['commit'] = 'deadbeef'
        write_lock(lock)
        rc, out, err = self._run_pm(pm_command='check')
        self.assertEqual(rc, 1)
        self.assertEqual(
            err,
            f'commit mismatch for checkpkg: installed {current_commit!r}, '
            f"lockfile {'deadbeef'!r}\n")
        write_lock(baseline_lock)

        # Tree tamper: exact digest pair.
        with open(os.path.join(VENDOR, 'checkpkg', 'lib.vnt'), 'a',
                  encoding='utf-8') as f:
            f.write('func extra() -> void:\n    return\n')
        changed_digest = _tree_digest(os.path.join(VENDOR, 'checkpkg'))
        locked_digest = baseline_lock['packages']['checkpkg']['sha256']
        rc, out, err = self._run_pm(pm_command='check')
        self.assertEqual(rc, 1)
        self.assertEqual(
            err,
            f'checksum mismatch for checkpkg: installed tree '
            f'{changed_digest!r} != {locked_digest!r}\n')
        self.assertEqual(out, '')
        write_lock(baseline_lock)

        # Restoring the content returns the healthy exact success text.
        with open(os.path.join(VENDOR, 'checkpkg', 'lib.vnt'), 'w',
                  encoding='utf-8', newline='\n') as f:
            f.write('func answer() -> i32:\n    return 1\n')
        rc, out, err = self._run_pm(pm_command='check')
        self.assertEqual(rc, 0, msg=(out, err))
        self.assertEqual(out, 'all dependencies present\n')
        self.assertEqual(err, '')

    def _make_registry(self, name):
        root = os.path.join(self._tmp.name, 'registry-' + name)
        pkg = os.path.join(root, name, '1.0.0')
        self._write(os.path.join(pkg, 'vanta.toml'),
                    f'[package]\nname = "{name}"\n')
        self._write(os.path.join(pkg, 'lib.vnt'),
                    'func answer() -> i32:\n    return 1\n')
        return root

    def test_registry_dependency_checksum_and_drift_exact_text(self):
        registry = self._make_registry('regdep2')
        cmd_pm(make_args(pm_command='init', name='project'))
        old = self._env('VANTA_REGISTRY', registry)
        try:
            rc, out, err = self._run_pm(pm_command='add',
                                        sources=['regdep2@1.0.0'],
                                        name=None, dest=None)
        finally:
            self._env('VANTA_REGISTRY', old)
        self.assertEqual(rc, 0)
        baseline_lock = read_lock()
        entry = baseline_lock['packages']['regdep2']
        self.assertEqual(entry['source'], 'registry:regdep2@1.0.0')
        self.assertTrue(os.path.exists(
            os.path.join(VENDOR, 'regdep2', 'lib.vnt')))
        locked_digest = entry['sha256']
        self.assertTrue(locked_digest)

        # Tampering is caught by pm check against the registry-backed digests.
        with open(os.path.join(VENDOR, 'regdep2', 'lib.vnt'), 'a',
                  encoding='utf-8') as f:
            f.write('func extra() -> void:\n    return\n')
        changed_digest = _tree_digest(os.path.join(VENDOR, 'regdep2'))
        rc, out, err = self._run_pm(pm_command='check')
        self.assertEqual(rc, 1)
        self.assertEqual(
            err,
            f'checksum mismatch for regdep2: installed tree '
            f'{changed_digest!r} != {locked_digest!r}\n')
        write_lock(baseline_lock)

        # Removing the vendor directory replays the registry source exactly.
        _rmtree(os.path.join(VENDOR, 'regdep2'))
        old = self._env('VANTA_REGISTRY', registry)
        try:
            rc = cmd_pm(make_args(pm_command='install', dest=None))
        finally:
            self._env('VANTA_REGISTRY', old)
        self.assertEqual(rc, 0)
        self.assertEqual(_tree_digest(os.path.join(VENDOR, 'regdep2')),
                         locked_digest)

        # A manifest version bump is drift while the lock stays on 1.0.0.
        manifest = _read_manifest()
        manifest['dependencies'] = {'regdep2': {'registry': '2.0.0'}}
        write_toml(MANIFEST, manifest)
        rc, out, err = self._run_pm(pm_command='install', dest=None)
        self.assertEqual(rc, 1)
        self.assertEqual(
            err,
            "source mismatch for regdep2: manifest has 'registry:2.0.0', "
            "lockfile has 'registry:regdep2@1.0.0'\n")
        # `latest` behaves the same way: the pinned 1.0.0 stays authoritative.
        manifest['dependencies'] = {'regdep2': {'registry': 'latest'}}
        write_toml(MANIFEST, manifest)
        rc, out, err = self._run_pm(pm_command='install', dest=None)
        self.assertEqual(rc, 1)
        self.assertEqual(
            err,
            "source mismatch for regdep2: manifest has 'registry:latest', "
            "lockfile has 'registry:regdep2@1.0.0'\n")

    def test_path_dependency_reproducible_install_and_tamper(self):
        pkg = os.path.join(self._tmp.name, 'pathpkg')
        self._write(os.path.join(pkg, 'vanta.toml'),
                    '[package]\nname = "pathdep2"\n')
        self._write(os.path.join(pkg, 'lib.vnt'),
                    'func answer() -> i32:\n    return 1\n')

        cmd_pm(make_args(pm_command='init', name='project'))
        write_lock({'packages': {}})
        manifest = _read_manifest()
        manifest['dependencies'] = {'pathdep2': {'path': pkg}}
        write_toml(MANIFEST, manifest)

        rc = cmd_pm(make_args(pm_command='install', dest=None))
        self.assertEqual(rc, 0)
        source = read_lock()['packages']['pathdep2']['source']
        self.assertEqual(source, pkg)
        locked_digest = read_lock()['packages']['pathdep2']['sha256']
        self.assertTrue(locked_digest)

        # The vendored copy is not a git checkout for path sources.
        vendor_pkg = os.path.join(VENDOR, 'pathdep2')
        self.assertFalse(os.path.exists(os.path.join(vendor_pkg, '.git')))
        self.assertTrue(_installed_git_commit(vendor_pkg) == '')

        # Reinstall from scratch is byte-identical: same digest.
        _rmtree(VENDOR)
        rc = cmd_pm(make_args(pm_command='install', dest=None))
        self.assertEqual(rc, 0)
        self.assertEqual(read_lock()['packages']['pathdep2']['sha256'],
                         locked_digest)

        # A healthy reinstall second time reports already present.
        rc, out, err = self._run_pm(pm_command='install', dest=None)
        self.assertEqual(rc, 0)
        self.assertIn('already present: pathdep2\n', out)

        # A vendored edit is detected with the exact digest text.
        with open(os.path.join(vendor_pkg, 'extra.txt'), 'w',
                  encoding='utf-8') as f:
            f.write('tampered')
        changed_digest = _tree_digest(vendor_pkg)
        rc, out, err = self._run_pm(pm_command='check')
        self.assertEqual(rc, 1)
        self.assertEqual(
            err,
            f'checksum mismatch for pathdep2: installed tree '
            f'{changed_digest!r} != {locked_digest!r}\n')
        rc, out, err = self._run_pm(pm_command='install', dest=None)
        self.assertEqual(rc, 1)
        self.assertEqual(
            err,
            f'checksum mismatch for pathdep2: installed tree '
            f'{changed_digest!r} != {locked_digest!r}\n')
        os.remove(os.path.join(vendor_pkg, 'extra.txt'))
        rc, out, err = self._run_pm(pm_command='check')
        self.assertEqual(rc, 0)
        self.assertEqual(out, 'all dependencies present\n')

    def test_malformed_lockfile_degrades_without_crash(self):
        repo = os.path.join(self._tmp.name, 'lockjunkrepo')
        self._make_git_repo(repo, [
            ({'vanta.toml': '[package]\nname = "lockjunk"\n',
              'lib.vnt': 'func answer() -> i32:\n    return 1\n'}, 'v1', 'v1'),
        ])
        cmd_pm(make_args(pm_command='init', name='project'))
        self.assertEqual(cmd_pm(make_args(
            pm_command='add', sources=[self._git_source(repo, 'tag=v1')],
            name='lockjunk', dest=None)), 0)
        baseline_lock = read_lock()
        entry = baseline_lock['packages']['lockjunk']

        # A lock file without any [packages.*] section behaves as absent.
        with open(LOCK, 'w', encoding='utf-8', newline='\n') as f:
            f.write('not really a lockfile at all\n')
        rc, out, err = self._run_pm(pm_command='check')
        self.assertEqual(rc, 0)
        self.assertEqual(out, 'all dependencies present\n')
        rc = cmd_pm(make_args(pm_command='install', dest=None))
        self.assertEqual(rc, 0)
        self.assertEqual(
            open(os.path.join(VENDOR, 'lockjunk', 'lib.vnt'),
                 encoding='utf-8').read(),
            'func answer() -> i32:\n    return 1\n')

        # An unterminated string is parsed tolerantly rather than crashing;
        # it downgrades to a reported commit mismatch next to a real HEAD.
        junk_commit = '"abc'
        raw = (f'[packages.lockjunk]\n'
               f"source = \"{entry['source']}\"\n"
               f"path = \"{entry['path']}\"\n"
               f"commit = {junk_commit}\n"
               f"sha256 = \"{entry['sha256']}\"\n")
        with open(LOCK, 'w', encoding='utf-8', newline='\n') as f:
            f.write(raw)
        current_commit = _installed_git_commit(os.path.join(VENDOR, 'lockjunk'))
        rc, out, err = self._run_pm(pm_command='check')
        self.assertEqual(rc, 1)
        self.assertEqual(
            err,
            f'commit mismatch for lockjunk: installed {current_commit!r}, '
            f"lockfile {junk_commit!r}\n")
        self.assertEqual(out, '')
        write_lock(baseline_lock)
        rc, out, err = self._run_pm(pm_command='check')
        self.assertEqual(rc, 0)
        self.assertEqual(out, 'all dependencies present\n')


if __name__ == '__main__':
    unittest.main()
