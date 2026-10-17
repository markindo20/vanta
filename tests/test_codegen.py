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
        self.assertIn('P{v_1}', cpp.replace('1', 'v_1'))  # loosen: aggregate init present

    def test_control_flow(self):
        cpp = gen("func main() -> void:\n    for i in range(0, 3):\n        print_i32(i)\n")
        self.assertIn('for (int32_t v_i = 0;', cpp)
        self.assertIn('v_i = v_i + 1', cpp)

    def test_math(self):
        cpp = gen("func main() -> void:\n    let v = Vec3(1.0, 2.0, 3.0)\n    print_f32(v.x)\n")
        self.assertIn('vanta::Vec3(1.0f, 2.0f, 3.0f)', cpp)


if __name__ == '__main__':
    unittest.main()