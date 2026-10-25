import os, sys, subprocess, tempfile, shutil, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from compiler.driver import find_cxx_compiler, _frontend_only, _emit_source, _compiler_cmd
from compiler.type_checker import CheckError


HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _have_compiler():
    return find_cxx_compiler()[1] is not None


class ClassesTests(unittest.TestCase):
    def setUp(self):
        if not _have_compiler():
            self.skipTest('no C++ compiler on PATH')
        self.tmp = tempfile.mkdtemp(prefix='vanta_classes_test_')
        self.src = os.path.join(self.tmp, 't.vnt')

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def src_write(self, text):
        with open(self.src, 'w', encoding='utf-8') as f:
            f.write(text)

    def _build_and_run(self):
        name, path = find_cxx_compiler()
        prog, tc = _frontend_only(self.src)
        cpp = os.path.join(self.tmp, 'main.cpp')
        _emit_source(prog, tc, cpp)
        exe = os.path.join(self.tmp, 'prog.exe' if os.name == 'nt' else 'prog')
        cmd = _compiler_cmd(name, path, cpp, exe, release=True)
        p = subprocess.run(cmd, capture_output=True, text=True)
        if p.returncode != 0:
            raise RuntimeError(f"build failed:\n{p.stdout}\n{p.stderr}")
        r = subprocess.run([exe], capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"run failed:\n{r.stderr}")
        return r.stdout.strip().replace('\r', '')

    def expect(self, text, want):
        self.src_write(text)
        self.assertEqual(self._build_and_run(), want)

    def compile_fail(self, text, needle):
        self.src_write(text)
        try:
            name, path = find_cxx_compiler()
            prog, tc = _frontend_only(self.src)
            cpp = os.path.join(self.tmp, 'main.cpp')
            _emit_source(prog, tc, cpp)
            exe = os.path.join(self.tmp, 'prog.exe' if os.name == 'nt' else 'prog')
            cmd = _compiler_cmd(name, path, cpp, exe, release=True)
            p = subprocess.run(cmd, capture_output=True, text=True)
            if p.returncode == 0:
                subprocess.run([exe], capture_output=True, text=True)
        except CheckError as e:
            self.assertIn(needle, str(e))
        else:
            self.fail("expected CheckError, but compilation succeeded")

    def test_basic_field_read(self):
        self.expect(
            "class Foo:\n    x: i32\n\n"
            "func main() -> void:\n"
            "    mut f = Foo(x: 7)\n"
            "    print_i32(f.x)\n",
            "7")

    def test_field_write(self):
        self.expect(
            "class Foo:\n    x: i32\n\n"
            "func main() -> void:\n"
            "    mut f = Foo(x: 1)\n"
            "    f.x = 41\n"
            "    print_i32(f.x)\n",
            "41")

    def test_method_read(self):
        self.expect(
            "class Foo:\n    x: i32\n"
            "    func get(self: ptr<Foo>) -> i32:\n"
            "        return self.x\n\n"
            "func main() -> void:\n"
            "    mut f = Foo(x: 10)\n"
            "    print_i32(f.get())\n",
            "10")

    def test_method_mutation(self):
        self.expect(
            "class Foo:\n    x: i32\n"
            "    func set(self: ptr<Foo>, v: i32) -> void:\n"
            "        self.x = v\n\n"
            "func main() -> void:\n"
            "    mut f = Foo(x: 1)\n"
            "    f.set(77)\n"
            "    print_i32(f.x)\n",
            "77")

    def test_method_with_extra_params(self):
        self.expect(
            "class Foo:\n    x: i32\n    y: i32\n"
            "    func sum(self: ptr<Foo>, z: i32) -> i32:\n"
            "        return self.x + self.y + z\n\n"
            "func main() -> void:\n"
            "    mut f = Foo(x: 2, y: 3)\n"
            "    print_i32(f.sum(10))\n",
            "15")

    def test_inheritance_fields(self):
        self.expect(
            "class Base:\n    x: i32\n\n"
            "class Child extends Base:\n    y: i32\n\n"
            "func main() -> void:\n"
            "    mut c = Child(x: 5, y: 9)\n"
            "    print_i32(c.x)\n"
            "    print_i32(c.y)\n",
            "5\n9")

    def test_inherited_method(self):
        self.expect(
            "class Base:\n    x: i32\n"
            "    func get(self: ptr<Base>) -> i32:\n"
            "        return self.x\n\n"
            "class Child extends Base:\n    y: i32\n\n"
            "func main() -> void:\n"
            "    mut c = Child(x: 11, y: 2)\n"
            "    print_i32(c.get())\n",
            "11")

    def test_missing_field_rejected(self):
        self.compile_fail(
            "class Foo:\n    x: i32\n    y: i32\n\n"
            "func main() -> void:\n"
            "    mut f = Foo(x: 1)\n"
            "    print_i32(f.x)\n",
            "missing fields")

    def test_unknown_field_rejected(self):
        self.compile_fail(
            "class Foo:\n    x: i32\n\n"
            "func main() -> void:\n"
            "    mut f = Foo(x: 1, z: 2)\n"
            "    print_i32(f.x)\n",
            "unknown field")

    def test_pub_struct_field_read_write(self):
        self.expect(
            "struct Point:\n    pub x: i32\n    pub y: i32\n\n"
            "func main() -> void:\n"
            "    mut p = Point(x: 3, y: 4)\n"
            "    p.x = 10\n"
            "    print_i32(p.x)\n"
            "    print_i32(p.y)\n",
            "10\n4")

    def test_pub_class_field_read_write(self):
        self.expect(
            "class Point:\n    pub x: i32\n    pub y: i32\n\n"
            "func main() -> void:\n"
            "    mut p = Point(x: 3, y: 4)\n"
            "    p.y = 7\n"
            "    print_i32(p.x)\n"
            "    print_i32(p.y)\n",
            "3\n7")


if __name__ == '__main__':
    unittest.main()
