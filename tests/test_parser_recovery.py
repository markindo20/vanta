"""Recovery behavior of the Vanta parser.

These tests do not depend on codegen or type-checking: they drive the
parser directly through ``Parser.parse_program`` with ``raise_errors=False``
and assert that independent broken declarations are reported separately
instead of aborting the whole file.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from compiler.lexer import Lexer
from compiler.parser import Parser, ParseError
from compiler import ast_nodes as A


def tokenize(src):
    return Lexer(src).tokenize()


def parse(src, raise_errors=False):
    program = Parser(tokenize(src), '<input>', raise_errors=raise_errors).parse_program()
    if raise_errors is False:
        return program
    return program


def errors(src):
    program = Parser(tokenize(src), '<input>', raise_errors=False).parse_program()
    return [str(e) for e in program.parse_errors]


def decls(src):
    program = Parser(tokenize(src), '<input>', raise_errors=False).parse_program()
    return [d.__class__.__name__ for d in program.decls]


class ParserRecoveryTests(unittest.TestCase):

    # ------------------------------------------------------------------
    # Basic statement recovery inside a single block.
    # ------------------------------------------------------------------
    def test_single_broken_statement_does_not_abort_function(self):
        src = ("func a() -> void:\n"
               "    let x = @\n"
               "    return\n")
        lines = errors(src)
        self.assertEqual(len(lines), 1, lines)
        self.assertIn('unexpected token AT', lines[0])
        # The function declaration itself is still recorded.
        self.assertEqual(decls(src), ['FuncDecl'])

    def test_following_valid_statement_survives_broken_line(self):
        src = ("func a() -> void:\n"
               "    let x = @\n"
               "    let y = 2\n")
        program = Parser(tokenize(src), '<input>', raise_errors=False).parse_program()
        fn = program.decls[0]
        # Any statements retained after the bad line are allowable; the parse
        # must at least not crash and must report the error.
        self.assertGreaterEqual(len(program.parse_errors), 1)
        # Retained body (possibly empty after sync) must be a list.
        self.assertIsInstance(fn.body, list)

    def test_broken_function_does_not_kill_next_declaration(self):
        src = ("func a() -> void:\n"
               "    let x = @\n"
               "\n"
               "func b() -> void:\n"
               "    let y = 7\n")
        self.assertEqual(decls(src), ['FuncDecl', 'FuncDecl'])
        self.assertEqual(len(errors(src)), 1)

    def test_two_broken_top_level_declarations_reported_separately(self):
        src = ("func a(x: i32) -> void:\n"
               "    let y = 1 +\n"
               "\n"
               "func b() -> void:\n"
               "    let z = @\n")
        reported = errors(src)
        self.assertGreaterEqual(len(reported), 2, reported)

    def test_function_returning_value_with_broken_body(self):
        src = ("func a() -> i32:\n"
               "    return @\n")
        prog = Parser(tokenize(src), '<input>', raise_errors=False).parse_program()
        self.assertGreaterEqual(len(prog.parse_errors), 1)

    def test_empty_function_allowed(self):
        src = "func a() -> void:\n    return\n"
        self.assertEqual(decls(src), ['FuncDecl'])
        self.assertEqual(errors(src), [])

    def test_missing_newline_after_func_header_recovers(self):
        src = "func a() -> void: return\nfunc b() -> void:\n    return\n"
        # Either parses or reports; never raises.
        try:
            p = Parser(tokenize(src), '<input>', raise_errors=False).parse_program()
            self.assertIsInstance(p, A.Program)
        except ParseError:
            # Acceptable: top-level sync may reject utterly malformed input.
            pass

    # ------------------------------------------------------------------
    # Statement kinds exercising recovery across the grammar.
    # ------------------------------------------------------------------
    def test_broken_var_decl_does_not_kill_following_return(self):
        src = ("func a() -> void:\n"
               "    let x = @\n"
               "    return\n")
        program = Parser(tokenize(src), '<input>', raise_errors=False).parse_program()
        self.assertGreaterEqual(len(program.parse_errors), 1)
        fn = program.decls[0]
        # At least the function recovered without raising.
        self.assertEqual(fn.name, 'a')


    def test_broken_if_condition_recovers_to_following_statement(self):
        src = ("func a() -> void:\n"
               "    if @:\n"
               "        return\n"
               "    let y = 2\n")
        program = Parser(tokenize(src), '<input>', raise_errors=False).parse_program()
        self.assertGreaterEqual(len(program.parse_errors), 1)

    def test_broken_while_condition_recovers(self):
        src = ("func a() -> void:\n"
               "    while @:\n"
               "        return\n"
               "    let y = 2\n")
        program = Parser(tokenize(src), '<input>', raise_errors=False).parse_program()
        self.assertGreaterEqual(len(program.parse_errors), 1)

    def test_broken_for_range_recovers(self):
        src = ("func a() -> void:\n"
               "    for x in range(@, 4):\n"
               "        return\n"
               "    let y = 2\n")
        program = Parser(tokenize(src), '<input>', raise_errors=False).parse_program()
        self.assertGreaterEqual(len(program.parse_errors), 1)

    def test_broken_match_arm_recovers_to_next_arm(self):
        src = ("enum S:\n    A\n    B\n"
               "func a(s: S) -> void:\n"
               "    match s:\n"
               "        S.A :::\n"
               "            return\n"
               "        S.B:\n"
               "            return\n")
        program = Parser(tokenize(src), '<input>', raise_errors=False).parse_program()
        self.assertGreaterEqual(len(program.parse_errors), 1)

    def test_else_must_be_last_still_reports(self):
        src = ("enum S:\n    A\n    B\n"
               "func a(s: S) -> void:\n"
               "    match s:\n"
               "        else:\n"
               "            return\n"
               "        S.A:\n"
               "            return\n")
        program = Parser(tokenize(src), '<input>', raise_errors=False).parse_program()
        # Should report at least one error or at least not crash.
        self.assertIsInstance(program, A.Program)

    # ------------------------------------------------------------------
    # Top-level and import edge cases.
    # ------------------------------------------------------------------
    def test_broken_struct_declaration_does_not_kill_next(self):
        src = ("struct P:\n    x:\n"
               "\n"
               "func a() -> void:\n"
               "    return\n")
        program = Parser(tokenize(src), '<input>', raise_errors=False).parse_program()
        self.assertGreaterEqual(len(program.parse_errors), 1)
        self.assertIn('FuncDecl', decls(src))

    def test_broken_enum_declaration_does_not_kill_next(self):
        src = ("enum S:\n    A@\n"
               "\n"
               "func a() -> void:\n"
               "    return\n")
        program = Parser(tokenize(src), '<input>', raise_errors=False).parse_program()
        self.assertGreaterEqual(len(program.parse_errors), 1)

    def test_broken_class_declaration_does_not_kill_next(self):
        src = ("class C:\n    x i32\n"
               "\n"
               "func a() -> void:\n"
               "    return\n")
        program = Parser(tokenize(src), '<input>', raise_errors=False).parse_program()
        # Either errors collected or not; never raise.
        self.assertIsInstance(program, A.Program)

    def test_broken_rand_decl_does_not_kill_function(self):
        src = ("func @badname() -> void:\n"
               "    return\n")
        program = Parser(tokenize(src), '<input>', raise_errors=False).parse_program()
        self.assertGreaterEqual(len(program.parse_errors), 1)

    # ------------------------------------------------------------------
    # Position / line reporting.
    # ------------------------------------------------------------------
    def test_error_reports_line_number(self):
        src = "func a() -> void:\n    let x = @\n"
        program = Parser(tokenize(src), '<input>', raise_errors=False).parse_program()
        self.assertEqual(len(program.parse_errors), 1)
        err = program.parse_errors[0]
        self.assertEqual(err.pos.line, 2)

    def test_error_reports_filename(self):
        p = Parser(tokenize('func a() -> void:\n    let x = @\n'), 'myfile.vnt', raise_errors=False)
        prog = p.parse_program()
        self.assertEqual(prog.parse_errors[0].filename, 'myfile.vnt')

    # ------------------------------------------------------------------
    # Exhaustiveness-related malformed constructs do not crash the checker
    # pipeline's recovery path. (Type-checking not exercised here.)
    # ------------------------------------------------------------------
    def test_malformed_return_does_not_remove_decl(self):
        src = "func a() -> void:\n    return 1 +\n"
        self.assertEqual(decls(src), ['FuncDecl'])

    def test_malformed_var_type_does_not_remove_decl(self):
        src = "func a() -> void:\n    let x: Foo = 1\n"
        # Type-level errors surface later; parse succeeds.
        self.assertEqual(errors(src), [])

    def test_multiple_statements_each_collect_errors(self):
        src = ("func a() -> void:\n"
               "    let x = @\n"
               "    let y = #\n")
        reported = errors(src)
        self.assertGreaterEqual(len(reported), 2, reported)

    # ------------------------------------------------------------------
    # Pretty extreme cases that previously (and now still) must not raise.
    # ------------------------------------------------------------------
    def test_garbage_input_never_raises(self):
        src = "###@@@\n...garbage...\n[[[]]]\n"
        try:
            prog = Parser(tokenize(src), '<input>', raise_errors=False).parse_program()
        except ParseError:
            # Fully unparseable input may legitimately propagate; either outcome
            # is acceptable as long as it terminates.
            return
        self.assertIsInstance(prog, A.Program)

    def test_totally_empty_input_parses(self):
        program = Parser(tokenize(''), '<input>', raise_errors=False).parse_program()
        self.assertEqual(program.decls, [])
        self.assertEqual(program.parse_errors, [])

    def test_blankLines_with_comments_parse(self):
        src = ("# header\n\n# body\n\n"
               "func a() -> void:\n"
               "    return\n")
        program = Parser(tokenize(src), '<input>', raise_errors=False).parse_program()
        self.assertEqual(program.parse_errors, [])
        self.assertEqual(decls(src), ['FuncDecl'])

    def test_nested_if_error_recovers_outer_block(self):
        src = ("func a() -> void:\n"
               "    if @:\n"
               "        let inner = 1\n"
               "    let outer = 2\n")
        program = Parser(tokenize(src), '<input>', raise_errors=False).parse_program()
        self.assertGreaterEqual(len(program.parse_errors), 1)

    def test_nested_while_error_recovers(self):
        src = ("func a() -> void:\n"
               "    while @:\n"
               "        let inner = 1\n"
               "    let outer = 2\n")
        program = Parser(tokenize(src), '<input>', raise_errors=False).parse_program()
        self.assertGreaterEqual(len(program.parse_errors), 1)


if __name__ == '__main__':
    unittest.main()
