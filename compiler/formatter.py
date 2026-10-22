"""Canonical formatting for Vanta source.

The formatter keeps a program's structure and only tidies the whitespace
around it:

* every logical line is indented with four spaces per block level,
* a line that continues an expression keeps its alignment relative to the
  line that opened it,
* a comment keeps its text and its place in the file,
* trailing whitespace is removed, runs of blank lines collapse to one, and
  the file ends with exactly one newline.

Only the indentation of a line changes, so the block structure the parser
sees is the same before and after.  A file that does not parse is left
alone: the formatter cannot know what the author meant.
"""

from .lexer import LexError, Lexer
from .parser import ParseError, Parser
from .tokens import TT

INDENT = '    '


class FormatError(Exception):
    """The source cannot be formatted."""


def format_source(source: str, filename: str = '<input>') -> str:
    """Return the formatted source, or raise FormatError."""
    newline = '\r\n' if '\r\n' in source else '\n'
    text = source.replace('\r\n', '\n')
    try:
        tokens = Lexer(text, filename).tokenize()
    except LexError as exc:
        raise FormatError(str(exc)) from exc
    try:
        Parser(tokens, filename).parse_program()
    except ParseError as exc:
        raise FormatError(str(exc)) from exc
    lines = text.split('\n')
    if lines and lines[-1] == '':
        lines.pop()
    out = _format_lines(lines, _logical_lines(tokens))
    result = newline.join(out)
    if result:
        result += newline
    return result


class _Group:
    """One logical line: a statement or declaration and its depth."""

    def __init__(self, start: int, end: int, depth: int):
        self.start = start          # 1-based first physical line
        self.end = end              # 1-based last physical line
        self.depth = depth
        self.new_indent = ''
        self.old_indent = 0


def _logical_lines(tokens) -> list[_Group]:
    """Group the lexer's tokens into logical lines with their depth.

    The lexer emits a newline only outside brackets, so a statement that
    spans several physical lines is one logical line.  An indent token
    opens a block and a dedent token closes one, which is what gives each
    logical line its depth.
    """
    groups: list[_Group] = []
    depth = 0
    start = 0
    end = 0
    for token in tokens:
        if token.type == TT.INDENT:
            depth += 1
            continue
        if token.type == TT.DEDENT:
            depth = max(0, depth - 1)
            continue
        if token.type == TT.EOF:
            break
        if start == 0:
            start = token.line
        end = token.line
        if token.type == TT.NEWLINE:
            groups.append(_Group(start, end, depth))
            start = 0
    if start != 0:
        groups.append(_Group(start, end, depth))
    return groups


def _scan_line(line: str) -> tuple[str, int, str, int]:
    """Split a physical line into code, gap, comment, and bracket depth.

    The gap is the whitespace between the code and a trailing comment, the
    comment keeps its marker, and the depth is the bracket nesting at the
    start of the line.  Only round and square brackets suppress the newline
    in the lexer, so they are the ones that matter here.
    """
    depth = 0
    index = 0
    in_string = False
    while index < len(line):
        char = line[index]
        if in_string:
            if char == '\\':
                index += 2
                continue
            if char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
            index += 1
            continue
        if char == '#':
            code = line[:index].rstrip()
            return code, index - len(code), line[index:], depth
        if char in '([':
            depth += 1
        elif char in ')]':
            depth = max(0, depth - 1)
        index += 1
    return line.rstrip(), 0, '', depth


def _indent_width(line: str) -> int:
    return len(line) - len(line.lstrip(' '))


def _format_lines(lines: list[str], groups: list[_Group]) -> list[str]:
    """Re-indent every logical line of the source."""
    owner: dict[int, _Group] = {}
    for group in groups:
        group.old_indent = _indent_width(lines[group.start - 1])
        for number in range(group.start, group.end + 1):
            owner[number] = group
    # A comment's own indentation says which block it belongs to.
    depth_of_width: dict[int, int] = {}
    for group in groups:
        depth_of_width.setdefault(group.old_indent, group.depth)
    widths = sorted(depth_of_width)

    out: list[str] = []
    pending_blank = False
    for number, line in enumerate(lines, 1):
        group = owner.get(number)
        code, gap, comment, start_depth = _scan_line(line)
        if group is not None and number == group.start:
            group.new_indent = INDENT * group.depth
            out.append(group.new_indent + _body(code, gap, comment))
            pending_blank = False
            continue
        if group is not None:
            # A continuation of the line above: keep its alignment.
            if not code and not comment:
                out.append('')
                continue
            delta = _indent_width(line) - group.old_indent
            width = max(0, len(group.new_indent) + delta)
            out.append(' ' * width + _body(code, gap, comment))
            continue
        if not code and not comment:
            # A blank line: keep one, drop the rest.
            if out and not pending_blank:
                out.append('')
                pending_blank = True
            continue
        pending_blank = False
        if start_depth > 0:
            # A comment inside a bracketed expression keeps its own column.
            out.append(' ' * _indent_width(line) + comment.strip())
            continue
        level = _depth_for_width(_indent_width(line), widths,
                                 depth_of_width)
        out.append(INDENT * level + comment.strip())
    while out and not out[-1]:
        out.pop()
    return out


def _body(code: str, gap: int, comment: str) -> str:
    """The text of a line, with its trailing comment."""
    if not comment:
        return code.strip()
    space = ' ' * max(1, gap)
    return code.strip() + space + comment.strip()


def _depth_for_width(width: int, widths: list[int],
                     depth_of_width: dict[int, int]) -> int:
    """The block depth of a comment at the given original indentation."""
    level = 0
    for candidate in widths:
        if candidate <= width:
            level = depth_of_width[candidate]
        else:
            break
    return level
