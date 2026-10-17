import os, sys, subprocess, tempfile, shutil, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from compiler.driver import find_cxx_compiler, _frontend_only, _emit_source


HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXAMPLES = os.path.join(HERE, 'examples')


def _have_compiler():
    name, path = find_cxx_compiler()
    return path is not None


@unittest.skipUnless(_have_compiler(), "no C++17 compiler available")
class IntegrationTests(unittest.TestCase):
    def _build_and_run(self, source, expected_lines):
        name, path = find_cxx_compiler()
        prog, tc = _frontend_only(source)
        tmp = tempfile.mkdtemp(prefix='vanta_it_')
        try:
            cpp = os.path.join(tmp, 'main.cpp')
            _emit_source(prog, tc, cpp)
            exe = os.path.join(tmp, 'prog.exe' if os.name == 'nt' else 'prog')
            from compiler.driver import _compiler_cmd
            cmd = _compiler_cmd(name, path, cpp, exe, release=True)
            p = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, msg=p.stdout + p.stderr)
            r = subprocess.run([exe], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            got = r.stdout.strip().splitlines()
            self.assertEqual(got, expected_lines)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def _build_and_run_expect_fail(self, source_path):
        name, path = find_cxx_compiler()
        prog, tc = _frontend_only(source_path)
        tmp = tempfile.mkdtemp(prefix='vanta_it_')
        try:
            cpp = os.path.join(tmp, 'main.cpp')
            _emit_source(prog, tc, cpp)
            exe = os.path.join(tmp, 'prog.exe' if os.name == 'nt' else 'prog')
            from compiler.driver import _compiler_cmd
            cmd = _compiler_cmd(name, path, cpp, exe, release=True)
            p = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, msg=p.stdout + p.stderr)
            r = subprocess.run([exe], capture_output=True, text=True)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn('assertion failed', r.stderr)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_vector_example(self):
        self._build_and_run(os.path.join(EXAMPLES, 'vector_math.vnt'),
                            ['5.000000', '7.000000', '9.000000', '32.000000'])

    def test_physics_example(self):
        self._build_and_run(os.path.join(EXAMPLES, 'physics.vnt'), ['60', '120', '180'])

    def test_loops_example(self):
        self._build_and_run(os.path.join(EXAMPLES, 'loops.vnt'),
                            ['0', '1', '2', '3', '4', '6', '7', '8', '9', '40'])

    def test_tier1_demo(self):
        self._build_and_run(os.path.join(EXAMPLES, 'tier1_demo.vnt'),
                            ['9.810000', '100', '0.500000', '49', '15',
                             'true', 'false', '10.000000', '20.000000', '30.000000'])

    def test_arrays_and_math_example(self):
        self._build_and_run(os.path.join(EXAMPLES, 'arrays_and_math.vnt'),
                            ['4', '100', '10', '40', '101',
                             '1.000000', '2.000000', '3.000000',
                             '1.000000', '2.000000'])

    def test_assert_failure(self):
        with tempfile.NamedTemporaryFile('w', suffix='.vnt', delete=False, encoding='utf-8') as f:
            f.write("func main() -> void:\n    assert(1 == 2)\n")
            path = f.name
        try:
            self._build_and_run_expect_fail(path)
        finally:
            os.unlink(path)

    def test_invalid_fails_before_codegen(self):
        from compiler.type_checker import CheckError
        with tempfile.NamedTemporaryFile('w', suffix='.vnt', delete=False, encoding='utf-8') as f:
            f.write("func main() -> void:\n    let x: i32 = 1.5\n")
            path = f.name
        try:
            with self.assertRaises(CheckError):
                _frontend_only(path)
        finally:
            os.unlink(path)

    def test_strings_example(self):
        self._build_and_run(os.path.join(EXAMPLES, 'strings.vnt'),
                            ['Hello, Vanta!', 'tab:\there', 'quote: "hi"',
                             'true', 'false'])




if __name__ == '__main__':
    unittest.main()