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

    def test_import_decl(self):
        prog = parse('import "lib/math.vnt"\n'
                     'func main() -> void:\n    return\n')
        imp = prog.decls[0]
        self.assertIsInstance(imp, A.ImportDecl)
        self.assertEqual(imp.path, 'lib/math.vnt')

    def test_import_requires_string(self):
        with self.assertRaises(ParseError):
            parse('import math\n')

    def test_multiline_array_literal(self):
        prog = parse("func f() -> void:\n"
                     "    let g = [[1, 2],\n"
                     "             [3, 4]]\n")
        lit = prog.decls[0].body[0].value
        self.assertIsInstance(lit, A.ArrayLit)
        self.assertEqual(len(lit.elements), 2)
        self.assertEqual(len(lit.elements[0].elements), 2)

    def test_multiline_call_arguments(self):
        prog = parse("func f() -> void:\n"
                     "    g(\n"
                     "        1,\n"
                     "        2\n"
                     "    )\n")
        call = prog.decls[0].body[0].expr
        self.assertIsInstance(call, A.Call)
        self.assertEqual(len(call.args), 2)

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

    def test_match_stmt(self):
        src = ("func f(s: State) -> void:\n"
               "    match s:\n"
               "        State.A, State.B:\n"
               "            return\n"
               "        else:\n"
               "            return\n")
        prog = parse(src)
        stmt = prog.decls[0].body[0]
        self.assertIsInstance(stmt, A.MatchStmt)
        self.assertEqual(len(stmt.arms), 2)
        self.assertFalse(stmt.arms[0].is_else)
        self.assertEqual([p[:2] for p in stmt.arms[0].patterns],
                         [('State', 'A'), ('State', 'B')])
        self.assertTrue(stmt.arms[1].is_else)

    def test_match_else_must_be_last(self):
        with self.assertRaisesRegex(ParseError, "'else' must be the last match arm"):
            parse("func f(s: State) -> void:\n"
                  "    match s:\n"
                  "        else:\n"
                  "            return\n"
                  "        State.A:\n"
                  "            return\n")

    def test_match_pattern_needs_member(self):
        with self.assertRaisesRegex(ParseError, "match patterns are written Enum.Member"):
            parse("func f(s: State) -> void:\n"
                  "    match s:\n"
                  "        A:\n"
                  "            return\n")

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

    def test_func_type_annotation(self):
        prog = parse("func f() -> void:\n    let cb: func(i32, f32) -> f32 = g\n")
        ann = prog.decls[0].body[0].type_ann
        self.assertEqual(ann.kind, 'func')
        self.assertEqual([p.name for p in ann.params], ['i32', 'f32'])
        self.assertEqual(ann.inner.name, 'f32')

    def test_func_type_void_shorthand(self):
        prog = parse("func f() -> void:\n    let cb: func(i32) = g\n")
        ann = prog.decls[0].body[0].type_ann
        self.assertEqual(ann.kind, 'func')
        self.assertIsNone(ann.inner)

    def test_func_type_no_params(self):
        prog = parse("func f() -> void:\n    let cb: func() -> i32 = g\n")
        ann = prog.decls[0].body[0].type_ann
        self.assertEqual(ann.kind, 'func')
        self.assertEqual(ann.params, [])
        self.assertEqual(ann.inner.name, 'i32')

    def test_func_type_nested_return(self):
        prog = parse("func f() -> void:\n"
                     "    let cb: func(i32) -> func(i32) -> i32 = g\n")
        ann = prog.decls[0].body[0].type_ann
        self.assertEqual(ann.kind, 'func')
        self.assertEqual(ann.inner.kind, 'func')
        self.assertEqual(ann.inner.inner.name, 'i32')

    def test_func_param_type(self):
        prog = parse("func apply(f: func(i32) -> i32, x: i32) -> i32:\n    return x\n")
        ft = prog.decls[0].params[0].type
        self.assertEqual(ft.kind, 'func')
        self.assertEqual(len(ft.params), 1)

    def test_indexed_call_parses(self):
        prog = parse("func f() -> void:\n    g[0](1)\n")
        call = prog.decls[0].body[0].expr
        self.assertIsInstance(call, A.Call)
        self.assertIsInstance(call.func, A.Index)

    def test_member_call_parses(self):
        prog = parse("func f() -> void:\n    s.cb(1)\n")
        call = prog.decls[0].body[0].expr
        self.assertIsInstance(call, A.Call)
        self.assertIsInstance(call.func, A.Member)

    def test_chained_call_parses(self):
        prog = parse("func f() -> void:\n    g(1)(2)\n")
        call = prog.decls[0].body[0].expr
        self.assertIsInstance(call, A.Call)
        self.assertIsInstance(call.func, A.Call)


if __name__ == '__main__':
    unittest.main()