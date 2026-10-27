import contextlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from compiler.driver import (
    find_cxx_compiler, _compiler_cmd, _emit_source, _frontend_only)
from compiler.packages import (
    LOCK, MANIFEST, VENDOR, _rmtree, _read_manifest,
    cmd_pm, read_lock, write_lock, write_toml)


def arguments(**kwargs):
    return type('Args', (), kwargs)()


class PackageSmokeTests(unittest.TestCase):
    def setUp(self):
        self._old_cwd = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        os.chdir(self._tmp.name)
        self._old_vanta_registry = os.environ.get('VANTA_REGISTRY')

    def tearDown(self):
        if self._old_vanta_registry is None:
            os.environ.pop('VANTA_REGISTRY', None)
        else:
            os.environ['VANTA_REGISTRY'] = self._old_vanta_registry
        os.chdir(self._old_cwd)
        self._tmp.cleanup()

    def _write(self, path, content):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8', newline='\n') as f:
            f.write(content)

    def _git(self, cwd, *args):
        subprocess.run(['git', '-C', cwd, *args],
                       check=True, capture_output=True, text=True)

    def _make_git_repository(self, path, commits):
        os.makedirs(path, exist_ok=True)
        subprocess.run(['git', 'init', '-q', '-b', 'main'], cwd=path,
                       check=True, capture_output=True, text=True)
        self._git(path, 'config', 'user.email', 'smoke@example.test')
        self._git(path, 'config', 'user.name', 'Package Smoke Tests')
        for files, message, tag in commits:
            for relative, content in files.items():
                self._write(os.path.join(path, relative), content)
            self._git(path, 'add', '-A')
            self._git(path, 'commit', '-q', '-m', message)
            if tag:
                self._git(path, 'tag', '-f', tag)

    def _rev(self, repository, ref):
        output = subprocess.run(['git', '-C', repository, 'rev-parse', ref],
                                check=True, capture_output=True, text=True)
        return output.stdout.strip()

    def _compile_and_run(self, source_path):
        name, compiler = find_cxx_compiler()
        if compiler is None:
            self.skipTest('no C++ compiler on PATH')
        program, typed = _frontend_only(source_path)
        cpp = os.path.join(self._tmp.name, 'smoke.cpp')
        _emit_source(program, typed, cpp)
        exe = os.path.join(self._tmp.name, 'smoke.exe' if os.name == 'nt' else 'smoke')
        command = _compiler_cmd(name, compiler, cpp, exe, release=True)
        build = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(build.returncode, 0, msg=build.stderr)
        run = subprocess.run([exe], capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, msg=run.stderr)
        return run.stdout.strip().replace('\r', '')

    def test_lock_commit_replay_edge_cases(self):
        repository = os.path.join(self._tmp.name, 'lockedrepo')
        self._make_git_repository(repository, [
            ({'vanta.toml': '[package]\nname = "localrepo"\n',
              'lib.vnt': 'func answer() -> i32:\n    return 1\n'}, 'first commit', 'v1'),
            ({'vanta.toml': '[package]\nname = "localrepo"\n',
              'lib.vnt': 'func answer() -> i32:\n    return 2\n'}, 'second commit', 'v2'),
        ])
        first_commit = self._rev(repository, 'v1')

        cmd_pm(arguments(pm_command='init', name='project'))
        src = 'git+' + repository + '#tag=v1'
        self.assertEqual(cmd_pm(arguments(pm_command='add', sources=[src],
                                          name='localrepo')), 0)
        self.assertEqual(read_lock()['packages']['localrepo']['commit'],
                         first_commit)

        self._git(repository, 'tag', '-f', 'v1', 'v2')
        second_commit = self._rev(repository, 'v1')
        self.assertNotEqual(first_commit, second_commit)
        if os.path.isdir(VENDOR):
            _rmtree(VENDOR)
        self.assertEqual(cmd_pm(arguments(pm_command='install', dest=None)), 0)
        self.assertEqual(read_lock()['packages']['localrepo']['commit'],
                         first_commit)
        self.assertEqual(open(os.path.join(VENDOR, 'localrepo', 'lib.vnt'),
                              encoding='utf-8').read(),
                         'func answer() -> i32:\n    return 1\n')

        locked = read_lock()['packages']['localrepo']
        locked['commit'] = ''
        lock = read_lock()
        lock['packages']['localrepo'] = locked
        write_lock(lock)

        if os.path.isdir(VENDOR):
            _rmtree(VENDOR)
        self.assertEqual(cmd_pm(arguments(pm_command='install', dest=None)), 0)
        self.assertEqual(read_lock()['packages']['localrepo']['commit'],
                         second_commit)
        self.assertEqual(open(os.path.join(VENDOR, 'localrepo', 'lib.vnt'),
                              encoding='utf-8').read(),
                         'func answer() -> i32:\n    return 2\n')

        reinstalled_commit = read_lock()['packages']['localrepo']['commit']
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            rc = cmd_pm(arguments(pm_command='install', dest=None))
        self.assertEqual(rc, 0)
        self.assertIn('already present', buffer.getvalue())
        self.assertEqual(read_lock()['packages']['localrepo']['commit'],
                         reinstalled_commit)

    def test_package_cli_smoke_and_mismatch_failure(self):
        project_root = os.path.join(self._tmp.name, 'smokeapp')
        os.makedirs(project_root)
        os.chdir(project_root)
        dependency = os.path.join(project_root, 'src')
        os.makedirs(dependency)
        self._write(os.path.join(dependency, 'vanta.toml'),
                    '[package]\nname = "localdep"\n')
        self._write(os.path.join(dependency, 'lib.vnt'),
                    'func answer() -> i32:\n    return 41\n')
        entry = os.path.join(project_root, 'main.vnt')
        self._write(entry, 'import "vendor/src/lib.vnt"\n'
                           'func main() -> void:\n    print_i32(answer())\n')

        self.assertEqual(cmd_pm(arguments(pm_command='init', name='smokeapp')), 0)
        self.assertEqual(cmd_pm(arguments(pm_command='add', sources=['./src'],
                                          dest=None)), 0)
        self.assertEqual(cmd_pm(arguments(pm_command='check')), 0)
        self.assertEqual(cmd_pm(arguments(pm_command='lock')), 0)
        self.assertIn('src', read_lock()['packages'])
        self.assertIn('src', _read_manifest()['dependencies'])

        self.assertEqual(self._compile_and_run(entry), '41')

        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            rc = cmd_pm(arguments(pm_command='list'))
        self.assertEqual(rc, 0)
        self.assertIn('src:', buffer.getvalue())

        self.assertEqual(cmd_pm(arguments(pm_command='remove', names=['src'],
                                          sources=[])), 0)
        self.assertFalse(os.path.exists(os.path.join(VENDOR, 'src')))

        original = _read_manifest()
        original['dependencies'] = {'ghost': './missing'}
        write_toml(MANIFEST, original)
        self.assertEqual(cmd_pm(arguments(pm_command='check')), 1)
        self.assertEqual(cmd_pm(arguments(pm_command='install', dest=None)), 1)

    def test_registry_dependency_has_no_git_commit(self):
        project_root = os.path.join(self._tmp.name, 'regsmoke')
        os.makedirs(project_root)
        os.chdir(project_root)
        registry = os.path.join(self._tmp.name, 'reg')
        package = os.path.join(registry, 'regdep', '1.0.0')
        os.makedirs(package, exist_ok=True)
        self._write(os.path.join(package, 'vanta.toml'),
                    '[package]\nname = "regdep"\nversion = "1.0.0"\n')
        self._write(os.path.join(package, 'lib.vnt'),
                    'func main() -> void: print_i32(9)\n')
        os.environ['VANTA_REGISTRY'] = registry

        self.assertEqual(cmd_pm(arguments(pm_command='init', name='regsmoke')), 0)
        self.assertEqual(cmd_pm(arguments(pm_command='add',
                                          sources=['regdep@1.0.0'],
                                          name='regdep')), 0)
        lock = read_lock()
        self.assertEqual(lock['packages']['regdep']['commit'], '')
        self.assertEqual(lock['packages']['regdep']['source'],
                         'registry:regdep@1.0.0')
        self.assertTrue(os.path.exists(os.path.join(VENDOR, 'regdep', 'lib.vnt')))

        if os.path.isdir(VENDOR):
            _rmtree(VENDOR)
        self.assertEqual(cmd_pm(arguments(pm_command='install', dest=None)), 0)
        self.assertEqual(read_lock()['packages']['regdep']['commit'], '')


if __name__ == '__main__':
    unittest.main()

