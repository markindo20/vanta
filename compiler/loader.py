"""Import expansion: parse a source file and everything it imports.

Vanta has a single flat namespace, so importing a file merges its top-level
declarations into the importing program — dependencies are expanded first, so
a declaration's imports (and their imports) always precede it in the merged
program. Each file is loaded once (keyed by its real path), so diamonds are
fine; cycles are reported as errors. An import path is resolved relative to
the file that contains the import statement.

Every node is stamped with the path of the file it came from (see
`Pos.file`), so type errors in imported files name the file that actually
contains the problem instead of the entry file.
"""

import os
from dataclasses import fields, is_dataclass

from . import ast_nodes as A
from .lexer import Lexer
from .parser import Parser


class LoadError(Exception):
    """A file could not be read, an import target is missing, or a cycle exists."""

    def __init__(self, msg, filename=None, pos=None):
        self.msg = msg
        self.filename = filename
        self.pos = pos
        if filename is None:
            super().__init__(msg)
        elif pos is not None:
            super().__init__(f"{filename}:{pos.line}:{pos.col}: {msg}")
        else:
            super().__init__(f"{filename}: {msg}")


def _stamp(node, filename):
    if isinstance(node, A.Pos):
        node.file = filename
        return
    if isinstance(node, list):
        for item in node:
            _stamp(item, filename)
        return
    if node is None or not is_dataclass(node):
        return
    pos = getattr(node, 'pos', None)
    if isinstance(pos, A.Pos):
        pos.file = filename
    for f in fields(node):
        if f.name != 'pos':
            _stamp(getattr(node, f.name), filename)


class _Loader:
    def __init__(self):
        self._done = set()   # real paths of fully loaded files
        self._active = []    # [(real path, display path)] of files in progress

    def load(self, entry_path):
        return self._load(entry_path, None, None)

    def _load(self, path, importer, pos):
        real = os.path.realpath(path)
        for i, (r, _display) in enumerate(self._active):
            if r == real:
                chain = [d for _r, d in self._active[i:]] + [path]
                raise LoadError('import cycle: ' + ' -> '.join(chain), importer, pos)
        if real in self._done:
            return []
        try:
            with open(path, 'r', encoding='utf-8') as f:
                src = f.read()
        except OSError:
            if importer is None:
                raise LoadError(f"cannot open '{path}'")
            raise LoadError(f"cannot open import '{path}'", importer, pos)

        program = Parser(Lexer(src, path).tokenize(), path).parse_program()
        _stamp(program, path)

        self._active.append((real, path))
        decls = []
        for d in program.decls:
            if isinstance(d, A.ImportDecl):
                target = os.path.normpath(os.path.join(os.path.dirname(path), d.path))
                decls.extend(self._load(target, path, d.pos))
            else:
                decls.append(d)
        self._active.pop()
        self._done.add(real)
        return decls


def load_program(entry_path):
    """Parse entry_path and its imports into one Program, dependencies first."""
    return A.Program(_Loader().load(entry_path))
