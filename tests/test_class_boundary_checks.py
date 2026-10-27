import os, sys, subprocess, tempfile, shutil, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from compiler.driver import find_cxx_compiler, _frontend_only, _emit_source, _compiler_cmd


def _compiler_available():
    return find_cxx_compiler()[1] is not None


class ClassBoundaryChecks(unittest.TestCase):
    def setUp(self):
        if not _compiler_available():
            self.skipTest('no C++ compiler on PATH')
        self.tmp = tempfile.mkdtemp(prefix='vanta_class_boundary_')

    def tearDown(self):
        if os.path.isdir(self.tmp):
            shutil.rmtree(self.tmp, ignore_errors=True)

    def src_path(self):
        return os.path.join(self.tmp, 'main.vnt')

    def write(self, source):
        with open(self.src_path(), 'w', encoding='utf-8', newline='\n') as f:
            f.write(source)

    def build_and_run(self):
        name, path = find_cxx_compiler()
        prog, tc = _frontend_only(self.src_path())
        cpp = os.path.join(self.tmp, 'main.cpp')
        _emit_source(prog, tc, cpp)
        exe = os.path.join(self.tmp, 'prog.exe' if os.name == 'nt' else 'prog')
        cmd = _compiler_cmd(
            name, path, cpp, exe, release=True)
        built = subprocess.run(cmd, capture_output=True, text=True)
        if built.returncode != 0:
            raise RuntimeError('build failed:\n' + built.stdout + built.stderr)
        run = subprocess.run([exe], capture_output=True, text=True)
        if run.returncode != 0:
            raise RuntimeError('run failed:\n' + run.stderr)
        return run.stdout.strip().replace('\r', '')

    def expect(self, source, wanted):
        self.write(source)
        self.assertEqual(self.build_and_run(), wanted)

    def test_virtual_dispatch_with_reverse_type_name_order(self):
        self.expect(
            "class Zoo:\n"
            "    tag: i32\n"
            "    func label(self: ptr<Zoo>) -> i32:\n"
            "        return self.tag\n\n"
            "class Aardvark extends Zoo:\n"
            "    extra: i32\n"
            "    func label(self: ptr<Aardvark>) -> i32:\n"
            "        return self.tag * 10 + self.extra\n\n"
            "class Zebra extends Zoo:\n"
            "    stripes: i32\n"
            "    func label(self: ptr<Zebra>) -> i32:\n"
            "        return self.tag * 100 + self.stripes\n\n"
            "func report(p: ptr<Zoo>) -> i32:\n"
            "    return p.label()\n\n"
            "func main() -> void:\n"
            "    let arena = Arena(2048)\n"
            "    let a = arena.alloc::<Aardvark>(1)\n"
            "    a.tag = 2\n"
            "    a.extra = 3\n"
            "    let z = arena.alloc::<Zebra>(1)\n"
            "    z.tag = 5\n"
            "    z.stripes = 7\n"
            "    let base = arena.alloc::<Zoo>(1)\n"
            "    base.tag = 11\n"
            "    print_i32(report(ptr_cast::<Zoo>(a)))\n"
            "    print_i32(report(ptr_cast::<Zoo>(z)))\n"
            "    print_i32(report(ptr_cast::<Zoo>(base)))\n",
            "23\n507\n11")

    def test_virtual_dispatch_three_level_hierarchy_dispatches_to_leaf(self):
        self.expect(
            "class Animal:\n"
            "    x: i32\n"
            "    func score(self: ptr<Animal>) -> i32:\n"
            "        return self.x\n\n"
            "class Mammal extends Animal:\n"
            "    y: i32\n"
            "    func score(self: ptr<Mammal>) -> i32:\n"
            "        return self.x * 10 + self.y\n\n"
            "class Dog extends Mammal:\n"
            "    z: i32\n"
            "    func score(self: ptr<Dog>) -> i32:\n"
            "        return self.x * 100 + self.y * 10 + self.z\n\n"
            "func assess(p: ptr<Animal>) -> i32:\n"
            "    return p.score()\n\n"
            "func main() -> void:\n"
            "    let arena = Arena(4096)\n"
            "    let animal = arena.alloc::<Animal>(1)\n"
            "    animal.x = 1\n"
            "    let mammal = arena.alloc::<Mammal>(1)\n"
            "    mammal.x = 2\n"
            "    mammal.y = 3\n"
            "    let dog = arena.alloc::<Dog>(1)\n"
            "    dog.x = 4\n"
            "    dog.y = 5\n"
            "    dog.z = 6\n"
            "    print_i32(assess(ptr_cast::<Animal>(animal)))\n"
            "    print_i32(assess(ptr_cast::<Animal>(mammal)))\n"
            "    print_i32(assess(ptr_cast::<Animal>(dog)))\n",
            "1\n23\n456")

    def test_virtual_dispatch_repeated_calls_keep_branch_return_paths(self):
        self.expect(
            "class Engine:\n"
            "    n: i32\n"
            "    func run(self: ptr<Engine>) -> i32:\n"
            "        return 1\n\n"
            "class FastEngine extends Engine:\n"
            "    factor: i32\n"
            "    func run(self: ptr<FastEngine>) -> i32:\n"
            "        return self.n * self.factor\n\n"
            "class SlowEngine extends Engine:\n"
            "    extra: i32\n"
            "    func run(self: ptr<SlowEngine>) -> i32:\n"
            "        return self.n + self.extra\n\n"
            "func benchmark(e: ptr<Engine>, calls: i32) -> i32:\n"
            "    mut sum: i32 = 0\n"
            "    mut i: i32 = 0\n"
            "    while i < calls:\n"
            "        sum = sum + e.run()\n"
            "        i = i + 1\n"
            "    return sum\n\n"
            "func main() -> void:\n"
            "    let arena = Arena(2048)\n"
            "    let fast = arena.alloc::<FastEngine>(1)\n"
            "    fast.n = 4\n"
            "    fast.factor = 5\n"
            "    let slow = arena.alloc::<SlowEngine>(1)\n"
            "    slow.n = 4\n"
            "    slow.extra = 2\n"
            "    print_i32(benchmark(ptr_cast::<Engine>(fast), 3))\n"
            "    print_i32(benchmark(ptr_cast::<Engine>(slow), 3))\n"
            "    print_i32(benchmark(ptr_cast::<Engine>(arena.alloc::<Engine>(1)), 3))\n",
            "60\n18\n3")

    def test_codegen_virtual_type_identifiers_are_self_consistent(self):
        source = (
            "class Zoo:\n"
            "    tag: i32\n"
            "    func label(self: ptr<Zoo>) -> i32:\n"
            "        return self.tag\n\n"
            "class Aardvark extends Zoo:\n"
            "    extra: i32\n"
            "    func label(self: ptr<Aardvark>) -> i32:\n"
            "        return self.tag * 10 + self.extra\n\n"
            "class Zebra extends Zoo:\n"
            "    stripes: i32\n"
            "    func label(self: ptr<Zebra>) -> i32:\n"
            "        return self.tag * 100 + self.stripes\n\n"
            "func report(p: ptr<Zoo>) -> i32:\n"
            "    return p.label()\n\n"
            "func main() -> void:\n"
            "    return\n")
        self.write(source)
        name, path = find_cxx_compiler()
        prog, tc = _frontend_only(self.src_path())
        cpp = os.path.join(self.tmp, 'main.cpp')
        _emit_source(prog, tc, cpp)
        text = open(cpp, encoding='utf-8').read()
        compact = ' '.join(text.split())
        for type_name in ("Zoo", "Aardvark", "Zebra"):
            self.assertIn("inline constexpr int32_t VANTA_TYPE_ID_" + type_name + " =",
                          text)
            self.assertIn("v__vanta_runtime_type = VANTA_TYPE_ID_" + type_name + ";",
                          compact)
        self.assertIn("case VANTA_TYPE_ID_Aardvark:", text)
        self.assertIn("case VANTA_TYPE_ID_Zebra:", text)
        self.assertIn("VANTA_TYPE_ID_Zoo", text)


if __name__ == "__main__":
    unittest.main()
