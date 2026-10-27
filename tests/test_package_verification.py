import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from compiler.packages import (
    MANIFEST, LOCK, VENDOR, _rmtree,
    _read_manifest, read_toml, write_toml,
    read_lock,
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

        # Force a fresh resolution so the moved remote tag is actually consulted.
        # (`pm install` intentionally leaves already-present departments alone.)
        if os.path.isdir(VENDOR):
            _rmtree(VENDOR)
        # Reinstall should resolve to the new (changed) ref.
        rc = cmd_pm(make_args(pm_command='install', dest=None))
        self.assertEqual(rc, 0)
        self.assertEqual(read_lock()['packages']['tagrepo']['commit'], new_commit)
        self.assertNotEqual(new_commit, old_commit)
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


if __name__ == '__main__':
    unittest.main()
