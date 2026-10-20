import os, sys, subprocess, tempfile, shutil, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from compiler.driver import find_cxx_compiler, _frontend_only, _emit_source, _is_msvc


HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXAMPLES = os.path.join(HERE, 'examples')


def _have_compiler():
    name, path = find_cxx_compiler()
    return path is not None


def _find_sdl2():
    """How to build against SDL2, or None when it is not available."""
    name, path = find_cxx_compiler()
    if name is None or _is_msvc(name):
        # link.exe cannot consume the MinGW import library below; an MSVC
        # setup would need SDL2's own .lib, so treat SDL2 as unavailable.
        return None
    if os.name == 'nt':
        candidates = []
        if path:
            # g++ lives in <prefix>\mingw64\bin; the libs are two levels up
            # in <prefix>\mingw64\lib, wherever MSYS2 was installed.
            candidates.append(os.path.join(os.path.dirname(os.path.dirname(path)), 'lib'))
        candidates.append(r'C:\msys64\mingw64\lib')
        for lib_dir in candidates:
            if os.path.exists(os.path.join(lib_dir, 'libSDL2.dll.a')):
                return {'lib_dirs': [lib_dir], 'libs': ['SDL2']}
        return None
    cfg = shutil.which('sdl2-config')
    if cfg:
        out = subprocess.run([cfg, '--libs'], capture_output=True, text=True).stdout
        lib_dirs = [tok[2:] for tok in out.split() if tok.startswith('-L')]
        return {'lib_dirs': lib_dirs, 'libs': ['SDL2']}
    import ctypes.util
    if ctypes.util.find_library('SDL2'):
        return {'lib_dirs': [], 'libs': ['SDL2']}
    return None


SDL2 = _find_sdl2()


def _find_sdl2_ttf():
    """How to build against SDL2_ttf (with SDL2), or None when it is not
    available."""
    base = _find_sdl2()
    if base is None:
        return None
    if os.name == 'nt':
        for d in base['lib_dirs']:
            if os.path.exists(os.path.join(d, 'libSDL2_ttf.dll.a')):
                return {'lib_dirs': [d], 'libs': ['SDL2_ttf', 'SDL2']}
        return None
    import ctypes.util
    if ctypes.util.find_library('SDL2_ttf'):
        return {'lib_dirs': base['lib_dirs'], 'libs': ['SDL2_ttf', 'SDL2']}
    # macOS: Homebrew installs outside dyld's default search paths, where
    # find_library cannot see it, so ask brew. The keg and the linked
    # prefix directory both carry the unversioned libSDL2_ttf.dylib that
    # -lSDL2_ttf looks for.
    brew = shutil.which('brew')
    if brew:
        dirs = []
        for args in (['--prefix', 'sdl2_ttf'], ['--prefix']):
            p = subprocess.run([brew] + args, capture_output=True, text=True)
            if p.returncode == 0:
                lib_dir = os.path.join(p.stdout.strip(), 'lib')
                if os.path.exists(os.path.join(lib_dir, 'libSDL2_ttf.dylib')):
                    dirs.append(lib_dir)
        if dirs:
            return {'lib_dirs': base['lib_dirs'] + dirs,
                    'libs': ['SDL2_ttf', 'SDL2']}
    return None


SDL2_TTF = _find_sdl2_ttf()


def _find_sdl2_image():
    """How to build against SDL2_image (with SDL2), or None when it is not
    available."""
    base = _find_sdl2()
    if base is None:
        return None
    if os.name == 'nt':
        for d in base['lib_dirs']:
            if os.path.exists(os.path.join(d, 'libSDL2_image.dll.a')):
                return {'lib_dirs': [d], 'libs': ['SDL2_image', 'SDL2']}
        return None
    import ctypes.util
    if ctypes.util.find_library('SDL2_image'):
        return {'lib_dirs': base['lib_dirs'], 'libs': ['SDL2_image', 'SDL2']}
    # macOS: Homebrew installs outside dyld's default search paths, where
    # find_library cannot see it, so ask brew (same story as SDL2_ttf).
    brew = shutil.which('brew')
    if brew:
        dirs = []
        for args in (['--prefix', 'sdl2_image'], ['--prefix']):
            p = subprocess.run([brew] + args, capture_output=True, text=True)
            if p.returncode == 0:
                lib_dir = os.path.join(p.stdout.strip(), 'lib')
                if os.path.exists(os.path.join(lib_dir, 'libSDL2_image.dylib')):
                    dirs.append(lib_dir)
        if dirs:
            return {'lib_dirs': base['lib_dirs'] + dirs,
                    'libs': ['SDL2_image', 'SDL2']}
    return None


SDL2_IMAGE = _find_sdl2_image()


def _sdl2_all():
    """SDL2 + SDL2_ttf + SDL2_image together, for the game that uses all
    three, or None when any is missing."""
    if SDL2 is None or SDL2_TTF is None or SDL2_IMAGE is None:
        return None
    dirs = []
    for cfg in (SDL2_TTF, SDL2_IMAGE):
        for d in cfg['lib_dirs']:
            if d not in dirs:
                dirs.append(d)
    return {'lib_dirs': dirs, 'libs': ['SDL2_image', 'SDL2_ttf', 'SDL2']}


SDL2_ALL = _sdl2_all()


def _write_wav(path, samples, channels, rate):
    """Write a minimal 16-bit PCM WAV, for the kit's sound-format tests."""
    import struct
    data = struct.pack('<%dh' % len(samples), *samples)
    with open(path, 'wb') as f:
        f.write(b'RIFF' + struct.pack('<I', 36 + len(data)) + b'WAVE'
                + b'fmt ' + struct.pack('<IHHIIHH', 16, 1, channels, rate,
                                        rate * channels * 2, channels * 2, 16)
                + b'data' + struct.pack('<I', len(data)) + data)


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

    def _build_and_run_expect_error(self, source_path, message):
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
            self.assertIn(message, r.stderr)
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
                             '1.000000', '2.000000',
                             '0.707107', '0.707107', '0.785398'])

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

    def test_dispatch_example(self):
        # First-class functions: array of function values, higher-order
        # apply, struct-held callback, and a void function value.
        self._build_and_run(os.path.join(EXAMPLES, 'dispatch.vnt'),
                            ['25', '-5', '49', 'square op: 16', 'done'])

    def test_bounds_example(self):
        # Bounds-checked access: checked reads and writes, including a
        # computed index and a nested checked read as the index.
        self._build_and_run(os.path.join(EXAMPLES, 'bounds.vnt'),
                            ['66', '1', '25', '16', '25'])

    def test_trig_runtime(self):
        # sin/cos/tan/atan2 at known values, f32 and f64.
        src = (
            "func main() -> void:\n"
            "    print_f32(sin_f32(0.0))\n"
            "    print_f32(cos_f32(0.0))\n"
            "    print_f32(sin_f32(1.5707964))\n"
            "    print_f32(cos_f32(3.1415927))\n"
            "    print_f32(tan_f32(0.0))\n"
            "    print_f32(atan2_f32(1.0, 1.0))\n"
            "    print_f64(atan2_f64(1.0, 1.0))\n"
        )
        tmp = tempfile.mkdtemp(prefix='vanta_trig_')
        try:
            path = os.path.join(tmp, 'trig.vnt')
            with open(path, 'w', encoding='utf-8') as f:
                f.write(src)
            self._build_and_run(path, ['0.000000', '1.000000', '1.000000',
                                       '-1.000000', '0.000000', '0.785398',
                                       '0.785398'])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_lists_example(self):
        self._build_and_run(os.path.join(EXAMPLES, 'lists.vnt'),
                            ['5', '0.000000', '1.000000', '2.000000', '3.000000',
                             '4.000000', '4.000000', '4', '9.000000',
                             '9.000000', '3.000000', '2.000000', '1.000000',
                             '0.000000', '4'])

    def test_list_grow_and_iterate(self):
        # Pushing past the initial capacity exercises arena-backed growth.
        src = (
            "func main() -> void:\n"
            "    let a = Arena(65536)\n"
            "    let xs = a.list::<i32>()\n"
            "    for i in range(0, 20):\n"
            "        xs.push(i * i)\n"
            "    mut total = 0\n"
            "    for i in range(0, len(xs)):\n"
            "        total += xs.at(i)\n"
            "    print_i32(len(xs))\n"
            "    print_i32(total)\n"
        )
        tmp = tempfile.mkdtemp(prefix='vanta_list_')
        try:
            path = os.path.join(tmp, 'grow.vnt')
            with open(path, 'w', encoding='utf-8') as f:
                f.write(src)
            self._build_and_run(path, ['20', '2470'])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_list_push_pop_alias(self):
        # A List is a handle: helpers and copies see the same underlying list.
        src = (
            "func fill(xs: List<i32>):\n"
            "    for i in range(1, 4):\n"
            "        xs.push(i)\n"
            "func main() -> void:\n"
            "    let a = Arena(4096)\n"
            "    let xs = a.list::<i32>()\n"
            "    fill(xs)\n"
            "    let ys = xs\n"
            "    ys.push(4)\n"
            "    print_i32(len(xs))\n"
            "    print_i32(xs.pop())\n"
            "    print_i32(xs.at(0))\n"
            "    print_i32(len(xs))\n"
        )
        tmp = tempfile.mkdtemp(prefix='vanta_list_')
        try:
            path = os.path.join(tmp, 'alias.vnt')
            with open(path, 'w', encoding='utf-8') as f:
                f.write(src)
            self._build_and_run(path, ['4', '4', '1', '3'])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_list_unchecked_index(self):
        src = (
            "func main() -> void:\n"
            "    let a = Arena(4096)\n"
            "    let xs = a.list::<i32>()\n"
            "    for i in range(0, 3):\n"
            "        xs.push(i * 10)\n"
            "    xs[1] += 5\n"
            "    print_i32(xs[1])\n"
            "    print_i32(xs[2])\n"
        )
        tmp = tempfile.mkdtemp(prefix='vanta_list_')
        try:
            path = os.path.join(tmp, 'index.vnt')
            with open(path, 'w', encoding='utf-8') as f:
                f.write(src)
            self._build_and_run(path, ['15', '20'])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_list_at_oob_fails(self):
        src = (
            "func main() -> void:\n"
            "    let a = Arena(1024)\n"
            "    let xs = a.list::<i32>()\n"
            "    xs.push(1)\n"
            "    print_i32(xs.at(4))\n"
        )
        tmp = tempfile.mkdtemp(prefix='vanta_list_')
        try:
            path = os.path.join(tmp, 'oob.vnt')
            with open(path, 'w', encoding='utf-8') as f:
                f.write(src)
            self._build_and_run_expect_error(
                path, 'vanta: index 4 out of bounds (size 1) at line 5')
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_list_pop_empty_fails(self):
        src = (
            "func main() -> void:\n"
            "    let a = Arena(1024)\n"
            "    let xs = a.list::<i32>()\n"
            "    print_i32(xs.pop())\n"
        )
        tmp = tempfile.mkdtemp(prefix='vanta_list_')
        try:
            path = os.path.join(tmp, 'pop.vnt')
            with open(path, 'w', encoding='utf-8') as f:
                f.write(src)
            self._build_and_run_expect_error(
                path, 'vanta: pop from empty list at line 4')
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_list_insert_remove(self):
        # insert shifts the rest right (index len is push); remove shifts
        # left and returns the element.
        src = (
            "func main() -> void:\n"
            "    let a = Arena(4096)\n"
            "    let xs = a.list::<i32>()\n"
            "    xs.push(3)\n"
            "    xs.push(1)\n"
            "    xs.push(2)\n"
            "    xs.insert(0, 9)\n"
            "    xs.insert(2, 8)\n"
            "    xs.insert(len(xs), 7)\n"
            "    print_i32(len(xs))\n"
            "    for i in range(0, len(xs)):\n"
            "        print_i32(xs.at(i))\n"
            "    print_i32(xs.remove(0))\n"
            "    print_i32(xs.remove(len(xs) - 1))\n"
            "    print_i32(xs.remove(1))\n"
            "    print_i32(len(xs))\n"
        )
        tmp = tempfile.mkdtemp(prefix='vanta_list_')
        try:
            path = os.path.join(tmp, 'insert.vnt')
            with open(path, 'w', encoding='utf-8') as f:
                f.write(src)
            self._build_and_run(path, ['6', '9', '3', '8', '1', '2', '7',
                                       '9', '7', '8', '3'])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_list_sort_comparator(self):
        # The comparator returns negative / zero / positive, so the same
        # list sorts ascending or descending.
        src = (
            "func cmp(a: i32, b: i32) -> i32:\n"
            "    return a - b\n"
            "\n"
            "func desc(a: i32, b: i32) -> i32:\n"
            "    return b - a\n"
            "\n"
            "func main() -> void:\n"
            "    let a = Arena(4096)\n"
            "    let xs = a.list::<i32>()\n"
            "    xs.push(3)\n"
            "    xs.push(1)\n"
            "    xs.push(2)\n"
            "    xs.sort(cmp)\n"
            "    for i in range(0, len(xs)):\n"
            "        print_i32(xs.at(i))\n"
            "    xs.sort(desc)\n"
            "    for i in range(0, len(xs)):\n"
            "        print_i32(xs.at(i))\n"
        )
        tmp = tempfile.mkdtemp(prefix='vanta_list_')
        try:
            path = os.path.join(tmp, 'sort.vnt')
            with open(path, 'w', encoding='utf-8') as f:
                f.write(src)
            self._build_and_run(path, ['1', '2', '3', '3', '2', '1'])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_list_sort_stable(self):
        # Merge sort is stable: equal keys keep their relative order.
        src = (
            "struct Item:\n"
            "    key: i32\n"
            "    tag: str\n"
            "\n"
            "func by_key(a: Item, b: Item) -> i32:\n"
            "    return a.key - b.key\n"
            "\n"
            "func main() -> void:\n"
            "    let a = Arena(4096)\n"
            "    let xs = a.list::<Item>()\n"
            "    xs.push(Item(key: 2, tag: \"a\"))\n"
            "    xs.push(Item(key: 1, tag: \"b\"))\n"
            "    xs.push(Item(key: 2, tag: \"c\"))\n"
            "    xs.push(Item(key: 1, tag: \"d\"))\n"
            "    xs.sort(by_key)\n"
            "    for i in range(0, len(xs)):\n"
            "        print_str(xs.at(i).tag)\n"
            "    let first = xs.remove(0)\n"
            "    print_str(first.tag)\n"
        )
        tmp = tempfile.mkdtemp(prefix='vanta_list_')
        try:
            path = os.path.join(tmp, 'stable.vnt')
            with open(path, 'w', encoding='utf-8') as f:
                f.write(src)
            self._build_and_run(path, ['b', 'd', 'a', 'c', 'b'])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_list_insert_oob_fails(self):
        src = (
            "func main() -> void:\n"
            "    let a = Arena(1024)\n"
            "    let xs = a.list::<i32>()\n"
            "    xs.push(1)\n"
            "    xs.push(2)\n"
            "    xs.insert(3, 9)\n"
        )
        tmp = tempfile.mkdtemp(prefix='vanta_list_')
        try:
            path = os.path.join(tmp, 'insert_oob.vnt')
            with open(path, 'w', encoding='utf-8') as f:
                f.write(src)
            self._build_and_run_expect_error(
                path, 'vanta: insert index 3 out of bounds (size 2) at line 6')
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_list_remove_oob_fails(self):
        src = (
            "func main() -> void:\n"
            "    let a = Arena(1024)\n"
            "    let xs = a.list::<i32>()\n"
            "    xs.remove(0)\n"
        )
        tmp = tempfile.mkdtemp(prefix='vanta_list_')
        try:
            path = os.path.join(tmp, 'remove_oob.vnt')
            with open(path, 'w', encoding='utf-8') as f:
                f.write(src)
            self._build_and_run_expect_error(
                path, 'vanta: remove index 0 out of bounds (size 0) at line 4')
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_str_builder_example(self):
        self._build_and_run(os.path.join(EXAMPLES, 'str_builder.vnt'),
                            ['score 1250, hp 87.500000', '24', 'player: 100 hp',
                             'player: 100 hp', 'rebuilt'])

    def test_strbuilder_build_line(self):
        src = (
            "func main() -> void:\n"
            "    let a = Arena(4096)\n"
            "    let b = a.str_builder()\n"
            "    b.append_str(\"hp \")\n"
            "    b.append_i32(42)\n"
            "    b.append_str(\" / \")\n"
            "    b.append_f32(1.5)\n"
            "    print_str(b.to_str())\n"
            "    print_i32(len(b))\n"
        )
        tmp = tempfile.mkdtemp(prefix='vanta_strb_')
        try:
            path = os.path.join(tmp, 'line.vnt')
            with open(path, 'w', encoding='utf-8') as f:
                f.write(src)
            self._build_and_run(path, ['hp 42 / 1.500000', '16'])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_strbuilder_growth(self):
        # Appends crossing the initial capacity grow the arena buffer.
        src = (
            "func main() -> void:\n"
            "    let a = Arena(65536)\n"
            "    let b = a.str_builder()\n"
            "    for i in range(0, 30):\n"
            "        b.append_i32(i)\n"
            "    print_i32(len(b))\n"
            "    print_str(b.to_str())\n"
        )
        tmp = tempfile.mkdtemp(prefix='vanta_strb_')
        try:
            path = os.path.join(tmp, 'grow.vnt')
            with open(path, 'w', encoding='utf-8') as f:
                f.write(src)
            self._build_and_run(path, [
                '50', '01234567891011121314151617181920212223242526272829'])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_strbuilder_to_str_snapshot(self):
        # to_str() copies into a fresh arena block: the result survives
        # later appends, growth, and clear().
        src = (
            "func main() -> void:\n"
            "    let a = Arena(4096)\n"
            "    let b = a.str_builder()\n"
            "    b.append_str(\"abc\")\n"
            "    let s = b.to_str()\n"
            "    b.clear()\n"
            "    print_str(s)\n"
            "    print_i32(len(b))\n"
            "    b.append_str(\"xyz\")\n"
            "    print_str(b.to_str())\n"
        )
        tmp = tempfile.mkdtemp(prefix='vanta_strb_')
        try:
            path = os.path.join(tmp, 'snapshot.vnt')
            with open(path, 'w', encoding='utf-8') as f:
                f.write(src)
            self._build_and_run(path, ['abc', '0', 'xyz'])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_strbuilder_helper_appends(self):
        # A StrBuilder is a handle: helpers append to the caller's builder.
        src = (
            "func key(b: StrBuilder, k: str, v: i32):\n"
            "    b.append_str(k)\n"
            "    b.append_str(\"=\")\n"
            "    b.append_i32(v)\n"
            "    b.append_str(\";\")\n"
            "func main() -> void:\n"
            "    let a = Arena(4096)\n"
            "    let b = a.str_builder()\n"
            "    key(b, \"hp\", 100)\n"
            "    key(b, \"mp\", 30)\n"
            "    print_str(b.to_str())\n"
        )
        tmp = tempfile.mkdtemp(prefix='vanta_strb_')
        try:
            path = os.path.join(tmp, 'helper.vnt')
            with open(path, 'w', encoding='utf-8') as f:
                f.write(src)
            self._build_and_run(path, ['hp=100;mp=30;'])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_function_value_runtime(self):
        # Nested function types, arena-stored function pointers, and copies
        # of function values executed for real.
        src = (
            "func twice(f: func(i32) -> i32, x: i32) -> i32:\n"
            "    return f(f(x))\n"
            "func inc(x: i32) -> i32:\n"
            "    return x + 1\n"
            "func main() -> void:\n"
            "    let arena = Arena(256)\n"
            "    let slots = arena.alloc::<func(func(i32) -> i32, i32) -> i32>(1)\n"
            "    slots[0] = twice\n"
            "    let t: func(i32) -> i32 = inc\n"
            "    print_i32(slots[0](t, 3))\n"
            "    let a: [func(i32) -> i32, 2] = [inc, t]\n"
            "    mut acc = 0\n"
            "    for i in range(0, len(a)):\n"
            "        acc += a[i](10)\n"
            "    print_i32(acc)\n"
        )
        tmp = tempfile.mkdtemp(prefix='vanta_fcf_')
        try:
            path = os.path.join(tmp, 'fcf.vnt')
            with open(path, 'w', encoding='utf-8') as f:
                f.write(src)
            self._build_and_run(path, ['5', '22'])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

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
        if _is_msvc(name):
            self.skipTest('fixture is a GNU archive (libdemo.a); '
                          'MSVC would need a .lib fixture')
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

    def test_callback_atexit(self):
        # atexit is a libc function taking a callback: the Vanta function
        # farewell runs after main returns. No C fixture needed, so this
        # exercises callbacks everywhere (MSVC included).
        tmp = tempfile.mkdtemp(prefix='vanta_atexit_')
        try:
            path = os.path.join(tmp, 'atexit.vnt')
            with open(path, 'w', encoding='utf-8') as f:
                f.write('extern "C" {\n'
                        '    func atexit(cb: func()) -> i32\n'
                        '}\n'
                        '\n'
                        'func farewell():\n'
                        '    print_str("goodbye from the callback")\n'
                        '\n'
                        'func main() -> void:\n'
                        '    atexit(farewell)\n'
                        '    print_str("main is done")\n')
            self._build_and_run(path, ['main is done', 'goodbye from the callback'])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_callbacks_example(self):
        # Build the C side of examples/callbacks.vnt into a static library,
        # link the generated program against it, and check that C calls back
        # into Vanta functions — including one with pointer user data.
        ar = shutil.which('ar')
        if ar is None:
            self.skipTest('ar not available (needed to archive the C fixture)')
        cc = shutil.which('gcc') or shutil.which('clang') or shutil.which('cc')
        if cc is None:
            self.skipTest('no C compiler available for the fixture')
        name, path = find_cxx_compiler()
        if _is_msvc(name):
            self.skipTest('fixture is a GNU archive (libcallback.a); '
                          'MSVC would need a .lib fixture')
        tmp = tempfile.mkdtemp(prefix='vanta_callbacks_')
        try:
            obj = os.path.join(tmp, 'callbacks_lib.o')
            p = subprocess.run([cc, '-c', os.path.join(EXAMPLES, 'callbacks_lib.c'),
                                '-o', obj], capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, msg=p.stdout + p.stderr)
            lib = os.path.join(tmp, 'libcallback.a')
            p = subprocess.run([ar, 'rcs', lib, obj], capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, msg=p.stdout + p.stderr)

            prog, tc = _frontend_only(os.path.join(EXAMPLES, 'callbacks.vnt'))
            cpp = os.path.join(tmp, 'main.cpp')
            _emit_source(prog, tc, cpp)
            exe = os.path.join(tmp, 'prog.exe' if os.name == 'nt' else 'prog')
            from compiler.driver import _compiler_cmd
            cmd = _compiler_cmd(name, path, cpp, exe, release=True,
                                lib_dirs=[tmp], libs=['callback'])
            p = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, msg=p.stdout + p.stderr)
            r = subprocess.run([exe], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            self.assertEqual(r.stdout.strip().splitlines(), ['12', '14'])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_extern_return_example(self):
        # C returns a function pointer, and Vanta calls it, compares it by
        # address, and tests it for null — the extern return path end to end.
        tmp = tempfile.mkdtemp(prefix='vanta_extret_')
        try:
            lib = self._build_c_fixture(tmp, 'extern_return_lib.c')
            exe = self._build_example_linked('extern_return.vnt', tmp, [lib])
            r = subprocess.run([exe], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            self.assertEqual(r.stdout.strip().splitlines(),
                             ['42', '-7', 'false', 'true', 'true', 'false', 'true'])
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

    def test_checked_index_runtime(self):
        # Reads and writes through xs.at(i): plain, compound, nested 2D, and
        # a pointer-backed row.
        src = (
            "func main() -> void:\n"
            "    mut xs: [i32, 4] = [10, 20, 30, 40]\n"
            "    print_i32(xs.at(1))\n"
            "    xs.at(2) = 99\n"
            "    print_i32(xs.at(2))\n"
            "    xs.at(3) += 1\n"
            "    print_i32(xs.at(3))\n"
            "    mut g: [[i32, 2], 2] = [[1, 2], [3, 4]]\n"
            "    g.at(1).at(0) = 30\n"
            "    print_i32(g.at(1).at(0))\n"
            "    let n = len(xs)\n"
            "    print_i32(xs.at(n - 1))\n"
            "    let a = Arena(256)\n"
            "    let rows = a.alloc::<[i32, 2]>(1)\n"
            "    rows[0].at(0) = 7\n"
            "    print_i32(rows[0].at(0))\n"
        )
        tmp = tempfile.mkdtemp(prefix='vanta_at_')
        try:
            path = os.path.join(tmp, 'at.vnt')
            with open(path, 'w', encoding='utf-8') as f:
                f.write(src)
            self._build_and_run(path, ['20', '99', '41', '30', '41', '7'])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_checked_index_out_of_bounds_read_fails_loudly(self):
        src = (
            "func main() -> void:\n"
            "    let xs: [i32, 3] = [1, 2, 3]\n"
            "    let i = 5 - 2\n"
            "    print_i32(xs.at(i))\n"
        )
        tmp = tempfile.mkdtemp(prefix='vanta_at_oob_')
        try:
            path = os.path.join(tmp, 'oob.vnt')
            with open(path, 'w', encoding='utf-8') as f:
                f.write(src)
            self._build_and_run_expect_error(
                path, 'vanta: index 3 out of bounds (size 3) at line 4')
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_checked_index_out_of_bounds_write_fails_loudly(self):
        src = (
            "func main() -> void:\n"
            "    mut xs: [i32, 3] = [1, 2, 3]\n"
            "    xs.at(-1) = 9\n"
        )
        tmp = tempfile.mkdtemp(prefix='vanta_at_oobw_')
        try:
            path = os.path.join(tmp, 'oobw.vnt')
            with open(path, 'w', encoding='utf-8') as f:
                f.write(src)
            self._build_and_run_expect_error(
                path, 'vanta: index -1 out of bounds (size 3) at line 3')
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_enums_example(self):
        self._build_and_run(os.path.join(EXAMPLES, 'enums.vnt'),
                            ['menu', 'playing', '2', 'menu', 'playing',
                             'paused', 'game over'])

    def test_match_example(self):
        self._build_and_run(os.path.join(EXAMPLES, 'match.vnt'),
                            ['in game', 'fresh start', 'menu',
                             'in game', 'in game', 'in game', 'in game',
                             'caught the run at in game'])

    def test_match_break_binds_to_loop(self):
        # break/continue in an arm control the enclosing loop: match is
        # not a loop and never captures them (codegen uses if/else, not
        # a C++ switch).
        src = (
            "enum Kind:\n"
            "    A\n"
            "    B\n"
            "    C\n"
            "func main() -> void:\n"
            "    let ks: [Kind, 3] = [Kind.A, Kind.B, Kind.C]\n"
            "    for i in range(0, 3):\n"
            "        match ks.at(i):\n"
            "            Kind.A:\n"
            "                continue\n"
            "            Kind.B:\n"
            "                break\n"
            "            else:\n"
            "                print_str(\"C reached\")\n"
            "    print_str(\"done\")\n"
        )
        tmp = tempfile.mkdtemp(prefix='vanta_match_')
        try:
            path = os.path.join(tmp, 'flow.vnt')
            with open(path, 'w', encoding='utf-8') as f:
                f.write(src)
            self._build_and_run(path, ['done'])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_enum_state_machine(self):
        src = (
            "enum State:\n"
            "    Menu\n"
            "    Playing\n"
            "    Paused\n"
            "    GameOver\n"
            "struct Game:\n"
            "    state: State\n"
            "    hp: i32\n"
            "func state_name(s: State) -> str:\n"
            "    if s == State.Menu:\n"
            "        return \"menu\"\n"
            "    elif s == State.Playing:\n"
            "        return \"playing\"\n"
            "    elif s == State.Paused:\n"
            "        return \"paused\"\n"
            "    return \"game over\"\n"
            "func main() -> void:\n"
            "    let g = Game(state: State.Menu, hp: 3)\n"
            "    print_str(state_name(g.state))\n"
            "    mut s = State.Playing\n"
            "    print_str(state_name(s))\n"
            "    print_i32(enum_to_i32(s))\n"
            "    s = State.GameOver\n"
            "    if s != State.Playing:\n"
            "        print_str(state_name(s))\n"
            "    let cycle: [State, 4] = [State.Menu, State.Playing, State.Paused, State.GameOver]\n"
            "    for i in range(0, len(cycle)):\n"
            "        print_i32(enum_to_i32(cycle.at(i)))\n"
        )
        tmp = tempfile.mkdtemp(prefix='vanta_enum_')
        try:
            path = os.path.join(tmp, 'states.vnt')
            with open(path, 'w', encoding='utf-8') as f:
                f.write(src)
            self._build_and_run(path, ['menu', 'playing', '1', 'game over',
                                       '0', '1', '2', '3'])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_enum_field_transition(self):
        src = (
            "enum State:\n"
            "    Menu\n"
            "    Playing\n"
            "func is_playing(s: State) -> bool:\n"
            "    return s == State.Playing\n"
            "struct Game:\n"
            "    state: State\n"
            "func main() -> void:\n"
            "    mut g = Game(state: State.Menu)\n"
            "    print_bool(is_playing(g.state))\n"
            "    g.state = State.Playing\n"
            "    print_bool(is_playing(g.state))\n"
        )
        tmp = tempfile.mkdtemp(prefix='vanta_enum_field_')
        try:
            path = os.path.join(tmp, 'field.vnt')
            with open(path, 'w', encoding='utf-8') as f:
                f.write(src)
            self._build_and_run(path, ['false', 'true'])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_enum_list_and_function_values(self):
        src = (
            "enum Suit:\n"
            "    Clubs\n"
            "    Diamonds\n"
            "func is_clubs(s: Suit) -> bool:\n"
            "    return s == Suit.Clubs\n"
            "func apply(f: func(Suit) -> bool, s: Suit) -> bool:\n"
            "    return f(s)\n"
            "func main() -> void:\n"
            "    let arena = Arena(4096)\n"
            "    let xs = arena.list::<Suit>()\n"
            "    xs.push(Suit.Clubs)\n"
            "    xs.push(Suit.Diamonds)\n"
            "    xs.push(Suit.Clubs)\n"
            "    print_i32(len(xs))\n"
            "    print_i32(enum_to_i32(xs.at(1)))\n"
            "    let p = xs.pop()\n"
            "    print_i32(enum_to_i32(p))\n"
            "    if is_clubs(xs[0]):\n"
            "        print_str(\"clubs\")\n"
            "    if apply(is_clubs, Suit.Clubs):\n"
            "        print_str(\"applied\")\n"
        )
        tmp = tempfile.mkdtemp(prefix='vanta_enum_list_')
        try:
            path = os.path.join(tmp, 'suit.vnt')
            with open(path, 'w', encoding='utf-8') as f:
                f.write(src)
            self._build_and_run(path, ['3', '1', '0', 'clubs', 'applied'])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_str_returning_function(self):
        # Regression: functions with a str return type used to emit the
        # invalid default 'return const char*{};'.
        src = (
            "func pick(x: i32) -> str:\n"
            "    if x > 0:\n"
            "        return \"pos\"\n"
            "func main() -> void:\n"
            "    print_str(pick(1))\n"
            "    print_str(pick(0))\n"
            "    print_str(\"end\")\n"
        )
        tmp = tempfile.mkdtemp(prefix='vanta_strret_')
        try:
            path = os.path.join(tmp, 'strret.vnt')
            with open(path, 'w', encoding='utf-8') as f:
                f.write(src)
            self._build_and_run(path, ['pos', '', 'end'])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def _build_sdl(self, source_path, tmp, cfg=None):
        cfg = cfg or SDL2
        name, path = find_cxx_compiler()
        prog, tc = _frontend_only(source_path)
        cpp = os.path.join(tmp, 'main.cpp')
        _emit_source(prog, tc, cpp)
        exe = os.path.join(tmp, 'prog.exe' if os.name == 'nt' else 'prog')
        from compiler.driver import _compiler_cmd
        cmd = _compiler_cmd(name, path, cpp, exe, release=True,
                            lib_dirs=cfg['lib_dirs'], libs=cfg['libs'])
        p = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, msg=p.stdout + p.stderr)
        return exe

    def test_sdl_examples_typecheck(self):
        # Pure frontend: needs no SDL2 at all, so it runs everywhere.
        # breakout.vnt imports seven of the nine gamekit modules, so this
        # also type-checks most of the kit's extern declarations.
        for fn in ('sdl_window.vnt', 'sdl_game.vnt', 'sdl_text.vnt', 'sdl_audio.vnt',
                   'sdl_audio_cb.vnt', 'sdl_texture.vnt', 'sdl_sound.vnt',
                   'sdl_gamepad.vnt', 'text_bench.vnt', 'pong.vnt', 'breakout.vnt'):
            _frontend_only(os.path.join(EXAMPLES, fn))

    @unittest.skipUnless(SDL2, "SDL2 not found")
    def test_sdl_window_headless(self):
        tmp = tempfile.mkdtemp(prefix='vanta_sdlwin_')
        try:
            exe = self._build_sdl(os.path.join(EXAMPLES, 'sdl_window.vnt'), tmp)
            env = dict(os.environ, SDL_VIDEODRIVER='dummy')
            r = subprocess.run([exe, '120'], capture_output=True, text=True, env=env)
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            self.assertEqual(r.stdout.strip().splitlines(), ['frames 120'])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    @unittest.skipUnless(SDL2, "SDL2 not found")
    def test_sdl_game_headless(self):
        # rand() is deterministic, the dummy driver produces no input, so the
        # whole simulation is reproducible: 600 frames, one catch, two misses.
        tmp = tempfile.mkdtemp(prefix='vanta_sdlgame_')
        try:
            exe = self._build_sdl(os.path.join(EXAMPLES, 'sdl_game.vnt'), tmp)
            env = dict(os.environ, SDL_VIDEODRIVER='dummy')
            r = subprocess.run([exe, '600'], capture_output=True, text=True, env=env)
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            self.assertEqual(r.stdout.strip().splitlines(), ['score 1 misses 2'])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    @unittest.skipUnless(SDL2_TTF, "SDL2_ttf not found")
    def test_pong_headless(self):
        # The second game, built on the game kit, now drawing its score with
        # the text module and beeping with the audio module, so it links
        # SDL2_ttf as well. With no input under the dummy drivers the AI
        # takes every point, and the whole run is reproducible: the AI wins
        # 5-0 in frame 576, well before the frame cap, so the cap never
        # fires — it is only the backstop.
        tmp = tempfile.mkdtemp(prefix='vanta_pong_')
        try:
            exe = self._build_sdl(os.path.join(EXAMPLES, 'pong.vnt'), tmp,
                                  cfg=SDL2_TTF)
            env = dict(os.environ, SDL_VIDEODRIVER='dummy',
                       SDL_AUDIODRIVER='dummy')
            r = subprocess.run([exe, '3000'], capture_output=True, text=True,
                               env=env, cwd=HERE)
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            self.assertEqual(r.stdout.strip().splitlines(),
                             ['player 0 ai 5 frames 576'])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    @unittest.skipUnless(SDL2_ALL, "SDL2 + SDL2_ttf + SDL2_image not found")
    def test_breakout_headless(self):
        # The third game: sprites, tinted brick rows, and WAV sound files.
        # With no input the paddle auto-pilot plays, and the whole run is
        # reproducible: the wall is cleared without losing a life, at frame
        # 2064, well before the frame cap — which is only the backstop.
        # cwd=HERE so the relative asset and font paths resolve.
        tmp = tempfile.mkdtemp(prefix='vanta_breakout_')
        try:
            exe = self._build_sdl(os.path.join(EXAMPLES, 'breakout.vnt'), tmp,
                                  cfg=SDL2_ALL)
            env = dict(os.environ, SDL_VIDEODRIVER='dummy',
                       SDL_AUDIODRIVER='dummy')
            r = subprocess.run([exe, '5000'], capture_output=True, text=True,
                               env=env, cwd=HERE)
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            self.assertEqual(r.stdout.strip().splitlines(),
                             ['cleared 40 lives 3 frames 2064'])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    @unittest.skipUnless(SDL2_TTF, "SDL2_ttf not found")
    def test_sdl_text_headless(self):
        # The raw SDL_ttf example: render one string per frame and keep
        # going; the frame count is the frozen output. cwd=HERE so the
        # relative path to the shipped font resolves.
        tmp = tempfile.mkdtemp(prefix='vanta_sdltext_')
        try:
            exe = self._build_sdl(os.path.join(EXAMPLES, 'sdl_text.vnt'), tmp,
                                  cfg=SDL2_TTF)
            env = dict(os.environ, SDL_VIDEODRIVER='dummy')
            r = subprocess.run([exe, '120'], capture_output=True, text=True,
                               env=env, cwd=HERE)
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            self.assertEqual(r.stdout.strip().splitlines(), ['frames 120'])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    @unittest.skipUnless(SDL2_TTF, "SDL_ttf not found")
    def test_text_bench_headless(self):
        # examples/text_bench.vnt is the measured before/after behind
        # TextSprite: it draws one string with text_draw and with a
        # pre-rendered sprite and prints the draw counts and milliseconds.
        # The counts are stable; the milliseconds are this machine's, so
        # the test checks the line shapes and never the numbers.
        tmp = tempfile.mkdtemp(prefix='vanta_textbench_')
        try:
            exe = self._build_sdl(os.path.join(EXAMPLES, 'text_bench.vnt'),
                                  tmp, cfg=SDL2_TTF)
            env = dict(os.environ, SDL_VIDEODRIVER='dummy')
            r = subprocess.run([exe, '200'], capture_output=True, text=True,
                               env=env, cwd=HERE)
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            lines = r.stdout.strip().splitlines()
            self.assertEqual(len(lines), 2)
            drawn = lines[0].split()
            self.assertEqual(drawn[:3], ['text_draw', '200', 'draws'])
            self.assertTrue(drawn[3].isdigit(), msg=lines[0])
            self.assertEqual(drawn[4], 'ms')
            sprite = lines[1].split()
            self.assertEqual(sprite[:5],
                             ['text_sprite', '1', 'render', '200', 'draws'])
            self.assertTrue(sprite[5].isdigit(), msg=lines[1])
            self.assertEqual(sprite[6], 'ms')
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    @unittest.skipUnless(SDL2_IMAGE, "SDL2_image not found")
    def test_sdl_texture_headless(self):
        # The raw SDL_image example: load PNG and BMP textures, tint, draw
        # a sheet region, flip and rotate, and check every draw by reading
        # the pixels back. The example force-picks the software renderer,
        # so the readbacks are exact everywhere. cwd=HERE so the relative
        # paths to the generated assets resolve.
        tmp = tempfile.mkdtemp(prefix='vanta_sdltex_')
        try:
            exe = self._build_sdl(os.path.join(EXAMPLES, 'sdl_texture.vnt'),
                                  tmp, cfg=SDL2_IMAGE)
            env = dict(os.environ, SDL_VIDEODRIVER='dummy')
            r = subprocess.run([exe], capture_output=True, text=True,
                               env=env, cwd=HERE)
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            self.assertEqual(r.stdout.strip().splitlines(),
                             ['loaded true', 'ball 10 10', 'paddle 44 10',
                              'ball centre true', 'ball corner true',
                              'tint true', 'sheet true', 'flipped true',
                              'rotated true'])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    @unittest.skipUnless(SDL2, "SDL2 not found")
    def test_sdl_audio_headless(self):
        # The raw queue-mode example: build an SDL_AudioSpec by hand with a
        # null callback, queue a synthesized 440 Hz tone, and let the dummy
        # audio driver play it out in real time. The obtained spec is the
        # requested one on every driver, so the values are safe to freeze.
        tmp = tempfile.mkdtemp(prefix='vanta_sdlaudio_')
        try:
            exe = self._build_sdl(os.path.join(EXAMPLES, 'sdl_audio.vnt'), tmp)
            env = dict(os.environ, SDL_AUDIODRIVER='dummy')
            r = subprocess.run([exe], capture_output=True, text=True, env=env)
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            self.assertEqual(r.stdout.strip().splitlines(),
                             ['opened true', 'rate 44100 channels 1',
                              'queued true', 'drained true'])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    @unittest.skipUnless(SDL2, "SDL2 not found")
    def test_sdl_audio_callback_headless(self):
        # The callback-mode example: a Vanta function lives inside the
        # SDL_AudioSpec and SDL runs it on its audio thread. Only booleans
        # are frozen — how many times the callback runs depends on the
        # machine; the samples per call are the requested buffer.
        tmp = tempfile.mkdtemp(prefix='vanta_sdlcbaudio_')
        try:
            exe = self._build_sdl(os.path.join(EXAMPLES, 'sdl_audio_cb.vnt'), tmp)
            env = dict(os.environ, SDL_AUDIODRIVER='dummy')
            r = subprocess.run([exe], capture_output=True, text=True, env=env)
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            self.assertEqual(r.stdout.strip().splitlines(),
                             ['opened true', 'callbacks ran true',
                              'samples per call 1024'])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    @unittest.skipUnless(SDL2, "SDL2 not found")
    def test_sdl_sound_headless(self):
        # The raw WAV example: SDL_LoadWAV_RW pulls examples/assets/blip.wav
        # into a buffer SDL allocates, the queue API plays it, SDL_FreeWAV
        # gives the buffer back. The spec of a known file is safe to freeze;
        # cwd=HERE so the relative path resolves.
        tmp = tempfile.mkdtemp(prefix='vanta_sdlsound_')
        try:
            exe = self._build_sdl(os.path.join(EXAMPLES, 'sdl_sound.vnt'), tmp)
            env = dict(os.environ, SDL_AUDIODRIVER='dummy')
            r = subprocess.run([exe], capture_output=True, text=True,
                               env=env, cwd=HERE)
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            self.assertEqual(r.stdout.strip().splitlines(),
                             ['opened true', 'loaded true',
                              'sample rate 44100 channels 1', 'pcm16 true',
                              'bytes 5292', 'queued true', 'pending true',
                              'drained true'])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    @unittest.skipUnless(SDL2, "SDL2 not found")
    def test_sdl_gamepad_headless(self):
        # The raw controller example: SDL_GameControllerOpen at an index no
        # machine has returns NULL, so the program reports the dead path and
        # exits cleanly. Index 9999 keeps the frozen output independent of
        # whether real hardware is attached.
        tmp = tempfile.mkdtemp(prefix='vanta_sdlpad_')
        try:
            exe = self._build_sdl(os.path.join(EXAMPLES, 'sdl_gamepad.vnt'), tmp)
            env = dict(os.environ, SDL_VIDEODRIVER='dummy')
            r = subprocess.run([exe, '9999'], capture_output=True, text=True,
                               env=env, cwd=HERE)
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            self.assertEqual(r.stdout.strip().splitlines(),
                             ['false', 'no controller at index 9999'])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    @unittest.skipUnless(SDL2, "SDL2 not found")
    def test_gamekit_audio(self):
        # gamekit/audio.vnt: the copy puts the relative imports where the
        # probe program can reach them. The probe opens the device, queues
        # a tone and waits for the dummy driver to play it out, then walks
        # the guards: a nonsense frequency queues nothing, and a tone
        # longer than the caller's buffer is cut to its capacity. 3528
        # samples is exactly 80 ms at 44.1 kHz.
        tmp = tempfile.mkdtemp(prefix='vanta_kitaudio_')
        try:
            shutil.copytree(os.path.join(EXAMPLES, 'gamekit'),
                            os.path.join(tmp, 'gamekit'))
            path = os.path.join(tmp, 'prog.vnt')
            with open(path, 'w', encoding='utf-8') as f:
                f.write('import "gamekit/audio.vnt"\n'
                        '\n'
                        'func main() -> void:\n'
                        '    let audio = audio_open()\n'
                        '    print_bool(audio_ok(audio))\n'
                        '    if not audio_ok(audio):\n'
                        '        return\n'
                        '    print_i32(audio.rate)\n'
                        '    let arena = Arena(32768)\n'
                        '    let buf = arena.alloc::<i16>(11025)\n'
                        '    print_i32(audio_play_tone(audio, 880, 80, buf, 11025))\n'
                        '    print_bool(audio_pending(audio) > 0)\n'
                        '    audio_wait(audio)\n'
                        '    print_bool(audio_pending(audio) == 0)\n'
                        '    print_i32(audio_play_tone(audio, 0, 50, buf, 11025))\n'
                        '    print_i32(audio_play_tone(audio, 880, 80, buf, 100))\n'
                        '    audio_wait(audio)\n'
                        '    audio_close(audio)\n')
            exe = self._build_sdl(path, tmp)
            env = dict(os.environ, SDL_AUDIODRIVER='dummy')
            r = subprocess.run([exe], capture_output=True, text=True, env=env)
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            self.assertEqual(r.stdout.strip().splitlines(),
                             ['true', '44100', '3528', 'true', 'true',
                              '0', '100'])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    @unittest.skipUnless(SDL2_IMAGE, "SDL2_image not found")
    def test_gamekit_texture(self):
        # gamekit/image.vnt textures: load PNG and BMP, read the sizes
        # back, draw whole / sheet-region / rotated-flipped, tint and fade,
        # and walk the guards — a missing file loads dead, and drawing a
        # dead texture is a no-op, not a crash. The copy puts the relative
        # imports and the assets where the probe program can reach them.
        tmp = tempfile.mkdtemp(prefix='vanta_kittex_')
        try:
            shutil.copytree(os.path.join(EXAMPLES, 'gamekit'),
                            os.path.join(tmp, 'gamekit'))
            shutil.copytree(os.path.join(EXAMPLES, 'assets'),
                            os.path.join(tmp, 'assets'))
            path = os.path.join(tmp, 'prog.vnt')
            with open(path, 'w', encoding='utf-8') as f:
                f.write('import "gamekit/sdl.vnt"\n'
                        'import "gamekit/gfx.vnt"\n'
                        'import "gamekit/image.vnt"\n'
                        '\n'
                        'func main() -> void:\n'
                        '    let screen = screen_open("kit texture", 64, 64)\n'
                        '    print_bool(screen_ok(screen))\n'
                        '    let ball = tex_load(screen, "assets/ball.png")\n'
                        '    let paddle = tex_load(screen, "assets/paddle.bmp")\n'
                        '    let tiles = tex_load(screen, "assets/tiles.png")\n'
                        '    print_bool(tex_ok(ball) and tex_ok(paddle) and tex_ok(tiles))\n'
                        '    print_i32(ball.w)\n'
                        '    print_i32(ball.h)\n'
                        '    print_i32(paddle.w)\n'
                        '    print_i32(paddle.h)\n'
                        '    let missing = tex_load(screen, "assets/nope.png")\n'
                        '    print_bool(tex_ok(missing))\n'
                        '    tex_tint(tiles, 200, 100, 50)\n'
                        '    tex_alpha(tiles, 200)\n'
                        '    gfx_clear(screen, 0, 0, 0)\n'
                        '    tex_draw(screen, ball, 4, 4)\n'
                        '    tex_draw(screen, missing, 4, 40)\n'
                        '    tex_draw_src(screen, tiles, 0, 0, 16, 16, 20, 4)\n'
                        '    tex_draw_ex(screen, paddle, 4, 60, 45.0, SDL_FLIP_HORIZONTAL)\n'
                        '    gfx_present(screen)\n'
                        '    print_str("drawn")\n'
                        '    tex_free(ball)\n'
                        '    tex_free(missing)\n'
                        '    tex_free(paddle)\n'
                        '    tex_free(tiles)\n'
                        '    screen_close(screen)\n')
            exe = self._build_sdl(path, tmp, cfg=SDL2_IMAGE)
            env = dict(os.environ, SDL_VIDEODRIVER='dummy')
            r = subprocess.run([exe], capture_output=True, text=True,
                               env=env, cwd=tmp)
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            self.assertEqual(r.stdout.strip().splitlines(),
                             ['true', 'true', '10', '10', '44', '10',
                              'false', 'drawn'])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    @unittest.skipUnless(SDL2_IMAGE, "SDL2_image not found")
    def test_gamekit_animation(self):
        # gamekit/anim.vnt: a frame clock over tex_draw_src. The step is
        # 0.125 s at 8 fps, so each tick advances exactly one frame and the
        # frozen numbers cannot drift; a dead texture and an empty clock are
        # guarded no-ops. The copy puts the kit and the sheet where the
        # probe's relative paths can reach them.
        tmp = tempfile.mkdtemp(prefix='vanta_kitanim_')
        try:
            shutil.copytree(os.path.join(EXAMPLES, 'gamekit'),
                            os.path.join(tmp, 'gamekit'))
            shutil.copytree(os.path.join(EXAMPLES, 'assets'),
                            os.path.join(tmp, 'assets'))
            path = os.path.join(tmp, 'prog.vnt')
            with open(path, 'w', encoding='utf-8') as f:
                f.write('import "gamekit/sdl.vnt"\n'
                        'import "gamekit/gfx.vnt"\n'
                        'import "gamekit/image.vnt"\n'
                        'import "gamekit/anim.vnt"\n'
                        '\n'
                        'func main() -> void:\n'
                        '    let screen = screen_open("kit anim", 64, 64)\n'
                        '    print_bool(screen_ok(screen))\n'
                        '    let spin = tex_load(screen, "assets/ball_spin.png")\n'
                        '    print_bool(tex_ok(spin))\n'
                        '    print_fmt("{}x{}", spin.w, spin.h)\n'
                        '    mut a = anim_new(4, 10, 10, 8.0)\n'
                        '    for i in range(0, 8):\n'
                        '        a = anim_tick(a, 0.125)\n'
                        '        print_i32(anim_frame(a))\n'
                        '    print_i32(a.count)\n'
                        '    gfx_clear(screen, 0, 0, 0)\n'
                        '    anim_draw(screen, spin, a, 4, 4)\n'
                        '    gfx_present(screen)\n'
                        '    let dead = tex_load(screen, "assets/nope.png")\n'
                        '    anim_draw(screen, dead, a, 0, 0)\n'
                        '    let empty = anim_new(0, 10, 10, 8.0)\n'
                        '    print_i32(anim_frame(anim_tick(empty, 1.0)))\n'
                        '    tex_free(spin)\n'
                        '    tex_free(dead)\n'
                        '    screen_close(screen)\n'
                        '    print_str("drawn")\n')
            exe = self._build_sdl(path, tmp, cfg=SDL2_IMAGE)
            env = dict(os.environ, SDL_VIDEODRIVER='dummy')
            r = subprocess.run([exe], capture_output=True, text=True,
                               env=env, cwd=tmp)
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            self.assertEqual(r.stdout.strip().splitlines(),
                             ['true', 'true', '40x10',
                              '1', '2', '3', '0', '1', '2', '3', '0',
                              '4', '0', 'drawn'])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    @unittest.skipUnless(SDL2, "SDL2 not found")
    def test_gamekit_sound(self):
        # gamekit/audio.vnt sound files: a 44.1 kHz mono WAV loads and
        # plays at full length; a stereo one folds to mono in place (half
        # the bytes); a wrong-rate file and a missing file load dead, and
        # freeing a dead sound is harmless. The stereo and low-rate files
        # are written here; the copy puts the kit where the probe can
        # reach it.
        tmp = tempfile.mkdtemp(prefix='vanta_kitsnd_')
        try:
            shutil.copytree(os.path.join(EXAMPLES, 'gamekit'),
                            os.path.join(tmp, 'gamekit'))
            os.makedirs(os.path.join(tmp, 'snd'))
            shutil.copy(os.path.join(EXAMPLES, 'assets', 'blip.wav'),
                        os.path.join(tmp, 'snd', 'blip.wav'))
            _write_wav(os.path.join(tmp, 'snd', 'stereo.wav'),
                       [8000, 4000] * 1000, 2, 44100)
            _write_wav(os.path.join(tmp, 'snd', 'lowrate.wav'),
                       [0] * 2205, 1, 22050)
            path = os.path.join(tmp, 'prog.vnt')
            with open(path, 'w', encoding='utf-8') as f:
                f.write('import "gamekit/audio.vnt"\n'
                        '\n'
                        'func main() -> void:\n'
                        '    let audio = audio_open()\n'
                        '    print_bool(audio_ok(audio))\n'
                        '    if not audio_ok(audio):\n'
                        '        return\n'
                        '    let good = sound_load(audio, "snd/blip.wav")\n'
                        '    print_bool(sound_ok(good))\n'
                        '    print_i32(good.len)\n'
                        '    print_bool(sound_play(audio, good))\n'
                        '    print_bool(audio_pending(audio) > 0)\n'
                        '    audio_wait(audio)\n'
                        '    print_bool(audio_pending(audio) == 0)\n'
                        '    let stereo = sound_load(audio, "snd/stereo.wav")\n'
                        '    print_bool(sound_ok(stereo))\n'
                        '    print_i32(stereo.len)\n'
                        '    let lowrate = sound_load(audio, "snd/lowrate.wav")\n'
                        '    print_bool(sound_ok(lowrate))\n'
                        '    let missing = sound_load(audio, "snd/nope.wav")\n'
                        '    print_bool(sound_ok(missing))\n'
                        '    sound_free(good)\n'
                        '    sound_free(stereo)\n'
                        '    sound_free(lowrate)\n'
                        '    sound_free(missing)\n'
                        '    audio_close(audio)\n')
            exe = self._build_sdl(path, tmp)
            env = dict(os.environ, SDL_AUDIODRIVER='dummy')
            r = subprocess.run([exe], capture_output=True, text=True,
                               env=env, cwd=tmp)
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            self.assertEqual(r.stdout.strip().splitlines(),
                             ['true', 'true', '5292', 'true', 'true', 'true',
                              'true', '2000', 'false', 'false'])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    @unittest.skipUnless(SDL2, "SDL2 not found")
    def test_gamekit_gamepad(self):
        # gamekit/gamepad.vnt: an out-of-range index opens dead, and every
        # accessor is a guarded no-op on a dead pad (false / 0), so the test
        # is deterministic with or without a controller plugged in. The copy
        # puts the kit where the probe's relative import can reach it.
        tmp = tempfile.mkdtemp(prefix='vanta_kitpad_')
        try:
            shutil.copytree(os.path.join(EXAMPLES, 'gamekit'),
                            os.path.join(tmp, 'gamekit'))
            path = os.path.join(tmp, 'prog.vnt')
            with open(path, 'w', encoding='utf-8') as f:
                f.write('import "gamekit/sdl.vnt"\n'
                        'import "gamekit/gamepad.vnt"\n'
                        '\n'
                        'func main() -> void:\n'
                        '    let screen = screen_open("kit gamepad", 64, 64)\n'
                        '    print_bool(screen_ok(screen))\n'
                        '    let pad = pad_open(9999)\n'
                        '    print_bool(pad_ok(pad))\n'
                        '    print_bool(pad_attached(pad))\n'
                        '    print_bool(pad_button(pad, PAD_BUTTON_A))\n'
                        '    print_i32(pad_axis(pad, PAD_AXIS_LEFT_X))\n'
                        '    pad_close(pad)\n'
                        '    print_str("closed")\n'
                        '    screen_close(screen)\n')
            exe = self._build_sdl(path, tmp)
            env = dict(os.environ, SDL_VIDEODRIVER='dummy')
            r = subprocess.run([exe], capture_output=True, text=True,
                               env=env, cwd=tmp)
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            self.assertEqual(r.stdout.strip().splitlines(),
                             ['true', 'false', 'false', 'false', '0', 'closed'])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_gamekit_rng(self):
        # gamekit/rng.vnt stands alone (no SDL), so this slice of the kit
        # runs on every machine that has a C++ compiler. The copy puts the
        # relative import where the probe program can reach it; the frozen
        # values are the deterministic stream.
        tmp = tempfile.mkdtemp(prefix='vanta_kitrng_')
        try:
            shutil.copytree(os.path.join(EXAMPLES, 'gamekit'),
                            os.path.join(tmp, 'gamekit'))
            path = os.path.join(tmp, 'prog.vnt')
            with open(path, 'w', encoding='utf-8') as f:
                f.write('import "gamekit/rng.vnt"\n'
                        '\n'
                        'func main() -> void:\n'
                        '    print_i32(rand_int(1, 6))\n'
                        '    print_i32(rand_int(1, 6))\n'
                        '    print_i32(rand_int(1, 6))\n'
                        '    print_f32(rand_range_f32(0.0, 1.0))\n'
                        '    print_i32(rand_sign())\n'
                        '    print_i32(rand_sign())\n')
            self._build_and_run(path, ['4', '3', '1', '0.701852', '-1', '1'])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    @unittest.skipUnless(SDL2_TTF, "SDL2_ttf not found")
    def test_gamekit_text(self):
        # gamekit/text.vnt on top of the kit's Screen: the copy puts the
        # relative imports and the shipped font where the probe program can
        # reach them (it runs with cwd=tmp). The probe measures, draws, and
        # also exercises the failure paths: a font that will not open
        # measures 0x0 and draws nothing instead of crashing.
        tmp = tempfile.mkdtemp(prefix='vanta_kittext_')
        try:
            shutil.copytree(os.path.join(EXAMPLES, 'gamekit'),
                            os.path.join(tmp, 'gamekit'))
            path = os.path.join(tmp, 'prog.vnt')
            with open(path, 'w', encoding='utf-8') as f:
                f.write('import "gamekit/sdl.vnt"\n'
                        'import "gamekit/text.vnt"\n'
                        '\n'
                        'func main() -> void:\n'
                        '    let screen = screen_open("text", 320, 240)\n'
                        '    if not screen_ok(screen):\n'
                        '        print_str("no screen")\n'
                        '        return\n'
                        '    let font = font_open("gamekit/fonts/tom-thumb.ttf", 32)\n'
                        '    print_bool(font_ok(font))\n'
                        '    let arena = Arena(512)\n'
                        '    let scratch = arena.alloc::<i32>(10)\n'
                        '    text_measure(font, "Score: 12", scratch)\n'
                        '    print_bool(scratch[0] > 0)\n'
                        '    print_bool(scratch[1] > 0)\n'
                        '    text_draw(screen, font, 16, 16, "Score: 12", scratch, 255, 255, 255)\n'
                        '    text_draw(screen, font, 9999, 9999, "offscreen", scratch, 255, 0, 0)\n'
                        '    let missing = font_open("no-such-font.ttf", 16)\n'
                        '    print_bool(font_ok(missing))\n'
                        '    text_measure(missing, "x", scratch)\n'
                        '    print_i32(scratch[0])\n'
                        '    text_draw(screen, missing, 0, 0, "x", scratch, 255, 255, 255)\n'
                        '    print_str("drawn")\n'
                        '    font_close(font)\n'
                        '    text_quit()\n'
                        '    screen_close(screen)\n')
            name, cpath = find_cxx_compiler()
            prog, tc = _frontend_only(path)
            cpp = os.path.join(tmp, 'main.cpp')
            _emit_source(prog, tc, cpp)
            exe = os.path.join(tmp, 'prog.exe' if os.name == 'nt' else 'prog')
            from compiler.driver import _compiler_cmd
            cmd = _compiler_cmd(name, cpath, cpp, exe, release=True,
                                lib_dirs=SDL2_TTF['lib_dirs'],
                                libs=SDL2_TTF['libs'])
            p = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, msg=p.stdout + p.stderr)
            env = dict(os.environ, SDL_VIDEODRIVER='dummy')
            r = subprocess.run([exe], capture_output=True, text=True,
                               env=env, cwd=tmp)
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            self.assertEqual(r.stdout.strip().splitlines(),
                             ['true', 'true', 'true', 'false', '0', 'drawn'])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    @unittest.skipUnless(SDL2_TTF, "SDL_ttf not found")
    def test_gamekit_text_sprite(self):
        # gamekit/text.vnt's TextSprite: render once, draw many times. The
        # copy puts the relative imports and the shipped font where the
        # probe can reach them (it runs with cwd=tmp). The sprite's size
        # matches text_measure, a failed font and an empty string both
        # render dead, a dead sprite draws nothing, and a sprite can be
        # freed and rendered again.
        tmp = tempfile.mkdtemp(prefix='vanta_kitsprite_')
        try:
            shutil.copytree(os.path.join(EXAMPLES, 'gamekit'),
                            os.path.join(tmp, 'gamekit'))
            path = os.path.join(tmp, 'prog.vnt')
            with open(path, 'w', encoding='utf-8') as f:
                f.write('import "gamekit/sdl.vnt"\n'
                        'import "gamekit/text.vnt"\n'
                        '\n'
                        'func main() -> void:\n'
                        '    let screen = screen_open("text sprite", 320, 240)\n'
                        '    if not screen_ok(screen):\n'
                        '        print_str("no screen")\n'
                        '        return\n'
                        '    let font = font_open("gamekit/fonts/tom-thumb.ttf", 32)\n'
                        '    print_bool(font_ok(font))\n'
                        '    let sprite = text_sprite(screen, font, "Score: 12", 255, 255, 255)\n'
                        '    print_bool(text_sprite_ok(sprite))\n'
                        '    let arena = Arena(64)\n'
                        '    let scratch = arena.alloc::<i32>(10)\n'
                        '    text_measure(font, "Score: 12", scratch)\n'
                        '    print_bool(sprite.w == scratch[0] and sprite.h == scratch[1])\n'
                        '    text_sprite_draw(screen, sprite, 16, 16)\n'
                        '    text_sprite_free(sprite)\n'
                        '    let again = text_sprite(screen, font, "Score: 12", 200, 200, 200)\n'
                        '    print_bool(text_sprite_ok(again))\n'
                        '    text_sprite_draw(screen, again, 16, 48)\n'
                        '    text_sprite_free(again)\n'
                        '    let missing = font_open("no-such-font.ttf", 16)\n'
                        '    let dead = text_sprite(screen, missing, "x", 255, 255, 255)\n'
                        '    print_bool(text_sprite_ok(dead))\n'
                        '    text_sprite_draw(screen, dead, 0, 0)\n'
                        '    text_sprite_free(dead)\n'
                        '    font_close(missing)\n'
                        '    let empty = text_sprite(screen, font, "", 255, 255, 255)\n'
                        '    print_bool(text_sprite_ok(empty))\n'
                        '    text_sprite_free(empty)\n'
                        '    font_close(font)\n'
                        '    text_quit()\n'
                        '    screen_close(screen)\n'
                        '    print_str("drawn")\n')
            exe = self._build_sdl(path, tmp, cfg=SDL2_TTF)
            env = dict(os.environ, SDL_VIDEODRIVER='dummy')
            r = subprocess.run([exe], capture_output=True, text=True,
                               env=env, cwd=tmp)
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            self.assertEqual(r.stdout.strip().splitlines(),
                             ['true', 'true', 'true', 'true',
                              'false', 'false', 'drawn'])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    # ---------- v0.17.0: narrow ints, enum extern, ptr_cast, for-each -----

    def _build_c_fixture(self, tmp, *sources):
        """Compile C sources from examples/ into libfixture.a in tmp and
        return the library name for _compiler_cmd. Skips when a C toolchain
        or ar is missing, or when the C++ compiler is MSVC (which cannot
        link a GNU archive)."""
        ar = shutil.which('ar')
        if ar is None:
            self.skipTest('ar not available (needed to archive the C fixture)')
        cc = shutil.which('gcc') or shutil.which('clang') or shutil.which('cc')
        if cc is None:
            self.skipTest('no C compiler available for the fixture')
        name, _path = find_cxx_compiler()
        if _is_msvc(name):
            self.skipTest('fixture is a GNU archive (libfixture.a); '
                          'MSVC would need a .lib fixture')
        objs = []
        for src in sources:
            obj = os.path.join(tmp, os.path.basename(src) + '.o')
            p = subprocess.run([cc, '-c', os.path.join(EXAMPLES, src), '-o', obj],
                               capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, msg=p.stdout + p.stderr)
            objs.append(obj)
        lib = os.path.join(tmp, 'libfixture.a')
        p = subprocess.run([ar, 'rcs', lib] + objs, capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, msg=p.stdout + p.stderr)
        return 'fixture'

    def _build_example_linked(self, example, tmp, libs):
        name, path = find_cxx_compiler()
        prog, tc = _frontend_only(os.path.join(EXAMPLES, example))
        cpp = os.path.join(tmp, 'main.cpp')
        _emit_source(prog, tc, cpp)
        exe = os.path.join(tmp, 'prog.exe' if os.name == 'nt' else 'prog')
        from compiler.driver import _compiler_cmd
        cmd = _compiler_cmd(name, path, cpp, exe, release=True,
                            lib_dirs=[tmp], libs=libs)
        p = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, msg=p.stdout + p.stderr)
        return exe

    def test_narrow_ints_example(self):
        # Exact-width storage, C-ABI parameters, and struct layout: the C
        # fixture declares int8_t/uint8_t/int16_t/uint16_t parameters, and
        # reads a Vanta Pixel through a mirror struct — the widths have to
        # line up byte for byte for the sums to come out right.
        tmp = tempfile.mkdtemp(prefix='vanta_narrow_')
        try:
            lib = self._build_c_fixture(tmp, 'narrow_ints_lib.c')
            exe = self._build_example_linked('narrow_ints.vnt', tmp, [lib])
            r = subprocess.run([exe], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            self.assertEqual(r.stdout.strip().splitlines(),
                             ['325', '4000000000', '44', '0', '59700',
                              '65', '66', '44', '4', '255', '44', '77',
                              '325', '4000000000'])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_enums_extern_example(self):
        # C takes and returns the enum as a plain int32_t; the Vanta side
        # declares it as Light. The C symbol has a plain-int signature, so
        # this also pins the enum ABI.
        tmp = tempfile.mkdtemp(prefix='vanta_enumext_')
        try:
            lib = self._build_c_fixture(tmp, 'enums_extern_lib.c')
            exe = self._build_example_linked('enums_extern.vnt', tmp, [lib])
            r = subprocess.run([exe], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            self.assertEqual(r.stdout.strip().splitlines(),
                             ['true', 'true', 'dim', 'true', '2'])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_ptr_cast_example(self):
        self._build_and_run(os.path.join(EXAMPLES, 'ptr_cast.vnt'),
                            ['3.141593', '1078530011'])

    def test_foreach_example(self):
        self._build_and_run(os.path.join(EXAMPLES, 'foreach.vnt'),
                            ['8', '2', '3', '5', '7', '10', '20', '3',
                             'torch=12', 'rope=5'])

    def test_struct_eq_example(self):
        self._build_and_run(os.path.join(EXAMPLES, 'struct_eq.vnt'),
                            ['true', 'true', 'true', 'false', 'true'])

    # ---------- v0.18.0: pointer offsets -----------------------------------

    def test_ptr_offset_example(self):
        self._build_and_run(os.path.join(EXAMPLES, 'ptr_offset.vnt'),
                            ['30', '16', '9', '7'])


if __name__ == '__main__':
    unittest.main()