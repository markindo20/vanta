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
        self.assertIn(TT.EQ, names)
        self.assertIn(TT.NEQ, names)
        self.assertIn(TT.LT, names)
        self.assertIn(TT.LTE, names)
        self.assertIn(TT.GT, names)
        self.assertIn(TT.GTE, names)
        self.assertIn(TT.ARROW, names)
        self.assertIn(TT.COLONCOLON, names)

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

    def test_invalid_char(self):
        with self.assertRaises(LexError):
            lex("x = @\n")

    def test_tab_rejected(self):
        with self.assertRaises(LexError):
            lex("func f():\n\treturn 1\n")


if __name__ == '__main__':
    unittest.main()