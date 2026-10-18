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

    def test_boids_example(self):
        name, path = find_cxx_compiler()
        source = os.path.join(EXAMPLES, 'boids.vnt')
        prog, tc = _frontend_only(source)
        tmp = tempfile.mkdtemp(prefix='vanta_boids_')
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
            lines = r.stdout.strip().splitlines()
            # Exactly 4 quadrant counts
            self.assertEqual(len(lines), 4)
            # Every count is non-negative
            for line in lines:
                self.assertGreaterEqual(int(line), 0)
            # Sum equals N — every boid in exactly one quadrant
            total = sum(int(x) for x in lines)
            self.assertEqual(total, 30)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)



    def test_rand_builtins(self):
        # Same seed must reproduce the same stream; a different seed must not.
        src = (
            "func main() -> void:\n"
            "    rand_seed(1)\n"
            "    let a = rand_f32()\n"
            "    rand_seed(1)\n"
            "    let b = rand_f32()\n"
            "    print_bool(a == b)\n"
            "    rand_seed(2)\n"
            "    let c = rand_f32()\n"
            "    print_bool(a == c)\n"
        )
        tmp = tempfile.mkdtemp(prefix='vanta_rand_')
        try:
            path = os.path.join(tmp, 'rand.vnt')
            with open(path, 'w', encoding='utf-8') as f:
                f.write(src)
            self._build_and_run(path, ['true', 'false'])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


    def test_life_example(self):
        name, path = find_cxx_compiler()
        source = os.path.join(EXAMPLES, 'life.vnt')
        prog, tc = _frontend_only(source)
        tmp = tempfile.mkdtemp(prefix='vanta_life_')
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
            lines = r.stdout.splitlines()
            # 20 rows of 40 columns
            self.assertEqual(len(lines), 20)
            for ln in lines:
                self.assertEqual(len(ln), 40)
            # a glider (5 cells) plus a blinker (3) always total 8
            self.assertEqual(sum(ln.count('#') for ln in lines), 8)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_grid_output(self):
        # The point of write_* + print_newline: build a row without newlines.
        src = (
            "func main() -> void:\n"
            "    for y in range(0, 3):\n"
            "        for x in range(0, 3):\n"
            "            if (x + y) % 2 == 0:\n"
            "                write_str(\"#\")\n"
            "            else:\n"
            "                write_str(\".\")\n"
            "        print_newline()\n"
        )
        tmp = tempfile.mkdtemp(prefix='vanta_grid_')
        try:
            path = os.path.join(tmp, 'grid.vnt')
            with open(path, 'w', encoding='utf-8') as f:
                f.write(src)
            self._build_and_run(path, ['#.#', '.#.', '#.#'])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


    def test_command_line_args(self):
        src = (
            "func main() -> void:\n"
            "    print_i32(arg_count())\n"
            "    for i in range(1, arg_count()):\n"
            "        print_str(arg_str(i))\n"
            "    write_str(\"missing=[\")\n"
            "    write_str(arg_str(999))\n"
            "    write_str(\"]\")\n"
            "    print_newline()\n"
        )
        name, path = find_cxx_compiler()
        tmp = tempfile.mkdtemp(prefix='vanta_args_')
        try:
            src_path = os.path.join(tmp, 'args.vnt')
            with open(src_path, 'w', encoding='utf-8') as f:
                f.write(src)
            prog, tc = _frontend_only(src_path)
            cpp = os.path.join(tmp, 'main.cpp')
            _emit_source(prog, tc, cpp)
            exe = os.path.join(tmp, 'prog.exe' if os.name == 'nt' else 'prog')
            from compiler.driver import _compiler_cmd
            cmd = _compiler_cmd(name, path, cpp, exe, release=True)
            p = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, msg=p.stdout + p.stderr)
            r = subprocess.run([exe, 'alpha', 'beta'], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            self.assertEqual(r.stdout.strip().splitlines(),
                             ['3', 'alpha', 'beta', 'missing=[]'])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()