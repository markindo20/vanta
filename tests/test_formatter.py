import os
import tempfile
import unittest

from compiler.formatter import FormatError, format_source
from compiler.lexer import LexError, Lexer
from compiler.parser import ParseError, Parser


class FormatterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='vanta_fmt_')

    def write(self, name, source):
        path = os.path.join(self.tmp, name)
        with open(path, 'w', encoding='utf-8', newline='\n') as f:
            f.write(source)
        return path

    def format(self, source, name='main.vnt'):
        path = self.write(name, source)
        return format_source(source, path)

    def test_indent_is_four_spaces_per_level(self):
        source = ('func main() -> i32:\n'
                  '    let x: i32 = 1\n'
                  '    if x > 0:\n'
                  '        let y: i32 = 2\n'
                  '        return y\n'
                  '    return x\n')
        out = self.format(source)
        self.assertEqual(out, ('func main() -> i32:\n'
                               '    let x: i32 = 1\n'
                               '    if x > 0:\n'
                               '        let y: i32 = 2\n'
                               '        return y\n'
                               '    return x\n'))

    def test_two_space_indentation_becomes_four(self):
        source = ('func main() -> i32:\n'
                  '  let x: i32 = 1\n'
                  '  if x > 0:\n'
                  '    return x\n'
                  '  return 0\n')
        out = self.format(source)
        self.assertEqual(out, ('func main() -> i32:\n'
                               '    let x: i32 = 1\n'
                               '    if x > 0:\n'
                               '        return x\n'
                               '    return 0\n'))

    def test_tabs_are_refused(self):
        with self.assertRaises(FormatError):
            self.format('func main() -> void:\n\treturn\n')

    def test_a_file_that_does_not_parse_is_refused(self):
        with self.assertRaises(FormatError):
            self.format('func main() -> void:\n'
                        '    let x: i32 = \n')

    def test_formatting_keeps_the_block_structure(self):
        source = ('func main() -> i32:\n'
                  '    let x: i32 = 1\n'
                  '    if x > 0:\n'
                  '        return x\n'
                  '    return 0\n')
        out = self.format(source)
        self.assertEqual(len(_blocks(out)), len(_blocks(source)))

    def test_comments_keep_their_text(self):
        source = ('# a note about the function\n'
                  'func main() -> void:\n'
                  '    # an inner note\n'
                  '    return\n')
        out = self.format(source)
        self.assertIn('# a note about the function', out)
        self.assertIn('# an inner note', out)

    def test_a_trailing_comment_stays_on_its_line(self):
        source = 'func main() -> void:\n    return  # done\n'
        out = self.format(source)
        self.assertEqual(out, 'func main() -> void:\n    return  # done\n')

    def test_blank_line_runs_collapse(self):
        source = ('func main() -> void:\n'
                  '    return\n'
                  '\n'
                  '\n'
                  '\n'
                  'func other() -> void:\n'
                  '    return\n')
        out = self.format(source)
        self.assertEqual(out.count('\n\n'), 1)

    def test_the_file_ends_with_exactly_one_newline(self):
        out = self.format('func main() -> void:\n    return\n\n\n')
        self.assertTrue(out.endswith('\n'))
        self.assertFalse(out.endswith('\n\n'))

    def test_a_missing_final_newline_is_added(self):
        out = self.format('func main() -> void:\n    return')
        self.assertTrue(out.endswith('\n'))

    def test_formatting_is_idempotent(self):
        source = ('func main() -> i32:\n'
                  '  let x: i32 = 1\n'
                  '  if x > 0:\n'
                  '    return x\n'
                  '  return 0\n')
        once = self.format(source)
        twice = self.format(once, 'other.vnt')
        self.assertEqual(once, twice)

    def test_a_continued_expression_keeps_its_alignment(self):
        source = ('func main() -> void:\n'
                  '    let xs: List<i32> = [1,\n'
                  '                       2]\n'
                  '    return\n')
        out = self.format(source)
        self.assertIn('                       2]', out)

    def test_the_result_still_parses(self):
        source = ('func main() -> i32:\n'
                  '    let x: i32 = 1\n'
                  '    if x > 0:\n'
                  '        return x\n'
                  '    return 0\n')
        out = self.format(source)
        Parser(Lexer(out, 'main.vnt').tokenize(), 'main.vnt').parse_program()

    def test_crlf_line_endings_survive(self):
        source = 'func main() -> void:\r\n    return\r\n'
        out = format_source(source, 'main.vnt')
        self.assertIn('\r\n', out)
        self.assertNotIn('\n\n', out.replace('\r\n', ''))

    def test_an_empty_file_stays_empty(self):
        self.assertEqual(self.format(''), '')


def _blocks(source):
    """The block structure of a source, as a comparable shape."""
    tokens = Lexer(source, 'x.vnt').tokenize()
    program = Parser(tokens, 'x.vnt').parse_program()
    return [type(decl).__name__ for decl in program.decls]


if __name__ == '__main__':
    unittest.main()
