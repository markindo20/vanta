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


if __name__ == '__main__':
    unittest.main()