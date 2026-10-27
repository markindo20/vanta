import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from compiler.driver import _build_cache_key


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(text)


def cache_key(path, release=False, include_dirs=None, lib_dirs=None,
              links=None):
    return _build_cache_key(path, release, False, False, include_dirs or [],
                            lib_dirs or [], links or [])


class BuildCacheTests(unittest.TestCase):
    def _project(self, env=None):
        old = os.environ.get('VANTA_PATH')
        try:
            if env is not None:
                os.environ['VANTA_PATH'] = env
            self.tmp = tempfile.TemporaryDirectory()
            root = self.tmp.name
            paths = {}
            return root, paths, old
        except Exception:
            if old is None:
                os.environ.pop('VANTA_PATH', None)
            else:
                os.environ['VANTA_PATH'] = old
            raise

    def test_imported_dependency_invalidates_key(self):
        root, _, _ = self._project()
        lib = os.path.join(root, 'lib')
        os.makedirs(lib)
        entry = os.path.join(root, 'main.vnt')
        dep = os.path.join(root, 'dep.vnt')
        write(dep, 'func answer() -> i32:\n    return 7\n')
        write(entry, 'import "dep.vnt"\nfunc main() -> void:\n    print_i32(answer())\n')
        before = cache_key(entry)
        write(dep, 'func answer() -> i32:\n    return 8\n')
        after = cache_key(entry)
        self.tmp.cleanup()
        self.assertNotEqual(before, after)

    def test_transitive_dependency_invalidates_key(self):
        root, _, _ = self._project()
        parent = os.path.join(root, 'parent.vnt')
        child = os.path.join(root, 'child.vnt')
        entry = os.path.join(root, 'main.vnt')
        write(child, 'func leaf() -> i32:\n    return 1\n')
        write(parent, 'import "child.vnt"\nfunc middle() -> i32:\n    return leaf()\n')
        write(entry, 'import "parent.vnt"\nfunc main() -> void:\n    print_i32(middle())\n')
        before = cache_key(entry)
        write(child, 'func leaf() -> i32:\n    return 2\n')
        after = cache_key(entry)
        self.tmp.cleanup()
        self.assertNotEqual(before, after)

    def test_vanta_path_dependency_invalidates_key(self):
        old = os.environ.get('VANTA_PATH')
        root = tempfile.mkdtemp()
        libdir = os.path.join(root, 'search')
        os.makedirs(libdir)
        entry = os.path.join(root, 'proj', 'main.vnt')
        os.makedirs(os.path.dirname(entry))
        write(os.path.join(libdir, 'dep.vnt'), 'func answer() -> i32:\n    return 7\n')
        write(entry, 'import "dep.vnt"\nfunc main() -> void:\n    print_i32(answer())\n')
        os.environ['VANTA_PATH'] = libdir
        before = cache_key(entry)
        write(os.path.join(libdir, 'dep.vnt'), 'func answer() -> i32:\n    return 8\n')
        after = cache_key(entry)
        os.chdir(os.getcwd())
        if old is None:
            os.environ.pop('VANTA_PATH', None)
        else:
            os.environ['VANTA_PATH'] = old
        self.assertNotEqual(before, after)

    def test_source_change_invalidates_key(self):
        root = tempfile.mkdtemp()
        entry = os.path.join(root, 'main.vnt')
        write(entry, 'func main() -> void:\n    print_i32(1)\n')
        before = cache_key(entry)
        write(entry, 'func main() -> void:\n    print_i32(2)\n')
        after = cache_key(entry)
        self.assertNotEqual(before, after)

    def test_unrelated_source_does_not_invalidate_key(self):
        root = tempfile.mkdtemp()
        entry = os.path.join(root, 'main.vnt')
        write(entry, 'func main() -> void:\n    print_i32(1)\n')
        write(os.path.join(root, 'unrelated.vnt'), 'func helper() -> i32: return 1\n')
        before = cache_key(entry)
        write(os.path.join(root, 'unrelated.vnt'), 'func helper() -> i32: return 2\n')
        after = cache_key(entry)
        self.assertEqual(before, after)

    def test_missing_import_does_not_scan_unrelated_files(self):
        root = tempfile.mkdtemp()
        entry = os.path.join(root, 'main.vnt')
        write(entry, 'import "missing.vnt"\nfunc main() -> void:\n    return\n')
        unrelated = os.path.join(root, 'unrelated.vnt')
        missing = os.path.join(root, 'missing.vnt')
        os.makedirs(missing, exist_ok=True)  # fixture that could confuse resolution
        write(unrelated, 'x')
        before = cache_key(entry)
        write(unrelated, 'y')
        after = cache_key(entry)
        self.assertEqual(before, after)


if __name__ == '__main__':
    unittest.main()
