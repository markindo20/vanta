"""A small Language Server Protocol implementation for Vanta.

The language server deliberately reuses the real lexer, parser, loader, and
type checker for diagnostics.  Completion and navigation are backed by a
tolerant source index built from the same AST, with a line-based fallback for
the very common case where the user is in the middle of typing and the buffer
does not parse yet.

Only the pieces of LSP that the VS Code client needs are implemented:
document sync, diagnostics, completion, hover, go-to-definition, and document
symbols.  The server speaks JSON-RPC over stdin/stdout with the usual
``Content-Length`` framing.
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any, Optional
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

from . import VERSION
from . import ast_nodes as A
from .lexer import LexError, Lexer
from .loader import LoadError, STDLIB_DIR, load_program
from .parser import ParseError, Parser
from .tokens import KEYWORDS
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
    idx = line.find(name, start)
    if idx < 0:
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
        self.current = self._load(entry_path, [])

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
        self._finish_ranges(mod.decls, source_lines)
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
                    for fname, ftype, fpos in d.fields
                ]
                keyword = 'component' if d.is_component else 'struct'
                details = ', '.join(f'{f.name}: {f.type_name}' for f in fields)
                decls.append(DeclInfo(
                    name=d.name, kind='struct',
                    detail=f'{keyword} {d.name}' + (f' {{ {details} }}'
                                                     if details else ''),
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
                    'hoverProvider': True,
                    'definitionProvider': True,
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
        elif method == 'textDocument/hover':
            self._response(msg_id, self._hover(params))
        elif method == 'textDocument/definition':
            self._response(msg_id, self._definition(params))
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
                # Full sync: use the final change. If a client sends range
                # changes anyway, fall back to replacing the whole document
                # only when text is present.
                doc.text = _strip_bom(changes[-1].get('text', doc.text))
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
        index = _completion_word_start(line_text, char)
        word_start = _py_to_lsp_char(line_text, index)
        object_path = _object_before_dot(line_text, index)
        project = self._project(doc)
        locals_ = project.local_symbols(line, _to_lsp(line_text, char))

        items: list[dict] = []
        if object_path is not None:
            items.extend(self._member_completions(
                project, object_path, locals_, line, line_text, word_start))
        else:
            items.extend(self._general_completions(
                project, locals_, line, line_text, word_start))
        return _dedupe_completion(items)

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
        word, start, end = _word_at(line_text, _to_lsp(line_text, char))
        if not word:
            return None
        project = self._project(doc)
        locals_ = project.local_symbols(line, _to_lsp(line_text, char))
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
        word, start, _ = _word_at(line_text, _to_lsp(line_text, char))
        if not word:
            return None
        project = self._project(doc)
        locals_ = project.local_symbols(line, _to_lsp(line_text, char))
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
