import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from compiler.lexer import Lexer
from compiler.parser import Parser
from compiler.type_checker import TypeChecker
from compiler.codegen_cpp import CodeGen


def gen(src):
    toks = Lexer(src).tokenize()
    prog = Parser(toks).parse_program()
    tc = TypeChecker(prog)
    tc.register()
    tc.check()
    return CodeGen(prog, tc).generate()


class CodegenTests(unittest.TestCase):
    def test_hello(self):
        cpp = gen("func main() -> void:\n    print_i32(42)\n")
        self.assertIn('vanta::print_i32(42)', cpp)
        self.assertIn('int main()', cpp)

    def test_struct(self):
        cpp = gen("struct P:\n    x: i32\n"
                  "func main() -> void:\n    let p = P(x: 1)\n    print_i32(p.x)\n")
        self.assertIn('struct P {', cpp)
        self.assertIn('v_p.v_x', cpp)

    def test_control_flow(self):
        cpp = gen("func main() -> void:\n    for i in range(0, 3):\n        print_i32(i)\n")
        self.assertIn('for (int32_t v_i = 0;', cpp)
        self.assertIn('v_i = v_i + 1', cpp)

    def test_math(self):
        cpp = gen("func main() -> void:\n    let v = Vec3(1.0, 2.0, 3.0)\n    print_f32(v.x)\n")
        self.assertIn('vanta::Vec3(1.0f, 2.0f, 3.0f)', cpp)

    def test_compound_assign_codegen(self):
        cpp = gen("func main() -> void:\n    mut x = 1\n    x += 2\n")
        self.assertIn('v_x = (v_x + 2)', cpp)

    def test_compound_assign_member(self):
        cpp = gen("struct P:\n    x: i32\n"
                  "func main() -> void:\n    mut p = P(x: 0)\n    p.x += 5\n")
        self.assertIn('v_p.v_x = (v_p.v_x + 5)', cpp)

    def test_break_continue_codegen(self):
        cpp = gen("func main() -> void:\n"
                  "    for i in range(0, 5):\n"
                  "        if i == 2:\n"
                  "            break\n"
                  "        if i == 1:\n"
                  "            continue\n")
        self.assertIn('break;', cpp)
        self.assertIn('continue;', cpp)

    def test_const_emitted(self):
        cpp = gen("const X: i32 = 5\nfunc main() -> void:\n    print_i32(X)\n")
        self.assertIn('constexpr int32_t v_X = 5', cpp)
        self.assertIn('print_i32(v_X)', cpp)

    def test_assert_emitted(self):
        cpp = gen("func main() -> void:\n    assert(1 == 1)\n")
        self.assertIn('vanta::assert_impl(', cpp)

    def test_range_3arg_codegen(self):
        cpp = gen("func main() -> void:\n    for i in range(10, 0, -1):\n        print_i32(i)\n")
        self.assertIn('__step_1', cpp)
        self.assertIn('__end_1', cpp)

    def test_inferred_return_codegen(self):
        cpp = gen("func add(a: i32, b: i32):\n    return a + b\n"
                  "func main() -> void:\n    print_i32(add(1, 2))\n")
        self.assertIn('int32_t fn_add(', cpp)

    def test_array_emit(self):
        cpp = gen("func main() -> void:\n    let xs = [1, 2, 3]\n    print_i32(xs[0])\n")
        self.assertIn('std::array<int32_t, 3>{1, 2, 3}', cpp)
        self.assertIn('v_xs[0]', cpp)

    def test_len_emit(self):
        cpp = gen("func main() -> void:\n    let xs = [1, 2, 3]\n    let n = len(xs)\n")
        self.assertIn('.size()', cpp)

    def test_quat_mul_emit(self):
        cpp = gen("func main() -> void:\n    let q = Quat(0.0, 0.0, 0.0, 1.0)\n    let r = q * q\n")
        self.assertIn('(v_q * v_q)', cpp)


if __name__ == '__main__':
    unittest.main()