import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from compiler.lexer import Lexer
from compiler.parser import Parser
from compiler.type_checker import TypeChecker, CheckError


def run(src):
    toks = Lexer(src).tokenize()
    prog = Parser(toks).parse_program()
    tc = TypeChecker(prog)
    tc.register()
    tc.check()
    return prog, tc


class TypeCheckerTests(unittest.TestCase):
    def test_inference(self):
        run("func f() -> void:\n    let x = 100\n    let y = 3.5\n")
        # no exception = pass

    def test_type_mismatch(self):
        with self.assertRaises(CheckError):
            run("func f() -> void:\n    let x: i32 = 3.5\n")

    def test_unknown_name(self):
        with self.assertRaises(CheckError):
            run("func f() -> void:\n    y = 1\n")

    def test_bad_call(self):
        with self.assertRaises(CheckError):
            run("func g(a: i32) -> void:\n    return\n"
                "func f() -> void:\n    g(1, 2)\n")

    def test_immutable_assignment(self):
        with self.assertRaises(CheckError):
            run("func f() -> void:\n    let x = 1\n    x = 2\n")

    def test_bad_return(self):
        with self.assertRaises(CheckError):
            run("func f() -> i32:\n    return\n")

    def test_arena_copy_rejected(self):
        with self.assertRaises(CheckError):
            run("func f() -> void:\n    let a = Arena(64)\n    let b = a\n")

    def test_ok_arena(self):
        run("func f() -> void:\n    let a = Arena(64)\n    let p = a.alloc::<i32>(4)\n    p[0] = 7\n")

    def test_void_func_no_value_return(self):
        with self.assertRaises(CheckError):
            run("func f() -> void:\n    return 3\n")


if __name__ == '__main__':
    unittest.main()