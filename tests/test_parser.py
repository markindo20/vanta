import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from compiler.lexer import Lexer
from compiler.parser import Parser, ParseError
from compiler import ast_nodes as A


def parse(src):
    toks = Lexer(src).tokenize()
    return Parser(toks).parse_program()


class ParserTests(unittest.TestCase):
    def test_function_decl(self):
        prog = parse("func add(a: i32, b: i32) -> i32:\n    return a + b\n")
        self.assertEqual(len(prog.decls), 1)
        fn = prog.decls[0]
        self.assertIsInstance(fn, A.FuncDecl)
        self.assertEqual(fn.name, 'add')
        self.assertEqual(len(fn.params), 2)

    def test_struct_decl(self):
        prog = parse("struct P:\n    x: i32\n    y: f32\n")
        sd = prog.decls[0]
        self.assertIsInstance(sd, A.StructDecl)
        self.assertEqual(len(sd.fields), 2)

    def test_operator_precedence(self):
        prog = parse("func f() -> i32:\n    return 1 + 2 * 3\n")
        ret = prog.decls[0].body[0]
        self.assertIsInstance(ret.value, A.BinOp)
        self.assertEqual(ret.value.op, '+')
        self.assertEqual(ret.value.right.op, '*')

    def test_if_else(self):
        src = ("func f() -> i32:\n"
               "    if a == 1:\n"
               "        return 1\n"
               "    elif a == 2:\n"
               "        return 2\n"
               "    else:\n"
               "        return 3\n")
        prog = parse(src)
        stmt = prog.decls[0].body[0]
        self.assertIsInstance(stmt, A.IfStmt)
        self.assertEqual(len(stmt.elif_branches), 1)
        self.assertIsNotNone(stmt.else_body)

    def test_for_loop(self):
        prog = parse("func f() -> void:\n    for i in range(0, 10):\n        print_i32(i)\n")
        stmt = prog.decls[0].body[0]
        self.assertIsInstance(stmt, A.ForRangeStmt)
        self.assertEqual(stmt.var, 'i')

    def test_compound_assignment(self):
        prog = parse("func f() -> void:\n    mut x = 1\n    x += 2\n")
        stmt = prog.decls[0].body[1]
        self.assertIsInstance(stmt, A.AssignStmt)
        self.assertIsInstance(stmt.value, A.BinOp)
        self.assertEqual(stmt.value.op, '+')

    def test_compound_minus(self):
        prog = parse("func f() -> void:\n    mut x = 5\n    x -= 2\n")
        stmt = prog.decls[0].body[1]
        self.assertIsInstance(stmt.value, A.BinOp)
        self.assertEqual(stmt.value.op, '-')

    def test_break_continue_parse(self):
        src = ("func f() -> void:\n"
               "    for i in range(0, 10):\n"
               "        if i == 5:\n"
               "            continue\n"
               "        if i == 8:\n"
               "            break\n")
        prog = parse(src)
        body = prog.decls[0].body[0].body
        inner1 = body[0].then_body[0]
        inner2 = body[1].then_body[0]
        self.assertIsInstance(inner1, A.ContinueStmt)
        self.assertIsInstance(inner2, A.BreakStmt)

    def test_syntax_error(self):
        with self.assertRaises(ParseError):
            parse("func f(:\n    return 1\n")

    def test_const_decl(self):
        prog = parse("const GRAVITY: f32 = 9.8\n")
        cd = prog.decls[0]
        self.assertIsInstance(cd, A.ConstDecl)
        self.assertEqual(cd.name, 'GRAVITY')
        self.assertIsNotNone(cd.type_ann)

    def test_const_no_type(self):
        prog = parse("const MAX = 100\n")
        cd = prog.decls[0]
        self.assertIsInstance(cd, A.ConstDecl)
        self.assertIsNone(cd.type_ann)

    def test_range_3arg(self):
        prog = parse("func f() -> void:\n    for i in range(10, 0, -1):\n        print_i32(i)\n")
        stmt = prog.decls[0].body[0]
        self.assertIsInstance(stmt, A.ForRangeStmt)
        self.assertIsNotNone(stmt.step)

    def test_assert_parses_as_call(self):
        prog = parse("func f() -> void:\n    assert(x == 1)\n")
        stmt = prog.decls[0].body[0]
        self.assertIsInstance(stmt, A.ExprStmt)
        self.assertIsInstance(stmt.expr, A.Call)
        self.assertEqual(stmt.expr.func.name, 'assert')

    def test_array_type_annotation(self):
        prog = parse("func f() -> void:\n    let xs: [i32, 4] = [1, 2, 3, 4]\n")
        v = prog.decls[0].body[0]
        self.assertIsNotNone(v.type_ann)
        self.assertEqual(v.type_ann.kind, 'array')
        self.assertEqual(v.type_ann.size, 4)

    def test_array_literal_parse(self):
        prog = parse("func f() -> void:\n    let xs = [10, 20, 30]\n")
        v = prog.decls[0].body[0]
        self.assertIsInstance(v.value, A.ArrayLit)
        self.assertEqual(len(v.value.elements), 3)

    def test_string_literal_parse(self):
        prog = parse('func f() -> void:\n    let s = "hi"\n')
        v = prog.decls[0].body[0]
        self.assertIsInstance(v.value, A.StringLit)
        self.assertEqual(v.value.value, "hi")

    def test_extern_decl(self):
        src = ('extern "mylib" {\n'
               '    func add(a: i32, b: i32) -> i32\n'
               '    func log(msg: str)\n'
               '}\n')
        prog = parse(src)
        ed = prog.decls[0]
        self.assertIsInstance(ed, A.ExternDecl)
        self.assertEqual(ed.lib_name, 'mylib')
        self.assertEqual(len(ed.funcs), 2)
        add, log = ed.funcs
        self.assertIsInstance(add, A.FuncDecl)
        self.assertEqual(add.name, 'add')
        self.assertEqual([p.name for p in add.params], ['a', 'b'])
        self.assertEqual(add.ret.name, 'i32')
        self.assertEqual(add.body, [])
        self.assertIsNone(log.ret)

    def test_extern_empty_block(self):
        prog = parse('extern "c" {\n}\n')
        ed = prog.decls[0]
        self.assertIsInstance(ed, A.ExternDecl)
        self.assertEqual(ed.funcs, [])


if __name__ == '__main__':
    unittest.main()