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


    def test_format_strings(self):
        src = (
            "func main() -> void:\n"
            "    print_fmt(\"pos=({}, {})\", 1.5, 2.5)\n"
            "    print_fmt(\"n={} b={} s={}\", 7, true, \"hi\")\n"
            "    write_fmt(\"a\")\n"
            "    write_fmt(\"{}\", 9)\n"
            "    print_newline()\n"
            "    let s = str_concat(\"x\", to_str_i32(5))\n"
            "    print_fmt(\"{} len={}\", s, str_len(s))\n"
            "    print_fmt(\"braces {{}} pct 50%\")\n"
        )
        tmp = tempfile.mkdtemp(prefix='vanta_fmt_')
        try:
            path = os.path.join(tmp, 'fmt.vnt')
            with open(path, 'w', encoding='utf-8') as f:
                f.write(src)
            self._build_and_run(path, [
                'pos=(1.500000, 2.500000)',
                'n=7 b=true s=hi',
                'a9',
                'x5 len=2',
                'braces {} pct 50%',
            ])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


    def test_report_example_with_arg(self):
        name, path = find_cxx_compiler()
        source = os.path.join(EXAMPLES, 'report.vnt')
        prog, tc = _frontend_only(source)
        tmp = tempfile.mkdtemp(prefix='vanta_report_')
        try:
            cpp = os.path.join(tmp, 'main.cpp')
            _emit_source(prog, tc, cpp)
            exe = os.path.join(tmp, 'prog.exe' if os.name == 'nt' else 'prog')
            from compiler.driver import _compiler_cmd
            cmd = _compiler_cmd(name, path, cpp, exe, release=True)
            p = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, msg=p.stdout + p.stderr)

            # with an explicit scale
            r = subprocess.run([exe, '3'], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            self.assertEqual(r.stdout.strip().splitlines(), [
                'scale=3 n=8',
                'values: 3 6 9 12 15 18 21 24',
                'sum=108 mean=13.500000 big=4',
                'label=scale3 chars=6',
            ])

            # with no argument the scale defaults to 1
            r2 = subprocess.run([exe], capture_output=True, text=True)
            self.assertEqual(r2.returncode, 0, msg=r2.stderr)
            self.assertEqual(r2.stdout.strip().splitlines(), [
                'scale=1 n=8',
                'values: 1 2 3 4 5 6 7 8',
                'sum=36 mean=4.500000 big=4',
                'label=scale1 chars=6',
            ])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_imports_example(self):
        # Multi-file program: examples/imports_demo.vnt imports
        # imports_demo_lib.vnt relative to its own directory.
        self._build_and_run(os.path.join(EXAMPLES, 'imports_demo.vnt'),
                            ['sprite pixel 35 tile_id 35', '16'])

    def test_grid_example(self):
        # 2D arrays: stack grid, struct-held grid, and an arena-backed grid.
        self._build_and_run(os.path.join(EXAMPLES, 'grid.vnt'),
                            ['#.#.#.#.', '.#.#.#.#', '#.#.#.#.', '.#.#.#.#',
                             '9', '168'])

    def test_extern_link_end_to_end(self):
        # Build the C side of examples/extern_demo.vnt into a static library,
        # link the generated program against it, run it, and check the output.
        ar = shutil.which('ar')
        if ar is None:
            self.skipTest('ar not available (needed to archive the C fixture)')
        cc = shutil.which('gcc') or shutil.which('clang') or shutil.which('cc')
        if cc is None:
            self.skipTest('no C compiler available for the fixture')
        name, path = find_cxx_compiler()
        tmp = tempfile.mkdtemp(prefix='vanta_extern_')
        try:
            obj = os.path.join(tmp, 'extern_demo_lib.o')
            p = subprocess.run([cc, '-c', os.path.join(EXAMPLES, 'extern_demo_lib.c'),
                                '-o', obj], capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, msg=p.stdout + p.stderr)
            lib = os.path.join(tmp, 'libdemo.a')
            p = subprocess.run([ar, 'rcs', lib, obj], capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, msg=p.stdout + p.stderr)

            prog, tc = _frontend_only(os.path.join(EXAMPLES, 'extern_demo.vnt'))
            cpp = os.path.join(tmp, 'main.cpp')
            _emit_source(prog, tc, cpp)
            exe = os.path.join(tmp, 'prog.exe' if os.name == 'nt' else 'prog')
            from compiler.driver import _compiler_cmd
            cmd = _compiler_cmd(name, path, cpp, exe, release=True,
                                lib_dirs=[tmp], libs=['demo'])
            p = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, msg=p.stdout + p.stderr)
            r = subprocess.run([exe], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            self.assertEqual(r.stdout.strip().splitlines(),
                             ['10', '0', '7', '8.000000'])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_file_io_example(self):
        # Build examples/file_io.vnt and exercise all three branches:
        # missing argument, missing file, and a real read/write round-trip
        # through a copy next to the source file.
        name, path = find_cxx_compiler()
        tmp = tempfile.mkdtemp(prefix='vanta_fileio_')
        try:
            prog, tc = _frontend_only(os.path.join(EXAMPLES, 'file_io.vnt'))
            cpp = os.path.join(tmp, 'main.cpp')
            _emit_source(prog, tc, cpp)
            exe = os.path.join(tmp, 'prog.exe' if os.name == 'nt' else 'prog')
            from compiler.driver import _compiler_cmd
            cmd = _compiler_cmd(name, path, cpp, exe, release=True)
            p = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, msg=p.stdout + p.stderr)

            r = subprocess.run([exe], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            self.assertEqual(r.stdout.strip().splitlines(),
                             ['usage: file_io <path>'])

            missing = os.path.join(tmp, 'missing.txt')
            r = subprocess.run([exe, missing], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            self.assertEqual(r.stdout.strip().splitlines(),
                             ['no such file: ' + missing])

            src = os.path.join(tmp, 'in.txt')
            with open(src, 'w', encoding='utf-8') as f:
                f.write('hello world')
            r = subprocess.run([exe, src], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            self.assertEqual(r.stdout.strip().splitlines(), [
                'read 11 bytes from ' + src,
                'wrote 11 bytes to ' + src + '.copy',
            ])
            with open(src + '.copy', 'r', encoding='utf-8') as f:
                self.assertEqual(f.read(), 'hello world')
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_file_read_pool_overflow_fails_loudly(self):
        # A file larger than the 64 KiB string pool must fail loudly with a
        # specific message rather than returning garbage or a truncated read.
        name, path = find_cxx_compiler()
        src = (
            "func main() -> void:\n"
            "    let s = file_read(arg_str(1))\n"
            "    print_i32(str_len(s))\n"
        )
        tmp = tempfile.mkdtemp(prefix='vanta_fileio_big_')
        try:
            src_path = os.path.join(tmp, 'big.vnt')
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

            big = os.path.join(tmp, 'big.txt')
            with open(big, 'w', encoding='utf-8') as f:
                f.write('x' * 70000)
            r = subprocess.run([exe, big], capture_output=True, text=True)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn('does not fit the 65536-byte string pool', r.stderr)
            self.assertIn('(70000 bytes)', r.stderr)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_string_pool_exhaustion_fails_loudly(self):
        src = (
            "func main() -> void:\n"
            "    mut s = \"x\"\n"
            "    for i in range(0, 100000):\n"
            "        s = str_concat(s, \"y\")\n"
            "    print_i32(str_len(s))\n"
        )
        name, path = find_cxx_compiler()
        tmp = tempfile.mkdtemp(prefix='vanta_pool_')
        try:
            src_path = os.path.join(tmp, 'pool.vnt')
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
            r = subprocess.run([exe], capture_output=True, text=True)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn('string pool exhausted', r.stderr)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()