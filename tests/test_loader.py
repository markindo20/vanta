import os, sys, tempfile, shutil, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from compiler.loader import load_program, LoadError
from compiler.type_checker import TypeChecker, CheckError
from compiler import ast_nodes as A


class LoaderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='vanta_loader_')

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, rel, src):
        path = os.path.join(self.tmp, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(src)
        return path

    def test_no_imports_returns_own_decls(self):
        p = self.write('main.vnt', 'func main() -> void:\n    print_i32(1)\n')
        prog = load_program(p)
        self.assertEqual([d.name for d in prog.decls], ['main'])

    def test_utf8_bom_file_loads(self):
        p = self.write('main.vnt',
                       '\ufefffunc main() -> void:\n    print_i32(1)\n')
        prog = load_program(p)
        self.assertEqual([d.name for d in prog.decls], ['main'])

    def test_import_merges_dependencies_first(self):
        self.write('lib.vnt', 'func helper() -> i32:\n    return 7\n')
        p = self.write('main.vnt', 'import "lib.vnt"\n'
                                   'func main() -> void:\n    print_i32(helper())\n')
        prog = load_program(p)
        self.assertEqual([d.name for d in prog.decls], ['helper', 'main'])
        self.assertFalse(any(isinstance(d, A.ImportDecl) for d in prog.decls))

    def test_diamond_loaded_once(self):
        self.write('d.vnt', 'func d() -> i32:\n    return 1\n')
        self.write('b.vnt', 'import "d.vnt"\nfunc b() -> i32:\n    return 2\n')
        self.write('c.vnt', 'import "d.vnt"\nfunc c() -> i32:\n    return 3\n')
        p = self.write('main.vnt', 'import "b.vnt"\nimport "c.vnt"\n'
                                   'func main() -> void:\n    return\n')
        prog = load_program(p)
        self.assertEqual([d.name for d in prog.decls], ['d', 'b', 'c', 'main'])

    def test_same_file_via_different_paths_loaded_once(self):
        self.write('lib.vnt', 'func h() -> i32:\n    return 1\n')
        p = self.write('main.vnt', 'import "lib.vnt"\nimport "./lib.vnt"\n'
                                   'func main() -> void:\n    return\n')
        prog = load_program(p)
        self.assertEqual([d.name for d in prog.decls], ['h', 'main'])

    def test_cycle_reports_chain(self):
        a = self.write('a.vnt', 'import "b.vnt"\nfunc a() -> void:\n    return\n')
        self.write('b.vnt', 'import "a.vnt"\nfunc b() -> void:\n    return\n')
        with self.assertRaises(LoadError) as cm:
            load_program(a)
        msg = str(cm.exception)
        self.assertIn('import cycle', msg)
        self.assertIn('a.vnt', msg)
        self.assertIn('b.vnt', msg)

    def test_missing_import_reports_importer_position(self):
        p = self.write('main.vnt', 'import "nope.vnt"\n')
        with self.assertRaises(LoadError) as cm:
            load_program(p)
        msg = str(cm.exception)
        self.assertIn('cannot open import', msg)
        self.assertIn('nope.vnt', msg)
        self.assertIn('main.vnt:1:1', msg)

    def test_missing_entry_file(self):
        with self.assertRaises(LoadError) as cm:
            load_program(os.path.join(self.tmp, 'gone.vnt'))
        self.assertIn('cannot open', str(cm.exception))

    def test_relative_to_importing_file(self):
        self.write('sub/helper.vnt', 'func h() -> i32:\n    return 5\n')
        self.write('sub/lib.vnt', 'import "helper.vnt"\nfunc l() -> i32:\n    return h()\n')
        main = self.write('main.vnt', 'import "sub/lib.vnt"\n'
                                      'func main() -> void:\n    return\n')
        prog = load_program(main)
        self.assertEqual([d.name for d in prog.decls], ['h', 'l', 'main'])

    def test_type_error_in_import_reports_its_file(self):
        lib = self.write('lib.vnt', 'func bad() -> i32:\n    return "oops"\n')
        main = self.write('main.vnt', 'import "lib.vnt"\n'
                                      'func main() -> void:\n    return\n')
        prog = load_program(main)
        tc = TypeChecker(prog, main)
        tc.register()
        with self.assertRaises(CheckError) as cm:
            tc.check()
        msg = str(cm.exception)
        self.assertIn(lib, msg)
        self.assertNotIn('main.vnt', msg)

    def test_std_import_falls_back_to_standard_library(self):
        main = self.write('main.vnt', 'import "std/option.vnt"\n'
                                      'func main() -> void:\n'
                                      '    let value: Option<i32> = Option.None\n')
        prog = load_program(main)
        tc = TypeChecker(prog, main)
        tc.register()
        tc.check()
        self.assertTrue(any(repr(et) == 'Option<i32>'
                            for et in tc.enums.values()))

    def test_sibling_std_path_wins_over_standard_library(self):
        self.write('std/option.vnt', 'enum LocalOption:\n    None\n')
        main = self.write('main.vnt', 'import "std/option.vnt"\n'
                                      'func main() -> void:\n'
                                      '    let value = LocalOption.None\n')
        prog = load_program(main)
        tc = TypeChecker(prog, main)
        tc.register()
        tc.check()
        self.assertIn('LocalOption', tc.enums)
        self.assertNotIn('Option', tc.generic_enums)

    def test_source_overlay_replaces_entry_source(self):
        main = self.write('main.vnt',
                          'func main() -> void:\n    print_i32(1)\n')
        overlay = ('func main() -> void:\n'
                   '    let value: i32 = 7\n'
                   '    print_i32(value)\n')
        prog = load_program(main, sources={main: overlay})
        self.assertEqual([d.name for d in prog.decls], ['main'])
        self.assertEqual(prog.decls[0].body[0].value.value, 7)

    def test_source_overlay_replaces_imported_source(self):
        lib = self.write('lib.vnt', 'func helper() -> i32:\n    return 1\n')
        main = self.write('main.vnt', 'import "lib.vnt"\n'
                                      'func main() -> void:\n'
                                      '    print_i32(helper())\n')
        overlay = 'func changed() -> i32:\n    return 2\n'
        prog = load_program(main, sources={lib: overlay})
        self.assertEqual([d.name for d in prog.decls], ['changed', 'main'])
        tc = TypeChecker(prog, main)
        tc.register()
        with self.assertRaises(CheckError):
            tc.check()

    def test_source_overlay_satisfies_missing_import(self):
        main = self.write('main.vnt', 'import "new.vnt"\n'
                                      'func main() -> void:\n'
                                      '    print_i32(from_overlay())\n')
        overlay_path = os.path.join(self.tmp, 'new.vnt')
        overlay = 'func from_overlay() -> i32:\n    return 3\n'
        prog = load_program(main, sources={overlay_path: overlay})
        self.assertEqual([d.name for d in prog.decls],
                         ['from_overlay', 'main'])


if __name__ == '__main__':
    unittest.main()
