"""A small Language Server Protocol implementation for Vanta.

The language server deliberately reuses the real lexer, parser, loader, and
type checker for diagnostics.  Completion and navigation are backed by a
tolerant source index built from the same AST, with a line-based fallback for
the very common case where the user is in the middle of typing and the buffer
does not parse yet.

Only the pieces of LSP that the VS Code client needs are implemented:
document sync, diagnostics, completion, hover, go-to-definition, references,
rename, quick fixes, workspace symbols, semantic tokens, and document symbols.
The server speaks JSON-RPC over stdin/stdout with the usual ``Content-Length``
framing.
"""

from __future__ import annotations

import difflib
import json
import hashlib
import os
import re
import sys
import time
from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any, Optional
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

from . import VERSION
from . import ast_nodes as A
from .formatter import FormatError, format_source
from .lexer import LexError, Lexer
from .loader import LoadError, STDLIB_DIR, load_program
from .tokens import KEYWORDS, TT
from .parser import ParseError, Parser
from .type_checker import CheckError, TypeChecker
from .typesys import PRIM_TYPES


# LSP CompletionItemKind values.  Keeping names here makes the request
# handlers readable and avoids magic numbers in the symbol index.
K_TEXT = 1
K_METHOD = 2
K_FUNCTION = 3
K_CONSTRUCTOR = 4
K_FIELD = 5
K_VARIABLE = 6
K_CLASS = 7
K_MODULE = 9
K_PROPERTY = 10
K_ENUM = 13
K_KEYWORD = 14
K_SNIPPET = 15
K_ENUM_MEMBER = 20
K_CONSTANT = 21
K_STRUCT = 22
K_TYPE_PARAMETER = 25

# DocumentSymbol kinds.
S_FILE = 1
S_MODULE = 2
S_NAMESPACE = 3
S_PACKAGE = 4
S_CLASS = 5
S_METHOD = 6
S_PROPERTY = 7
S_FIELD = 8
S_CONSTRUCTOR = 9
S_ENUM = 10
S_INTERFACE = 11
S_FUNCTION = 12
S_VARIABLE = 13
S_CONSTANT = 14
S_STRING = 15
S_NUMBER = 16
S_BOOLEAN = 17
S_ARRAY = 18
S_OBJECT = 19
S_KEY = 20
S_NULL = 21
S_ENUM_MEMBER = 22
S_STRUCT = 23
S_EVENT = 24
S_OPERATOR = 25
S_TYPE_PARAMETER = 26

# Semantic token types.  The order is the legend the server advertises, so
# the numbers are part of the protocol contract with the editor.
ST_NAMESPACE = 0
ST_TYPE = 1
ST_CLASS = 2
ST_ENUM = 3
ST_INTERFACE = 4
ST_STRUCT = 5
ST_TYPE_PARAMETER = 6
ST_PARAMETER = 7
ST_VARIABLE = 8
ST_PROPERTY = 9
ST_ENUM_MEMBER = 10
ST_EVENT = 11
ST_FUNCTION = 12
ST_METHOD = 13
ST_MACRO = 14
ST_KEYWORD = 15
ST_MODIFIER = 16
ST_COMMENT = 17
ST_STRING = 18
ST_NUMBER = 19
ST_REGEXP = 20
ST_OPERATOR = 21
ST_DECORATOR = 22

SEMANTIC_TOKEN_TYPES = [
    'namespace', 'type', 'class', 'enum', 'interface', 'struct',
    'typeParameter', 'parameter', 'variable', 'property', 'enumMember',
    'event', 'function', 'method', 'macro', 'keyword', 'modifier', 'comment',
    'string', 'number', 'regexp', 'operator', 'decorator',
]

# Semantic token modifiers, in legend order.
ST_MOD_DECLARATION = 1 << 0
ST_MOD_DEFINITION = 1 << 1
ST_MOD_READONLY = 1 << 2
ST_MOD_STATIC = 1 << 3
ST_MOD_DEPRECATED = 1 << 4
ST_MOD_ABSTRACT = 1 << 5
ST_MOD_ASYNC = 1 << 6
ST_MOD_MODIFICATION = 1 << 7
ST_MOD_DOCUMENTATION = 1 << 8
ST_MOD_DEFAULT_LIBRARY = 1 << 9

SEMANTIC_TOKEN_MODIFIERS = [
    'declaration', 'definition', 'readonly', 'static', 'deprecated',
    'abstract', 'async', 'modification', 'documentation', 'defaultLibrary',
]

# The semantic kind of a resolved identifier, mapped to a token type and
# the modifiers that kind always carries.
_SEMANTIC_TOKEN_BY_KIND = {
    'function': (ST_FUNCTION, 0),
    'struct': (ST_STRUCT, 0),
    'enum': (ST_ENUM, 0),
    'const': (ST_VARIABLE, ST_MOD_READONLY),
    'parameter': (ST_PARAMETER, 0),
    'variable': (ST_VARIABLE, 0),
    'property': (ST_PROPERTY, 0),
    'enumMember': (ST_ENUM_MEMBER, 0),
    'namespace': (ST_NAMESPACE, 0),
}

# Lexical token types, mapped to a semantic token type.
_SEMANTIC_LEXICAL_TYPE = {
    TT.FUNC: ST_KEYWORD,
    TT.LET: ST_KEYWORD,
    TT.MUT: ST_KEYWORD,
    TT.RETURN: ST_KEYWORD,
    TT.CONST: ST_KEYWORD,
    TT.STRUCT: ST_KEYWORD,
    TT.COMPONENT: ST_KEYWORD,
    TT.SYSTEM: ST_KEYWORD,
    TT.EXTERN: ST_KEYWORD,
    TT.ENUM: ST_KEYWORD,
    TT.IMPORT: ST_KEYWORD,
    TT.MODULE: ST_KEYWORD,
    TT.PUB: ST_KEYWORD,
    TT.AS: ST_KEYWORD,
    TT.IF: ST_KEYWORD,
    TT.ELIF: ST_KEYWORD,
    TT.ELSE: ST_KEYWORD,
    TT.MATCH: ST_KEYWORD,
    TT.WHILE: ST_KEYWORD,
    TT.FOR: ST_KEYWORD,
    TT.IN: ST_KEYWORD,
    TT.BREAK: ST_KEYWORD,
    TT.CONTINUE: ST_KEYWORD,
    TT.TRUE: ST_KEYWORD,
    TT.FALSE: ST_KEYWORD,
    TT.AND: ST_KEYWORD,
    TT.OR: ST_KEYWORD,
    TT.NOT: ST_KEYWORD,
    TT.STRING: ST_STRING,
    TT.INT: ST_NUMBER,
    TT.FLOAT: ST_NUMBER,
    TT.PLUS: ST_OPERATOR,
    TT.MINUS: ST_OPERATOR,
    TT.STAR: ST_OPERATOR,
    TT.SLASH: ST_OPERATOR,
    TT.PERCENT: ST_OPERATOR,
    TT.EQ: ST_OPERATOR,
    TT.NEQ: ST_OPERATOR,
    TT.LT: ST_OPERATOR,
    TT.LTE: ST_OPERATOR,
    TT.GT: ST_OPERATOR,
    TT.GTE: ST_OPERATOR,
    TT.ASSIGN: ST_OPERATOR,
    TT.PLUS_EQ: ST_OPERATOR,
    TT.MINUS_EQ: ST_OPERATOR,
    TT.STAR_EQ: ST_OPERATOR,
    TT.SLASH_EQ: ST_OPERATOR,
    TT.ARROW: ST_OPERATOR,
    TT.DOT: ST_OPERATOR,
    TT.COLONCOLON: ST_OPERATOR,
}


# ---------------------------------------------------------------------------
# URI, position, and text helpers
# ---------------------------------------------------------------------------


def uri_to_path(uri: str) -> Optional[str]:
    """Convert a file:// URI from the editor into a native path."""
    if not uri:
        return None
    parsed = urlparse(uri)
    if parsed.scheme != 'file':
        return None
    path = url2pathname(unquote(parsed.path))
    if parsed.netloc and parsed.netloc not in ('', 'localhost'):
        path = '//' + parsed.netloc + path
    if os.name == 'nt' and path.startswith('/') and len(path) > 2 \
            and path[2] == ':':
        path = path[1:]
    return os.path.normpath(path)


def path_to_uri(path: str) -> str:
    """Convert a native path into a file:// URI."""
    return Path(os.path.abspath(path)).as_uri()


def _norm_path(path: str) -> str:
    return os.path.normcase(os.path.realpath(path))


def _strip_bom(text: str) -> str:
    """Match the lexer's UTF-8 BOM handling for editor buffers."""
    return text[1:] if text.startswith('\ufeff') else text


def _lines(text: str) -> list[str]:
    # splitlines() drops the final empty line for text ending in '\n', which
    # is exactly what a position at EOF should not do.  Keep one final empty
    # line so line numbers past the last newline remain valid.
    lines = text.splitlines()
    if not lines or text.endswith(('\n', '\r')):
        lines.append('')
    return lines


def _line_at(lines: list[str], line: int) -> str:
    if not lines:
        return ''
    return lines[max(0, min(line, len(lines) - 1))]


def _utf16_len(text: str) -> int:
    return len(text.encode('utf-16-le')) // 2


def _py_to_lsp_char(line_text: str, index: int) -> int:
    index = max(0, min(index, len(line_text)))
    return _utf16_len(line_text[:index])


def _lsp_to_py_char(line_text: str, char: int) -> int:
    """Convert a UTF-16 code-unit offset to a Python string index."""
    units = 0
    for i, ch in enumerate(line_text):
        width = 2 if ord(ch) > 0xFFFF else 1
        if units + width > char:
            return i
        units += width
        if units == char:
            return i + 1
    return len(line_text)


def _position_to_py(text: str, line: int, char: int) -> tuple[int, int]:
    lines = _lines(text)
    line = max(0, min(line, len(lines) - 1))
    return line, _lsp_to_py_char(lines[line], max(0, char))


def _range(line: int, col: int, end_line: int, end_col: int) -> dict:
    """A range from 1-based Vanta positions."""
    return {
        'start': {'line': max(0, line - 1), 'character': max(0, col - 1)},
        'end': {'line': max(0, end_line - 1), 'character': max(0, end_col - 1)},
    }


def _quoted_span(line_text: str, value: str) -> Optional[tuple[int, int]]:
    """Return the (start, end) of a quoted string on the line."""
    token = '"' + value + '"'
    index = line_text.find(token)
    if index >= 0:
        return index, index + len(token)
    index = line_text.find(value)
    if index < 0:
        return None
    return index, index + len(value)


def _comment_folds(lines: list[str]) -> list[dict]:
    """Fold runs of two or more comment-only lines at one indentation."""
    ranges: list[dict] = []
    start = -1
    last = -1
    indent = -1
    for number, text in enumerate(lines):
        if text.strip().startswith('#'):
            current = len(text) - len(text.lstrip(' '))
            if start >= 0 and current == indent:
                last = number
                continue
            if start >= 0 and last > start:
                ranges.append({'startLine': start, 'endLine': last,
                               'kind': 'comment'})
            start = number
            last = number
            indent = current
        else:
            if start >= 0 and last > start:
                ranges.append({'startLine': start, 'endLine': last,
                               'kind': 'comment'})
            start = -1
            last = -1
            indent = -1
    if start >= 0 and last > start:
        ranges.append({'startLine': start, 'endLine': last,
                       'kind': 'comment'})
    return ranges


def _import_folds(lines: list[str]) -> list[dict]:
    """Fold a run of two or more consecutive import lines."""
    ranges: list[dict] = []
    start = -1
    last = -1
    for number, text in enumerate(lines):
        if _IMPORT_RE.match(text):
            if start < 0:
                start = number
            last = number
        else:
            if start >= 0 and last > start:
                ranges.append({'startLine': start, 'endLine': last,
                               'kind': 'imports'})
            start = -1
            last = -1
    if start >= 0 and last > start:
        ranges.append({'startLine': start, 'endLine': last,
                       'kind': 'imports'})
    return ranges


def _word_at(line_text: str, char: int) -> tuple[str, int, int]:
    """Return (word, start, end) for the identifier at a UTF-16 offset."""
    index = _lsp_to_py_char(line_text, char)
    if index and (index >= len(line_text)
                  or not (line_text[index].isalnum()
                          or line_text[index] == '_')):
        probe = index - 1
    else:
        probe = index
    start = probe
    while start > 0 and (line_text[start - 1].isalnum()
                         or line_text[start - 1] == '_'):
        start -= 1
    end = probe
    while end < len(line_text) and (line_text[end].isalnum()
                                    or line_text[end] == '_'):
        end += 1
    return line_text[start:end], _py_to_lsp_char(line_text, start), \
        _py_to_lsp_char(line_text, end)


def _ranges_overlap(first: dict, second: dict) -> bool:
    def key(value: Optional[dict]) -> tuple[int, int]:
        value = value or {}
        return (int(value.get('line', 0)), int(value.get('character', 0)))

    return (key(first.get('start')) <= key(second.get('end'))
            and key(second.get('start')) <= key(first.get('end')))


def _decl_symbol_kind(kind: str) -> int:
    """The LSP SymbolKind for a declaration kind."""
    return {
        'func': S_FUNCTION,
        'struct': S_STRUCT,
        'enum': S_ENUM,
        'const': S_CONSTANT,
    }.get(kind, S_VARIABLE)


def _symbol_score(name: str, query: str) -> Optional[int]:
    """Rank a symbol against a workspace-symbol query; None means no match.

    The ranking mirrors what editors expect: an exact name first, then a
    prefix, then a case-insensitive substring, and finally a loose
    subsequence match so `dmg` still finds `damage`.
    """
    if not query:
        return 0
    lowered = name.lower()
    needle = query.lower()
    if lowered == needle:
        return 0
    if lowered.startswith(needle):
        return 1
    index = lowered.find(needle)
    if index >= 0:
        return 2
    position = 0
    for char in needle:
        position = lowered.find(char, position)
        if position < 0:
            return None
        position += 1
    return 3


def _lexical_token_length(token: Any, line_text: str, col: int) -> int:
    """The source length of a lexical token, in UTF-16 units.

    The lexer stores decoded values, so a string's escapes and a number's
    leading zeros would make the value shorter than the text it came from.
    The source is measured instead.
    """
    if token.type == TT.STRING:
        index = col
        while index < len(line_text) and line_text[index] != '"':
            index += 1
        if index < len(line_text):
            index += 1
        while index < len(line_text) and line_text[index] != '"':
            index += 1
        if index < len(line_text):
            index += 1
        return _utf16_len(line_text[col:index])
    if token.type in (TT.INT, TT.FLOAT):
        index = col
        while index < len(line_text) and (
                line_text[index].isdigit() or line_text[index] == '.'):
            index += 1
        return _utf16_len(line_text[col:index])
    value = token.value
    if not isinstance(value, str):
        value = str(value)
    return _utf16_len(value)


def _dedupe_tokens(tokens: list[tuple[int, int, int, int, int]]) \
        -> list[tuple[int, int, int, int, int]]:
    """Drop tokens that overlap an earlier one at the same place.

    The protocol forbids overlapping tokens, and the walker and the lexer can
    both claim the same word: a resolved identifier wins, because it carries
    more meaning than the lexical classification.
    """
    ordered = sorted(tokens, key=lambda item: (item[0], item[1], -item[2]))
    result: list[tuple[int, int, int, int, int]] = []
    seen: set[tuple[int, int]] = set()
    for token in ordered:
        key = (token[0], token[1])
        if key in seen:
            continue
        seen.add(key)
        result.append(token)
    return result


def _comment_tokens(text: str, lines: list[str]) \
        -> list[tuple[int, int, int, int, int]]:
    """Comment tokens, which the lexer drops from its token stream."""
    tokens: list[tuple[int, int, int, int, int]] = []
    for number, line in enumerate(lines):
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
                start = _py_to_lsp_char(line, index)
                length = _utf16_len(line[index:])
                tokens.append((number, start, length, ST_COMMENT, 0))
                break
            index += 1
    return tokens


def _walk_vanta_files(root: str, limit: int = 2000) -> list[str]:
    """Every .vnt file under a directory, skipping noisy folders."""
    skip = {'.git', 'node_modules', '__pycache__', '.venv', 'venv', 'env',
            'build', 'dist', 'target', '.mypy_cache', '.pytest_cache'}
    found: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames
                       if name not in skip and not name.startswith('.')]
        for name in sorted(filenames):
            if not name.endswith('.vnt'):
                continue
            found.append(os.path.join(dirpath, name))
            if len(found) >= limit:
                return found
    return found


def _object_before_dot(line_text: str, word_start: int) -> Optional[list[str]]:
    """Return the dotted object path immediately before a member word."""
    prefix = line_text[:word_start]
    if not prefix.endswith('.'):
        return None
    prefix = prefix[:-1].rstrip()
    match = re.search(r'([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)$', prefix)
    if match is None:
        return None
    return match.group(1).split('.')


def _find_name_pos(source_lines: list[str], pos: A.Pos, name: str) \
        -> tuple[int, int]:
    """Locate a declaration name on its declaration line."""
    if not (1 <= pos.line <= len(source_lines)):
        return pos.line, pos.col
    line = source_lines[pos.line - 1]
    start = max(0, pos.col - 1)
    match = re.search(r'\b' + re.escape(name) + r'\b', line[start:])
    if match is not None:
        return pos.line, start + match.start() + 1
    idx = line.find(name)
    if idx < 0:
        return pos.line, pos.col
    return pos.line, idx + 1


def _line_indent(line: str) -> int:
    return len(line) - len(line.lstrip(' '))


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class FieldInfo:
    name: str
    type_name: str
    line: int
    col: int
    detail: str = ''


@dataclass
class MemberInfo:
    name: str
    payload: str = ''
    line: int = 1
    col: int = 1

    @property
    def detail(self) -> str:
        return f'{self.name}({self.payload})' if self.payload else self.name


@dataclass
class DeclInfo:
    name: str
    kind: str                 # func, struct, enum, const, extern_func
    detail: str
    path: str
    line: int
    col: int
    end_line: int = 0
    end_col: int = 1
    name_line: int = 0
    name_col: int = 0
    public: bool = True
    type_params: list[str] = field(default_factory=list)
    fields: list[FieldInfo] = field(default_factory=list)
    members: list[MemberInfo] = field(default_factory=list)
    top_level: bool = True

    def location(self) -> dict:
        uri = path_to_uri(self.path)
        end_line = max(self.end_line or self.line, self.line)
        return {
            'uri': uri,
            'range': _range(self.line, self.col, end_line,
                            max(1, self.end_col)),
        }


@dataclass
class LocalInfo:
    name: str
    type_name: str
    detail: str
    line: int
    col: int
    name_line: int
    name_col: int
    kind: str = 'var'
    mutable: bool = False


@dataclass
class ImportInfo:
    path: str
    alias: Optional[str]
    line: int
    col: int
    target: Optional['ModuleInfo'] = None


@dataclass
class ModuleInfo:
    path: str
    source: str
    module_name: Optional[str] = None
    is_legacy: bool = True
    decls: list[DeclInfo] = field(default_factory=list)
    imports: list[ImportInfo] = field(default_factory=list)
    # The parsed program when the buffer parses, else None.  Editor features
    # that need lexical scopes (references, rename) walk this AST.
    program: Optional[A.Program] = None

    def public_decls(self) -> list[DeclInfo]:
        if self.is_legacy:
            return list(self.decls)
        return [d for d in self.decls if d.public]


# ---------------------------------------------------------------------------
# Tolerant project index
# ---------------------------------------------------------------------------


_TYPE_DECL_RE = re.compile(
    r'^(pub\s+)?(func|system|struct|component|enum|const|extern)\b(.*)$')
_MODULE_RE = re.compile(r'^module\s+([A-Za-z_]\w*)\s*$')
_IMPORT_RE = re.compile(
    r'^import\s+"([^"]+)"(?:\s+as\s+([A-Za-z_]\w*))?')
_FUNC_RE = re.compile(
    r'^\s+([A-Za-z_]\w*)\s*\((.*?)\)\s*(?:->\s*(.+?))?\s*:?\s*$')


_PARSE_CACHE: dict = {}


def _cache_key(path: str, text: str) -> tuple:
    return (os.path.normpath(path or ''),
            hashlib.sha256(text.encode('utf-8')).hexdigest())


class _ProjectIndex:
    """A source-level view of the current file and its imports.

    The loader's resolver mutates declaration names to internal module names.
    For editor features we want the names exactly as written, so this index
    parses files directly and only uses the loader's path resolution rules.
    It is intentionally tolerant: if a buffer does not parse, declarations
    are recovered with a line scanner instead.
    """

    def __init__(self, entry_path: str, sources: Optional[dict[str, str]] = None):
        self.entry_path = entry_path
        self.sources = {
            _norm_path(path): _strip_bom(text)
            for path, text in (sources or {}).items()
        }
        self.cache: dict[str, ModuleInfo] = {}
        self.standalone: dict[str, ModuleInfo] = {}
        self.current = self._load(entry_path, [])

    def parse_only(self, path: str) -> ModuleInfo:
        """Parse one file's declarations without following its imports."""
        text = self._source_for(path)
        if text is None:
            mod = ModuleInfo(path=path, source='')
            self.standalone[_norm_path(path)] = mod
            return mod
        return self.parse_text(path, text)

    def parse_text(self, path: str, text: str) -> ModuleInfo:
        """Parse declarations from text, reusing the last result if it fits."""
        key = _norm_path(path)
        cached = self.standalone.get(key)
        if cached is not None and cached.source == text:
            return cached
        mod = self._parse_module(path, text)
        self.standalone[key] = mod
        return mod

    def _source_for(self, path: str) -> Optional[str]:
        key = _norm_path(path)
        if key in self.sources:
            return self.sources[key]
        try:
            with open(path, 'r', encoding='utf-8-sig') as f:
                return f.read()
        except (OSError, UnicodeError):
            return None

    def _exists(self, path: str) -> bool:
        return _norm_path(path) in self.sources or os.path.exists(path)

    def _resolve_import(self, path: str, imp: str) -> str:
        target = os.path.normpath(os.path.join(os.path.dirname(path), imp))
        if self._exists(target) or STDLIB_DIR is None:
            return target
        rel = imp.replace('\\', '/')
        if rel.startswith('std/'):
            candidate = os.path.normpath(
                os.path.join(STDLIB_DIR, rel[len('std/'):]))
            if self._exists(candidate):
                return candidate
        return target

    def _load(self, path: str, stack: list[str]) -> ModuleInfo:
        key = _norm_path(path)
        if key in self.cache:
            return self.cache[key]
        text = self._source_for(path)
        if text is None:
            mod = ModuleInfo(path=path, source='')
            self.cache[key] = mod
            return mod
        mod = self._parse_module(path, text)
        self.cache[key] = mod
        if key in stack:
            return mod
        for imp in mod.imports:
            target = self._resolve_import(path, imp.path)
            if self._exists(target):
                imp.target = self._load(target, stack + [key])
        return mod

    def _parse_module(self, path: str, text: str) -> ModuleInfo:
        key = _cache_key(path, text)
        cached = _PARSE_CACHE.get(key)
        if cached is not None:
            return cached
        source_lines = text.splitlines()
        module_name = None
        imports: list[ImportInfo] = []
        for i, line in enumerate(source_lines, 1):
            m = _MODULE_RE.match(line)
            if m:
                module_name = m.group(1)
                break
        for i, line in enumerate(source_lines, 1):
            m = _IMPORT_RE.match(line)
            if m:
                imports.append(ImportInfo(path=m.group(1), alias=m.group(2),
                                           line=i, col=1))
        is_legacy = module_name is None

        program = None
        try:
            tokens = Lexer(text, path).tokenize()
            program = Parser(tokens, path).parse_program()
        except (LexError, ParseError):
            program = None

        if program is not None:
            mod = self._from_ast(path, text, source_lines, program,
                                 module_name, is_legacy)
        else:
            mod = self._from_text(path, text, source_lines,
                                  module_name, is_legacy)
        mod.imports = imports
        # Prefer AST import nodes: they know the exact import position and
        # have already handled the `as` alias.
        if program is not None:
            ast_imports = []
            for d in program.decls:
                if isinstance(d, A.ImportDecl):
                    ast_imports.append(ImportInfo(
                        path=d.path, alias=d.alias,
                        line=d.pos.line, col=d.pos.col))
            mod.imports = ast_imports
        mod.program = program
        self._finish_ranges(mod.decls, source_lines)
        _PARSE_CACHE[key] = mod
        return mod

    def _from_ast(self, path: str, text: str, source_lines: list[str],
                  program: A.Program, module_name: Optional[str],
                  is_legacy: bool) -> ModuleInfo:
        decls: list[DeclInfo] = []
        for d in program.decls:
            if isinstance(d, A.FuncDecl):
                name_line, name_col = _find_name_pos(
                    source_lines, d.pos, d.name)
                params = ', '.join(
                    f'{p.name}: {_type_expr_text(p.type)}' for p in d.params)
                ret = _type_expr_text(d.ret)
                keyword = 'system func' if d.is_system else 'func'
                detail = f'{keyword} {d.name}({params})'
                if d.ret is not None:
                    detail += f' -> {ret}'
                decls.append(DeclInfo(
                    name=d.name, kind='func', detail=detail, path=path,
                    line=d.pos.line, col=d.pos.col, name_line=name_line,
                    name_col=name_col, public=is_legacy or d.is_public))
            elif isinstance(d, A.StructDecl):
                name_line, name_col = _find_name_pos(
                    source_lines, d.pos, d.name)
                fields = [
                    FieldInfo(fname, _type_expr_text(ftype), fpos.line,
                              fpos.col, f'{fname}: {_type_expr_text(ftype)}')
                    for fname, ftype, fpos, _pub in d.fields
                ]
                keyword = 'component' if d.is_component else 'struct'
                generics = (f'<{", ".join(d.type_params)}>'
                            if d.type_params else '')
                details = ', '.join(f'{f.name}: {f.type_name}' for f in fields)
                decls.append(DeclInfo(
                    name=d.name, kind='struct',
                    detail=f'{keyword} {d.name}{generics}'
                           + (f' {{ {details} }}' if details else ''),
                    path=path, line=d.pos.line, col=d.pos.col,
                    name_line=name_line, name_col=name_col,
                    public=is_legacy or d.is_public, fields=fields))
            elif isinstance(d, A.EnumDecl):
                name_line, name_col = _find_name_pos(
                    source_lines, d.pos, d.name)
                members = []
                for m in d.members:
                    payload = ', '.join(_type_expr_text(t)
                                        for t in (m.payload or []))
                    members.append(MemberInfo(m.name, payload, m.pos.line,
                                              m.pos.col))
                params = (f'<{", ".join(d.type_params)}>'
                          if d.type_params else '')
                member_text = ', '.join(m.detail for m in members)
                decls.append(DeclInfo(
                    name=d.name, kind='enum',
                    detail=f'enum {d.name}{params}' +
                           (f' {{ {member_text} }}' if member_text else ''),
                    path=path, line=d.pos.line, col=d.pos.col,
                    name_line=name_line, name_col=name_col,
                    public=is_legacy or d.is_public,
                    type_params=list(d.type_params), members=members))
            elif isinstance(d, A.ConstDecl):
                name_line, name_col = _find_name_pos(
                    source_lines, d.pos, d.name)
                typ = _type_expr_text(d.type_ann) if d.type_ann else ''
                decls.append(DeclInfo(
                    name=d.name, kind='const',
                    detail=f'const {d.name}' + (f': {typ}' if typ else ''),
                    path=path, line=d.pos.line, col=d.pos.col,
                    name_line=name_line, name_col=name_col,
                    public=is_legacy or d.is_public))
            elif isinstance(d, A.ExternDecl):
                for fd in d.funcs:
                    name_line, name_col = _find_name_pos(
                        source_lines, fd.pos, fd.name)
                    params = ', '.join(
                        f'{p.name}: {_type_expr_text(p.type)}'
                        for p in fd.params)
                    ret = _type_expr_text(fd.ret)
                    detail = f'extern func {fd.name}({params})'
                    if fd.ret is not None:
                        detail += f' -> {ret}'
                    decls.append(DeclInfo(
                        name=fd.name, kind='func', detail=detail,
                        path=path, line=fd.pos.line, col=fd.pos.col,
                        name_line=name_line, name_col=name_col,
                        public=is_legacy or d.is_public))
        return ModuleInfo(path=path, source=text, module_name=module_name,
                          is_legacy=is_legacy, decls=decls)

    def _from_text(self, path: str, text: str, source_lines: list[str],
                   module_name: Optional[str], is_legacy: bool) -> ModuleInfo:
        decls: list[DeclInfo] = []
        i = 0
        while i < len(source_lines):
            line = source_lines[i]
            stripped = line.strip()
            if not stripped or stripped.startswith('#'):
                i += 1
                continue
            if _line_indent(line) != 0:
                i += 1
                continue
            m = _TYPE_DECL_RE.match(line)
            if not m:
                i += 1
                continue
            public = bool(m.group(1)) or is_legacy
            kind = m.group(2)
            rest = m.group(3).strip()
            line_no = i + 1
            if kind in ('func', 'system'):
                fm = re.match(
                    r'([A-Za-z_]\w*)\s*(?:\((.*?)\))?\s*'
                    r'(?:->\s*(.+?))?\s*:?\s*$', rest)
                if fm:
                    name = fm.group(1)
                    params = fm.group(2) or ''
                    ret = (fm.group(3) or '').strip()
                    name_col = line.find(name) + 1
                    detail = (f'{"system func" if kind == "system" else "func"} '
                              f'{name}({params})')
                    if ret:
                        detail += f' -> {ret}'
                    decls.append(DeclInfo(
                        name=name, kind='func', detail=detail, path=path,
                        line=line_no, col=1, name_line=line_no,
                        name_col=name_col, public=public))
                i += 1
                continue
            if kind in ('struct', 'component'):
                sm = re.match(r'([A-Za-z_]\w*)\s*:', rest)
                if not sm:
                    i += 1
                    continue
                name = sm.group(1)
                name_col = line.find(name) + 1
                fields: list[FieldInfo] = []
                j = i + 1
                while j < len(source_lines):
                    nxt = source_lines[j]
                    if not nxt.strip():
                        j += 1
                        continue
                    if _line_indent(nxt) == 0:
                        break
                    fld = re.match(
                        r'\s+([A-Za-z_]\w*)\s*:\s*(.+?)\s*$', nxt)
                    if fld:
                        fields.append(FieldInfo(
                            fld.group(1), fld.group(2).strip(), j + 1,
                            len(nxt) - len(nxt.lstrip()) + 1,
                            f'{fld.group(1)}: {fld.group(2).strip()}'))
                    j += 1
                details = ', '.join(f'{f.name}: {f.type_name}'
                                    for f in fields)
                decls.append(DeclInfo(
                    name=name, kind='struct',
                    detail=f'{kind} {name}' + (f' {{ {details} }}'
                                                if details else ''),
                    path=path, line=line_no, col=1, name_line=line_no,
                    name_col=name_col, public=public, fields=fields))
                i = j
                continue
            if kind == 'enum':
                em = re.match(
                    r'([A-Za-z_]\w*)\s*(?:<([^>]*)>)?\s*:', rest)
                if not em:
                    i += 1
                    continue
                name = em.group(1)
                name_col = line.find(name) + 1
                params = [p.strip() for p in (em.group(2) or '').split(',')
                          if p.strip()]
                members: list[MemberInfo] = []
                j = i + 1
                while j < len(source_lines):
                    nxt = source_lines[j]
                    if not nxt.strip():
                        j += 1
                        continue
                    if _line_indent(nxt) == 0:
                        break
                    mm = re.match(
                        r'\s+([A-Za-z_]\w*)\s*(?:\(([^)]*)\))?'
                        r'(?:\s*=\s*-?\d+)?\s*$', nxt)
                    if mm:
                        members.append(MemberInfo(
                            mm.group(1), (mm.group(2) or '').strip(),
                            j + 1, len(nxt) - len(nxt.lstrip()) + 1))
                    j += 1
                member_text = ', '.join(m.detail for m in members)
                decls.append(DeclInfo(
                    name=name, kind='enum',
                    detail=f'enum {name}' +
                           (f'<{", ".join(params)}>' if params else '') +
                           (f' {{ {member_text} }}' if member_text else ''),
                    path=path, line=line_no, col=1, name_line=line_no,
                    name_col=name_col, public=public, type_params=params,
                    members=members))
                i = j
                continue
            if kind == 'const':
                cm = re.match(
                    r'([A-Za-z_]\w*)\s*(?::\s*([^=]+?))?\s*=', rest)
                if cm:
                    name = cm.group(1)
                    typ = (cm.group(2) or '').strip()
                    decls.append(DeclInfo(
                        name=name, kind='const',
                        detail=f'const {name}' + (f': {typ}' if typ else ''),
                        path=path, line=line_no, col=1, name_line=line_no,
                        name_col=line.find(name) + 1, public=public))
                i += 1
                continue
            if kind == 'extern':
                j = i + 1
                while j < len(source_lines) and '}' not in source_lines[j]:
                    fm = _FUNC_RE.match(source_lines[j])
                    if fm:
                        name = fm.group(1)
                        params = fm.group(2) or ''
                        ret = (fm.group(3) or '').strip()
                        detail = f'extern func {name}({params})'
                        if ret:
                            detail += f' -> {ret}'
                        decls.append(DeclInfo(
                            name=name, kind='func', detail=detail,
                            path=path, line=j + 1, col=1,
                            name_line=j + 1,
                            name_col=source_lines[j].find(name) + 1,
                            public=public))
                    j += 1
                i = j + 1
                continue
            i += 1
        return ModuleInfo(path=path, source=text, module_name=module_name,
                          is_legacy=is_legacy, decls=decls)

    @staticmethod
    def _finish_ranges(decls: list[DeclInfo], source_lines: list[str]) -> None:
        top = sorted((d for d in decls if d.top_level), key=lambda d: d.line)
        for i, d in enumerate(top):
            if i + 1 < len(top):
                end = max(d.line, top[i + 1].line - 1)
            else:
                end = max(d.line, len(source_lines))
            while end > d.line and not _line_at(
                    source_lines, max(0, end - 1)).strip():
                end -= 1
            d.end_line = end
            d.end_col = _utf16_len(
                _line_at(source_lines, max(0, end - 1))) + 1

    # -- lookups -----------------------------------------------------------

    def visible_decls(self) -> list[DeclInfo]:
        result = list(self.current.decls)
        for imp in self.current.imports:
            if imp.target is None or imp.alias:
                continue
            result.extend(imp.target.public_decls())
        return result

    def public_imports(self) -> list[DeclInfo]:
        result: list[DeclInfo] = []
        for imp in self.current.imports:
            if imp.target is not None and not imp.alias:
                result.extend(imp.target.public_decls())
        return result

    def alias_module(self, name: str) -> Optional[ModuleInfo]:
        for imp in self.current.imports:
            if imp.alias == name and imp.target is not None:
                return imp.target
        return None

    def decl_by_name(self, name: str) -> Optional[DeclInfo]:
        for d in self.visible_decls():
            if d.name == name:
                return d
        return None

    def type_by_name(self, name: str) -> Optional[DeclInfo]:
        for d in self.visible_decls():
            if d.name == name and d.kind in ('struct', 'enum'):
                return d
        return None

    def type_in_module(self, module: ModuleInfo, name: str) \
            -> Optional[DeclInfo]:
        for d in module.public_decls():
            if d.name == name and d.kind in ('struct', 'enum'):
                return d
        return None

    def resolve_object(self, object_path: list[str],
                       local_type: Optional[str] = None) -> Optional[DeclInfo]:
        if not object_path:
            return None
        if len(object_path) == 1:
            if local_type:
                return self.type_by_name(_base_type_name(local_type))
            return self.type_by_name(object_path[0])
        first = object_path[0]
        rest = object_path[1:]
        module = self.alias_module(first)
        if module is not None:
            if rest:
                return self.type_in_module(module, _base_type_name(rest[-1]))
            return None
        # A type name followed by a member is not an object; the caller handles
        # enum members separately.
        return self.type_by_name(_base_type_name(object_path[-1]))

    def module_for_alias(self, name: str) -> Optional[ModuleInfo]:
        return self.alias_module(name)

    def local_symbols(self, line: int, char: int) -> dict[str, LocalInfo]:
        """Best-effort locals visible at a 0-based LSP position."""
        text = self.current.source
        lines = _lines(text)
        if line >= len(lines):
            line = len(lines) - 1
        # If the buffer parses, use its AST and return accurate names/types.
        try:
            program = Parser(Lexer(text, self.current.path).tokenize(),
                             self.current.path).parse_program()
            result = self._ast_locals(program, line, char)
            if result is not None:
                return result
        except (LexError, ParseError):
            pass
        return self._text_locals(lines, line, char)

    def _ast_locals(self, program: A.Program, line: int, char: int) \
            -> Optional[dict[str, LocalInfo]]:
        func = _containing_function(program, line)
        if func is None:
            return {}
        cursor_line_text = _line_at(_lines(self.current.source), line)
        if _line_indent(cursor_line_text) <= func.pos.col - 1:
            return {}
        result: dict[str, LocalInfo] = {}
        for p in func.params:
            result[p.name] = LocalInfo(
                p.name, _type_expr_text(p.type),
                f'{p.name}: {_type_expr_text(p.type)}',
                p.pos.line, p.pos.col, p.pos.line, p.pos.col, 'param')
        pending: list[A.VarDecl] = []
        _walk(func.body, lambda n: pending.append(n)
              if isinstance(n, A.VarDecl) else None)
        for v in pending:
            if v.pos.line > line + 1:
                continue
            nl, nc = _find_name_pos(_lines(self.current.source), v.pos, v.name)
            typ = _type_expr_text(v.type_ann) if v.type_ann else \
                _infer_value_type(v.value, result)
            qualifier = 'mut' if v.mutable else 'let'
            result[v.name] = LocalInfo(
                v.name, typ, f'{qualifier} {v.name}' + (f': {typ}' if typ else ''),
                v.pos.line, v.pos.col, nl, nc, 'var', v.mutable)
        for n in _walk_collect(func.body, (A.ForEachStmt, A.ForRangeStmt)):
            if n.pos.line <= line + 1:
                result.setdefault(n.var, LocalInfo(
                    n.var, '', n.var, n.pos.line, n.pos.col, n.pos.line,
                    n.pos.col, 'var'))
        return result

    def _text_locals(self, lines: list[str], line: int, char: int) \
            -> dict[str, LocalInfo]:
        result: dict[str, LocalInfo] = {}
        cursor_text = _line_at(lines, line)
        cursor_indent = _line_indent(cursor_text)
        func_line = None
        for i in range(min(line, len(lines) - 1), -1, -1):
            text = lines[i]
            m = re.match(r'^(\s*)(?:pub\s+)?(func|system)\s+'
                         r'([A-Za-z_]\w*)\s*(?:\((.*?)\))?', text)
            if m:
                indent = len(m.group(1))
                if indent < cursor_indent or indent == 0:
                    func_line = i
                    break
        if func_line is None:
            return {}
        start_text = lines[func_line]
        fm = re.search(r'\(([^)]*)\)', start_text)
        if fm:
            for part in _split_top(fm.group(1)):
                pm = re.match(r'\s*([A-Za-z_]\w*)\s*:\s*(.+?)\s*$', part)
                if pm:
                    name = pm.group(1)
                    idx = start_text.find(name)
                    result[name] = LocalInfo(
                        name, pm.group(2).strip(),
                        f'{name}: {pm.group(2).strip()}', func_line + 1,
                        idx + 1, func_line + 1, idx + 1, 'param')
        for i in range(func_line + 1, min(line + 1, len(lines))):
            text = lines[i]
            m = re.match(
                r'^(\s+)(let|mut)\s+([A-Za-z_]\w*)'
                r'(?:\s*:\s*([^=]+?))?\s*(?:=\s*(.*))?$', text)
            if not m:
                continue
            name = m.group(3)
            typ = (m.group(4) or '').strip() or _infer_text_type(m.group(5))
            idx = text.find(name) + 1
            qualifier = m.group(2)
            result[name] = LocalInfo(
                name, typ, f'{qualifier} {name}' + (f': {typ}' if typ else ''),
                i + 1, _line_indent(text) + 1, i + 1, idx, 'var',
                qualifier == 'mut')
        return result


def _base_type_name(type_name: str) -> str:
    return type_name.split('<', 1)[0].strip()


def _return_type_text(detail: str) -> str:
    """Extract the return type from a DeclInfo detail string."""
    if '->' not in detail:
        return ''
    return detail.rsplit('->', 1)[1].strip()


def _type_expr_text(te: Optional[A.TypeExpr]) -> str:
    if te is None:
        return 'void'
    if te.kind == 'array':
        return f'[{_type_expr_text(te.inner)}, {te.size}]'
    if te.kind == 'func':
        params = ', '.join(_type_expr_text(p) for p in (te.params or []))
        ret = _type_expr_text(te.inner) if te.inner is not None else 'void'
        return f'func({params}) -> {ret}'
    if te.kind == 'ptr':
        return f'ptr<{_type_expr_text(te.inner)}>'
    if te.kind == 'list':
        return f'List<{_type_expr_text(te.inner)}>'
    name = te.name or ''
    if te.args:
        name += '<' + ', '.join(_type_expr_text(a) for a in te.args) + '>'
    return name


def _split_top(text: str, sep: str = ',') -> list[str]:
    parts: list[str] = []
    start = 0
    depth = 0
    for i, ch in enumerate(text):
        if ch in '(<[':
            depth += 1
        elif ch in ')>]':
            depth = max(0, depth - 1)
        elif ch == sep and depth == 0:
            parts.append(text[start:i].strip())
            start = i + 1
    parts.append(text[start:].strip())
    return [p for p in parts if p]


# ---------------------------------------------------------------------------
# Scope-aware references (navigation and rename)
# ---------------------------------------------------------------------------


@dataclass
class _Hint:
    """An inferred type shown next to a local that has no annotation."""

    line: int          # 1-based
    col: int           # 1-based, Python characters
    type_text: str


@dataclass
class _Ref:
    """One occurrence of a symbol, with a stable workspace symbol key."""

    path: str
    line: int          # 1-based
    col: int           # 1-based, Python characters (not UTF-16 units)
    name: str          # exact source text to replace
    symbol: tuple      # stable identity, see _ReferenceWalker
    declaration: bool = False
    kind: str = ''     # semantic kind: function, struct, variable, ...
    enclosing: Optional[tuple] = None   # the function it appears in


def _decl_kind(decl: 'DeclInfo') -> str:
    """The semantic kind of a top-level declaration."""
    return {
        'func': 'function',
        'struct': 'struct',
        'enum': 'enum',
        'const': 'const',
    }.get(decl.kind, 'variable')


def _global_symbol(decl: 'DeclInfo') -> tuple:
    return ('global', decl.path, decl.name_line, decl.name_col)


def _symbol_from_item(item: dict) -> Optional[tuple]:
    """The symbol a call hierarchy item stands for."""
    data = item.get('data')
    if not isinstance(data, list) or not data:
        return None
    return tuple(data)


def _field_symbol(decl: 'DeclInfo', field: str) -> tuple:
    return ('field', decl.path, decl.name_line, decl.name_col, field)


def _member_symbol(decl: 'DeclInfo', member: str) -> tuple:
    return ('member', decl.path, decl.name_line, decl.name_col, member)


class _ReferenceWalker:
    """Collect every resolvable identifier occurrence in one module.

    Symbols are identified by stable tuples so occurrences found in different
    modules (and in separate walks) can be compared:

    ``('global', path, line, col)``          a top-level declaration
    ``('local', path, line, col)``           a parameter or local binding
    ``('field', path, line, col, name)``     a struct field
    ``('member', path, line, col, name)``    an enum member
    ``('alias', path, import_line, name)``   an import alias

    The walk is deliberately conservative: when a type cannot be established,
    the occurrence is not recorded rather than guessed.
    """

    def __init__(self, module: ModuleInfo, index: _ProjectIndex):
        self.module = module
        self.index = index
        self.path = module.path
        self.lines = _lines(module.source)
        self.refs: list[_Ref] = []
        self.hints: list[_Hint] = []
        self._scopes: list[dict[str, tuple[str, tuple, str]]] = []
        self._enclosing: list[tuple] = []
        self._aliases: dict[str, ImportInfo] = {
            imp.alias: imp for imp in module.imports
            if imp.alias and imp.target is not None
        }
        self._seed_declarations()
        if module.program is not None:
            self._walk_program(module.program)

    # -- recording ---------------------------------------------------------

    def _add(self, line: int, col: int, name: str, symbol: tuple,
             declaration: bool = False, kind: str = '') -> None:
        if not name or line <= 0 or col <= 0:
            return
        enclosing = self._enclosing[-1] if self._enclosing else None
        self.refs.append(_Ref(self.path, line, col, name, symbol, declaration,
                              kind, enclosing))

    def _seed_declarations(self) -> None:
        for decl in self.module.decls:
            self._add(decl.name_line, decl.name_col, decl.name,
                      _global_symbol(decl), True, _decl_kind(decl))
            if decl.kind == 'struct':
                for f in decl.fields:
                    self._add(f.line, f.col, f.name,
                              _field_symbol(decl, f.name), True, 'property')
            elif decl.kind == 'enum':
                for m in decl.members:
                    self._add(m.line, m.col, m.name,
                              _member_symbol(decl, m.name), True, 'enumMember')
        for imp in self.module.imports:
            if not imp.alias:
                continue
            pos = self._alias_decl_pos(imp)
            if pos is not None:
                self._add(pos[0], pos[1], imp.alias,
                          ('alias', self.path, imp.line, imp.alias), True,
                          'namespace')

    def _func_symbol(self, name: str) -> Optional[tuple]:
        """The global symbol of a function declared in this module."""
        for decl in self.module.decls:
            if decl.name == name and decl.kind == 'func':
                return _global_symbol(decl)
        return None

    def _alias_decl_pos(self, imp: ImportInfo) -> Optional[tuple[int, int]]:
        line_text = _line_at(self.lines, imp.line - 1)
        m = re.search(r'\bas\s+([A-Za-z_]\w*)', line_text)
        if m and m.group(1) == imp.alias:
            return imp.line, m.start(1) + 1
        idx = line_text.find(imp.alias or '')
        if idx >= 0:
            return imp.line, idx + 1
        return None

    # -- scopes ------------------------------------------------------------

    def _lookup(self, name: str) -> Optional[tuple[str, tuple, str]]:
        for scope in reversed(self._scopes):
            hit = scope.get(name)
            if hit is not None:
                return hit
        return None

    def _walk_scoped(self, body: list) -> None:
        self._scopes.append({})
        try:
            self._walk_block(body)
        finally:
            self._scopes.pop()

    # -- declarations ------------------------------------------------------

    def _walk_program(self, program: A.Program) -> None:
        for decl in program.decls:
            if isinstance(decl, A.FuncDecl):
                self._walk_function(decl, self._func_symbol(decl.name))
            elif isinstance(decl, A.StructDecl):
                for _name, ftype, _pos, _pub in decl.fields:
                    self._visit_type(ftype)
            elif isinstance(decl, A.EnumDecl):
                for member in decl.members:
                    for payload_type in (member.payload or []):
                        self._visit_type(payload_type)
            elif isinstance(decl, A.ConstDecl):
                self._visit_type(decl.type_ann)
                self._visit_expr(decl.value)
            elif isinstance(decl, A.ExternDecl):
                for fd in decl.funcs:
                    for param in fd.params:
                        self._visit_type(param.type)
                    self._visit_type(fd.ret)

    def _walk_function(self, func: A.FuncDecl, symbol: Optional[tuple] = None) \
            -> None:
        scope: dict[str, tuple[str, tuple, str]] = {}
        self._scopes.append(scope)
        self._enclosing.append(symbol) if symbol is not None else None
        try:
            for param in func.params:
                psymbol = ('local', self.path, param.pos.line, param.pos.col)
                self._add(param.pos.line, param.pos.col, param.name,
                          psymbol, True, 'parameter')
                scope[param.name] = (_type_expr_text(param.type), psymbol,
                                     'parameter')
                self._visit_type(param.type)
            self._visit_type(func.ret)
            self._walk_block(func.body)
        finally:
            if symbol is not None:
                self._enclosing.pop()
            self._scopes.pop()

    # -- statements --------------------------------------------------------

    def _walk_block(self, body: list) -> None:
        for stmt in body or []:
            self._walk_stmt(stmt)

    def _walk_stmt(self, stmt: Any) -> None:
        if isinstance(stmt, A.VarDecl):
            self._visit_type(stmt.type_ann)
            self._visit_expr(stmt.value)
            pos = _find_name_pos(self.lines, stmt.pos, stmt.name)
            symbol = ('local', self.path, pos[0], pos[1])
            self._add(pos[0], pos[1], stmt.name, symbol, True, 'variable')
            type_text = (_type_expr_text(stmt.type_ann)
                         if stmt.type_ann is not None
                         else self._expr_type_text(stmt.value))
            hint_text = (self._hint_type_text(stmt.value)
                         if stmt.type_ann is None else '')
            if hint_text:
                self.hints.append(_Hint(pos[0], pos[1] + len(stmt.name),
                                       hint_text))
            self._scopes[-1][stmt.name] = (type_text, symbol, 'variable')
        elif isinstance(stmt, A.AssignStmt):
            self._visit_expr(stmt.target)
            self._visit_expr(stmt.value)
        elif isinstance(stmt, A.ReturnStmt):
            self._visit_expr(stmt.value)
        elif isinstance(stmt, A.ExprStmt):
            self._visit_expr(stmt.expr)
        elif isinstance(stmt, A.IfStmt):
            self._visit_expr(stmt.cond)
            self._walk_scoped(stmt.then_body)
            for cond, body in stmt.elif_branches or []:
                self._visit_expr(cond)
                self._walk_scoped(body)
            if stmt.else_body is not None:
                self._walk_scoped(stmt.else_body)
        elif isinstance(stmt, A.WhileStmt):
            self._visit_expr(stmt.cond)
            self._walk_scoped(stmt.body)
        elif isinstance(stmt, A.ForRangeStmt):
            self._visit_expr(stmt.start)
            self._visit_expr(stmt.end)
            self._visit_expr(stmt.step)
            self._scopes.append({})
            try:
                self._bind_loop_var(stmt.var, stmt.pos, 'i32')
                self._walk_block(stmt.body)
            finally:
                self._scopes.pop()
        elif isinstance(stmt, A.ForEachStmt):
            self._visit_expr(stmt.iterable)
            self._scopes.append({})
            try:
                element = self._element_type_text(
                    self._expr_type_text(stmt.iterable))
                self._bind_loop_var(stmt.var, stmt.pos, element)
                self._walk_block(stmt.body)
            finally:
                self._scopes.pop()
        elif isinstance(stmt, A.MatchStmt):
            self._visit_expr(stmt.value)
            for arm in stmt.arms:
                self._scopes.append({})
                try:
                    for pattern in arm.patterns:
                        self._walk_pattern(pattern)
                    self._walk_block(arm.body)
                finally:
                    self._scopes.pop()

    def _bind_loop_var(self, name: str, pos: A.Pos, type_text: str) -> None:
        line_text = _line_at(self.lines, pos.line - 1)
        start = max(0, pos.col - 1)
        m = re.search(r'\bfor\s+([A-Za-z_]\w*)', line_text[start:])
        if m is not None:
            col = start + m.start(1) + 1
        else:
            col = pos.col
        symbol = ('local', self.path, pos.line, col)
        self._add(pos.line, col, name, symbol, True, 'variable')
        self._scopes[-1][name] = (type_text, symbol, 'variable')

    def _walk_pattern(self, pattern: A.MatchPattern) -> None:
        enum_decl = self._resolve_type_decl(pattern.enum_name)
        if enum_decl is None or enum_decl.kind != 'enum':
            return
        # The qualifier is a type name (`Color.`) or an alias plus a type
        # (`math.Shape.`); keep both renameable, not just the member.
        if '.' in pattern.enum_name:
            qualifier = pattern.enum_name.split('.', 1)[0]
            imp = self._aliases.get(qualifier)
            if imp is not None:
                self._add(pattern.pos.line, pattern.pos.col, qualifier,
                          ('alias', self.path, imp.line, qualifier), False,
                          'namespace')
            tail = pattern.enum_name.rsplit('.', 1)[-1]
            pos = self._pattern_segment_pos(pattern, tail)
            if pos is not None:
                self._add(pos[0], pos[1], tail, _global_symbol(enum_decl),
                          False, 'enum')
        else:
            self._add(pattern.pos.line, pattern.pos.col, pattern.enum_name,
                      _global_symbol(enum_decl), False, 'enum')
        member = next((m for m in enum_decl.members
                       if m.name == pattern.member), None)
        if member is None:
            return
        pos = self._pattern_member_pos(pattern)
        if pos is not None:
            self._add(pos[0], pos[1], pattern.member,
                      _member_symbol(enum_decl, pattern.member), False,
                      'enumMember')
        if not pattern.bindings:
            return
        payload = _split_top(member.payload) if member.payload else []
        owner = self._module_for_path(enum_decl.path)
        used: set[tuple[int, int]] = set()
        for i, binding in enumerate(pattern.bindings):
            if binding == '_':
                continue
            pos = self._pattern_binding_pos(pattern, binding, used)
            if pos is None:
                continue
            used.add(pos)
            type_text = (self._qualify_type_text(payload[i], owner)
                         if i < len(payload) else '')
            symbol = ('local', self.path, pos[0], pos[1])
            self._add(pos[0], pos[1], binding, symbol, True, 'variable')
            self._scopes[-1][binding] = (type_text, symbol, 'variable')

    def _pattern_member_pos(self, pattern: A.MatchPattern) \
            -> Optional[tuple[int, int]]:
        line_text = _line_at(self.lines, pattern.pos.line - 1)
        start = max(0, pattern.pos.col - 1) + len(pattern.enum_name)
        idx = line_text.find(pattern.member, start)
        if idx >= 0:
            return pattern.pos.line, idx + 1
        idx = line_text.rfind(pattern.member, 0, len(line_text))
        if idx >= 0:
            return pattern.pos.line, idx + 1
        return None

    def _pattern_segment_pos(self, pattern: A.MatchPattern, segment: str) \
            -> Optional[tuple[int, int]]:
        line_text = _line_at(self.lines, pattern.pos.line - 1)
        idx = line_text.find(segment, max(0, pattern.pos.col - 1))
        if idx >= 0:
            return pattern.pos.line, idx + 1
        return None

    def _pattern_binding_pos(self, pattern: A.MatchPattern, name: str,
                             used: set) -> Optional[tuple[int, int]]:
        line_text = _line_at(self.lines, pattern.pos.line - 1)
        start = max(0, pattern.pos.col - 1)
        paren = line_text.find('(', start)
        if paren >= 0:
            start = paren + 1
        for m in re.finditer(r'\b' + re.escape(name) + r'\b', line_text[start:]):
            pos = (pattern.pos.line, start + m.start() + 1)
            if pos not in used:
                return pos
        return None

    # -- expressions -------------------------------------------------------

    def _visit_expr(self, expr: Any) -> None:
        if expr is None:
            return
        if isinstance(expr, A.Name):
            self._visit_name(expr)
        elif isinstance(expr, A.Member):
            self._visit_member(expr)
        elif isinstance(expr, A.Call):
            self._visit_expr(expr.func)
            for arg in expr.args or []:
                self._visit_expr(arg)
            for type_arg in expr.type_args or []:
                self._visit_type(type_arg)
            self._visit_constructor_labels(expr)
        elif isinstance(expr, A.Index):
            self._visit_expr(expr.obj)
            self._visit_expr(expr.index)
        elif isinstance(expr, A.BinOp):
            self._visit_expr(expr.left)
            self._visit_expr(expr.right)
        elif isinstance(expr, A.UnaryOp):
            self._visit_expr(expr.operand)
        elif isinstance(expr, A.ArrayLit):
            for element in expr.elements:
                self._visit_expr(element)

    def _visit_name(self, expr: A.Name) -> None:
        local = self._lookup(expr.name)
        if local is not None:
            self._add(expr.pos.line, expr.pos.col, expr.name, local[1],
                      False, local[2])
            return
        decl = self._resolve_global(expr.name)
        if decl is not None:
            self._add(expr.pos.line, expr.pos.col, expr.name,
                      _global_symbol(decl), False, _decl_kind(decl))
            return
        imp = self._aliases.get(expr.name)
        if imp is not None:
            self._add(expr.pos.line, expr.pos.col, expr.name,
                      ('alias', self.path, imp.line, expr.name), False,
                      'namespace')

    def _visit_member(self, expr: A.Member) -> None:
        self._visit_expr(expr.obj)
        # `alias.member` where member is a declaration in the imported module:
        # a function call, constant, type, or enum member constructor.
        if (isinstance(expr.obj, A.Name)
                and self._lookup(expr.obj.name) is None
                and expr.obj.name in self._aliases):
            imp = self._aliases[expr.obj.name]
            target: Optional[DeclInfo] = None
            if imp.target is not None:
                for decl in imp.target.public_decls():
                    if decl.name == expr.field:
                        target = decl
                        break
            if target is not None:
                pos = self._field_pos(expr)
                if pos is not None:
                    self._add(pos[0], pos[1], expr.field,
                              _global_symbol(target), False,
                              _decl_kind(target))
                return
        receiver = self._receiver_decl(expr.obj)
        if receiver is None:
            return
        pos = self._field_pos(expr)
        if pos is None:
            return
        if receiver.kind == 'struct':
            if any(f.name == expr.field for f in receiver.fields):
                self._add(pos[0], pos[1], expr.field,
                          _field_symbol(receiver, expr.field), False,
                          'property')
        elif receiver.kind == 'enum':
            if any(m.name == expr.field for m in receiver.members):
                self._add(pos[0], pos[1], expr.field,
                          _member_symbol(receiver, expr.field), False,
                          'enumMember')

    def _visit_constructor_labels(self, call: A.Call) -> None:
        decl = self._call_result_decl(call)
        if decl is None or decl.kind != 'struct' or not call.arg_names:
            return
        fields = {f.name for f in decl.fields}
        for i, label in enumerate(call.arg_names):
            if not label or label not in fields or i >= len(call.args):
                continue
            pos = self._label_pos(call.args[i], label)
            if pos is not None:
                self._add(pos[0], pos[1], label,
                          _field_symbol(decl, label), False, 'property')

    def _field_pos(self, node: A.Member) -> Optional[tuple[int, int]]:
        if node.pos is None:
            return None
        line_text = _line_at(self.lines, node.pos.line - 1)
        start = max(0, node.pos.col)  # AST Member.pos is the dot token
        m = re.match(r'\s*([A-Za-z_]\w*)', line_text[start:])
        if m is not None and m.group(1) == node.field:
            return node.pos.line, start + m.start(1) + 1
        idx = line_text.find(node.field, start)
        if idx >= 0:
            return node.pos.line, idx + 1
        return None

    def _label_pos(self, arg: Any, label: str) \
            -> Optional[tuple[int, int]]:
        pos = getattr(arg, 'pos', None)
        if pos is None:
            return None
        line_text = _line_at(self.lines, pos.line - 1)
        prefix = line_text[:max(0, pos.col - 1)]
        best = None
        for m in re.finditer(r'\b' + re.escape(label) + r'\s*:', prefix):
            best = m
        if best is not None:
            return pos.line, best.start() + 1
        for line_no in range(pos.line - 2, max(-1, pos.line - 4), -1):
            text = _line_at(self.lines, line_no)
            for m in re.finditer(r'\b' + re.escape(label) + r'\s*:', text):
                best = m
            if best is not None:
                return line_no + 1, best.start() + 1
        return None

    # -- types -------------------------------------------------------------

    def _visit_type(self, te: Optional[A.TypeExpr]) -> None:
        if te is None:
            return
        if te.kind == 'array':
            self._visit_type(te.inner)
            return
        if te.kind == 'func':
            for param in te.params or []:
                self._visit_type(param)
            self._visit_type(te.inner)
            return
        if te.kind in ('ptr', 'list'):
            self._visit_type(te.inner)
            return
        name = te.name or ''
        if name and te.pos is not None:
            if '.' in name:
                qualifier, _, tail = name.rpartition('.')
                imp = self._aliases.get(qualifier)
                if imp is not None:
                    self._add(te.pos.line, te.pos.col, qualifier,
                              ('alias', self.path, imp.line, qualifier), False,
                              'namespace')
                decl = self._resolve_type_decl(name)
                if decl is not None:
                    pos = self._qualified_segment_pos(te, tail)
                    if pos is not None:
                        self._add(pos[0], pos[1], tail,
                                  _global_symbol(decl), False,
                                  _decl_kind(decl))
            else:
                decl = self._resolve_type_decl(name)
                if decl is not None:
                    self._add(te.pos.line, te.pos.col, name,
                              _global_symbol(decl), False, _decl_kind(decl))
        for arg in te.args or []:
            self._visit_type(arg)

    def _qualified_segment_pos(self, te: A.TypeExpr, tail: str) \
            -> Optional[tuple[int, int]]:
        line_text = _line_at(self.lines, te.pos.line - 1)
        idx = line_text.find(tail, max(0, te.pos.col - 1))
        if idx >= 0:
            return te.pos.line, idx + 1
        return None

    # -- symbol resolution -------------------------------------------------

    def _module_aliases(self, module: ModuleInfo) -> dict[str, ImportInfo]:
        if module is self.module:
            return self._aliases
        return {imp.alias: imp for imp in module.imports
                if imp.alias and imp.target is not None}

    def _module_for_path(self, path: str) -> ModuleInfo:
        for module in self.index.cache.values():
            if module.path == path:
                return module
        return self.module

    def _qualified_name(self, decl: DeclInfo) -> str:
        """Name that can be used to refer to decl from the current module."""
        if self._resolve_global(decl.name) is decl:
            return decl.name
        for alias, imp in self._aliases.items():
            if imp.target is None:
                continue
            for candidate in imp.target.public_decls():
                if candidate is decl:
                    return f'{alias}.{decl.name}'
        return decl.name

    def _qualify_type_text(self, type_text: str,
                           owner: ModuleInfo) -> str:
        """Qualify a type written in owner so the current module can resolve it."""
        named = self._named_type_text(type_text)
        decl = self._resolve_type_decl(named, owner)
        if decl is None:
            return type_text
        qualified = self._qualified_name(decl)
        if qualified == decl.name:
            return type_text
        return type_text.replace(decl.name, qualified, 1)

    def _resolve_global(self, name: str,
                        module: Optional[ModuleInfo] = None) \
            -> Optional[DeclInfo]:
        module = module or self.module
        for decl in module.decls:
            if decl.name == name:
                return decl
        for imp in module.imports:
            if imp.alias is not None or imp.target is None:
                continue
            for decl in imp.target.public_decls():
                if decl.name == name:
                    return decl
        return None

    def _named_type_text(self, type_text: str) -> str:
        text = (type_text or '').strip()
        if text.startswith('List<') and text.endswith('>'):
            text = text[len('List<'):-1].strip()
        elif text.startswith('ptr<') and text.endswith('>'):
            text = text[len('ptr<'):-1].strip()
        elif text.startswith('[') and text.endswith(']'):
            parts = _split_top(text[1:-1])
            text = parts[0] if parts else ''
        return _base_type_name(text)

    def _resolve_type_decl(self, written: str,
                           module: Optional[ModuleInfo] = None) \
            -> Optional[DeclInfo]:
        module = module or self.module
        name = self._named_type_text(written)
        if not name:
            return None
        if '.' in name:
            qualifier, _, tail = name.rpartition('.')
            imp = self._module_aliases(module).get(qualifier)
            if imp is None or imp.target is None:
                return None
            for decl in imp.target.public_decls():
                if decl.name == tail and decl.kind in ('struct', 'enum'):
                    return decl
            return None
        decl = self._resolve_global(name, module)
        if decl is not None and decl.kind in ('struct', 'enum'):
            return decl
        return None

    def _element_type_text(self, type_text: str) -> str:
        text = (type_text or '').strip()
        if text.startswith('List<') and text.endswith('>'):
            return text[len('List<'):-1].strip()
        if text.startswith('[') and text.endswith(']'):
            parts = _split_top(text[1:-1])
            if parts:
                return parts[0]
        return ''

    def _receiver_decl(self, expr: Any) -> Optional[DeclInfo]:
        decl = self._type_decl_of_expr(expr)
        if decl is not None:
            return decl
        if isinstance(expr, A.Name):
            return self._resolve_type_decl(expr.name)
        return None

    def _type_decl_of_expr(self, expr: Any) -> Optional[DeclInfo]:
        if expr is None:
            return None
        if isinstance(expr, A.Name):
            local = self._lookup(expr.name)
            if local is not None and local[0]:
                return self._resolve_type_decl(local[0])
            return None
        if isinstance(expr, A.Call):
            return self._call_result_decl(expr)
        if isinstance(expr, A.Member):
            if isinstance(expr.obj, A.Name) and expr.obj.name in self._aliases:
                return self._resolve_type_decl(
                    f'{expr.obj.name}.{expr.field}')
            base = self._type_decl_of_expr(expr.obj)
            if base is not None and base.kind == 'struct':
                owner = self._module_for_path(base.path)
                for f in base.fields:
                    if f.name == expr.field:
                        return self._resolve_type_decl(f.type_name, owner)
            return None
        if isinstance(expr, A.Index):
            element = self._element_type_text(self._expr_type_text(expr.obj))
            return self._resolve_type_decl(element)
        return None

    def _call_result_decl(self, call: A.Call) -> Optional[DeclInfo]:
        if (isinstance(call.func, A.Member)
                and call.func.field == 'alloc'
                and call.type_args):
            return self._resolve_type_decl(_type_expr_text(call.type_args[0]))
        return self._callee_type_decl(call.func)

    def _callee_type_decl(self, func: Any) -> Optional[DeclInfo]:
        if isinstance(func, A.Name):
            decl = self._resolve_global(func.name)
            if decl is not None:
                if decl.kind in ('struct', 'enum'):
                    return decl
                if decl.kind in ('func', 'system', 'extern_func'):
                    ret = _return_type_text(decl.detail)
                    if ret:
                        owner = self._module_for_path(decl.path)
                        return self._resolve_type_decl(ret, owner)
            return self._resolve_type_decl(func.name)
        if isinstance(func, A.Member) and isinstance(func.obj, A.Name):
            if func.obj.name in self._aliases:
                imp = self._aliases[func.obj.name]
                if imp.target is not None:
                    for decl in imp.target.public_decls():
                        if decl.name != func.field:
                            continue
                        if decl.kind in ('struct', 'enum'):
                            return decl
                        if decl.kind in ('func', 'system', 'extern_func'):
                            ret = _return_type_text(decl.detail)
                            if ret:
                                return self._resolve_type_decl(ret, imp.target)
                return self._resolve_type_decl(
                    f'{func.obj.name}.{func.field}')
        return None

    def _hint_type_text(self, expr: Any) -> str:
        """The type of an expression, as text, for an inlay hint.

        Unlike `_expr_type_text`, this keeps a primitive type: a function
        returning `i32` shows `i32`, not nothing.
        """
        if expr is None:
            return ''
        if isinstance(expr, A.Name):
            local = self._lookup(expr.name)
            if local is not None:
                return local[0]
            decl = self._resolve_global(expr.name)
            return self._decl_type_text(decl) if decl is not None else ''
        if isinstance(expr, A.Call):
            if (isinstance(expr.func, A.Member)
                    and expr.func.field == 'alloc'
                    and expr.type_args):
                return f'ptr<{_type_expr_text(expr.type_args[0])}>'
            return self._callee_type_text(expr.func)
        if isinstance(expr, A.Member):
            base = self._type_decl_of_expr(expr.obj)
            if base is not None and base.kind == 'struct':
                owner = self._module_for_path(base.path)
                for f in base.fields:
                    if f.name == expr.field:
                        return self._qualify_type_text(f.type_name, owner)
            return ''
        if isinstance(expr, A.Index):
            return self._element_type_text(self._hint_type_text(expr.obj))
        if isinstance(expr, A.IntLit):
            return 'i32'
        if isinstance(expr, A.FloatLit):
            return 'f32'
        if isinstance(expr, A.BoolLit):
            return 'bool'
        if isinstance(expr, A.StringLit):
            return 'str'
        if isinstance(expr, A.ArrayLit) and expr.elements:
            inner = self._hint_type_text(expr.elements[0])
            return f'[{inner}, {len(expr.elements)}]' if inner else ''
        if isinstance(expr, A.BinOp):
            if expr.op in ('==', '!=', '<', '>', '<=', '>=', 'and', 'or'):
                return 'bool'
            return (self._hint_type_text(expr.left)
                    or self._hint_type_text(expr.right))
        if isinstance(expr, A.UnaryOp):
            return self._hint_type_text(expr.operand)
        return ''

    def _decl_type_text(self, decl: DeclInfo) -> str:
        """The type a declaration produces."""
        if decl.kind in ('struct', 'enum'):
            return decl.name
        if decl.kind == 'const':
            return ''
        if decl.kind in ('func', 'system', 'extern_func'):
            return _return_type_text(decl.detail)
        return ''

    def _callee_type_text(self, func: Any) -> str:
        """The type a call produces, as text."""
        if isinstance(func, A.Name):
            decl = self._resolve_global(func.name)
            if decl is not None:
                if decl.kind in ('struct', 'enum'):
                    return decl.name
                if decl.kind in ('func', 'system', 'extern_func'):
                    return _return_type_text(decl.detail)
            return ''
        if isinstance(func, A.Member) and isinstance(func.obj, A.Name):
            if func.obj.name in self._aliases:
                imp = self._aliases[func.obj.name]
                if imp.target is not None:
                    for decl in imp.target.public_decls():
                        if decl.name != func.field:
                            continue
                        if decl.kind in ('struct', 'enum'):
                            return f'{func.obj.name}.{decl.name}'
                        if decl.kind in ('func', 'system', 'extern_func'):
                            return _return_type_text(decl.detail)
            return ''
        return ''

    def _expr_type_text(self, expr: Any) -> str:
        if expr is None:
            return ''
        if isinstance(expr, A.Name):
            local = self._lookup(expr.name)
            return local[0] if local is not None else ''
        if isinstance(expr, A.Call):
            if (isinstance(expr.func, A.Member)
                    and expr.func.field == 'alloc'
                    and expr.type_args):
                return f'ptr<{_type_expr_text(expr.type_args[0])}>'
            decl = self._callee_type_decl(expr.func)
            if decl is None:
                return ''
            if (isinstance(expr.func, A.Member)
                    and isinstance(expr.func.obj, A.Name)
                    and expr.func.obj.name in self._aliases):
                return f'{expr.func.obj.name}.{decl.name}'
            return decl.name
        if isinstance(expr, A.Member):
            base = self._type_decl_of_expr(expr.obj)
            if base is not None and base.kind == 'struct':
                owner = self._module_for_path(base.path)
                for f in base.fields:
                    if f.name == expr.field:
                        return self._qualify_type_text(f.type_name, owner)
            return ''
        if isinstance(expr, A.Index):
            return self._element_type_text(self._expr_type_text(expr.obj))
        if isinstance(expr, A.IntLit):
            return 'i32'
        if isinstance(expr, A.FloatLit):
            return 'f32'
        if isinstance(expr, A.BoolLit):
            return 'bool'
        if isinstance(expr, A.StringLit):
            return 'str'
        if isinstance(expr, A.ArrayLit) and expr.elements:
            inner = self._expr_type_text(expr.elements[0])
            return f'[{inner}, {len(expr.elements)}]' if inner else ''
        if isinstance(expr, A.BinOp):
            if expr.op in ('==', '!=', '<', '>', '<=', '>=', 'and', 'or'):
                return 'bool'
            return (self._expr_type_text(expr.left)
                    or self._expr_type_text(expr.right))
        if isinstance(expr, A.UnaryOp):
            return self._expr_type_text(expr.operand)
        return ''


_SIGNATURE_RE = re.compile(
    r'^(?:(?:system|extern)\s+)?(?:func\s+)?'
    r'[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)?'
    r'\s*(?:<[^<>()]*>)?\s*\((?P<params>.*)\)'
    r'(?:\s*->\s*(?P<ret>.+))?$')


def _parse_signature(detail: str) -> Optional[dict]:
    """Split a detail such as ``func f(a: i32) -> i32`` into parameters."""
    text = detail.strip()
    match = _SIGNATURE_RE.match(text)
    if match is None:
        return None
    return {
        'label': text,
        'params': _split_top(match.group('params')),
        'ret': (match.group('ret') or '').strip(),
    }


_FUNC_TYPE_RE = re.compile(
    r'^func\((?P<params>.*)\)(?:\s*->\s*(?P<ret>.+))?$')


def _signature_from_function_type(type_text: str) -> Optional[dict]:
    """Build a signature from a value's ``func(...) -> ...`` type."""
    text = type_text.strip()
    match = _FUNC_TYPE_RE.match(text)
    if match is None:
        return None
    return {
        'label': text,
        'params': _split_top(match.group('params')),
        'ret': (match.group('ret') or '').strip(),
    }


def _offset_at(text: str, line: int, char: int) -> int:
    """Convert a 0-based LSP position into a Python string offset."""
    line, py_char = _position_to_py(text, line, char)
    offset = 0
    for _ in range(line):
        newline = text.find('\n', offset)
        if newline < 0:
            return len(text)
        offset = newline + 1
    return min(offset + py_char, len(text))


def _skip_comment(text: str, index: int, limit: int) -> int:
    newline = text.find('\n', index)
    if newline < 0 or newline >= limit:
        return limit
    return newline + 1


def _skip_string(text: str, index: int, limit: int) -> int:
    """``index`` is the opening quote; return the index just past the string."""
    index += 1
    while index < limit and text[index] != '"':
        if text[index] == '\\':
            index += 1
        index += 1
    return index + 1


_DECL_HEAD_RE = re.compile(
    r'\b(?:func|system)\s+[A-Za-z_]\w*(?:<[^<>]*>)?$')


def _in_declaration(text: str, open_index: int) -> bool:
    """True when the paren opens a ``func``/``system`` declaration."""
    line_start = text.rfind('\n', 0, open_index) + 1
    return _DECL_HEAD_RE.search(text[line_start:open_index].rstrip()) \
        is not None


def _callee_path(text: str, open_index: int) -> Optional[list[str]]:
    """Return the dotted name written immediately before an opening paren."""
    i = open_index - 1
    while i >= 0 and text[i] in ' \t':
        i -= 1
    end = i + 1
    while i >= 0 and (text[i].isalnum() or text[i] == '_'):
        i -= 1
    name = text[i + 1:end]
    if not name or not (name[0].isalpha() or name[0] == '_'):
        return None
    parts = [name]
    while i >= 0 and text[i] == '.':
        j = i - 1
        while j >= 0 and text[j] in ' \t':
            j -= 1
        part_end = j + 1
        while j >= 0 and (text[j].isalnum() or text[j] == '_'):
            j -= 1
        part = text[j + 1:part_end]
        if not part or not (part[0].isalpha() or part[0] == '_'):
            break
        parts.insert(0, part)
        i = j
    return parts


def _call_context(text: str, offset: int) \
        -> Optional[tuple[int, Optional[list[str]]]]:
    """Find the innermost call left open at ``offset``.

    The scan runs forward so that parentheses inside comments and strings are
    ignored, and so that nested calls pop in the right order.
    """
    stack: list[int] = []
    names: list[Optional[list[str]]] = []
    limit = max(0, min(offset, len(text)))
    i = 0
    while i < limit:
        ch = text[i]
        if ch == '#':
            i = _skip_comment(text, i, limit)
            continue
        if ch == '"':
            i = _skip_string(text, i, limit)
            continue
        if ch == '(':
            stack.append(i)
            names.append(_callee_path(text, i))
        elif ch == ')' and stack:
            stack.pop()
            names.pop()
        i += 1
    if not stack:
        return None
    return stack[-1], names[-1]


def _active_parameter(text: str, open_index: int, offset: int) -> int:
    """Count top-level commas between an opening paren and the cursor."""
    depth = 0
    active = 0
    limit = max(open_index + 1, min(offset, len(text)))
    i = open_index + 1
    while i < limit:
        ch = text[i]
        if ch == '#':
            i = _skip_comment(text, i, limit)
            continue
        if ch == '"':
            i = _skip_string(text, i, limit)
            continue
        if ch in '([{':
            depth += 1
        elif ch in ')]}':
            depth = max(0, depth - 1)
        elif ch == ',' and depth == 0:
            active += 1
        i += 1
    return active


def _struct_signature(decl: DeclInfo) -> dict:
    params = [f'{f.name}: {f.type_name}' for f in decl.fields]
    generics = f'<{", ".join(decl.type_params)}>' if decl.type_params else ''
    return {
        'label': f'{decl.name}{generics}(' + ', '.join(params) + ')',
        'params': params,
        'ret': decl.name,
    }


def _member_signature(decl: DeclInfo, member: str) -> Optional[dict]:
    if decl.kind != 'enum':
        return None
    for m in decl.members:
        if m.name != member:
            continue
        payload = _split_top(m.payload)
        if not payload:
            return None
        return {
            'label': f'{decl.name}.{m.name}(' + ', '.join(payload) + ')',
            'params': payload,
            'ret': decl.name,
        }
    return None


def _walk_collect(node: Any, kinds: tuple[type, ...]) -> list[Any]:
    found: list[Any] = []
    _walk(node, lambda n: found.append(n) if isinstance(n, kinds) else None)
    return found


def _walk(node: Any, visit) -> None:
    if node is None:
        return
    if isinstance(node, list):
        for item in node:
            _walk(item, visit)
        return
    if not is_dataclass(node):
        return
    visit(node)
    for f in fields(node):
        if f.name == 'pos':
            continue
        _walk(getattr(node, f.name), visit)


def _containing_function(program: A.Program, line: int) -> Optional[A.FuncDecl]:
    funcs = [d for d in program.decls if isinstance(d, A.FuncDecl)]
    for i, d in enumerate(funcs):
        next_line = funcs[i + 1].pos.line if i + 1 < len(funcs) else 10 ** 9
        if d.pos.line <= line + 1 < next_line:
            return d
    return None


def _infer_value_type(value: Any, locals_: dict[str, LocalInfo]) -> str:
    if value is None:
        return ''
    if isinstance(value, A.StringLit):
        return 'str'
    if isinstance(value, A.BoolLit):
        return 'bool'
    if isinstance(value, A.IntLit):
        return 'i32'
    if isinstance(value, A.FloatLit):
        return 'f32'
    if isinstance(value, A.Name):
        if value.name in locals_:
            return locals_[value.name].type_name
        return ''
    if isinstance(value, A.Call):
        target = value.func
        if isinstance(target, A.Name):
            return target.name
        if isinstance(target, A.Member):
            if target.field == 'list' and value.type_args:
                return 'List<' + _type_expr_text(value.type_args[0]) + '>'
            if target.field == 'str_builder':
                return 'StrBuilder'
    return ''


def _infer_text_type(expr: Optional[str]) -> str:
    if not expr:
        return ''
    expr = expr.strip()
    if re.match(r'^".*"$', expr):
        return 'str'
    if re.match(r'^(true|false)$', expr):
        return 'bool'
    if re.match(r'^-?\d+$', expr):
        return 'i32'
    if re.match(r'^-?\d+\.\d+$', expr):
        return 'f32'
    m = re.match(r'([A-Za-z_]\w*)\s*\(', expr)
    if m:
        return m.group(1)
    m = re.search(r'\.list::<(.+?)>', expr)
    if m:
        return f'List<{m.group(1).strip()}>'
    if re.search(r'\.alloc::<(.+?)>', expr):
        m = re.search(r'\.alloc::<(.+?)>', expr)
        return f'ptr<{m.group(1).strip()}>'
    if '.str_builder' in expr:
        return 'StrBuilder'
    return ''


# ---------------------------------------------------------------------------
# Builtin information and completions
# ---------------------------------------------------------------------------

_KEYWORD_DETAILS = {
    'func': 'Declare a function',
    'system': 'Declare an ECS system',
    'let': 'Declare an immutable local',
    'mut': 'Declare a mutable local',
    'return': 'Return from a function',
    'const': 'Declare a compile-time constant',
    'struct': 'Declare a struct',
    'component': 'Declare an ECS component',
    'enum': 'Declare an enum',
    'extern': 'Declare functions from a C library',
    'import': 'Import another Vanta file',
    'module': 'Name the current module',
    'pub': 'Expose a module declaration',
    'as': 'Alias an import',
    'if': 'Conditional branch',
    'elif': 'Else-if branch',
    'else': 'Fallback branch',
    'match': 'Pattern match a value',
    'while': 'Loop while a condition holds',
    'for': 'Loop over a range or collection',
    'in': 'Collection or range in a for loop',
    'break': 'Leave the nearest loop',
    'continue': 'Skip to the next loop iteration',
    'true': 'Boolean true',
    'false': 'Boolean false',
    'and': 'Short-circuit boolean and',
    'or': 'Short-circuit boolean or',
    'not': 'Boolean negation',
}

_BUILTIN_FIELDS = {
    'Vec2': [('x', 'f32'), ('y', 'f32')],
    'Vec3': [('x', 'f32'), ('y', 'f32'), ('z', 'f32')],
    'Quat': [('x', 'f32'), ('y', 'f32'), ('z', 'f32'), ('w', 'f32')],
}

_BUILTIN_METHODS = {
    'List': [
        ('push', 'push(${1:value})', 'func push(value: T) -> void', 2),
        ('pop', 'pop()', 'func pop() -> T', 2),
        ('insert', 'insert(${1:index}, ${2:value})',
         'func insert(index: i32, value: T) -> void', 2),
        ('remove', 'remove(${1:index})', 'func remove(index: i32) -> T', 2),
        ('sort', 'sort(${1:comparator})',
         'func sort(comparator: func(T, T) -> i32) -> void', 2),
    ],
    'Arena': [
        ('reset', 'reset()', 'func reset() -> void', 2),
        ('alloc', 'alloc::<${1:T}>(${2:count})',
         'func alloc<T>(count: i32) -> ptr<T>', 2),
        ('list', 'list::<${1:T}>()', 'func list<T>() -> List<T>', 2),
        ('str_builder', 'str_builder()', 'func str_builder() -> StrBuilder', 2),
    ],
    'StrBuilder': [
        ('append_str', 'append_str(${1:value})',
         'func append_str(value: str) -> void', 2),
        ('append_i32', 'append_i32(${1:value})',
         'func append_i32(value: i32) -> void', 2),
        ('append_u32', 'append_u32(${1:value})',
         'func append_u32(value: u32) -> void', 2),
        ('append_f32', 'append_f32(${1:value})',
         'func append_f32(value: f32) -> void', 2),
        ('append_f64', 'append_f64(${1:value})',
         'func append_f64(value: f64) -> void', 2),
        ('append_bool', 'append_bool(${1:value})',
         'func append_bool(value: bool) -> void', 2),
        ('to_str', 'to_str()', 'func to_str() -> str', 2),
        ('clear', 'clear()', 'func clear() -> void', 2),
    ],
    'Vec2': [
        ('dot', 'dot(${1:other})', 'func dot(other: Vec2) -> f32', 2),
        ('length', 'length()', 'func length() -> f32', 2),
        ('normalized', 'normalized()', 'func normalized() -> Vec2', 2),
    ],
    'Vec3': [
        ('dot', 'dot(${1:other})', 'func dot(other: Vec3) -> f32', 2),
        ('cross', 'cross(${1:other})', 'func cross(other: Vec3) -> Vec3', 2),
        ('length', 'length()', 'func length() -> f32', 2),
        ('normalized', 'normalized()', 'func normalized() -> Vec3', 2),
    ],
    'Quat': [
        ('dot', 'dot(${1:other})', 'func dot(other: Quat) -> f32', 2),
        ('length', 'length()', 'func length() -> f32', 2),
        ('normalized', 'normalized()', 'func normalized() -> Quat', 2),
    ],
}


def _builtin_functions() -> dict[str, str]:
    """Builtin function name -> human-readable signature."""
    tc = TypeChecker(A.Program([]), '<builtins>')
    result: dict[str, str] = {}
    for name, sig in tc.functions.items():
        params = ', '.join(f'{n}: {t}' for n, t in sig.params)
        result[name] = f'func {name}({params}) -> {sig.ret}'
    return result


def _builtin_types() -> dict[str, str]:
    result = {name: f'{name}' for name in PRIM_TYPES}
    result['List'] = 'List<T>'
    result['ptr'] = 'ptr<T>'
    tc = TypeChecker(A.Program([]), '<builtins>')
    for name, st in tc.structs.items():
        if st.builtin:
            result[name] = name
    return result


_BUILTIN_FUNCS_CACHE: Optional[dict[str, str]] = None
_BUILTIN_TYPES_CACHE: Optional[dict[str, str]] = None


def _builtin_funcs() -> dict[str, str]:
    global _BUILTIN_FUNCS_CACHE
    if _BUILTIN_FUNCS_CACHE is None:
        _BUILTIN_FUNCS_CACHE = _builtin_functions()
    return _BUILTIN_FUNCS_CACHE


def _builtin_type_names() -> dict[str, str]:
    global _BUILTIN_TYPES_CACHE
    if _BUILTIN_TYPES_CACHE is None:
        _BUILTIN_TYPES_CACHE = _builtin_types()
    return _BUILTIN_TYPES_CACHE


# ---------------------------------------------------------------------------
# Language server
# ---------------------------------------------------------------------------


@dataclass
class Document:
    uri: str
    text: str
    version: Optional[int] = None
    path: Optional[str] = None


class LanguageServer:
    def __init__(self, reader=None, writer=None):
        self.reader = reader
        self.writer = writer
        self.documents: dict[str, Document] = {}
        self.diagnostics_by_doc: dict[str, set[str]] = {}
        self.outbox: list[dict] = []
        self.running = True
        self.shutdown_requested = False
        self.root_uri: Optional[str] = None
        self.root_path: Optional[str] = None
        self._workspace_cache: dict[str, tuple] = {}
        self._file_list_cache: dict[str, tuple[float, list[str]]] = {}

    # -- protocol ----------------------------------------------------------

    def serve(self) -> None:
        reader = self.reader or sys.stdin.buffer
        writer = self.writer or sys.stdout.buffer
        while self.running:
            message = _read_message(reader)
            if message is None:
                break
            try:
                responses = self.handle_message(message)
            except Exception as exc:  # keep the editor connection alive
                sys.stderr.write(f'vanta lsp: {exc}\n')
                sys.stderr.flush()
                if message.get('id') is not None:
                    _write_message(writer, {
                        'jsonrpc': '2.0', 'id': message['id'],
                        'error': {'code': -32603,
                                  'message': 'internal language server error'},
                    })
                continue
            for response in responses:
                _write_message(writer, response)
        try:
            writer.flush()
        except Exception:
            pass

    def handle_message(self, message: dict) -> list[dict]:
        self.outbox = []
        method = message.get('method')
        msg_id = message.get('id')
        params = message.get('params') or {}
        if method == 'initialize':
            self.root_uri = params.get('rootUri')
            self.root_path = uri_to_path(self.root_uri) if self.root_uri else None
            if self.root_path is None:
                # A multi-root workspace sends the folders instead.
                for folder in params.get('workspaceFolders') or []:
                    path = uri_to_path(folder.get('uri') or '')
                    if path:
                        self.root_path = path
                        break
            self._response(msg_id, {
                'capabilities': {
                    'positionEncoding': 'utf-16',
                    'textDocumentSync': {
                        'openClose': True,
                        'change': 1,
                        'save': {'includeText': True},
                    },
                    'completionProvider': {
                        'triggerCharacters': ['.', ':', '<'],
                        'resolveProvider': False,
                    },
                    'signatureHelpProvider': {
                        'triggerCharacters': ['(', ','],
                        'retriggerCharacters': [','],
                    },
                    'hoverProvider': True,
                    'definitionProvider': True,
                    'referencesProvider': True,
                    'renameProvider': {'prepareProvider': True},
                    'codeActionProvider': {'codeActionKinds': ['quickfix']},
                    'workspaceSymbolProvider': True,
                    'documentFormattingProvider': True,
                    'inlayHintProvider': True,
                    'documentHighlightProvider': True,
                    'documentLinkProvider': {'resolveProvider': False},
                    'codeLensProvider': {'resolveProvider': False},
                    'callHierarchyProvider': True,
                    'typeHierarchyProvider': True,
                    'foldingRangeProvider': True,
                    'selectionRangeProvider': True,
                    'typeDefinitionProvider': True,
                    'implementationProvider': True,
                    'semanticTokensProvider': {
                        'legend': {
                            'tokenTypes': SEMANTIC_TOKEN_TYPES,
                            'tokenModifiers': SEMANTIC_TOKEN_MODIFIERS,
                        },
                        # A null selector means "use the client's", which is
                        # what the VS Code language client expects.
                        'documentSelector': None,
                        'full': True,
                    },
                    'documentSymbolProvider': True,
                },
                'serverInfo': {
                    'name': 'vanta-lsp',
                    'version': VERSION,
                },
            })
        elif method == 'initialized':
            pass
        elif method == 'shutdown':
            self.shutdown_requested = True
            self._response(msg_id, None)
        elif method == 'exit':
            self.running = False
        elif method in ('textDocument/didOpen', 'textDocument/didChange',
                        'textDocument/didSave', 'textDocument/didClose'):
            self._document_event(method, params)
        elif method == 'textDocument/completion':
            self._response(msg_id, self._completion(params))
        elif method == 'textDocument/signatureHelp':
            self._response(msg_id, self._signature_help(params))
        elif method == 'textDocument/hover':
            self._response(msg_id, self._hover(params))
        elif method == 'textDocument/definition':
            self._response(msg_id, self._definition(params))
        elif method == 'textDocument/typeDefinition':
            self._response(msg_id, self._type_definition(params))
        elif method == 'textDocument/implementation':
            self._response(msg_id, self._implementation(params))
        elif method == 'textDocument/references':
            self._response(msg_id, self._references(params))
        elif method == 'textDocument/prepareRename':
            self._response(msg_id, self._prepare_rename(params))
        elif method == 'textDocument/rename':
            self._response(msg_id, self._rename(params))
        elif method == 'textDocument/codeAction':
            self._response(msg_id, self._code_actions(params))
        elif method == 'workspace/symbol':
            self._response(msg_id, self._workspace_symbols(params))
        elif method == 'textDocument/formatting':
            self._response(msg_id, self._formatting(params))
        elif method == 'textDocument/inlayHint':
            self._response(msg_id, self._inlay_hints(params))
        elif method == 'textDocument/codeLens':
            self._response(msg_id, self._code_lenses(params))
        elif method == 'textDocument/prepareCallHierarchy':
            self._response(msg_id, self._call_hierarchy_prepare(params))
        elif method == 'callHierarchy/incomingCalls':
            self._response(msg_id, self._call_hierarchy_incoming(params))
        elif method == 'callHierarchy/outgoingCalls':
            self._response(msg_id, self._call_hierarchy_outgoing(params))
        elif method == 'textDocument/prepareTypeHierarchy':
            self._response(msg_id, self._type_hierarchy_prepare(params))
        elif method == 'typeHierarchy/supertypes':
            self._response(msg_id, self._type_hierarchy_supertypes(params))
        elif method == 'typeHierarchy/subtypes':
            self._response(msg_id, self._type_hierarchy_subtypes(params))
        elif method == 'textDocument/semanticTokens/full':
            self._response(msg_id, self._semantic_tokens(params))
        elif method == 'textDocument/documentHighlight':
            self._response(msg_id, self._document_highlight(params))
        elif method == 'textDocument/documentLink':
            self._response(msg_id, self._document_links(params))
        elif method == 'textDocument/foldingRange':
            self._response(msg_id, self._folding_ranges(params))
        elif method == 'textDocument/selectionRange':
            self._response(msg_id, self._selection_ranges(params))
        elif method == 'textDocument/documentSymbol':
            self._response(msg_id, self._document_symbols(params))
        elif method in ('workspace/didChangeConfiguration',
                        '$/cancelRequest', 'workspace/didChangeWatchedFiles'):
            pass
        elif msg_id is not None:
            self._error(msg_id, -32601, f'method not found: {method}')
        return self.outbox

    def _response(self, msg_id: Any, result: Any) -> None:
        if msg_id is None:
            return
        self.outbox.append({'jsonrpc': '2.0', 'id': msg_id, 'result': result})

    def _error(self, msg_id: Any, code: int, message: str) -> None:
        self.outbox.append({
            'jsonrpc': '2.0', 'id': msg_id,
            'error': {'code': code, 'message': message},
        })

    def _notify(self, method: str, params: dict) -> None:
        self.outbox.append({
            'jsonrpc': '2.0', 'method': method, 'params': params,
        })

    # -- document lifecycle ------------------------------------------------

    def _document_event(self, method: str, params: dict) -> None:
        td = params.get('textDocument') or {}
        uri = td.get('uri')
        if not uri:
            return
        path = uri_to_path(uri)
        if method == 'textDocument/didOpen':
            self.documents[uri] = Document(
                uri=uri, text=_strip_bom(td.get('text', '')),
                version=td.get('version'), path=path)
            self._validate(uri)
        elif method == 'textDocument/didChange':
            doc = self.documents.get(uri)
            if doc is None:
                doc = Document(uri=uri, text='', version=None, path=path)
                self.documents[uri] = doc
            changes = params.get('contentChanges') or []
            if changes:
                for change in changes:
                    text_change = _strip_bom(change.get('text', ''))
                    rng = change.get('range')
                    if rng is None:
                        # Full sync (or incremental full content).
                        doc.text = text_change if 'text' in change \
                            else doc.text
                        continue
                    # Incremental range replacement (LSP coordinates).
                    start = rng.get('start') or {}
                    end = rng.get('end') or {}
                    try:
                        start_off = _offset_at(doc.text,
                                                  start.get('line', 0),
                                                  start.get('character', 0))
                        end_off = _offset_at(doc.text,
                                                end.get('line', 0),
                                                end.get('character', 0))
                    except (IndexError, ValueError):
                        start_off = 0
                        end_off = len(doc.text)
                    if end_off < start_off:
                        end_off = start_off
                    doc.text = doc.text[:start_off] + text_change \
                        + doc.text[end_off:]
                doc.text = _strip_bom(doc.text)
            doc.version = td.get('version', doc.version)
            self._validate(uri)
        elif method == 'textDocument/didSave':
            self._validate(uri)
        elif method == 'textDocument/didClose':
            self._clear_diagnostics(uri)
            self.documents.pop(uri, None)

    def _doc(self, params: dict) -> Optional[Document]:
        td = params.get('textDocument') or {}
        uri = td.get('uri')
        if not uri:
            return None
        doc = self.documents.get(uri)
        if doc is not None:
            return doc
        path = uri_to_path(uri)
        text = ''
        if path:
            try:
                with open(path, 'r', encoding='utf-8-sig') as f:
                    text = f.read()
            except (OSError, UnicodeError):
                text = ''
        doc = Document(uri=uri, text=text, path=path)
        self.documents[uri] = doc
        return doc

    def _project(self, doc: Document) -> _ProjectIndex:
        sources: dict[str, str] = {}
        for uri, d in self.documents.items():
            if d.path:
                sources[d.path] = d.text
        path = doc.path
        if path is None:
            path = '<untitled>'
            sources[path] = doc.text
        else:
            sources[path] = doc.text
        return _ProjectIndex(path, sources)

    def _validate(self, uri: str) -> None:
        doc = self.documents.get(uri)
        if doc is None or doc.path is None:
            return
        path = doc.path
        files = self._diagnostics(path)
        previous = self.diagnostics_by_doc.get(uri, set())
        current: set[str] = set()
        for old in previous:
            if old not in files:
                self._publish(old, [])
        for error_path, diags in files.items():
            self._publish(error_path, diags)
            current.add(error_path)
        self.diagnostics_by_doc[uri] = current

    def _clear_diagnostics(self, uri: str) -> None:
        for path in self.diagnostics_by_doc.pop(uri, set()):
            self._publish(path, [])

    def _publish(self, path: str, diagnostics: list[dict]) -> None:
        try:
            uri = path_to_uri(path)
        except (ValueError, OSError):
            return
        self._notify('textDocument/publishDiagnostics', {
            'uri': uri, 'diagnostics': diagnostics,
        })

    def _diagnostics(self, path: str) -> dict[str, list[dict]]:
        sources = {
            d.path: d.text for d in self.documents.values() if d.path
        }
        if path not in sources:
            try:
                with open(path, 'r', encoding='utf-8-sig') as f:
                    sources[path] = f.read()
            except (OSError, UnicodeError):
                pass
        result: dict[str, list[dict]] = {path: []}
        try:
            program = load_program(path, sources=sources)
            tc = TypeChecker(program, path)
            tc.register()
            tc.check()
        except (LexError, ParseError, CheckError, LoadError) as exc:
            filename, line, col = _error_location(exc, path)
            if not filename:
                filename = path
            filename = os.path.abspath(filename)
            range_ = _error_range(filename, line, col, sources)
            result[filename] = [{
                'range': range_,
                'severity': 1,
                'source': 'vanta',
                'message': getattr(exc, 'msg', str(exc)),
            }]
        except Exception as exc:
            # An editor must never die because of a frontend bug. The real
            # `vanta check` command still reports the traceback.
            sys.stderr.write(f'vanta lsp diagnostics: {exc}\n')
            sys.stderr.flush()
        return result

    # -- completion --------------------------------------------------------

    def _completion(self, params: dict) -> list[dict]:
        doc = self._doc(params)
        if doc is None:
            return []
        pos = params.get('position') or {}
        line, char = _position_to_py(doc.text, pos.get('line', 0),
                                     pos.get('character', 0))
        lines = _lines(doc.text)
        line_text = _line_at(lines, line)
        lsp_char = _to_lsp(line_text, char)
        # Inside an import path the only useful completions are file names.
        imported = self._import_completions(doc, line, lsp_char, line_text)
        if imported is not None:
            return imported
        index = _completion_word_start(line_text, char)
        word_start = _py_to_lsp_char(line_text, index)
        object_path = _object_before_dot(line_text, index)
        project = self._project(doc)
        locals_ = project.local_symbols(line, lsp_char)

        items: list[dict] = []
        if object_path is not None:
            items.extend(self._member_completions(
                project, object_path, locals_, line, line_text, word_start))
        else:
            items.extend(self._general_completions(
                project, locals_, line, line_text, word_start))
        return _dedupe_completion(items)

    def _import_completions(self, doc, line: int, lsp_char: int,
                            line_text: str) -> Optional[list[dict]]:
        """Complete the quoted path of an `import` line."""
        # _IMPORT_RE requires a closing quote, which does not exist while the
        # user is still typing. Accept a line that starts with `import "` and
        # handle a missing closing quote separately.
        if not line_text.startswith('import '):
            return None
        quote = line_text.find('"')
        if quote < 0:
            return None
        tail = line_text[quote + 1:]
        if '"' in tail:
            open_py = quote
            close_py = line_text.index('"', quote + 1)
        else:
            # Unterminated string while typing: replace to the line end.
            open_py = quote
            close_py = len(line_text)
        open_lsp = _py_to_lsp_char(line_text, open_py)
        close_lsp = _py_to_lsp_char(line_text, close_py)
        if not (open_lsp <= lsp_char <= close_lsp):
            return None
        cursor_py = _lsp_to_py_char(line_text, lsp_char)
        typed = line_text[open_py + 1:cursor_py].lower()
        suggestions = self._import_candidates(doc)
        edit = {'range': {
            'start': {'line': line,
                      'character': _py_to_lsp_char(line_text, open_py + 1)},
            'end': {'line': line,
                    'character': _py_to_lsp_char(line_text, close_py)},
        }}
        items: list[dict] = []
        for label, target in suggestions:
            if typed and not label.lower().startswith(typed):
                continue
            items.append(_item(label, K_MODULE, target, edit,
                               sort=f'0_{label.lower()}'))
        return items

    @staticmethod
    def _import_candidates(doc) -> list[tuple[str, str]]:
        """Sibling .vnt files and std modules as (label, target) pairs."""
        suggestions: list[tuple[str, str]] = []
        base_dir = os.path.dirname(doc.path) if doc.path else None
        own_name = os.path.basename(doc.path) if doc.path else ''
        if base_dir:
            try:
                for name in sorted(os.listdir(base_dir)):
                    if not name.endswith('.vnt') or name == own_name:
                        continue
                    full = os.path.join(base_dir, name)
                    if os.path.isfile(full):
                        suggestions.append((name, full))
            except OSError:
                pass
        if STDLIB_DIR and os.path.isdir(STDLIB_DIR):
            for root, dirs, files in os.walk(STDLIB_DIR):
                dirs.sort()
                for name in sorted(files):
                    if not name.endswith('.vnt'):
                        continue
                    full = os.path.join(root, name)
                    rel = os.path.relpath(full, STDLIB_DIR)
                    rel = rel.replace(os.sep, '/')
                    suggestions.append(('std/' + rel, full))
        return suggestions

    def _general_completions(self, project: _ProjectIndex,
                             locals_: dict[str, LocalInfo], line: int,
                             line_text: str, word_start: int) -> list[dict]:
        items: list[dict] = []
        edit = _word_edit(line, line_text, word_start)
        for name, info in locals_.items():
            items.append(_item(
                name, K_VARIABLE, info.detail, edit,
                sort=f'0_{name.lower()}'))
        for decl in project.current.decls:
            items.append(_decl_item(decl, edit, '1'))
        for decl in project.public_imports():
            items.append(_decl_item(decl, edit, '2'))
        for imp in project.current.imports:
            if imp.alias:
                items.append(_item(
                    imp.alias, K_MODULE,
                    f'module {imp.alias} ({imp.path})', edit,
                    sort=f'1_{imp.alias.lower()}'))
        for name, detail in _builtin_funcs().items():
            items.append(_item(name, K_FUNCTION, detail, edit,
                               sort=f'3_{name.lower()}'))
        for name, detail in _builtin_type_names().items():
            items.append(_item(name, K_CLASS, detail, edit,
                               sort=f'3_{name.lower()}'))
        for name in KEYWORDS:
            items.append(_item(name, K_KEYWORD, _KEYWORD_DETAILS.get(name, ''),
                               edit, sort=f'4_{name.lower()}'))
        return items

    def _member_completions(self, project: _ProjectIndex,
                            object_path: list[str],
                            locals_: dict[str, LocalInfo], line: int,
                            line_text: str, word_start: int) -> list[dict]:
        edit = _word_edit(line, line_text, word_start)
        local_type = None
        if len(object_path) == 1 and object_path[0] in locals_:
            local_type = locals_[object_path[0]].type_name
        type_decl = project.resolve_object(object_path, local_type)
        if type_decl is not None:
            items: list[dict] = []
            if type_decl.kind == 'enum':
                for member in type_decl.members:
                    insert = member.name
                    snippet = False
                    if member.payload:
                        params = ', '.join(
                            f'${{{i + 1}:{_payload_name(p)}}}'
                            for i, p in enumerate(_split_top(member.payload)))
                        insert = f'{member.name}({params})'
                        snippet = True
                    items.append(_item(
                        member.name, K_ENUM_MEMBER, member.detail, edit,
                        insert_text=insert, snippet=snippet,
                        sort=f'0_{member.name.lower()}'))
                return items
            if type_decl.kind == 'struct':
                if type_decl.fields:
                    for fld in type_decl.fields:
                        items.append(_item(
                            fld.name, K_FIELD, fld.detail, edit,
                            sort=f'0_{fld.name.lower()}'))
                for name, typ in _BUILTIN_FIELDS.get(type_decl.name, []):
                    items.append(_item(
                        name, K_FIELD, f'{name}: {typ}', edit,
                        sort=f'0_{name.lower()}'))
                for method in _BUILTIN_METHODS.get(type_decl.name, []):
                    name, insert, detail, fmt = method
                    items.append(_item(
                        name, K_METHOD, detail, edit, insert_text=insert,
                        snippet=fmt == 2, sort=f'1_{name.lower()}'))
                return items
            return []

        # Module alias: complete public declarations in the imported module.
        module = project.module_for_alias(object_path[0]) \
            if len(object_path) == 1 else None
        if module is not None:
            return [_decl_item(d, edit, '0')
                    for d in module.public_decls()]

        # Builtin values (Arena, List, Vec2, ...) reached through a local
        # annotation still need method/field completion even if no user
        # declaration exists.
        base = _base_type_name(local_type) if local_type else ''
        if base in _BUILTIN_METHODS or base in _BUILTIN_FIELDS:
            items = []
            for name, typ in _BUILTIN_FIELDS.get(base, []):
                items.append(_item(name, K_FIELD, f'{name}: {typ}', edit,
                                   sort=f'0_{name.lower()}'))
            for method in _BUILTIN_METHODS.get(base, []):
                name, insert, detail, fmt = method
                items.append(_item(name, K_METHOD, detail, edit,
                                   insert_text=insert, snippet=fmt == 2,
                                   sort=f'1_{name.lower()}'))
            return items
        return []

    # -- signature help ----------------------------------------------------

    def _signature_help(self, params: dict) -> Optional[dict]:
        doc = self._doc(params)
        if doc is None:
            return None
        pos = params.get('position') or {}
        line = pos.get('line', 0)
        char = pos.get('character', 0)
        offset = _offset_at(doc.text, line, char)
        context = _call_context(doc.text, offset)
        if context is None:
            return None
        open_index, path = context
        if not path or _in_declaration(doc.text, open_index):
            return None
        project = self._project(doc)
        locals_ = project.local_symbols(line, char)
        signature = self._resolve_signature(project, locals_, path)
        if signature is None:
            return None
        parameters = [{'label': p} for p in signature['params']]
        active = _active_parameter(doc.text, open_index, offset)
        if parameters:
            active = min(active, len(parameters) - 1)
        else:
            active = 0
        return {
            'signatures': [{
                'label': signature['label'],
                'parameters': parameters,
                'activeParameter': active,
            }],
            'activeSignature': 0,
            'activeParameter': active,
        }

    def _resolve_signature(self, project: _ProjectIndex,
                           locals_: dict[str, LocalInfo],
                           path: list[str]) -> Optional[dict]:
        if len(path) == 1:
            name = path[0]
            decl = project.decl_by_name(name)
            if decl is not None:
                if decl.kind in ('func', 'extern_func'):
                    return _parse_signature(decl.detail)
                if decl.kind == 'struct':
                    return _struct_signature(decl)
            builtin = _builtin_funcs().get(name)
            if builtin is not None:
                return _parse_signature(builtin)
            local = locals_.get(name)
            if local is not None:
                return _signature_from_function_type(local.type_name)
            return None

        obj, member = path[:-1], path[-1]
        local_type = None
        if len(obj) == 1 and obj[0] in locals_:
            local_type = locals_[obj[0]].type_name
        decl = project.resolve_object(obj, local_type)
        if decl is not None:
            signature = _member_signature(decl, member)
            if signature is not None:
                return signature
        if len(obj) == 1:
            module = project.module_for_alias(obj[0])
            if module is not None:
                for d in module.public_decls():
                    if d.name != member:
                        continue
                    if d.kind in ('func', 'extern_func'):
                        return _parse_signature(d.detail)
                    if d.kind == 'struct':
                        return _struct_signature(d)
        base = _base_type_name(local_type) if local_type else ''
        if base:
            for method in _BUILTIN_METHODS.get(base, []):
                if method[0] == member:
                    return _parse_signature(method[2])
        return None

    # -- hover / definition ------------------------------------------------

    def _hover(self, params: dict) -> Optional[dict]:
        doc = self._doc(params)
        if doc is None:
            return None
        pos = params.get('position') or {}
        line, char = _position_to_py(doc.text, pos.get('line', 0),
                                     pos.get('character', 0))
        lines = _lines(doc.text)
        line_text = _line_at(lines, line)
        lsp_char = _to_lsp(line_text, char)
        word, start, end = _word_at(line_text, lsp_char)
        if not word:
            return None
        project = self._project(doc)
        # Check if cursor is on an import path.
        import_hover = self._import_hover(project, line, lsp_char,
                                          line_text, lines)
        if import_hover is not None:
            return import_hover
        locals_ = project.local_symbols(line, lsp_char)
        detail = self._describe_word(
            project, locals_, line_text, word,
            _lsp_to_py_char(line_text, start))
        if detail is None:
            return None
        return {
            'contents': {'kind': 'markdown',
                         'value': f'```vanta\n{detail}\n```'},
            'range': {
                'start': {'line': line, 'character': start},
                'end': {'line': line, 'character': end},
            },
        }

    def _import_hover(self, project: _ProjectIndex, line: int,
                      lsp_char: int, line_text: str,
                      lines: list[str]) -> Optional[dict]:
        """Hover for an import path: show the resolved target file."""
        for imp in project.current.imports:
            if imp.line - 1 != line:
                continue
            span = _quoted_span(line_text, imp.path)
            if span is None:
                continue
            start, end = span
            start_lsp = _py_to_lsp_char(line_text, start)
            end_lsp = _py_to_lsp_char(line_text, end)
            if not (start_lsp <= lsp_char <= end_lsp):
                continue
            target = imp.target
            if (target is not None and target.path != '<untitled>'
                    and os.path.exists(target.path)):
                contents = f'Resolved import: {target.path}'
            else:
                contents = f'Unresolved import: {imp.path}'
            return {
                'contents': {'kind': 'markdown',
                             'value': f'```vanta\n{contents}\n```'},
                'range': {
                    'start': {'line': line, 'character': start_lsp},
                    'end': {'line': line, 'character': end_lsp},
                },
            }
        return None

    def _describe_word(self, project: _ProjectIndex,
                       locals_: dict[str, LocalInfo], line_text: str,
                       word: str, start: int) -> Optional[str]:
        object_path = _object_before_dot(line_text, start)
        if object_path is not None:
            local_type = None
            if len(object_path) == 1 and object_path[0] in locals_:
                local_type = locals_[object_path[0]].type_name
            decl = project.resolve_object(object_path, local_type)
            if decl is not None:
                if decl.kind == 'enum':
                    for m in decl.members:
                        if m.name == word:
                            return f'{decl.name}.{m.detail}'
                if decl.kind == 'struct':
                    for f in decl.fields:
                        if f.name == word:
                            return f'{decl.name}.{f.name}: {f.type_name}'
                    for name, typ in _BUILTIN_FIELDS.get(decl.name, []):
                        if name == word:
                            return f'{decl.name}.{name}: {typ}'
                    for method in _BUILTIN_METHODS.get(decl.name, []):
                        if method[0] == word:
                            return method[2]
                return f'{decl.name}.{word}'
            module = project.module_for_alias(object_path[0]) \
                if len(object_path) == 1 else None
            if module is not None:
                for d in module.public_decls():
                    if d.name == word:
                        return d.detail
        if word in locals_:
            return locals_[word].detail
        decl = project.decl_by_name(word)
        if decl is not None:
            return decl.detail
        if object_path is not None:
            base = _base_type_name(local_type) if local_type else ''
            for name, typ in _BUILTIN_FIELDS.get(base, []):
                if name == word:
                    return f'{base}.{name}: {typ}'
            for method in _BUILTIN_METHODS.get(base, []):
                if method[0] == word:
                    return method[2]
        if word in _builtin_funcs():
            return _builtin_funcs()[word]
        if word in _builtin_type_names():
            return _builtin_type_names()[word]
        if word in _KEYWORD_DETAILS:
            return f'{word}: {_KEYWORD_DETAILS[word]}'
        return None

    def _definition(self, params: dict) -> Optional[list[dict]]:
        doc = self._doc(params)
        if doc is None:
            return None
        pos = params.get('position') or {}
        line, char = _position_to_py(doc.text, pos.get('line', 0),
                                     pos.get('character', 0))
        lines = _lines(doc.text)
        line_text = _line_at(lines, line)
        lsp_char = _to_lsp(line_text, char)
        word, start, _ = _word_at(line_text, lsp_char)
        if not word:
            return None
        project = self._project(doc)
        # Check if cursor is on an import path.
        import_def = self._import_definition(project, line, lsp_char,
                                             line_text, lines)
        if import_def is not None:
            return import_def
        locals_ = project.local_symbols(line, lsp_char)
        object_path = _object_before_dot(
            line_text, _lsp_to_py_char(line_text, start))
        if object_path is not None:
            local_type = None
            if len(object_path) == 1 and object_path[0] in locals_:
                local_type = locals_[object_path[0]].type_name
            decl = project.resolve_object(object_path, local_type)
            if decl is not None:
                if decl.kind == 'enum':
                    for m in decl.members:
                        if m.name == word:
                            return [{
                                'uri': path_to_uri(decl.path),
                                'range': _range(m.line, m.col, m.line,
                                                m.col + len(m.name)),
                            }]
                if decl.kind == 'struct':
                    for f in decl.fields:
                        if f.name == word:
                            return [{
                                'uri': path_to_uri(decl.path),
                                'range': _range(f.line, f.col, f.line,
                                                f.col + len(f.name)),
                            }]
                return _decl_location(decl)
            module = project.module_for_alias(object_path[0]) \
                if len(object_path) == 1 else None
            if module is not None:
                for d in module.public_decls():
                    if d.name == word:
                        return _decl_location(d)
        if word in locals_:
            info = locals_[word]
            return [{
                'uri': path_to_uri(doc.path or project.current.path),
                'range': _range(info.name_line, info.name_col, info.name_line,
                                _line_end(info.name_line, info.name_col,
                                          lines)),
            }]
        decl = project.decl_by_name(word)
        if decl is not None:
            return _decl_location(decl)
        # Alias itself: jump to the import line.
        for imp in project.current.imports:
            if imp.alias == word:
                return [{
                    'uri': path_to_uri(project.current.path),
                    'range': _range(imp.line, imp.col, imp.line,
                                    _line_end(imp.line, imp.col, lines)),
                }]
        return None

    def _import_definition(self, project: _ProjectIndex, line: int,
                           lsp_char: int, line_text: str,
                           lines: list[str]) -> Optional[list[dict]]:
        """Go-to-definition for an import path: jump to the target file."""
        for imp in project.current.imports:
            if imp.line - 1 != line:
                continue
            span = _quoted_span(line_text, imp.path)
            if span is None:
                continue
            start, end = span
            start_lsp = _py_to_lsp_char(line_text, start)
            end_lsp = _py_to_lsp_char(line_text, end)
            if not (start_lsp <= lsp_char <= end_lsp):
                continue
            target = imp.target
            if (target is not None and target.path != '<untitled>'
                    and os.path.exists(target.path)):
                return [{
                    'uri': path_to_uri(target.path),
                    'range': _range(1, 1, 1, 1),
                }]
            return None
        return None

    def _implementation(self, params: dict) -> Optional[list[dict]]:
        """Concrete implementation / construction sites for a declaration."""
        target = self._reference_target(params)
        if target is None:
            return []
        locations: list[dict] = []
        seen: set[tuple[str, int, int]] = set()
        for ref in self._target_refs(target):
            if ref.declaration:
                continue
            uri = self._ref_uri(target, ref.path)
            if uri is None:
                continue
            key = (uri, ref.line, ref.col)
            if key in seen:
                continue
            seen.add(key)
            locations.append({'uri': uri,
                             'range': self._ref_range(target, ref)})
        locations.sort(key=lambda loc: (
            loc['uri'], loc['range']['start']['line'],
            loc['range']['start']['character']))
        return locations

    # -- references and rename ---------------------------------------------

    def _reference_target(self, params: dict) -> Optional[dict]:
        """Resolve the symbol under the cursor, or None if it cannot be renamed."""
        doc = self._doc(params)
        if doc is None or not doc.text:
            return None
        project = self._project(doc)
        # Index every open document, so references in sibling files that import
        # this one are found even when the entry file does not import them.
        for uri, other in self.documents.items():
            if other.path and uri != doc.uri:
                try:
                    project._load(other.path, [])
                except Exception:
                    pass
        lines = _lines(doc.text)
        pos = params.get('position') or {}
        line = max(0, min(int(pos.get('line', 0)), len(lines) - 1))
        line_text = lines[line]
        lsp_char = int(pos.get('character', 0))
        word, start_lsp, end_lsp = _word_at(line_text, lsp_char)
        if not word:
            return None
        py_start = _lsp_to_py_char(line_text, start_lsp)
        walker = _ReferenceWalker(project.current, project)
        symbol = None
        for ref in walker.refs:
            if ref.line == line + 1 and ref.col == py_start + 1:
                symbol = ref.symbol
                break
        if symbol is None:
            return None
        modules: dict[str, ModuleInfo] = {}
        for module in project.cache.values():
            modules[_norm_path(module.path)] = module
        modules[_norm_path(project.current.path)] = project.current
        return {
            'doc': doc,
            'module': project.current,
            'project': project,
            'modules': modules,
            'symbol': symbol,
            'word': word,
            'line': line,
            'start': py_start,
            'end': _lsp_to_py_char(line_text, end_lsp),
        }

    def _target_refs(self, target: dict) -> list[_Ref]:
        symbol = target['symbol']
        if symbol[0] in ('local', 'alias'):
            modules = [target['module']]
        else:
            modules = list(target['modules'].values())
        refs: list[_Ref] = []
        seen: set[tuple[str, int, int]] = set()
        for module in modules:
            walker = _ReferenceWalker(module, target['project'])
            for ref in walker.refs:
                if ref.symbol != symbol:
                    continue
                key = (ref.path, ref.line, ref.col)
                if key in seen:
                    continue
                seen.add(key)
                refs.append(ref)
        return refs

    def _ref_uri(self, target: dict, path: str) -> Optional[str]:
        if path == '<untitled>':
            return target['doc'].uri
        try:
            return path_to_uri(path)
        except (ValueError, OSError):
            return None

    def _ref_range(self, target: dict, ref: _Ref) -> dict:
        module = target['modules'].get(_norm_path(ref.path))
        line_text = ''
        if module is not None:
            line_text = _line_at(_lines(module.source), ref.line - 1)
        start = _py_to_lsp_char(line_text, ref.col - 1)
        return {
            'start': {'line': ref.line - 1, 'character': start},
            'end': {'line': ref.line - 1,
                    'character': start + _utf16_len(ref.name)},
        }

    def _references(self, params: dict) -> Optional[list[dict]]:
        target = self._reference_target(params)
        if target is None:
            return None
        include_declaration = True
        context = params.get('context')
        if isinstance(context, dict):
            include_declaration = context.get('includeDeclaration', True)
        locations: list[dict] = []
        seen: set[tuple[str, int, int]] = set()
        for ref in self._target_refs(target):
            if not include_declaration and ref.declaration:
                continue
            uri = self._ref_uri(target, ref.path)
            if uri is None:
                continue
            key = (uri, ref.line, ref.col)
            if key in seen:
                continue
            seen.add(key)
            locations.append({'uri': uri, 'range': self._ref_range(target, ref)})
        locations.sort(key=lambda loc: (
            loc['uri'], loc['range']['start']['line'],
            loc['range']['start']['character']))
        return locations

    def _prepare_rename(self, params: dict) -> Optional[dict]:
        target = self._reference_target(params)
        if target is None:
            return None
        line_text = _line_at(_lines(target['doc'].text), target['line'])
        start = _py_to_lsp_char(line_text, target['start'])
        end = _py_to_lsp_char(line_text, target['end'])
        return {
            'range': {
                'start': {'line': target['line'], 'character': start},
                'end': {'line': target['line'], 'character': end},
            },
            'placeholder': target['word'],
        }

    def _rename(self, params: dict) -> Optional[dict]:
        target = self._reference_target(params)
        if target is None:
            return None
        new_name = params.get('newName') or ''
        if re.fullmatch(r'[A-Za-z_]\w*', new_name) is None:
            return None
        if new_name in KEYWORDS:
            return None
        # Refuse names that would shadow an existing declaration visible from
        # this module, including anything exposed by an imported non-aliased
        # module. Prevents a rename from silently colliding with another name.
        _project = target['project']
        for decl in (_project.visible_decls()
                     + list(_project.public_imports())):
            if decl.name == new_name:
                return None
        changes: dict[str, list[dict]] = {}
        for ref in self._target_refs(target):
            uri = self._ref_uri(target, ref.path)
            if uri is None:
                continue
            edits = changes.setdefault(uri, [])
            range_ = self._ref_range(target, ref)
            if any(e['range'] == range_ for e in edits):
                continue
            edits.append({'range': range_, 'newText': new_name})
        if not changes:
            return None
        for edits in changes.values():
            edits.sort(key=lambda e: (
                e['range']['start']['line'], e['range']['start']['character']))
        return {'changes': changes}

    # -- code actions ------------------------------------------------------

    def _code_actions(self, params: dict) -> list[dict]:
        doc = self._doc(params)
        if doc is None or not doc.text:
            return []
        context = params.get('context') or {}
        requested = params.get('range') or {}
        only = context.get('only')
        if isinstance(only, list) and only and 'quickfix' not in only:
            return []
        diagnostics = self._range_diagnostics(doc, requested)
        supplied = context.get('diagnostics')
        if isinstance(supplied, list) and supplied:
            # A client only sends the diagnostics that overlap the requested
            # range, and a missing member is reported on the dot rather than
            # on the word, so the server's own list stays authoritative and
            # the client's list only fills in what the server cannot see.
            extra = [diagnostic for diagnostic in supplied
                     if isinstance(diagnostic, dict)
                     and self._diagnostic_near(diagnostic, requested)]
            diagnostics = self._merge_diagnostics(diagnostics, extra)
        project = self._project(doc)
        actions: list[dict] = []
        seen: set[str] = set()
        for diagnostic in diagnostics:
            if not isinstance(diagnostic, dict):
                continue
            for action in self._quick_fixes(diagnostic, doc, project):
                key = action['title'] + json.dumps(action['edit'],
                                                   sort_keys=True)
                if key in seen:
                    continue
                seen.add(key)
                actions.append(action)
        return actions

    def _range_diagnostics(self, doc: Document,
                           requested: dict) -> list[dict]:
        if doc.path is None:
            return []
        path = os.path.abspath(doc.path)
        diagnostics = self._diagnostics(path).get(path, [])
        if not requested:
            return diagnostics
        overlapping = [diagnostic for diagnostic in diagnostics
                       if _ranges_overlap(diagnostic.get('range') or {},
                                          requested)]
        if overlapping:
            return overlapping
        # A missing member is reported on the dot while the cursor sits on
        # the identifier, so fall back to every diagnostic on the same line.
        start = requested.get('start') or {}
        line = int(start.get('line', 0))
        return [diagnostic for diagnostic in diagnostics
                if int(((diagnostic.get('range') or {}).get('start') or {})
                       .get('line', -1)) == line]

    def _diagnostic_near(self, diagnostic: dict, requested: dict) -> bool:
        """True when a diagnostic is close enough to the requested range."""
        range_ = diagnostic.get('range') or {}
        if not requested:
            return True
        if _ranges_overlap(range_, requested):
            return True
        start = requested.get('start') or {}
        line = int(start.get('line', 0))
        other = range_.get('start') or {}
        return int(other.get('line', -1)) == line

    def _merge_diagnostics(self, own: list[dict],
                           supplied: list[dict]) -> list[dict]:
        """Combine the server's diagnostics with the ones a client sent."""
        merged = list(own)
        seen = {(str(d.get('message') or ''),
                 json.dumps(d.get('range') or {}, sort_keys=True))
                for d in own}
        for diagnostic in supplied:
            if not isinstance(diagnostic, dict):
                continue
            key = (str(diagnostic.get('message') or ''),
                   json.dumps(diagnostic.get('range') or {}, sort_keys=True))
            if key in seen:
                continue
            seen.add(key)
            merged.append(diagnostic)
        return merged

    def _quick_fixes(self, diagnostic: dict, doc: Document,
                     project: _ProjectIndex) -> list[dict]:
        message = str(diagnostic.get('message') or '')
        match = re.fullmatch(r"unknown name '([^']+)'", message)
        if match is not None:
            return self._name_fixes(diagnostic, doc, project,
                                    match.group(1))
        match = re.fullmatch(r"type \S+ has no field '([^']+)'", message)
        if match is not None:
            return self._member_fixes(diagnostic, doc, project,
                                      match.group(1), 'field')
        match = re.fullmatch(r"enum '[^']+' has no member '([^']+)'",
                             message)
        if match is not None:
            return self._member_fixes(diagnostic, doc, project,
                                      match.group(1), 'enum')
        match = re.fullmatch(r"unknown field '([^']+)'", message)
        if match is not None:
            return self._label_fixes(diagnostic, doc, project,
                                     match.group(1))
        if message == 'invalid assignment target':
            return self._mutability_fixes(diagnostic, doc, project)
        match = re.search(r'cannot assign (\S+) to (\S+)', message)
        if match is not None:
            return self._type_annotation_fixes(
                diagnostic, doc, project, match.group(1), match.group(2))
        return []

    def _type_annotation_fixes(self, diagnostic: dict, doc: Document,
                               project: _ProjectIndex, actual_type: str,
                               expected_type: str) -> list[dict]:
        range_ = diagnostic.get('range') or {}
        start = range_.get('start') or {}
        line = int(start.get('line', 0))
        lines = _lines(doc.text)
        line_text = _line_at(lines, line)
        colon = line_text.find(':')
        if colon < 0:
            return []
        index = line_text.find(expected_type, colon)
        if index < 0:
            return []
        word_range = self._word_range(line_text, line, index, expected_type)
        return [self._action(
            f"change annotation to {actual_type}",
            doc.uri, word_range, actual_type, diagnostic, preferred=True)]

    def _name_fixes(self, diagnostic: dict, doc: Document,
                    project: _ProjectIndex, name: str) -> list[dict]:
        range_ = diagnostic.get('range') or {}
        start = range_.get('start') or {}
        end = range_.get('end') or {}
        line = int(start.get('line', 0))
        char = int(start.get('character', 0))
        lines = _lines(doc.text)
        line_text = _line_at(lines, line)
        index = _lsp_to_py_char(line_text, char)
        stop = _lsp_to_py_char(line_text, int(end.get('character', 0)))
        if line_text[index:stop] != name:
            # A client may send a stale range; find the name on the line.
            index = self._find_word(line_text, name, index)
            if index is None:
                return []
        range_ = self._word_range(line_text, line, index, name)
        return self._suggest(doc, diagnostic, range_, name,
                             self._visible_names(project, line, char))

    def _find_word(self, line_text: str, word: str,
                   start: int) -> Optional[int]:
        """The index of the first whole-word occurrence at or after start."""
        for match in re.finditer(r'\b' + re.escape(word) + r'\b', line_text):
            if match.start() >= start:
                return match.start()
        return None

    def _visible_names(self, project: _ProjectIndex, line: int,
                       char: int) -> set[str]:
        names = set(project.local_symbols(line, char))
        for decl in project.visible_decls():
            names.add(decl.name)
        for imp in project.current.imports:
            if imp.alias:
                names.add(imp.alias)
            elif imp.target is not None:
                names.update(d.name for d in imp.target.public_decls())
        names.update(_builtin_funcs())
        names.update(_builtin_type_names())
        return names

    def _member_fixes(self, diagnostic: dict, doc: Document,
                      project: _ProjectIndex, word: str,
                      kind: str) -> list[dict]:
        range_ = diagnostic.get('range') or {}
        start = range_.get('start') or {}
        end = range_.get('end') or {}
        line = int(start.get('line', 0))
        char = int(start.get('character', 0))
        lines = _lines(doc.text)
        line_text = _line_at(lines, line)
        # Diagnostics for a missing member sit on the dot; walk to the
        # identifier that follows it.
        index = _lsp_to_py_char(line_text,
                                int(end.get('character', 0)))
        while index < len(line_text) and not (
                line_text[index].isalnum() or line_text[index] == '_'):
            index += 1
        start_index = index
        while index < len(line_text) and (
                line_text[index].isalnum() or line_text[index] == '_'):
            index += 1
        if line_text[start_index:index] != word:
            return []
        message = str(diagnostic.get('message') or '')
        decl = self._receiver_decl(project, line_text, start_index, line,
                                    char)
        if decl is not None:
            if kind == 'enum':
                candidates = {member.name for member in decl.members}
            else:
                candidates = {field_info.name for field_info in decl.fields}
        else:
            if kind == 'enum':
                match = re.search(r"enum '([^']+)'", message)
                candidates = self._enum_members(
                    project, match.group(1) if match is not None else '')
            else:
                match = re.search(r'type (\S+) has no field', message)
                candidates = self._struct_fields(
                    project, match.group(1) if match is not None else '')
        range_ = self._word_range(line_text, line, start_index, word)
        return self._suggest(doc, diagnostic, range_, word, candidates)

    def _receiver_decl(self, project: _ProjectIndex, line_text: str,
                       dot: int, line: int, char: int) -> Optional[DeclInfo]:
        """Resolve the type of the receiver in front of a missing member."""
        path = _object_before_dot(line_text, dot)
        if path is None:
            return None
        if len(path) == 1:
            name = path[0]
            info = project.local_symbols(line, char).get(name)
            if info is not None and info.type_name:
                decl = self._type_decl(project, info.type_name)
                if decl is not None:
                    return decl
            return project.type_by_name(name)
        module = project.alias_module(path[0])
        if module is not None:
            return project.type_in_module(module, path[-1])
        return project.type_by_name(path[-1])

    def _type_decl(self, project: _ProjectIndex,
                   type_name: str) -> Optional[DeclInfo]:
        name = _base_type_name(type_name)
        decl = project.type_by_name(name)
        if decl is not None:
            return decl
        if '.' in name:
            qualifier, _dot, tail = name.rpartition('.')
            module = project.alias_module(qualifier)
            if module is not None:
                return project.type_in_module(module, tail)
        return None

    def _label_fixes(self, diagnostic: dict, doc: Document,
                     project: _ProjectIndex, word: str) -> list[dict]:
        range_ = diagnostic.get('range') or {}
        start = range_.get('start') or {}
        start_line = int(start.get('line', 0))
        start_char = int(start.get('character', 0))
        lines = _lines(doc.text)
        callee_line = _line_at(lines, start_line)
        callee_start = _lsp_to_py_char(callee_line, start_char)
        label = None
        for offset in range(0, 8):
            line = start_line + offset
            if line >= len(lines):
                break
            text = _line_at(lines, line)
            begin = callee_start if offset == 0 else 0
            match = re.search(r'\b' + re.escape(word) + r'\s*:',
                              text[begin:])
            if match is not None:
                label = (line, begin + match.start(), text)
                break
        if label is None:
            return []
        line, index, line_text = label
        candidates = self._constructor_fields(
            project, self._callee_path(callee_line, start_char))
        range_ = self._word_range(line_text, line, index, word)
        return self._suggest(doc, diagnostic, range_, word, candidates)

    def _callee_path(self, line_text: str, char: int) -> Optional[list[str]]:
        """The dotted constructor path a diagnostic points at."""
        index = _lsp_to_py_char(line_text, char)
        if index < len(line_text) and line_text[index] == '.':
            # A qualified constructor is reported on its dot.
            start = index + 1
            end = start
            while end < len(line_text) and (
                    line_text[end].isalnum() or line_text[end] == '_'):
                end += 1
            name = line_text[start:end]
            head = _object_before_dot(line_text, start)
            if head is None:
                return [name] if name else None
            return head + [name]
        match = re.match(r'[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*',
                         line_text[index:])
        if match is None:
            return None
        return match.group(0).split('.')

    def _mutability_fixes(self, diagnostic: dict, doc: Document,
                          project: _ProjectIndex) -> list[dict]:
        range_ = diagnostic.get('range') or {}
        start = range_.get('start') or {}
        line = int(start.get('line', 0))
        char = int(start.get('character', 0))
        lines = _lines(doc.text)
        line_text = _line_at(lines, line)
        word, _word_start, _word_end = _word_at(line_text, char)
        if not word:
            return []
        info = project.local_symbols(line, char).get(word)
        # Parameters cannot be changed, and loop variables have no keyword;
        # only an immutable `let` local gets this fix.
        if info is None or info.kind != 'var' or info.mutable:
            return []
        declaration = _line_at(lines, info.name_line - 1)
        keyword = re.search(r'\b(let|mut)\s+' + re.escape(word) + r'\b',
                            declaration)
        if keyword is None or keyword.group(1) != 'let':
            return []
        edit_range = {
            'start': {'line': info.name_line - 1,
                      'character': _py_to_lsp_char(
                          declaration, keyword.start(1))},
            'end': {'line': info.name_line - 1,
                    'character': _py_to_lsp_char(
                        declaration, keyword.end(1))},
        }
        return [self._action(f"Make '{word}' mutable", doc.uri, edit_range,
                             'mut', diagnostic, preferred=True)]

    def _constructor_fields(self, project: _ProjectIndex,
                            path: Optional[list[str]]) -> set[str]:
        if not path:
            return self._all_field_names(project)
        decl = None
        if len(path) == 1:
            decl = project.type_by_name(path[0])
        else:
            module = project.alias_module(path[0])
            if module is not None:
                decl = project.type_in_module(module, path[-1])
            if decl is None:
                decl = project.type_by_name(path[-1])
        if decl is not None and decl.kind == 'struct':
            return {field_info.name for field_info in decl.fields}
        return self._all_field_names(project)

    def _struct_fields(self, project: _ProjectIndex, name: str) -> set[str]:
        builtin = _BUILTIN_FIELDS.get(name)
        if builtin is not None:
            return {field_name for field_name, _type in builtin}
        decl = project.type_by_name(name)
        if decl is None and '.' in name:
            qualifier, _dot, tail = name.rpartition('.')
            module = project.alias_module(qualifier)
            if module is not None:
                decl = project.type_in_module(module, tail)
        if decl is not None and decl.kind == 'struct':
            return {field_info.name for field_info in decl.fields}
        return self._all_field_names(project)

    def _enum_members(self, project: _ProjectIndex, name: str) -> set[str]:
        decl = project.type_by_name(name)
        if decl is not None and decl.kind == 'enum':
            return {member.name for member in decl.members}
        return self._all_member_names(project)

    def _all_field_names(self, project: _ProjectIndex) -> set[str]:
        names: set[str] = set()
        modules = list(project.cache.values()) + [project.current]
        for module in modules:
            for decl in module.decls:
                if decl.kind == 'struct':
                    names.update(field_info.name
                                 for field_info in decl.fields)
        for fields_ in _BUILTIN_FIELDS.values():
            names.update(field_name for field_name, _type in fields_)
        return names

    def _all_member_names(self, project: _ProjectIndex) -> set[str]:
        names: set[str] = set()
        modules = list(project.cache.values()) + [project.current]
        for module in modules:
            for decl in module.decls:
                if decl.kind == 'enum':
                    names.update(member.name for member in decl.members)
        return names

    def _suggest(self, doc: Document, diagnostic: dict, range_: dict,
                 word: str, candidates: set[str]) -> list[dict]:
        actions: list[dict] = []
        options = [name for name in sorted(candidates) if name != word]
        for position, candidate in enumerate(difflib.get_close_matches(
                word, options, n=3, cutoff=0.6)):
            actions.append(self._action(
                f"Change '{word}' to '{candidate}'", doc.uri, range_,
                candidate, diagnostic, preferred=position == 0))
        return actions

    def _word_range(self, line_text: str, line: int, start: int,
                    word: str) -> dict:
        return {
            'start': {'line': line,
                      'character': _py_to_lsp_char(line_text, start)},
            'end': {'line': line,
                    'character': _py_to_lsp_char(line_text,
                                                 start + len(word))},
        }

    def _action(self, title: str, uri: str, range_: dict, new_text: str,
                diagnostic: Optional[dict],
                preferred: bool = False) -> dict:
        action = {
            'title': title,
            'kind': 'quickfix',
            'edit': {'changes': {uri: [
                {'range': range_, 'newText': new_text},
            ]}},
        }
        if diagnostic is not None:
            action['diagnostics'] = [diagnostic]
        if preferred:
            action['isPreferred'] = True
        return action

    # -- workspace symbols --------------------------------------------------

    def _workspace_symbols(self, params: dict) -> list[dict]:
        query = str(params.get('query') or '')
        # Filter by SymbolKind if provided.
        kind_filter = params.get('kind')
        if kind_filter is not None:
            if isinstance(kind_filter, list):
                kind_filter = set(kind_filter)
            else:
                kind_filter = {kind_filter}
        scored: list[tuple[int, str, dict]] = []
        for path, module in self._workspace_modules():
            try:
                uri = path_to_uri(path)
            except (ValueError, OSError):
                continue
            container = module.module_name or os.path.basename(path)
            for decl in module.decls:
                entries = [(decl.name, _decl_symbol_kind(decl.kind),
                            decl.name_line or decl.line,
                            decl.name_col or decl.col, container)]
                for field_info in decl.fields:
                    entries.append((field_info.name, S_FIELD,
                                    field_info.line, field_info.col,
                                    decl.name))
                for member in decl.members:
                    entries.append((member.name, S_ENUM_MEMBER,
                                    member.line, member.col, decl.name))
                for name, kind, line, col, owner in entries:
                    if kind_filter is not None and kind not in kind_filter:
                        continue
                    score = _symbol_score(name, query)
                    if score is None:
                        continue
                    range_ = self._symbol_range(module, line, col, name)
                    if range_ is None:
                        continue
                    scored.append((score, name, {
                        'name': name,
                        'kind': kind,
                        'location': {'uri': uri, 'range': range_},
                        'containerName': owner,
                    }))
        scored.sort(key=lambda item: (item[0], item[1]))
        return [symbol for _score, _name, symbol in scored[:200]]

    def _symbol_range(self, module: ModuleInfo, line: int, col: int,
                      name: str) -> Optional[dict]:
        lines = _lines(module.source)
        if line < 1 or line > len(lines):
            return None
        line_text = lines[line - 1]
        index = max(0, col - 1)
        if line_text[index:index + len(name)] != name:
            found = line_text.find(name)
            if found < 0:
                return None
            index = found
        start = _py_to_lsp_char(line_text, index)
        return {
            'start': {'line': line - 1, 'character': start},
            'end': {'line': line - 1,
                    'character': start + _utf16_len(name)},
        }

    def _workspace_modules(self) -> list[tuple[str, ModuleInfo]]:
        """Parse every Vanta file the workspace can see."""
        files = self._workspace_files()
        sources = {d.path: d.text for d in self.documents.values()
                   if d.path}
        index = _ProjectIndex('<workspace>', sources)
        modules: list[tuple[str, ModuleInfo]] = []
        live: set[str] = set()
        for path in files:
            stamp = self._file_stamp(path, sources)
            key = _norm_path(path)
            live.add(key)
            cached = self._workspace_cache.get(key)
            if cached is not None and cached[0] == stamp:
                modules.append((path, cached[1]))
                continue
            module = index.parse_only(path)
            self._workspace_cache[key] = (stamp, module)
            modules.append((path, module))
        for key in [key for key in self._workspace_cache if key not in live]:
            del self._workspace_cache[key]
        return modules

    def _file_stamp(self, path: str,
                    sources: dict[str, str]) -> Optional[tuple]:
        key = _norm_path(path)
        for source_path, text in sources.items():
            if _norm_path(source_path) == key:
                return ('buffer', hash(text))
        try:
            info = os.stat(path)
        except OSError:
            return None
        return ('file', info.st_mtime_ns, info.st_size)

    def _workspace_files(self) -> list[str]:
        """The Vanta files the workspace can reach."""
        seen: set[str] = set()
        files: list[str] = []
        if self.root_path and os.path.isdir(self.root_path):
            for path in self._walk_root(self.root_path):
                key = _norm_path(path)
                if key in seen:
                    continue
                seen.add(key)
                files.append(path)
        # The open documents and the modules they import are always searched,
        # even when the editor sent no workspace root.
        for doc in self.documents.values():
            if not doc.path:
                continue
            project = self._project(doc)
            for module in list(project.cache.values()) + [project.current]:
                key = _norm_path(module.path)
                if key in seen:
                    continue
                seen.add(key)
                files.append(module.path)
        return files

    def _walk_root(self, root: str) -> list[str]:
        """The .vnt files under a root, cached for a few seconds.

        The editor asks for workspace symbols on every keystroke, so walking
        the tree again each time would be wasteful.
        """
        now = time.monotonic()
        cached = self._file_list_cache.get(root)
        if cached is not None and now - cached[0] < 5.0:
            return cached[1]
        files = _walk_vanta_files(root)
        self._file_list_cache[root] = (now, files)
        return files

    # -- semantic tokens ----------------------------------------------------

    def _semantic_tokens(self, params: dict) -> dict:
        doc = self._doc(params)
        if doc is None or not doc.text:
            return {'data': []}
        project = self._project(doc)
        module = project.current
        lines = _lines(module.source)
        tokens: list[tuple[int, int, int, int, int]] = []
        # The walker resolves every identifier to a declaration, so the token
        # kind is semantic rather than a guess from the spelling.
        walker = _ReferenceWalker(module, project)
        claimed: set[tuple[int, int]] = set()
        for ref in walker.refs:
            if ref.path != module.path or not ref.kind:
                continue
            line_text = _line_at(lines, ref.line - 1)
            start = _py_to_lsp_char(line_text, ref.col - 1)
            length = _utf16_len(ref.name)
            if length <= 0:
                continue
            entry = _SEMANTIC_TOKEN_BY_KIND.get(ref.kind)
            if entry is None:
                continue
            token_type, modifiers = entry
            if ref.declaration:
                modifiers |= ST_MOD_DECLARATION
            claimed.add((ref.line, ref.col))
            tokens.append((ref.line - 1, start, length, token_type,
                           modifiers))
        # Import path string literals.
        tokens.extend(self._import_string_tokens(module, lines, claimed))
        # Lexical tokens: keywords, strings, numbers, and comments.
        tokens.extend(self._lexical_tokens(doc.text, lines))
        # Builtins the walker cannot resolve, because they are not declared
        # anywhere in the project.
        tokens.extend(self._builtin_tokens(doc.text, lines, claimed))
        tokens = _dedupe_tokens(tokens)
        tokens.sort(key=lambda item: (item[0], item[1]))
        data: list[int] = []
        prev_line = 0
        prev_start = 0
        for line, start, length, token_type, modifiers in tokens:
            delta_line = line - prev_line
            delta_start = start - prev_start if delta_line == 0 else start
            data.extend([delta_line, delta_start, length, token_type,
                         modifiers])
            prev_line = line
            prev_start = start
        return {'data': data}

    def _builtin_tokens(self, text: str, lines: list[str],
                        claimed: set[tuple[int, int]]) \
            -> list[tuple[int, int, int, int, int]]:
        """Builtin functions and types, which nothing declares."""
        tokens: list[tuple[int, int, int, int, int]] = []
        functions = _builtin_funcs()
        types = _builtin_type_names()
        try:
            raw = Lexer(text, '<semantic>').tokenize()
        except LexError:
            return tokens
        for token in raw:
            if token.type != TT.IDENT:
                continue
            if (token.line, token.col) in claimed:
                continue
            name = str(token.value)
            if name in functions:
                token_type = ST_FUNCTION
            elif name in types:
                token_type = ST_TYPE
            else:
                continue
            line_text = _line_at(lines, token.line - 1)
            start = _py_to_lsp_char(line_text, token.col - 1)
            length = _utf16_len(name)
            if length <= 0:
                continue
            tokens.append((token.line - 1, start, length, token_type,
                           ST_MOD_DEFAULT_LIBRARY))
        return tokens

    def _import_string_tokens(self, module: ModuleInfo,
                              lines: list[str],
                              claimed: set[tuple[int, int]]) \
            -> list[tuple[int, int, int, int, int]]:
        """Semantic tokens for import path string literals."""
        tokens: list[tuple[int, int, int, int, int]] = []
        for imp in module.imports:
            # ImportInfo has line (1-based) and col (1-based) pointing at the
            # opening quote. The lexer already emits a STRING token for this.
            # We just need to find it and emit a semantic token.
            line_text = _line_at(lines, imp.line - 1)
            # The import path is at imp.col (1-based). Find the quoted string.
            start_idx = imp.col - 1
            if start_idx < 0 or start_idx >= len(line_text):
                continue
            # Skip if this position is already claimed by the reference walker.
            if (imp.line, imp.col) in claimed:
                continue
            # The token is a string literal; use 'string' type (index 16).
            token_type = ST_STRING
            length = _utf16_len(imp.path)
            if length <= 0:
                continue
            start_lsp = _py_to_lsp_char(line_text, start_idx)
            tokens.append((imp.line - 1, start_lsp, length, token_type, 0))
        return tokens

    def _lexical_tokens(self, text: str, lines: list[str]) \
            -> list[tuple[int, int, int, int, int]]:
        """Keyword, string, number, and comment tokens for the buffer."""
        tokens: list[tuple[int, int, int, int, int]] = []
        try:
            raw = Lexer(text, '<semantic>').tokenize()
        except LexError:
            return tokens
        for token in raw:
            if token.type in (TT.NEWLINE, TT.INDENT, TT.DEDENT, TT.EOF):
                continue
            if token.type == TT.IDENT:
                continue
            token_type = _SEMANTIC_LEXICAL_TYPE.get(token.type)
            if token_type is None:
                continue
            line_text = _line_at(lines, token.line - 1)
            start = _py_to_lsp_char(line_text, token.col - 1)
            length = _lexical_token_length(token, line_text, token.col - 1)
            if length <= 0:
                continue
            tokens.append((token.line - 1, start, length, token_type, 0))
        tokens.extend(_comment_tokens(text, lines))
        return tokens

    # -- formatting --------------------------------------------------------

    def _formatting(self, params: dict) -> list[dict]:
        """Format the whole document and return the edit that does it."""
        doc = self._doc(params)
        if doc is None or not doc.text:
            return []
        try:
            formatted = format_source(doc.text, doc.path or '<untitled>')
        except FormatError:
            return []
        if formatted == doc.text:
            return []
        lines = _lines(doc.text)
        last = len(lines) - 1
        if last >= 0 and lines[last] == '':
            last -= 1
        end_character = len(lines[last]) if last >= 0 else 0
        return [{
            'range': {
                'start': {'line': 0, 'character': 0},
                'end': {'line': max(0, last), 'character': end_character},
            },
            'newText': formatted,
        }]

    # -- inlay hints -------------------------------------------------------

    def _inlay_hints(self, params: dict) -> list[dict]:
        """Show the inferred type of a local that has no type annotation."""
        doc = self._doc(params)
        if doc is None or not doc.text:
            return []
        project = self._project(doc)
        module = project.current
        if module.program is None:
            return []
        requested = params.get('range') or {}
        start_line = int((requested.get('start') or {}).get('line', 0))
        end_line = int((requested.get('end') or {}).get('line', 10 ** 9))
        lines = _lines(module.source)
        walker = _ReferenceWalker(module, project)
        hints: list[dict] = []
        for hint in walker.hints:
            line = hint.line
            if not start_line <= line <= end_line:
                continue
            line_text = _line_at(lines, line - 1)
            index = _py_to_lsp_char(line_text, hint.col - 1)
            hints.append({
                'position': {'line': line - 1, 'character': index},
                'label': f': {hint.type_text}',
                'kind': 1,          # InlayHintKind.Type
                'paddingLeft': False,
                'paddingRight': False,
            })
        return hints

    # -- type hierarchy ----------------------------------------------------

    def _type_hierarchy_prepare(self, params: dict) -> list[dict]:
        """The struct or enum under the cursor, as a type hierarchy item."""
        doc = self._doc(params)
        if doc is None or not doc.text:
            return []
        pos = params.get('position') or {}
        line = int(pos.get('line', 0))
        char = int(pos.get('character', 0))
        project = self._project(doc)
        module = project.current
        for decl in module.decls:
            if decl.kind not in ('struct', 'enum'):
                continue
            range_ = self._decl_name_range(module, decl)
            if range_ is None:
                continue
            if not (range_['start']['line'] <= line <= range_['end']['line']):
                continue
            if range_['start']['line'] == line and not (
                    range_['start']['character'] <= char
                    <= range_['end']['character']):
                continue
            return [self._type_item(project, decl)]
        return []

    def _type_hierarchy_supertypes(self, params: dict) -> list[dict]:
        """The structs that hold this one by value."""
        item = params.get('item') or {}
        symbol = _symbol_from_item(item)
        if symbol is None:
            return []
        project = self._project_for_item(item)
        if project is None:
            return []
        result: list[dict] = []
        for decl in self._types_containing(project, symbol):
            result.append({'type': self._type_item(project, decl)})
        result.sort(key=lambda entry: entry['type']['name'])
        return result

    def _type_hierarchy_subtypes(self, params: dict) -> list[dict]:
        """The structs this one holds by value."""
        item = params.get('item') or {}
        symbol = _symbol_from_item(item)
        if symbol is None:
            return []
        project = self._project_for_item(item)
        if project is None:
            return []
        decl = self._decl_for_symbol(project, symbol)
        if decl is None or decl.kind != 'struct':
            return []
        result: list[dict] = []
        for field_info in decl.fields:
            child = self._resolve_field_type(project, decl, field_info)
            if child is None or child is decl:
                continue
            result.append({'type': self._type_item(project, child)})
        result.sort(key=lambda entry: entry['type']['name'])
        return result

    def _types_containing(self, project: _ProjectIndex,
                          symbol: tuple) -> list[DeclInfo]:
        """The structs with a field of the given type."""
        target = self._decl_for_symbol(project, symbol)
        if target is None:
            return []
        holders: list[DeclInfo] = []
        for module in self._project_modules(project):
            for decl in module.decls:
                if decl.kind != 'struct' or decl is target:
                    continue
                for field_info in decl.fields:
                    child = self._resolve_field_type(project, decl,
                                                     field_info)
                    if child is target:
                        holders.append(decl)
                        break
        return holders

    def _project_modules(self, project: _ProjectIndex) -> list[ModuleInfo]:
        modules = list(project.cache.values())
        if project.current not in modules:
            modules.append(project.current)
        return modules

    def _resolve_field_type(self, project: _ProjectIndex, owner: DeclInfo,
                            field_info: FieldInfo) -> Optional[DeclInfo]:
        """The struct a field holds, when it holds one by value."""
        written = field_info.type_name
        if not written or written.startswith('ptr<') \
                or written.startswith('List<') or written.startswith('['):
            return None
        name = _base_type_name(written)
        if '.' in name:
            qualifier, _dot, tail = name.rpartition('.')
            module = project.module_for_alias(qualifier)
            if module is None:
                return None
            for decl in module.public_decls():
                if decl.name == tail and decl.kind in ('struct', 'enum'):
                    return decl
            return None
        for module in self._project_modules(project):
            for decl in module.decls:
                if decl.name == name and decl.kind in ('struct', 'enum'):
                    return decl
        return None

    def _type_item(self, project: _ProjectIndex, decl: DeclInfo) -> dict:
        module = project.cache.get(_norm_path(decl.path))
        if module is None:
            module = project.current
        range_ = self._decl_name_range(module, decl) or {
            'start': {'line': max(0, decl.line - 1), 'character': 0},
            'end': {'line': max(0, decl.line - 1), 'character': 0},
        }
        try:
            uri = path_to_uri(decl.path)
        except (ValueError, OSError):
            uri = ''
        kind = S_STRUCT if decl.kind == 'struct' else S_ENUM
        return {
            'name': decl.name,
            'kind': kind,
            'detail': decl.detail,
            'uri': uri,
            'range': range_,
            'selectionRange': range_,
            'data': list(_global_symbol(decl)),
        }

    # -- call hierarchy ----------------------------------------------------

    def _call_hierarchy_prepare(self, params: dict) -> list[dict]:
        """The function under the cursor, as a call hierarchy item."""
        doc = self._doc(params)
        if doc is None or not doc.text:
            return []
        pos = params.get('position') or {}
        line = int(pos.get('line', 0))
        char = int(pos.get('character', 0))
        project = self._project(doc)
        module = project.current
        for decl in module.decls:
            if decl.kind not in ('func', 'extern_func'):
                continue
            range_ = self._decl_name_range(module, decl)
            if range_ is None:
                continue
            if not (range_['start']['line'] <= line <= range_['end']['line']):
                continue
            if range_['start']['line'] == line and not (
                    range_['start']['character'] <= char
                    <= range_['end']['character']):
                continue
            return [self._call_item(project, decl)]
        return []

    def _call_hierarchy_incoming(self, params: dict) -> list[dict]:
        """The functions that call the given one."""
        item = params.get('item') or {}
        symbol = _symbol_from_item(item)
        if symbol is None:
            return []
        project = self._project_for_item(item)
        if project is None:
            return []
        callers: dict[tuple, list] = {}
        for ref in self._call_refs(project):
            if ref.symbol != symbol or ref.enclosing is None:
                continue
            callers.setdefault(ref.enclosing, []).append(ref)
        result: list[dict] = []
        for enclosing, refs in callers.items():
            decl = self._decl_for_symbol(project, enclosing)
            if decl is None:
                continue
            ranges = []
            for ref in refs:
                location = self._ref_location(project, ref)
                if location is not None:
                    ranges.append(location['range'])
            if not ranges:
                continue
            result.append({'from': self._call_item(project, decl),
                           'fromRanges': ranges})
        result.sort(key=lambda entry: entry['from']['name'])
        return result

    def _call_hierarchy_outgoing(self, params: dict) -> list[dict]:
        """The functions that the given one calls."""
        item = params.get('item') or {}
        symbol = _symbol_from_item(item)
        if symbol is None:
            return []
        project = self._project_for_item(item)
        if project is None:
            return []
        callees: dict[tuple, list] = {}
        for ref in self._call_refs(project):
            if ref.enclosing != symbol or ref.kind != 'function':
                continue
            if ref.declaration:
                continue
            callees.setdefault(ref.symbol, []).append(ref)
        result: list[dict] = []
        for callee, refs in callees.items():
            decl = self._decl_for_symbol(project, callee)
            if decl is None:
                continue
            ranges = []
            for ref in refs:
                location = self._ref_location(project, ref)
                if location is not None:
                    ranges.append(location['range'])
            if not ranges:
                continue
            result.append({'to': self._call_item(project, decl),
                           'fromRanges': ranges})
        result.sort(key=lambda entry: entry['to']['name'])
        return result

    def _call_refs(self, project: _ProjectIndex) -> list:
        """Every reference in the project, with its enclosing function."""
        refs: list = []
        seen: set[tuple[str, int, int]] = set()
        modules = list(project.cache.values())
        if project.current not in modules:
            modules.append(project.current)
        for module in modules:
            walker = _ReferenceWalker(module, project)
            for ref in walker.refs:
                key = (ref.path, ref.line, ref.col)
                if key in seen:
                    continue
                seen.add(key)
                refs.append(ref)
        return refs

    def _project_for_item(self, item: dict) -> Optional[_ProjectIndex]:
        uri = item.get('uri')
        if not uri:
            return None
        doc = self._doc({'textDocument': {'uri': uri}})
        if doc is None:
            return None
        return self._project(doc)

    def _decl_for_symbol(self, project: _ProjectIndex,
                         symbol: tuple) -> Optional[DeclInfo]:
        if not symbol or symbol[0] != 'global':
            return None
        path = symbol[1]
        module = project.cache.get(_norm_path(path))
        if module is None:
            return None
        for decl in module.decls:
            if _global_symbol(decl) == symbol:
                return decl
        return None

    def _call_item(self, project: _ProjectIndex,
                   decl: DeclInfo) -> dict:
        module = project.cache.get(_norm_path(decl.path))
        if module is None:
            module = project.current
        range_ = self._decl_name_range(module, decl) or {
            'start': {'line': max(0, decl.line - 1), 'character': 0},
            'end': {'line': max(0, decl.line - 1), 'character': 0},
        }
        try:
            uri = path_to_uri(decl.path)
        except (ValueError, OSError):
            uri = ''
        return {
            'name': decl.name,
            'kind': S_FUNCTION,
            'detail': decl.detail,
            'uri': uri,
            'range': range_,
            'selectionRange': range_,
            'data': list(_global_symbol(decl)),
        }

    # -- code lens ---------------------------------------------------------

    def _code_lenses(self, params: dict) -> list[dict]:
        """Show how many places use each top-level function."""
        doc = self._doc(params)
        if doc is None or not doc.text:
            return []
        project = self._project(doc)
        for uri, other in self.documents.items():
            if other.path and uri != doc.uri:
                try:
                    project._load(other.path, [])
                except Exception:
                    pass
        uses = self._reference_uses(project)
        lenses: list[dict] = []
        for decl in project.current.decls:
            if decl.kind not in ('func', 'extern_func'):
                continue
            refs = uses.get(_global_symbol(decl), [])
            if not refs:
                continue
            range_ = self._decl_name_range(project.current, decl)
            if range_ is None:
                continue
            locations = []
            for ref in refs:
                location = self._ref_location(project, ref)
                if location is not None:
                    locations.append(location)
            if not locations:
                continue
            count = len(locations)
            lenses.append({
                'range': range_,
                'command': {
                    'title': ('1 reference' if count == 1
                              else f'{count} references'),
                    'command': 'editor.action.showReferences',
                    'arguments': [
                        doc.uri,
                        {'line': range_['start']['line'],
                         'character': range_['start']['character']},
                        locations,
                    ],
                },
            })
        return lenses

    def _reference_uses(self, project: _ProjectIndex) -> dict[tuple, list]:
        """Every use of every symbol in the project, keyed by symbol."""
        uses: dict[tuple, list] = {}
        seen: set[tuple[str, int, int]] = set()
        modules = list(project.cache.values())
        if project.current not in modules:
            modules.append(project.current)
        for module in modules:
            walker = _ReferenceWalker(module, project)
            for ref in walker.refs:
                if ref.declaration:
                    continue
                key = (ref.path, ref.line, ref.col)
                if key in seen:
                    continue
                seen.add(key)
                uses.setdefault(ref.symbol, []).append(ref)
        return uses

    def _decl_name_range(self, module: ModuleInfo,
                         decl: DeclInfo) -> Optional[dict]:
        lines = _lines(module.source)
        line = decl.name_line or decl.line
        if line < 1 or line > len(lines):
            return None
        line_text = lines[line - 1]
        index = max(0, (decl.name_col or 1) - 1)
        if line_text[index:index + len(decl.name)] != decl.name:
            found = line_text.find(decl.name)
            if found < 0:
                return None
            index = found
        start = _py_to_lsp_char(line_text, index)
        return {
            'start': {'line': line - 1, 'character': start},
            'end': {'line': line - 1,
                    'character': start + _utf16_len(decl.name)},
        }

    def _ref_location(self, project: _ProjectIndex, ref) -> Optional[dict]:
        module = project.cache.get(_norm_path(ref.path))
        if module is None:
            module = project.current if ref.path == project.current.path else None
        if module is None:
            return None
        try:
            uri = path_to_uri(ref.path)
        except (ValueError, OSError):
            return None
        line_text = _line_at(_lines(module.source), ref.line - 1)
        start = _py_to_lsp_char(line_text, ref.col - 1)
        return {
            'uri': uri,
            'range': {
                'start': {'line': ref.line - 1, 'character': start},
                'end': {'line': ref.line - 1,
                        'character': start + _utf16_len(ref.name)},
            },
        }

    # -- document highlight -------------------------------------------------

    def _document_highlight(self, params: dict) -> list[dict]:
        """Highlight every occurrence of the symbol under the cursor."""
        doc = self._doc(params)
        if doc is None or not doc.text:
            return []
        target = self._reference_target(params)
        if target is not None:
            doc_path = _norm_path(doc.path)
            highlights: list[dict] = []
            seen: set[tuple[int, int]] = set()
            walker = _ReferenceWalker(target['module'], target['project'])
            for ref in walker.refs:
                if ref.symbol != target['symbol']:
                    continue
                if _norm_path(ref.path) != doc_path:
                    continue
                key = (ref.line, ref.col)
                if key in seen:
                    continue
                seen.add(key)
                highlights.append({
                    'range': self._ref_range(target, ref),
                    'kind': 1 if ref.declaration else 2,
                })
            if highlights:
                return highlights
        # Fall back to every textual occurrence of the word under the cursor.
        lines = _lines(doc.text)
        pos = params.get('position') or {}
        line = max(0, min(int(pos.get('line', 0)), len(lines) - 1))
        char = max(0, int(pos.get('character', 0)))
        word, _, _ = _word_at(lines[line], char)
        if not word:
            return []
        pattern = re.compile(r'\b' + re.escape(word) + r'\b')
        highlights = []
        for line_number, text in enumerate(lines):
            for match in pattern.finditer(text):
                start = _py_to_lsp_char(text, match.start())
                end = _py_to_lsp_char(text, match.end())
                highlights.append({
                    'range': {
                        'start': {'line': line_number,
                                  'character': start},
                        'end': {'line': line_number, 'character': end},
                    },
                    'kind': 1,
                })
        return highlights

    # -- document links ----------------------------------------------------

    def _document_links(self, params: dict) -> list[dict]:
        """Make every import path a link to the file it names."""
        doc = self._doc(params)
        if doc is None or not doc.text:
            return []
        project = self._project(doc)
        lines = _lines(doc.text)
        links: list[dict] = []
        for imp in project.current.imports:
            line_text = _line_at(lines, imp.line - 1)
            span = _quoted_span(line_text, imp.path)
            if span is None:
                continue
            start, end = span
            start_char = _py_to_lsp_char(line_text, start)
            end_char = _py_to_lsp_char(line_text, end)
            link: dict = {
                'range': {
                    'start': {'line': imp.line - 1,
                              'character': start_char},
                    'end': {'line': imp.line - 1,
                            'character': end_char},
                },
            }
            target = imp.target
            if target is not None and target.path != '<untitled>':
                try:
                    link['target'] = path_to_uri(target.path)
                except (ValueError, OSError):
                    pass
                link['tooltip'] = target.path
            else:
                link['tooltip'] = 'unresolved import: ' + imp.path
            links.append(link)
        return links

    # -- folding ranges ----------------------------------------------------

    def _type_definition(self, params: dict) -> Optional[list[dict]]:
        doc = self._doc(params)
        if doc is None or not doc.text:
            return None
        pos = params.get('position') or {}
        line, char = _position_to_py(doc.text, pos.get('line', 0),
                                     pos.get('character', 0))
        lines = _lines(doc.text)
        line_text = _line_at(lines, line)
        lsp_char = _to_lsp(line_text, char)
        word, start, _ = _word_at(line_text, lsp_char)
        if not word:
            return None
        project = self._project(doc)
        locals_ = project.local_symbols(line, lsp_char)
        decl = None
        type_decl = project.type_by_name(word)
        if type_decl is not None:
            decl = type_decl
        elif word in locals_:
            type_name = _base_type_name(locals_[word].type_name)
            if type_name:
                decl = project.type_by_name(type_name)
        else:
            object_path = _object_before_dot(
                line_text, _lsp_to_py_char(line_text, start))
            if object_path is not None:
                # Resolve the type that owns the member under the cursor.
                owner_name = object_path[0]
                local_type = locals_.get(owner_name, None).type_name if (
                    owner_name in locals_) else None
                type_name = (_base_type_name(local_type)
                            if local_type else owner_name)
                owner = project.type_by_name(type_name)
                for comp in object_path[1:]:
                    if owner is None or owner.kind not in ('struct', 'enum'):
                        owner = None
                        break
                    matched = None
                    for fld in owner.fields:
                        if fld.name == comp:
                            matched = fld
                            break
                    if matched is None:
                        owner = None
                        break
                    tn = _base_type_name(matched.type_name)
                    owner = project.type_by_name(tn) if tn else None
                if owner is not None and owner.kind in ('struct', 'enum'):
                    for fld in owner.fields:
                        if fld.name == word:
                            tn = _base_type_name(fld.type_name)
                            cand = project.type_by_name(tn) if tn else None
                            if cand is not None:
                                decl = cand
                            break
        if decl is None:
            return None
        return [{
            'uri': path_to_uri(decl.path),
            'range': _range(decl.line, decl.col, decl.line,
                             decl.col + len(decl.name)),
        }]

    def _folding_ranges(self, params: dict) -> list[dict]:
        """Fold the indentation blocks, comment runs, and imports."""
        doc = self._doc(params)
        if doc is None or not doc.text:
            return []
        lines = _lines(doc.text)
        ranges: list[dict] = []
        stack: list[tuple[int, int]] = []
        last_nonblank = -1
        for number, text in enumerate(lines):
            stripped = text.strip()
            if not stripped:
                continue
            indent = len(text) - len(text.lstrip(' '))
            while stack and stack[-1][0] >= indent:
                start = stack.pop()[1]
                if last_nonblank > start:
                    ranges.append({'startLine': start,
                                   'endLine': last_nonblank})
            if not stripped.startswith('#'):
                stack.append((indent, number))
            last_nonblank = number
        while stack:
            start = stack.pop()[1]
            if last_nonblank > start:
                ranges.append({'startLine': start,
                               'endLine': last_nonblank})
        ranges.extend(_comment_folds(lines))
        ranges.extend(_import_folds(lines))
        ranges.sort(key=lambda item: (item['startLine'],
                                      item['endLine'],
                                      item.get('kind', '')))
        return ranges

    # -- selection ranges ----------------------------------------------------

    def _selection_ranges(self, params: dict) -> list[dict]:
        """Selection ranges: word, line, enclosing blocks, whole file."""
        doc = self._doc(params)
        if doc is None or not doc.text:
            return []
        pos = params.get('position') or {}
        line = max(0, min(int(pos.get('line', 0)),
                          len(_lines(doc.text)) - 1))
        char = max(0, int(pos.get('character', 0)))
        lines = _lines(doc.text)
        line_text = _line_at(lines, line)
        last_line = len(lines) - 1
        ranges: list[dict] = []
        word, wstart, wend = _word_at(line_text, char)
        if word:
            ranges.append({'start': {'line': line, 'character': wstart},
                           'end': {'line': line, 'character': wend}})
        line_end = _py_to_lsp_char(line_text, len(line_text))
        if line_end:
            line_range = {'start': {'line': line, 'character': 0},
                          'end': {'line': line, 'character': line_end}}
            if not ranges or ranges[-1] != line_range:
                ranges.append(line_range)
        cursor_indent = len(line_text) - len(line_text.lstrip(' '))
        block_min = cursor_indent
        for i in range(line - 1, -1, -1):
            if not lines[i].strip():
                continue
            indent_i = len(lines[i]) - len(lines[i].lstrip(' '))
            if indent_i < block_min:
                block_min = indent_i
                end = self._block_end(lines, i, indent_i)
                brange = {'start': {'line': i, 'character': 0},
                          'end': {'line': end,
                                  'character': _py_to_lsp_char(lines[end],
                                                             len(lines[end]))}}
                if not ranges or ranges[-1] != brange:
                    ranges.append(brange)
        file_range = {'start': {'line': 0, 'character': 0},
                      'end': {'line': last_line,
                              'character': _py_to_lsp_char(
                                  lines[last_line], len(lines[last_line]))}}
        if not ranges or ranges[-1] != file_range:
            ranges.append(file_range)
        return ranges

    @staticmethod
    def _block_end(lines: list[str], header: int, indent: int) -> int:
        end = header
        for i in range(header + 1, len(lines)):
            if not lines[i].strip():
                continue
            if len(lines[i]) - len(lines[i].lstrip(' ')) <= indent:
                break
            end = i
        return end

    # -- document symbols --------------------------------------------------

    def _document_symbols(self, params: dict) -> list[dict]:
        doc = self._doc(params)
        if doc is None:
            return []
        project = self._project(doc)
        lines = _lines(doc.text)
        symbols: list[dict] = []
        for decl in project.current.decls:
            kind = {
                'func': S_FUNCTION,
                'struct': S_STRUCT,
                'enum': S_ENUM,
                'const': S_CONSTANT,
            }.get(decl.kind, S_VARIABLE)
            symbol = {
                'name': decl.name,
                'detail': decl.detail,
                'kind': kind,
                'range': _range(
                    decl.line, decl.col, decl.end_line or decl.line,
                    _line_end(decl.end_line or decl.line, 1, lines)),
                'selectionRange': _range(
                    decl.name_line or decl.line, decl.name_col or decl.col,
                    decl.name_line or decl.line,
                    _line_end(decl.name_line or decl.line,
                              decl.name_col or decl.col, lines)),
            }
            children: list[dict] = []
            for fld in decl.fields:
                children.append({
                    'name': fld.name,
                    'detail': fld.detail,
                    'kind': S_FIELD,
                    'range': _range(fld.line, fld.col, fld.line,
                                    _line_end(fld.line, fld.col, lines)),
                    'selectionRange': _range(fld.line, fld.col, fld.line,
                                             _line_end(fld.line, fld.col,
                                                       lines)),
                })
            for member in decl.members:
                children.append({
                    'name': member.name,
                    'detail': member.detail,
                    'kind': S_ENUM_MEMBER,
                    'range': _range(member.line, member.col, member.line,
                                    _line_end(member.line, member.col,
                                              lines)),
                    'selectionRange': _range(
                        member.line, member.col, member.line,
                        _line_end(member.line, member.col, lines)),
                })
            if children:
                symbol['children'] = children
            symbols.append(symbol)
        return symbols


# ---------------------------------------------------------------------------
# Small shared helpers for the server
# ---------------------------------------------------------------------------


def _to_lsp(line_text: str, index: int) -> int:
    return _py_to_lsp_char(line_text, index)


def _completion_word_start(line_text: str, index: int) -> int:
    """Start of the identifier being typed at a Python index."""
    index = max(0, min(index, len(line_text)))
    while index > 0 and (line_text[index - 1].isalnum()
                         or line_text[index - 1] == '_'):
        index -= 1
    return index


def _word_edit(line: int, line_text: str, word_start: int) -> dict:
    start = _lsp_to_py_char(line_text, word_start)
    word_end = start
    while word_end < len(line_text) and (line_text[word_end].isalnum()
                                         or line_text[word_end] == '_'):
        word_end += 1
    return {
        'range': {
            'start': {'line': line, 'character': word_start},
            'end': {'line': line,
                    'character': _py_to_lsp_char(line_text, word_end)},
        },
    }


def _item(label: str, kind: int, detail: str, edit: dict,
          insert_text: Optional[str] = None, snippet: bool = False,
          sort: str = '') -> dict:
    item: dict = {
        'label': label,
        'kind': kind,
        'detail': detail or label,
        'filterText': label,
        'sortText': sort or label.lower(),
        'textEdit': {
            'range': edit['range'],
            'newText': insert_text if insert_text is not None else label,
        },
    }
    if snippet:
        item['insertTextFormat'] = 2
    return item


def _decl_item(decl: DeclInfo, edit: dict, priority: str) -> dict:
    kind = {
        'func': K_FUNCTION,
        'struct': K_STRUCT,
        'enum': K_ENUM,
        'const': K_CONSTANT,
    }.get(decl.kind, K_VARIABLE)
    return _item(decl.name, kind, decl.detail, edit,
                 sort=f'{priority}_{decl.name.lower()}')


def _dedupe_completion(items: list[dict]) -> list[dict]:
    seen = set()
    result = []
    for item in sorted(items, key=lambda i: (i.get('sortText', ''),
                                             i['label'].lower())):
        if item['label'] in seen:
            continue
        seen.add(item['label'])
        result.append(item)
    return result


def _payload_name(payload_type: str) -> str:
    name = _base_type_name(payload_type)
    name = re.sub(r'\W+', '', name)
    return name.lower() or 'value'


def _decl_location(decl: DeclInfo) -> list[dict]:
    return [decl.location()]


def _line_end(line: int, col: int, lines: list[str]) -> int:
    text = _line_at(lines, max(0, line - 1))
    return max(col, _utf16_len(text) + 1)


def _error_location(exc: Exception, fallback: str) \
        -> tuple[Optional[str], int, int]:
    filename = getattr(exc, 'filename', None)
    line = getattr(exc, 'line', None)
    col = getattr(exc, 'col', None)
    pos = getattr(exc, 'pos', None)
    if pos is not None:
        # The type checker keeps the entry filename, so a diagnostic from an
        # imported file is only identified by Pos.file.
        filename = getattr(pos, 'file', None) or filename
        if line is None:
            line = getattr(pos, 'line', None)
        if col is None:
            col = getattr(pos, 'col', None)
    if filename is None:
        filename = fallback
    return filename, int(line or 1), int(col or 1)


def _error_range(path: str, line: int, col: int,
                 sources: dict[str, str]) -> dict:
    text = sources.get(path)
    if text is None:
        try:
            with open(path, 'r', encoding='utf-8-sig') as f:
                text = f.read()
        except (OSError, UnicodeError):
            text = ''
    lines = _lines(text)
    line = max(1, min(line, len(lines)))
    line_text = _line_at(lines, line - 1)
    start = max(0, min(col - 1, len(line_text)))
    end = start
    while end < len(line_text) and (line_text[end].isalnum()
                                    or line_text[end] == '_'):
        end += 1
    if end == start and start < len(line_text):
        end += 1
    if end == start and start > 0:
        # An error at the end of a line should still underline something.
        start -= 1
        end = len(line_text)
    return {
        'start': {'line': line - 1,
                  'character': _py_to_lsp_char(line_text, start)},
        'end': {'line': line - 1,
                'character': _py_to_lsp_char(line_text, end)},
    }


# ---------------------------------------------------------------------------
# stdio transport
# ---------------------------------------------------------------------------


def _read_message(reader) -> Optional[dict]:
    headers: dict[str, str] = {}
    while True:
        line = reader.readline()
        if not line:
            return None
        if isinstance(line, bytes):
            line = line.decode('ascii', 'replace')
        line = line.rstrip('\r\n')
        if not line:
            break
        if ':' in line:
            key, value = line.split(':', 1)
            headers[key.strip().lower()] = value.strip()
    raw_length = headers.get('content-length')
    if raw_length is None:
        return None
    try:
        length = int(raw_length)
    except ValueError:
        return None
    body = reader.read(length)
    if isinstance(body, str):
        body = body.encode('utf-8')
    try:
        return json.loads(body.decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


def _write_message(writer, message: dict) -> None:
    payload = json.dumps(message, separators=(',', ':')).encode('utf-8')
    header = f'Content-Length: {len(payload)}\r\n\r\n'.encode('ascii')
    writer.write(header)
    writer.write(payload)
    writer.flush()


def run_stdio() -> int:
    """Run the language server on stdin/stdout."""
    LanguageServer().serve()
    return 0
