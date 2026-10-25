import os
import sys
import tempfile
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from compiler.packages import (
    MANIFEST, LOCK, VENDOR,
    _read_manifest, read_toml, write_toml,
    read_lock, write_lock,
    fetch_source, cmd_pm,
)


def make_args(**kwargs):
    return SimpleNamespace(**kwargs)


class PackagesTests(unittest.TestCase):
    def setUp(self):
        self._old_cwd = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        os.chdir(self._tmp.name)

    def tearDown(self):
        os.chdir(self._old_cwd)
        self._tmp.cleanup()

    def _write_file(self, path, content):
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)

    def _read(self, path):
        with open(path, encoding='utf-8') as f:
            return f.read()

    # ---------- manifest / lockfile IO ----------

    def test_init_creates_manifest(self):
        rc = cmd_pm(make_args(pm_command='init', name='myproj'))
        self.assertEqual(rc, 0)
        self.assertTrue(os.path.exists(MANIFEST))
        data = read_toml(MANIFEST)
        self.assertEqual(data['package']['name'], 'myproj')
        self.assertEqual(data['package']['version'], '0.1.0')
        self.assertIn(data.get('dependencies'), ({}, None))

    def test_init_when_exists_is_noop(self):
        rc1 = cmd_pm(make_args(pm_command='init', name='a'))
        rc2 = cmd_pm(make_args(pm_command='init', name='b'))
        self.assertEqual(rc1, 0)
        self.assertEqual(rc2, 0)
        self.assertEqual(read_toml(MANIFEST)['package']['name'], 'a')

    def test_write_toml_roundtrip(self):
        data = {'package': {'name': 'x', 'version': '1.0.0'},
                'dependencies': {'dep1': {'git': 'https://example.com/dep1.git'}}}
        write_toml(MANIFEST, data)
        back = read_toml(MANIFEST)
        self.assertEqual(back['package']['name'], 'x')
        self.assertEqual(back['dependencies']['dep1']['git'],
                         'https://example.com/dep1.git')

    def test_read_lock_default(self):
        lock = read_lock()
        self.assertEqual(lock, {'packages': {}})

    def test_write_lock_roundtrip(self):
        lock = {'packages': {'dep1': {'source': './dep1',
                                      'path': 'vendor/dep1',
                                      'commit': 'abc123'}}}
        write_lock(lock)
        back = read_lock()
        self.assertEqual(back['packages']['dep1']['source'], './dep1')
        self.assertEqual(back['packages']['dep1']['commit'], 'abc123')

    # ---------- fetch ----------

    def test_fetch_local_path(self):
        self._write_file('dep/vanta.toml', '[package]\nname = "dep"\n')
        self._write_file('dep/lib.vnt', 'func main() -> void: print_i32(1)\n')
        commit = fetch_source('dep', VENDOR, 'dep')
        self.assertEqual(commit, '')
        self.assertTrue(os.path.isdir(os.path.join(VENDOR, 'dep')))
        self.assertTrue(os.path.exists(os.path.join(VENDOR, 'dep', 'lib.vnt')))

    def test_fetch_source_unknown_raises(self):
        with self.assertRaises(RuntimeError):
            fetch_source('./does_not_exist', VENDOR, 'nope')

    # ---------- add / list / lock / check ----------

    def test_add_local_dep_updates_manifest_lockfile_vendor(self):
        self._write_file('dep/vanta.toml', '[package]\nname = "dep"\n')
        self._write_file('dep/lib.vnt', 'func main() -> void: print_i32(1)\n')
        rc = cmd_pm(make_args(pm_command='add', sources=['./dep'], names=[]))
        self.assertEqual(rc, 0)
        manifest = _read_manifest()
        self.assertEqual(manifest['dependencies']['dep'], './dep')
        lock = read_lock()
        self.assertIn('dep', lock['packages'])
        self.assertEqual(lock['packages']['dep']['source'], './dep')
        self.assertTrue(os.path.exists(os.path.join(VENDOR, 'dep', 'lib.vnt')))
        out = io_capture(lambda: cmd_pm(make_args(pm_command='list')))
        self.assertIn('dep:', out)

    def test_add_transitive_dependency(self):
        # dep2 is a dependency of dep1
        self._write_file('dep2/vanta.toml', '[package]\nname = "dep2"\n')
        self._write_file('dep2/lib.vnt', 'func main() -> void: print_i32(2)\n')
        self._write_file('dep1/vanta.toml',
                         '[package]\nname = "dep1"\n'
                         '[dependencies]\ndep2 = "./dep2"\n')
        self._write_file('dep1/lib.vnt', 'func main() -> void: print_i32(1)\n')
        rc = cmd_pm(make_args(pm_command='add', sources=['./dep1'], names=[]))
        self.assertEqual(rc, 0)
        manifest = _read_manifest()
        self.assertIn('dep1', manifest['dependencies'])
        self.assertIn('dep2', manifest['dependencies'])
        self.assertEqual(manifest['dependencies']['dep2'], './dep2')

    def test_list_no_deps(self):
        cmd_pm(make_args(pm_command='init', name='p'))
        out = io_capture(lambda: cmd_pm(make_args(pm_command='list')))
        self.assertIn('no dependencies', out)

    def test_lock_generates_lockfile(self):
        self._write_file('dep/vanta.toml', '[package]\nname = "dep"\n')
        self._write_file('dep/lib.vnt', 'func main() -> void: print_i32(1)\n')
        cmd_pm(make_args(pm_command='add', sources=['./dep'], names=[]))
        os.remove(LOCK)  # remove lockfile to test regeneration
        rc = cmd_pm(make_args(pm_command='lock'))
        self.assertEqual(rc, 0)
        self.assertTrue(os.path.exists(LOCK))
        lock = read_lock()
        self.assertIn('dep', lock['packages'])

    def test_check_passes_when_vendor_present(self):
        self._write_file('dep/vanta.toml', '[package]\nname = "dep"\n')
        self._write_file('dep/lib.vnt', 'func main() -> void: print_i32(1)\n')
        cmd_pm(make_args(pm_command='add', sources=['./dep'], names=[]))
        rc = cmd_pm(make_args(pm_command='check'))
        self.assertEqual(rc, 0)

    def test_check_fails_when_vendor_missing(self):
        cmd_pm(make_args(pm_command='init', name='p'))
        manifest = _read_manifest()
        manifest['dependencies'] = {'ghost': './ghost'}
        write_toml(MANIFEST, manifest)
        rc = cmd_pm(make_args(pm_command='check'))
        self.assertEqual(rc, 1)

    # ---------- remove / install ----------

    def test_remove_cleans_manifest_lockfile_vendor(self):
        self._write_file('dep/vanta.toml', '[package]\nname = "dep"\n')
        self._write_file('dep/lib.vnt', 'func main() -> void: print_i32(1)\n')
        cmd_pm(make_args(pm_command='add', sources=['./dep'], names=[]))
        self.assertTrue(os.path.exists(os.path.join(VENDOR, 'dep')))
        rc = cmd_pm(make_args(pm_command='remove', names=['dep'], sources=[]))
        self.assertEqual(rc, 0)
        manifest = _read_manifest()
        self.assertNotIn('dep', manifest.get('dependencies', {}))
        lock = read_lock()
        self.assertNotIn('dep', lock.get('packages', {}))
        self.assertFalse(os.path.exists(os.path.join(VENDOR, 'dep')))

    def test_remove_falls_back_to_sources(self):
        self._write_file('dep/vanta.toml', '[package]\nname = "dep"\n')
        self._write_file('dep/lib.vnt', 'func main() -> void: print_i32(1)\n')
        cmd_pm(make_args(pm_command='add', sources=['./dep'], names=[]))
        rc = cmd_pm(make_args(pm_command='remove', names=[], sources=['dep']))
        self.assertEqual(rc, 0)
        manifest = _read_manifest()
        self.assertNotIn('dep', manifest.get('dependencies', {}))

    def test_remove_needs_a_name(self):
        cmd_pm(make_args(pm_command='init', name='p'))
        rc = cmd_pm(make_args(pm_command='remove', names=[], sources=[]))
        self.assertEqual(rc, 1)

    def test_install_populates_vendor(self):
        self._write_file('dep/vanta.toml', '[package]\nname = "dep"\n')
        self._write_file('dep/lib.vnt', 'func main() -> void: print_i32(1)\n')
        cmd_pm(make_args(pm_command='add', sources=['./dep'], names=[]))
        shutil_rmtree_vendor()
        rc = cmd_pm(make_args(pm_command='install'))
        self.assertEqual(rc, 0)
        self.assertTrue(os.path.exists(os.path.join(VENDOR, 'dep', 'lib.vnt')))

    # ---------- error cases ----------

    def test_add_needs_a_source(self):
        cmd_pm(make_args(pm_command='init', name='p'))
        rc = cmd_pm(make_args(pm_command='add', sources=[], names=[]))
        self.assertEqual(rc, 1)

    def test_add_nonexistent_local_path_errors(self):
        cmd_pm(make_args(pm_command='init', name='p'))
        rc = cmd_pm(make_args(pm_command='add', sources=['./nope'], names=[]))
        self.assertEqual(rc, 1)

    def test_unknown_subcommand(self):
        rc = cmd_pm(make_args(pm_command='bogus'))
        self.assertEqual(rc, 1)

    # ---------- registry integration ----------

    def _make_registry(self, base, name, ver, files):
        root = os.path.join(base, name, ver)
        for rel, content in files.items():
            self._write_file(os.path.join(root, rel), content)
        return root

    def test_add_registry_dep_local_base(self):
        cmd_pm(make_args(pm_command='init', name='p'))
        base = os.path.join(self._tmp.name, 'registry')
        self._make_registry(base, 'regdep', '1.0.0', {
            'vanta.toml': '[package]\nname = "regdep"\nversion = "1.0.0"\n',
            'lib.vnt': 'func main() -> void: print_i32(7)\n',
        })
        old = os.environ.get('VANTA_REGISTRY')
        os.environ['VANTA_REGISTRY'] = base
        try:
            rc = cmd_pm(make_args(pm_command='add',
                                  sources=['regdep@1.0.0'], names=[]))
        finally:
            if old is None:
                os.environ.pop('VANTA_REGISTRY', None)
            else:
                os.environ['VANTA_REGISTRY'] = old
        self.assertEqual(rc, 0)
        manifest = _read_manifest()
        self.assertEqual(manifest['dependencies']['regdep'], {'registry': '1.0.0'})
        lock = read_lock()
        self.assertEqual(lock['packages']['regdep']['source'],
                         'registry:regdep@1.0.0')
        self.assertTrue(os.path.exists(os.path.join(VENDOR, 'regdep', 'lib.vnt')))

    def test_add_registry_missing_env_errors(self):
        cmd_pm(make_args(pm_command='init', name='p'))
        old = os.environ.pop('VANTA_REGISTRY', None)
        try:
            rc = cmd_pm(make_args(pm_command='add', sources=['regdep@1.0.0'], names=[]))
        finally:
            if old is not None:
                os.environ['VANTA_REGISTRY'] = old
        self.assertEqual(rc, 1)


def io_capture(fn):
    import io as _io
    import contextlib
    buf = _io.StringIO()
    with contextlib.redirect_stdout(buf):
        fn()
    return buf.getvalue()


def shutil_rmtree_vendor():
    import shutil
    if os.path.isdir(VENDOR):
        shutil.rmtree(VENDOR, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
