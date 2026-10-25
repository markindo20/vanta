import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from compiler.lexer import Lexer, LexError
from compiler.tokens import TT


def lex(src):
    return Lexer(src).tokenize()


class LexerTests(unittest.TestCase):
    def test_keywords(self):
        toks = lex("func let mut return struct component system if elif else while for in true false and or not\n")
        types = [t.type for t in toks]
        self.assertEqual(types[:18], [
            TT.FUNC, TT.LET, TT.MUT, TT.RETURN, TT.STRUCT, TT.COMPONENT,
            TT.SYSTEM, TT.IF, TT.ELIF, TT.ELSE, TT.WHILE, TT.FOR, TT.IN,
            TT.TRUE, TT.FALSE, TT.AND, TT.OR, TT.NOT,
        ])

    def test_break_continue_keywords(self):
        toks = lex("break continue\n")
        self.assertEqual(toks[0].type, TT.BREAK)
        self.assertEqual(toks[1].type, TT.CONTINUE)

    def test_match_keyword(self):
        toks = lex("match\n")
        self.assertEqual(toks[0].type, TT.MATCH)

    def test_ident_and_int(self):
        toks = lex("x 42 3.14\n")
        self.assertEqual(toks[0].type, TT.IDENT)
        self.assertEqual(toks[1].type, TT.INT)
        self.assertEqual(toks[1].value, 42)
        self.assertEqual(toks[2].type, TT.FLOAT)
        self.assertAlmostEqual(toks[2].value, 3.14)

    def test_operators(self):
        toks = lex("a == b != c < d <= e > f >= g -> h :: i\n")
        names = [t.type for t in toks]
        for expected in (TT.EQ, TT.NEQ, TT.LT, TT.LTE, TT.GT, TT.GTE, TT.ARROW, TT.COLONCOLON):
            self.assertIn(expected, names)

    def test_compound_ops(self):
        toks = lex("a += b -= c *= d /= e\n")
        kinds = [t.type for t in toks]
        for expected in (TT.PLUS_EQ, TT.MINUS_EQ, TT.STAR_EQ, TT.SLASH_EQ):
            self.assertIn(expected, kinds)

    def test_comments(self):
        toks = lex("# comment only\nx = 1\n")
        idents = [t for t in toks if t.type == TT.IDENT]
        self.assertEqual(len(idents), 1)
        self.assertEqual(idents[0].value, 'x')

    def test_indentation(self):
        toks = lex("func f():\n    return 1\n")
        kinds = [t.type for t in toks]
        self.assertIn(TT.INDENT, kinds)
        self.assertIn(TT.DEDENT, kinds)

    def test_newlines_ignored_inside_brackets(self):
        toks = lex("let g = [[1, 2],\n"
                   "         [3, 4]]\n"
                   "print_i32(1)\n")
        self.assertEqual(sum(1 for t in toks if t.type == TT.NEWLINE), 2)
        self.assertFalse(any(t.type in (TT.INDENT, TT.DEDENT) for t in toks))

    def test_utf8_bom_is_ignored_at_start(self):
        toks = lex("\ufefffunc f() -> i32:\n    return 1\n")
        self.assertEqual(toks[0].type, TT.FUNC)
        self.assertEqual(toks[0].line, 1)
        self.assertEqual(toks[0].col, 1)

    def test_utf8_bom_inside_source_is_rejected(self):
        with self.assertRaises(LexError):
            lex("x = 1\n\ufeffy = 2\n")

    def test_invalid_char(self):
        with self.assertRaises(LexError):
            lex("x = $\n")

    def test_tab_rejected(self):
        with self.assertRaises(LexError):
            lex("func f():\n\treturn 1\n")

    def test_const_keyword(self):
        toks = lex("const X = 1\n")
        self.assertEqual(toks[0].type, TT.CONST)

    def test_string_literal(self):
        toks = lex('"hello"\n')
        self.assertEqual(toks[0].type, TT.STRING)
        self.assertEqual(toks[0].value, 'hello')

    def test_string_escapes(self):
        toks = lex(r'"a\nb\tc\\d\"e"' + '\n')
        self.assertEqual(toks[0].value, 'a\nb\tc\\d"e')

    def test_unterminated_string(self):
        with self.assertRaises(LexError):
            lex('"hello\n')


if __name__ == '__main__':
    unittest.main()