"""Parse a source file, expand imports, and resolve module boundaries.

Vanta still has one flat C++ namespace, but source files can now opt into
module scope:

    module math

    pub func add(a: i32, b: i32) -> i32:
        return a + b

Imports keep the existing path form. A plain import brings a module's public
names into the importing file, while ``import "math.vnt" as math`` exposes them
through the alias (``math.add``). Files without a ``module`` declaration keep
the original flat, all-public behaviour, so existing programs and the game kit
continue to work unchanged.

The resolver gives every module-scoped declaration a unique internal name
before type checking. That keeps the type checker and C++ backend flat while
still allowing two modules to define the same source name.
"""

import os
from dataclasses import dataclass, fields, is_dataclass

from . import ast_nodes as A
from .lexer import Lexer
from .parser import Parser


_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_HERE)


def _first_existing_dir(*candidates):
    for candidate in candidates:
        if os.path.isdir(candidate):
            return candidate
    return None


def _source_key(path):
    """Stable key for in-memory source overlays.

    The editor can hold unsaved text for any file in a project, so the loader
    accepts a path -> source map. Keys are normalized the same way as import
    deduplication uses: real paths, case-folded on Windows.
    """
    return os.path.normcase(os.path.realpath(path))


# A wheel ships the standard library beside the compiler modules; a checkout
# keeps it at the repository root.
STDLIB_DIR = _first_existing_dir(
    os.path.join(_HERE, 'templates', 'stdlib'),
    os.path.join(_REPO_ROOT, 'stdlib'),
)


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


@dataclass
class _Symbol:
    name: str          # source name
    internal: str      # unique name seen by the type checker and codegen
    kind: str          # 'func', 'type', or 'const'
    public: bool
    module: '_Module'
    decl: object = None


class _Module:
    def __init__(self, path, real, declared_name=None, is_entry=False,
                 module_pos=None):
        self.path = path
        self.real = real
        self.declared_name = declared_name
        self.is_entry = is_entry
        self.module_pos = module_pos
        self.decls = []
        self.imports = []       # [(A.ImportDecl, _Module)]
        self.symbols = {}       # source name -> _Symbol
        self.imported = {}      # source name -> [_Symbol]
        self.aliases = {}       # alias -> _Module
        self.prefix = ''

    @property
    def is_legacy(self):
        return self.declared_name is None

    @property
    def display_name(self):
        return self.declared_name or os.path.basename(self.path)


class _Loader:
    def __init__(self, sources=None):
        self._modules = {}      # real path -> _Module
        self._active = []       # [(real path, display path)] in progress
        self._order = []        # modules in dependency-first order
        self._module_names = {} # declared name -> (real, path, pos)
        self._sources = {
            _source_key(path): text
            for path, text in (sources or {}).items()
        }

    def load(self, entry_path):
        self._load(entry_path, None, None)
        return self._order

    def _exists(self, path):
        return _source_key(path) in self._sources or os.path.exists(path)

    def _read(self, path):
        key = _source_key(path)
        if key in self._sources:
            return self._sources[key]
        with open(path, 'r', encoding='utf-8-sig') as f:
            return f.read()

    def _load(self, path, importer, pos):
        real = os.path.realpath(path)
        for i, (r, _display) in enumerate(self._active):
            if r == real:
                chain = [d for _r, d in self._active[i:]] + [path]
                raise LoadError('import cycle: ' + ' -> '.join(chain),
                                importer, pos)
        if real in self._modules:
            return self._modules[real]

        try:
            src = self._read(path)
        except (OSError, UnicodeError):
            if importer is None:
                raise LoadError(f"cannot open '{path}'")
            raise LoadError(f"cannot open import '{path}'", importer, pos)

        program = Parser(Lexer(src, path).tokenize(), path).parse_program()
        _stamp(program, path)

        module_decl = None
        decls = []
        imports = []
        for i, d in enumerate(program.decls):
            if isinstance(d, A.ModuleDecl):
                if module_decl is not None:
                    raise LoadError('only one module declaration is allowed',
                                    path, d.pos)
                if i != 0:
                    raise LoadError(
                        'a module declaration must be the first declaration '
                        'in a file', path, d.pos)
                module_decl = d
            elif isinstance(d, A.ImportDecl):
                imports.append(d)
            else:
                decls.append(d)

        name = module_decl.name if module_decl is not None else None
        if name is not None:
            previous = self._module_names.get(name)
            if previous is not None and previous[0] != real:
                raise LoadError(
                    f"module '{name}' is already defined in '{previous[1]}'",
                    path, module_decl.pos)
            self._module_names[name] = (real, path, module_decl.pos)

        mod = _Module(path, real, name, importer is None,
                      module_decl.pos if module_decl is not None else None)
        mod.decls = decls
        self._modules[real] = mod

        self._active.append((real, path))
        try:
            for imp in imports:
                target = self._import_target(path, imp)
                child = self._load(target, path, imp.pos)
                mod.imports.append((imp, child))
        finally:
            self._active.pop()

        self._order.append(mod)
        return mod

    def _import_target(self, path, imp):
        """Resolve an import relative to the importer, then the stdlib.

        `std/...` is the only special prefix. An actual sibling file with the
        same path wins, so projects can vendor their own copy. In-memory
        overlays count as existing files, which lets unsaved editor buffers
        take part in normal import resolution.
        """
        target = os.path.normpath(
            os.path.join(os.path.dirname(path), imp.path))
        if self._exists(target) or STDLIB_DIR is None:
            return target
        rel = imp.path.replace('\\', '/')
        if rel.startswith('std/'):
            candidate = os.path.normpath(
                os.path.join(STDLIB_DIR, rel[len('std/'):]))
            if self._exists(candidate):
                return candidate
        return target


class _Scopes:
    """Local names visible at a point in a function body."""

    def __init__(self):
        self.stack = [set()]

    def push(self, names=()):
        self.stack.append(set(names))

    def pop(self):
        self.stack.pop()

    def add(self, name):
        self.stack[-1].add(name)

    def has(self, name):
        return any(name in scope for scope in reversed(self.stack))


class _Resolver:
    def __init__(self, modules):
        self.modules = modules
        self.display_names = {}
        self.legacy_global = {}

    def resolve(self):
        self._collect_symbols()
        self._build_imports()
        for mod in self.modules:
            self._resolve_module(mod)

        decls = []
        for mod in self.modules:
            decls.extend(mod.decls)
        private_types = {
            sym.internal
            for mod in self.modules
            for sym in mod.symbols.values()
            if sym.kind == 'type' and not sym.public
        }
        return A.Program(decls, self.display_names, private_types)

    # -- symbol collection -------------------------------------------------

    def _collect_symbols(self):
        for mod in self.modules:
            mod.prefix = ('' if mod.is_legacy
                          else f'vanta_m_{mod.declared_name}__')
            for d in mod.decls:
                if isinstance(d, A.FuncDecl):
                    source = d.name
                    internal = ('main' if mod.is_entry and source == 'main'
                                else mod.prefix + source)
                    self._add_symbol(mod, source, internal, 'func',
                                     mod.is_legacy or d.is_public, d, d.pos)
                    d.name = internal
                elif isinstance(d, A.StructDecl):
                    source = d.name
                    internal = mod.prefix + source
                    self._add_symbol(mod, source, internal, 'type',
                                     mod.is_legacy or d.is_public, d, d.pos)
                    d.name = internal
                elif isinstance(d, A.EnumDecl):
                    source = d.name
                    internal = mod.prefix + source
                    self._add_symbol(mod, source, internal, 'type',
                                     mod.is_legacy or d.is_public, d, d.pos)
                    d.name = internal
                elif isinstance(d, A.ConstDecl):
                    source = d.name
                    internal = mod.prefix + source
                    self._add_symbol(mod, source, internal, 'const',
                                     mod.is_legacy or d.is_public, d, d.pos)
                    d.name = internal
                elif isinstance(d, A.ExternDecl):
                    for fd in d.funcs:
                        # Extern functions keep their C names. The C ABI is
                        # deliberately global even when the declaration lives
                        # in a module.
                        self._add_symbol(mod, fd.name, fd.name, 'func',
                                         mod.is_legacy or d.is_public, fd, fd.pos)

        # Legacy files shared one flat namespace. Keep that behaviour for
        # them even when a name reaches the program through a sibling import
        # rather than a direct one.
        for mod in self.modules:
            if not mod.is_legacy:
                continue
            for sym in mod.symbols.values():
                self.legacy_global.setdefault(sym.name, []).append(sym)

    def _add_symbol(self, mod, source, internal, kind, public, decl, pos):
        if source in mod.symbols:
            raise LoadError(
                f"duplicate declaration '{source}' in module "
                f"'{mod.display_name}'", self._where(mod, pos), pos)
        sym = _Symbol(source, internal, kind, public, mod, decl)
        mod.symbols[source] = sym
        if internal != source:
            self.display_names[internal] = source

    # -- imports and visibility -------------------------------------------

    @staticmethod
    def _where(mod, pos):
        return getattr(pos, 'file', None) or mod.path

    def _flat_export_symbols(self, target, seen=None):
        """Symbols an unaliased import of *target* adds to the bare namespace.

        A legacy target keeps the old transitive, flat import shape: its own
        unaliased imports were already part of its namespace, so an importer
        sees those names too. A declared module exports only its own public
        declarations; its imports stay scoped.
        """
        if seen is None:
            seen = set()
        if target.real in seen:
            return
        seen.add(target.real)
        for sym in target.symbols.values():
            if not sym.public:
                continue
            # A declared module's `main` stays behind its module name, both
            # for direct imports and when a legacy file imports it.
            if (sym.kind == 'func' and sym.name == 'main'
                    and not target.is_legacy):
                continue
            yield sym
        if not target.is_legacy:
            return
        for imp, child in target.imports:
            if imp.alias is None:
                yield from self._flat_export_symbols(child, seen)

    def _build_imports(self):
        for mod in self.modules:
            aliases = set()
            for imp, target in mod.imports:
                if imp.alias is not None:
                    alias = imp.alias
                    if alias in aliases:
                        raise LoadError(
                            f"duplicate import alias '{alias}'",
                            mod.path, imp.pos)
                    if alias in mod.symbols:
                        raise LoadError(
                            f"import alias '{alias}' collides with a "
                            f"declaration in this module", mod.path, imp.pos)
                    aliases.add(alias)
                    mod.aliases[alias] = target
                    continue

                for sym in self._flat_export_symbols(target):
                    name = sym.name
                    if name in mod.symbols:
                        raise LoadError(
                            f"imported name '{name}' conflicts with a "
                            f"declaration in this module; use an import alias",
                            mod.path, imp.pos)
                    bucket = mod.imported.setdefault(name, [])
                    if any(old is sym for old in bucket):
                        continue
                    if bucket and (target.is_legacy
                                   or any(old.module.is_legacy
                                          for old in bucket)):
                        # Keep the old flat-import rule: a legacy file
                        # cannot silently collide with another import.
                        raise LoadError(
                            f"imported name '{name}' is declared in multiple "
                            f"files", mod.path, imp.pos)
                    bucket.append(sym)

    def _lookup_global(self, mod, name, pos):
        sym = mod.symbols.get(name)
        if sym is not None:
            return sym
        candidates = list(mod.imported.get(name, []))
        if mod.is_legacy:
            candidates.extend(self.legacy_global.get(name, []))
        unique = {sym.internal: sym for sym in candidates}
        if len(unique) == 1:
            return next(iter(unique.values()))
        if len(unique) > 1:
            owners = ', '.join(sorted(sym.module.display_name
                                      for sym in unique.values()))
            raise LoadError(
                f"ambiguous name '{name}' imported from {owners}; "
                f"qualify it with an import alias", self._where(mod, pos), pos)
        return None

    def _lookup_qualified(self, mod, alias, name, pos):
        target = mod.aliases.get(alias)
        if target is None:
            return None
        sym = target.symbols.get(name)
        if sym is None:
            raise LoadError(
                f"module alias '{alias}' has no symbol '{name}'",
                self._where(mod, pos), pos)
        if not sym.public:
            raise LoadError(
                f"symbol '{name}' is private to module "
                f"'{target.display_name}'", self._where(mod, pos), pos)
        return sym

    # -- declaration and body resolution ----------------------------------

    def _resolve_module(self, mod):
        scopes = _Scopes()
        for d in mod.decls:
            self._resolve_decl_types(d, mod)
            self._check_public_types(d, mod)
            if isinstance(d, A.FuncDecl):
                self._resolve_func_body(d, mod, scopes)
            elif isinstance(d, A.ConstDecl):
                scopes.push()
                d.value = self._resolve_expr(d.value, mod, scopes)
                scopes.pop()

    def _resolve_decl_types(self, d, mod):
        if isinstance(d, A.FuncDecl):
            for p in d.params:
                self._resolve_type(p.type, mod)
            if d.ret is not None:
                self._resolve_type(d.ret, mod)
        elif isinstance(d, A.StructDecl):
            type_params = set(getattr(d, 'type_params', ()))
            for (_name, ftype, _pos) in d.fields:
                self._resolve_type(ftype, mod, type_params=type_params)
        elif isinstance(d, A.EnumDecl):
            type_params = set(d.type_params)
            for member in d.members:
                for te in (member.payload or []):
                    self._resolve_type(te, mod, type_params=type_params)
        elif isinstance(d, A.ConstDecl):
            if d.type_ann is not None:
                self._resolve_type(d.type_ann, mod)
        elif isinstance(d, A.ExternDecl):
            for fd in d.funcs:
                for p in fd.params:
                    self._resolve_type(p.type, mod)
                if fd.ret is not None:
                    self._resolve_type(fd.ret, mod)

    def _decl_type_exprs(self, d):
        if isinstance(d, A.FuncDecl):
            for p in d.params:
                yield p.type
            if d.ret is not None:
                yield d.ret
        elif isinstance(d, A.StructDecl):
            for (_name, ftype, _pos) in d.fields:
                yield ftype
        elif isinstance(d, A.EnumDecl):
            for member in d.members:
                for te in (member.payload or []):
                    yield te
        elif isinstance(d, A.ConstDecl):
            if d.type_ann is not None:
                yield d.type_ann
        elif isinstance(d, A.ExternDecl):
            for fd in d.funcs:
                for p in fd.params:
                    yield p.type
                if fd.ret is not None:
                    yield fd.ret

    def _walk_type_exprs(self, te):
        if te is None:
            return
        if te.kind in ('ptr', 'array', 'list'):
            yield from self._walk_type_exprs(te.inner)
        elif te.kind == 'func':
            for p in (te.params or []):
                yield from self._walk_type_exprs(p)
            yield from self._walk_type_exprs(te.inner)
        elif te.kind == 'named':
            yield te
            for arg in (te.args or []):
                yield from self._walk_type_exprs(arg)

    def _check_public_types(self, d, mod):
        if mod.is_legacy or not getattr(d, 'is_public', False):
            return
        private = {sym.internal for sym in mod.symbols.values()
                   if sym.kind == 'type' and not sym.public}
        if not private:
            return
        owner = 'extern block'
        internal_name = getattr(d, 'name', None)
        if internal_name is not None:
            owner = self.display_names.get(internal_name)
            if owner is None:
                for sym in mod.symbols.values():
                    if sym.internal == internal_name:
                        owner = sym.name
                        break
        owner = owner or 'declaration'
        for te in self._decl_type_exprs(d):
            for named in self._walk_type_exprs(te):
                if named.name not in private:
                    continue
                private_name = named.name
                for sym in mod.symbols.values():
                    if sym.internal == named.name:
                        private_name = sym.name
                        break
                raise LoadError(
                    f"public declaration '{owner}' exposes private type "
                    f"'{private_name}'", self._where(mod, named.pos),
                    named.pos)

    def _resolve_func_body(self, fn, mod, scopes):
        scopes.push()
        for p in fn.params:
            scopes.add(p.name)
        try:
            for stmt in fn.body:
                self._resolve_stmt(stmt, mod, scopes)
        finally:
            scopes.pop()

    def _resolve_stmt(self, stmt, mod, scopes):
        if isinstance(stmt, A.VarDecl):
            if stmt.type_ann is not None:
                self._resolve_type(stmt.type_ann, mod)
            stmt.value = self._resolve_expr(stmt.value, mod, scopes)
            scopes.add(stmt.name)
        elif isinstance(stmt, A.AssignStmt):
            stmt.target = self._resolve_expr(stmt.target, mod, scopes)
            stmt.value = self._resolve_expr(stmt.value, mod, scopes)
        elif isinstance(stmt, A.ReturnStmt):
            if stmt.value is not None:
                stmt.value = self._resolve_expr(stmt.value, mod, scopes)
        elif isinstance(stmt, A.IfStmt):
            stmt.cond = self._resolve_expr(stmt.cond, mod, scopes)
            scopes.push()
            for s in stmt.then_body:
                self._resolve_stmt(s, mod, scopes)
            scopes.pop()
            elifs = []
            for cond, body in stmt.elif_branches:
                cond = self._resolve_expr(cond, mod, scopes)
                scopes.push()
                for s in body:
                    self._resolve_stmt(s, mod, scopes)
                scopes.pop()
                elifs.append((cond, body))
            stmt.elif_branches = elifs
            if stmt.else_body is not None:
                scopes.push()
                for s in stmt.else_body:
                    self._resolve_stmt(s, mod, scopes)
                scopes.pop()
        elif isinstance(stmt, A.WhileStmt):
            stmt.cond = self._resolve_expr(stmt.cond, mod, scopes)
            scopes.push()
            for s in stmt.body:
                self._resolve_stmt(s, mod, scopes)
            scopes.pop()
        elif isinstance(stmt, A.ForRangeStmt):
            stmt.start = self._resolve_expr(stmt.start, mod, scopes)
            stmt.end = self._resolve_expr(stmt.end, mod, scopes)
            if stmt.step is not None:
                stmt.step = self._resolve_expr(stmt.step, mod, scopes)
            scopes.push((stmt.var,))
            for s in stmt.body:
                self._resolve_stmt(s, mod, scopes)
            scopes.pop()
        elif isinstance(stmt, A.ForEachStmt):
            stmt.iterable = self._resolve_expr(stmt.iterable, mod, scopes)
            scopes.push((stmt.var,))
            for s in stmt.body:
                self._resolve_stmt(s, mod, scopes)
            scopes.pop()
        elif isinstance(stmt, A.MatchStmt):
            stmt.value = self._resolve_expr(stmt.value, mod, scopes)
            for arm in stmt.arms:
                bindings = set()
                for pat in arm.patterns:
                    pat.enum_name = self._resolve_type_name(
                        mod, pat.enum_name, pat.pos)
                    for b in (pat.bindings or []):
                        if b != '_':
                            bindings.add(b)
                scopes.push(bindings)
                for s in arm.body:
                    self._resolve_stmt(s, mod, scopes)
                scopes.pop()
        elif isinstance(stmt, A.ExprStmt):
            stmt.expr = self._resolve_expr(stmt.expr, mod, scopes)

    def _resolve_expr(self, expr, mod, scopes):
        if isinstance(expr, A.Name):
            if scopes.has(expr.name):
                return expr
            sym = self._lookup_global(mod, expr.name, expr.pos)
            if sym is not None:
                expr.name = sym.internal
            return expr
        if isinstance(expr, A.Member):
            replacement = self._resolve_qualified_member(expr, mod, scopes)
            if replacement is not None:
                return replacement
            expr.obj = self._resolve_expr(expr.obj, mod, scopes)
            return expr
        if isinstance(expr, A.Call):
            expr.func = self._resolve_expr(expr.func, mod, scopes)
            expr.args = [self._resolve_expr(a, mod, scopes) for a in expr.args]
            if expr.type_args:
                for te in expr.type_args:
                    self._resolve_type(te, mod)
            return expr
        if isinstance(expr, A.BinOp):
            expr.left = self._resolve_expr(expr.left, mod, scopes)
            expr.right = self._resolve_expr(expr.right, mod, scopes)
            return expr
        if isinstance(expr, A.UnaryOp):
            expr.operand = self._resolve_expr(expr.operand, mod, scopes)
            return expr
        if isinstance(expr, A.Index):
            expr.obj = self._resolve_expr(expr.obj, mod, scopes)
            expr.index = self._resolve_expr(expr.index, mod, scopes)
            return expr
        if isinstance(expr, A.ArrayLit):
            expr.elements = [self._resolve_expr(e, mod, scopes)
                             for e in expr.elements]
            return expr
        return expr

    def _flatten_member(self, expr):
        parts = []
        node = expr
        while isinstance(node, A.Member):
            parts.append((node.field, node.pos))
            node = node.obj
        parts.reverse()
        return node, parts

    def _resolve_qualified_member(self, expr, mod, scopes):
        base, parts = self._flatten_member(expr)
        if not isinstance(base, A.Name) or scopes.has(base.name):
            return None
        if base.name not in mod.aliases:
            return None
        if not parts:
            return None

        first, first_pos = parts[0]
        sym = self._lookup_qualified(mod, base.name, first, first_pos)
        replacement = A.Name(sym.internal, first_pos)
        for field, field_pos in parts[1:]:
            replacement = A.Member(replacement, field, field_pos)
        return replacement

    def _resolve_type_name(self, mod, name, pos):
        if '.' in name:
            alias, rest = name.split('.', 1)
            if alias in mod.aliases:
                sym = self._lookup_qualified(mod, alias, rest, pos)
                if sym.kind != 'type':
                    raise LoadError(
                        f"'{name}' is not a type", self._where(mod, pos), pos)
                return sym.internal
            return name
        sym = self._lookup_global(mod, name, pos)
        if sym is not None and sym.kind == 'type':
            return sym.internal
        return name

    def _resolve_type(self, te, mod, type_params=None):
        if te is None:
            return
        type_params = type_params or set()
        if te.kind in ('ptr', 'array', 'list'):
            self._resolve_type(te.inner, mod, type_params)
            return
        if te.kind == 'func':
            for p in (te.params or []):
                self._resolve_type(p, mod, type_params)
            self._resolve_type(te.inner, mod, type_params)
            return
        if te.kind == 'named':
            for arg in (te.args or []):
                self._resolve_type(arg, mod, type_params)
            # A type parameter belongs to the enum being resolved; it is not
            # a module symbol and must be left for instantiation.
            if te.name not in type_params:
                te.name = self._resolve_type_name(mod, te.name, te.pos)


def load_program(entry_path, sources=None):
    """Parse entry_path and its imports into one resolved Program.

    `sources` optionally maps filesystem paths to unsaved source text. This is
    used by the language server so diagnostics reflect what is in the editor,
    not only what has been saved.
    """
    modules = _Loader(sources).load(entry_path)
    return _Resolver(modules).resolve()
