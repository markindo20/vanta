from . import ast_nodes as A
from .typesys import (
    Type, PrimType, IntLitType, FloatLitType, PtrType, ArrayType, ListType,
    InferType, StructType, EnumType, FuncType,
    I8, U8, I16, U16, I32, U32, F32, F64, BOOL, VOID, STR, INT_LIT, FLOAT_LIT, INFER,
    PRIM_TYPES, NARROW_RANGES, is_int, is_float, is_numeric, is_narrow,
    eq_blocker,
)
from .formats import parse_format


def _contains_func_type(t) -> bool:
    """True when t is a function type or wraps one (pointer/array/list)."""
    if isinstance(t, FuncType):
        return True
    if isinstance(t, (PtrType, ArrayType, ListType)):
        return _contains_func_type(t.inner)
    if isinstance(t, EnumType):
        return any(_contains_func_type(pt)
                   for payload in t.payloads.values() for pt in payload)
    return False


def _contains_noncopyable(t) -> bool:
    """True for void and for values the C++ backend cannot copy by value.
    Lists and pointers are handles, so only Arena (and structs/arrays that
    contain one) make a payload non-copyable."""
    if t is VOID:
        return True
    if isinstance(t, StructType):
        if t.builtin:
            return t.name == "Arena"
        return any(_contains_noncopyable(ft) for ft in t.fields.values())
    if isinstance(t, ArrayType):
        return _contains_noncopyable(t.inner)
    return False


def _payload_enum_name(t, seen=None) -> str | None:
    """The name of a payload enum appearing inside t, if any. A payload
    enum has no C representation, even behind a pointer, so extern
    signatures cannot mention one."""
    if seen is None:
        seen = set()
    if isinstance(t, EnumType):
        return repr(t) if t.has_payloads else None
    if isinstance(t, (PtrType, ArrayType, ListType)):
        return _payload_enum_name(t.inner, seen)
    if isinstance(t, StructType):
        if t.builtin or t.name in seen:
            return None
        seen.add(t.name)
        for ft in t.fields.values():
            found = _payload_enum_name(ft, seen)
            if found is not None:
                return found
        return None
    if isinstance(t, FuncType):
        for pt in t.params:
            found = _payload_enum_name(pt, seen)
            if found is not None:
                return found
        return _payload_enum_name(t.ret, seen)
    return None


def _is_function_pointer(t) -> bool:
    """True for a function type or a chain of pointers to one — the shapes a
    C signature can spell as a function-pointer declarator."""
    while isinstance(t, PtrType):
        t = t.inner
    return isinstance(t, FuncType)


class CheckError(Exception):
    def __init__(self, msg, filename, pos):
        self.msg = msg; self.filename = filename; self.pos = pos
        where = getattr(pos, 'file', None) or filename
        super().__init__(f"{where}:{pos.line}:{pos.col}: {msg}")


class FuncSig:
    def __init__(self, name, params, ret, is_extern=False):
        self.name = name; self.params = params; self.ret = ret; self.is_extern = is_extern


class GenericEnumInfo:
    """An enum declaration with type parameters, before instantiation.

    Payloads stay as TypeExprs so a type parameter may stand for a concrete
    type, or even another generic application such as List<T>. Instantiating
    the enum resolves those expressions in a type environment.
    """

    def __init__(self, name, type_params, members, payloads):
        self.name = name
        self.type_params = tuple(type_params)
        self.members = members
        self.payloads = payloads


class GenericFuncInfo:
    """A function declaration with type parameters, before instantiation.

    Parameter and return types stay as TypeExprs so a type parameter may
    stand for a concrete type. Instantiating the function resolves those
    expressions in a type environment.
    """

    def __init__(self, name, type_params, params, ret, body, pos,
                 is_system=False, is_public=False):
        self.name = name
        self.type_params = tuple(type_params)
        self.params = params  # list of (name, TypeExpr)
        self.ret = ret
        self.body = body
        self.pos = pos
        self.is_system = is_system
        self.is_public = is_public


class GenericStructInfo:
    """A struct declaration with type parameters, before instantiation.

    Fields keep their TypeExprs for the same reason generic enum payloads do:
    `Pair<T, U>` cannot choose concrete field types until a call site names
    the arguments.
    """

    def __init__(self, name, type_params, fields):
        self.name = name
        self.type_params = tuple(type_params)
        self.fields = tuple(fields)  # (field name, TypeExpr, Pos)


class TypeChecker:
    def __init__(self, program: A.Program, filename="<input>"):
        self.program = program
        self.filename = filename
        self.display_names = getattr(program, 'display_names', {}) or {}
        self.private_types = getattr(program, 'private_types', set()) or set()
        self.structs: dict[str, StructType] = {}
        self.enums: dict[str, EnumType] = {}
        self.generic_enums: dict[str, GenericEnumInfo] = {}
        self.generic_structs: dict[str, GenericStructInfo] = {}
        self.generic_functions: dict[str, GenericFuncInfo] = {}
        self.generic_func_instances: dict[tuple[str, tuple[Type, ...]], str] = {}
        self.generic_func_counter = 0
        # (family, concrete type arguments) -> instantiated EnumType. Keeping
        # one instance per combination makes named types behave nominally and
        # lets codegen emit each concrete representation exactly once.
        self._enum_instances: dict[tuple[str, tuple[Type, ...]], EnumType] = {}
        self._enum_instance_order: list[EnumType] = []
        self._enum_instance_counter = 0
        self._enum_instantiating: set[tuple[str, tuple[Type, ...]]] = set()
        self._struct_instances: dict[tuple[str, tuple[Type, ...]], StructType] = {}
        self._struct_instance_counter = 0
        self.functions: dict[str, FuncSig] = {}
        self.constants: dict[str, Type] = {}
        # Function types seen anywhere in the program, mapped to the C++
        # alias name codegen will emit for them.
        self.func_types: dict[FuncType, str] = {}
        self.scopes = []
        self.current_ret: Type = VOID
        self.loop_depth = 0
        self.return_values: list = []
        self._current_type_env = None
        self._register_builtins()

    def _register_builtins(self):
        self.structs["Vec2"] = StructType("Vec2", {"x": F32, "y": F32}, builtin=True)
        self.structs["Vec3"] = StructType("Vec3", {"x": F32, "y": F32, "z": F32}, builtin=True)
        self.structs["Quat"] = StructType("Quat", {"x": F32, "y": F32, "z": F32, "w": F32}, builtin=True)
        self.structs["Matrix4"] = StructType("Matrix4", {}, builtin=True)
        self.structs["Arena"] = StructType("Arena", {}, builtin=True)
        self.structs["StrBuilder"] = StructType("StrBuilder", {}, builtin=True)

        def bf(name, params, ret):
            self.functions[name] = FuncSig(name, params, ret, is_extern=True)

        bf("print_i32", [("v", I32)], VOID)
        bf("print_u32", [("v", U32)], VOID)
        bf("print_f32", [("v", F32)], VOID)
        bf("print_f64", [("v", F64)], VOID)
        bf("print_bool", [("v", BOOL)], VOID)
        bf("print_str", [("s", STR)], VOID)
        bf("write_i32", [("v", I32)], VOID)
        bf("write_u32", [("v", U32)], VOID)
        bf("write_f32", [("v", F32)], VOID)
        bf("write_f64", [("v", F64)], VOID)
        bf("write_bool", [("v", BOOL)], VOID)
        bf("write_str", [("s", STR)], VOID)
        bf("print_newline", [], VOID)
        bf("sqrt_f32", [("v", F32)], F32)
        bf("sqrt_f64", [("v", F64)], F64)
        bf("sin_f32", [("v", F32)], F32)
        bf("sin_f64", [("v", F64)], F64)
        bf("cos_f32", [("v", F32)], F32)
        bf("cos_f64", [("v", F64)], F64)
        bf("tan_f32", [("v", F32)], F32)
        bf("tan_f64", [("v", F64)], F64)
        bf("atan2_f32", [("y", F32), ("x", F32)], F32)
        bf("atan2_f64", [("y", F64), ("x", F64)], F64)
        bf("abs_i32", [("v", I32)], I32)
        bf("abs_f32", [("v", F32)], F32)
        bf("min_i32", [("a", I32), ("b", I32)], I32)
        bf("max_i32", [("a", I32), ("b", I32)], I32)
        bf("min_f32", [("a", F32), ("b", F32)], F32)
        bf("max_f32", [("a", F32), ("b", F32)], F32)
        bf("floor_f32", [("v", F32)], F32)
        bf("ceil_f32", [("v", F32)], F32)
        bf("i32_to_f32", [("v", I32)], F32)
        bf("f32_to_i32", [("v", F32)], I32)
        bf("rand_f32", [], F32)
        bf("rand_seed", [("seed", I32)], VOID)
        bf("arg_count", [], I32)
        bf("arg_str", [("i", I32)], STR)
        bf("str_concat", [("a", STR), ("b", STR)], STR)
        bf("str_contains", [("s", STR), ("sub", STR)], BOOL)
        bf("str_starts_with", [("s", STR), ("p", STR)], BOOL)
        bf("str_ends_with", [("s", STR), ("p", STR)], BOOL)
        bf("str_len", [("s", STR)], I32)
        bf("str_to_i32", [("s", STR)], I32)
        bf("str_to_f32", [("s", STR)], F32)
        bf("to_str_i32", [("v", I32)], STR)
        bf("to_str_f32", [("v", F32)], STR)
        bf("to_str_bool", [("v", BOOL)], STR)
        bf("str_pool_reset", [], VOID)
        bf("signal_emit", [("name", STR), ("value", I32)], VOID)
        _handler_type = FuncType((I32,), VOID)
        bf("signal_on", [("name", STR), ("handler", _handler_type)], VOID)
        bf("file_exists", [("path", STR)], BOOL)
        bf("file_write", [("path", STR), ("data", STR)], I32)
        bf("file_read", [("path", STR)], STR)
        bf("assert", [("cond", BOOL)], VOID)
        bf("translation", [("x", F32), ("y", F32), ("z", F32)], self.structs["Matrix4"])
        bf("scale", [("s", F32)], self.structs["Matrix4"])
        bf("from_quat", [("q", self.structs["Quat"])], self.structs["Matrix4"])

    def _resolve_type(self, te: A.TypeExpr, type_env=None) -> Type:
        if type_env is None:
            type_env = {}
        if self._current_type_env:
            merged = dict(self._current_type_env)
            merged.update(type_env)
            type_env = merged
        type_env = type_env or {}
        if te.kind == 'ptr':
            return PtrType(self._resolve_type(te.inner, type_env))
        if te.kind == 'list':
            return self._make_list_type(
                self._resolve_type(te.inner, type_env), te.pos)
        if te.kind == 'array':
            if te.size is None or te.size <= 0:
                raise CheckError("array size must be a positive integer", self.filename, te.pos)
            return ArrayType(self._resolve_type(te.inner, type_env), te.size)
        if te.kind == 'func':
            params = tuple(self._resolve_type(p, type_env)
                           for p in (te.params or []))
            ret = (self._resolve_type(te.inner, type_env)
                   if te.inner is not None else VOID)
            return self._func_type(params, ret)
        n = te.name
        if n in type_env:
            if te.args:
                raise CheckError(
                    f"type parameter '{n}' does not take type arguments",
                    self.filename, te.pos)
            return type_env[n]
        if n in PRIM_TYPES:
            if te.args:
                raise CheckError(
                    f"type '{n}' does not take type arguments",
                    self.filename, te.pos)
            return PRIM_TYPES[n]
        if n in self.generic_structs:
            info = self.generic_structs[n]
            if not te.args:
                params = ', '.join(info.type_params)
                raise CheckError(
                    f"generic type '{n}' requires type arguments: {n}<{params}>",
                    self.filename, te.pos)
            args = tuple(self._resolve_type(a, type_env) for a in te.args)
            return self._instantiate_struct(n, args, te.pos)
        if n in self.structs:
            if te.args:
                raise CheckError(
                    f"type '{n}' does not take type arguments",
                    self.filename, te.pos)
            return self.structs[n]
        if te.args:
            args = tuple(self._resolve_type(a, type_env) for a in te.args)
            if n in self.generic_enums:
                return self._instantiate_enum(n, args, te.pos)
            if n in self.enums:
                raise CheckError(
                    f"enum '{n}' does not take type arguments",
                    self.filename, te.pos)
            if n == 'List':
                raise CheckError(
                    "List requires exactly one element type: List<T>",
                    self.filename, te.pos)
            raise CheckError(f"unknown generic type '{n}'", self.filename, te.pos)
        if n in self.enums:
            return self.enums[n]
        if n in self.generic_enums:
            info = self.generic_enums[n]
            params = ', '.join(info.type_params)
            raise CheckError(
                f"generic type '{n}' requires type arguments: {n}<{params}>",
                self.filename, te.pos)
        if n == 'List':
            raise CheckError("List requires an element type: List<T>", self.filename, te.pos)
        raise CheckError(f"unknown type '{n}'", self.filename, te.pos)

    def _type_spelling(self, t) -> str:
        """A source-shaped type name for generic diagnostics."""
        if isinstance(t, EnumType):
            return repr(t)
        if isinstance(t, (PrimType, StructType, IntLitType, FloatLitType, InferType)):
            return repr(t)
        if isinstance(t, PtrType):
            return f"ptr<{self._type_spelling(t.inner)}>"
        if isinstance(t, ListType):
            return f"List<{self._type_spelling(t.inner)}>"
        if isinstance(t, ArrayType):
            return f"[{self._type_spelling(t.inner)}, {t.size}]"
        if isinstance(t, FuncType):
            params = ', '.join(self._type_spelling(p) for p in t.params)
            if t.ret is VOID:
                return f"func({params})"
            return f"func({params}) -> {self._type_spelling(t.ret)}"
        return repr(t)

    def _instantiate_enum(self, family, args, pos) -> EnumType:
        info = self.generic_enums[family]
        if len(args) != len(info.type_params):
            expected = ', '.join(info.type_params)
            raise CheckError(
                f"generic enum '{self._display(family)}' expects "
                f"{len(info.type_params)} type argument(s) <{expected}>, "
                f"got {len(args)}", self.filename, pos)
        for arg, param in zip(args, info.type_params):
            if arg is VOID:
                raise CheckError(
                    f"type argument for '{param}' cannot be void",
                    self.filename, pos)
            if isinstance(arg, (InferType, IntLitType, FloatLitType)):
                raise CheckError(
                    f"type argument for '{param}' must be a concrete type, "
                    f"got {arg}", self.filename, pos)
        key = (family, tuple(args))
        existing = self._enum_instances.get(key)
        if existing is not None:
            return existing
        if key in self._enum_instantiating:
            display = self._generic_display(family, args)
            raise CheckError(
                f"recursive generic enum instantiation of '{display}' is "
                f"not supported; store the nested value behind a pointer",
                self.filename, pos)

        self._enum_instantiating.add(key)
        try:
            env = dict(zip(info.type_params, args))
            payloads = {}
            for member, payload_exprs in info.payloads.items():
                resolved = []
                for te in payload_exprs:
                    ptype = self._resolve_type(te, env)
                    if _contains_noncopyable(ptype):
                        where = f"value {len(resolved) + 1} of '{member}'"
                        display = self._generic_display(family, args)
                        raise CheckError(
                            f"enum payload {where} cannot be "
                            f"{self._type_spelling(ptype)} in '{display}': "
                            f"payload values must be copyable and non-void",
                            self.filename, pos)
                    resolved.append(ptype)
                payloads[member] = tuple(resolved)

            while True:
                self._enum_instance_counter += 1
                internal = f"{family}__g{self._enum_instance_counter - 1}"
                if (internal not in self.enums
                        and internal not in self.structs
                        and internal not in self.generic_enums):
                    break
            display = self._generic_display(family, args)
            et = EnumType(internal, dict(info.members), payloads,
                          family=family, type_args=tuple(args), display=display)
            self.enums[internal] = et
            self._enum_instances[key] = et
            self._enum_instance_order.append(et)
            return et
        finally:
            self._enum_instantiating.discard(key)

    def _generic_display(self, family, args) -> str:
        name = self._display(family)
        inner = ', '.join(self._type_spelling(a) for a in args)
        return f"{name}<{inner}>"

    def _instantiate_struct(self, family, args, pos) -> StructType:
        """Resolve one concrete `Family<args>` struct instance."""
        info = self.generic_structs[family]
        if len(args) != len(info.type_params):
            expected = ', '.join(info.type_params)
            raise CheckError(
                f"generic struct '{self._display(family)}' expects "
                f"{len(info.type_params)} type argument(s) <{expected}>, "
                f"got {len(args)}", self.filename, pos)
        for arg, param in zip(args, info.type_params):
            if arg is VOID:
                raise CheckError(
                    f"type argument for '{param}' cannot be void",
                    self.filename, pos)
            if isinstance(arg, (InferType, IntLitType, FloatLitType)):
                raise CheckError(
                    f"type argument for '{param}' must be a concrete type, "
                    f"got {arg}", self.filename, pos)
        key = (family, tuple(args))
        existing = self._struct_instances.get(key)
        if existing is not None:
            return existing

        while True:
            self._struct_instance_counter += 1
            internal = f"{family}__g{self._struct_instance_counter - 1}"
            if (internal not in self.structs
                    and internal not in self.enums
                    and internal not in self.generic_enums
                    and internal not in self.generic_structs):
                break
        display = self._generic_display(family, args)
        st = StructType(internal, {}, family=family, type_args=tuple(args),
                        display=display)
        # Register before resolving fields so `ptr<Node<T>>` inside the
        # declaration refers back to this same instance instead of recursing.
        self.structs[internal] = st
        self._struct_instances[key] = st
        env = dict(zip(info.type_params, args))
        fields = {}
        for (fname, fte, fpos) in info.fields:
            if fname in fields:
                raise CheckError(f"duplicate field '{fname}'",
                                 self.filename, fpos)
            fields[fname] = self._resolve_type(fte, env)
        st.fields = fields
        return st

    def _make_list_type(self, inner: Type, pos) -> ListType:
        if inner is VOID:
            raise CheckError("a List cannot hold void", self.filename, pos)
        if isinstance(inner, StructType) and inner.name == "Arena":
            raise CheckError("a List cannot hold Arena (it is non-copyable)",
                             self.filename, pos)
        return ListType(inner)

    def _func_type(self, params, ret) -> FuncType:
        ft = FuncType(tuple(params), ret)
        if ft not in self.func_types:
            self.func_types[ft] = f'FnPtr{len(self.func_types)}'
        return ft

    def _display(self, msg):
        for internal, source in sorted(
                self.display_names.items(), key=lambda kv: len(kv[0]),
                reverse=True):
            msg = msg.replace(internal, source)
        return msg

    def _reraise_pretty(self, exc):
        raise CheckError(self._display(exc.msg), exc.filename, exc.pos) from None

    def _find_private_type(self, t):
        if isinstance(t, EnumType):
            if t.name in self.private_types:
                return t.name
            if t.family is not None and t.family in self.private_types:
                return t.family
            for arg in t.type_args:
                found = self._find_private_type(arg)
                if found is not None:
                    return found
            for payload in t.payloads.values():
                for ptype in payload:
                    found = self._find_private_type(ptype)
                    if found is not None:
                        return found
            return None
        if isinstance(t, StructType):
            return t.name if t.name in self.private_types else None
        if isinstance(t, (PtrType, ArrayType, ListType)):
            return self._find_private_type(t.inner)
        if isinstance(t, FuncType):
            for p in t.params:
                found = self._find_private_type(p)
                if found is not None:
                    return found
            return self._find_private_type(t.ret)
        return None

    def _check_inferred_public(self, d, t):
        bad = self._find_private_type(t)
        if bad is None:
            return
        raise CheckError(
            f"public declaration '{d.name}' exposes private type "
            f"'{self._display(bad)}' in its inferred type",
            self.filename, d.pos)

    def register(self):
        try:
            for d in self.program.decls:
                if isinstance(d, A.StructDecl):
                    self._register_struct(d)
                elif isinstance(d, A.EnumDecl):
                    self._register_enum(d)
                elif isinstance(d, A.FuncDecl):
                    self._register_func(d)
                elif isinstance(d, A.ConstDecl):
                    self._register_const(d)
                    if d.is_public and d.type_ann is None:
                        self._check_inferred_public(d, self.constants.get(d.name))
                elif isinstance(d, A.ExternDecl):
                    self._register_extern(d)
        except CheckError as exc:
            self._reraise_pretty(exc)

    def _register_struct(self, d):
        if (d.name in self.structs or d.name in self.enums
                or d.name in self.generic_enums
                or d.name in self.generic_structs
                or d.name in self.generic_functions):
            raise CheckError(f"duplicate type '{d.name}'", self.filename, d.pos)
        if d.name in self.functions:
            raise CheckError(f"type name '{d.name}' collides with function",
                             self.filename, d.pos)
        if d.name.startswith('FnPtr') and d.name[5:].isdigit():
            raise CheckError(
                f"type name '{d.name}' is reserved for generated function-pointer aliases",
                self.filename, d.pos)
        if d.name == 'List':
            raise CheckError("'List' is a reserved built-in type name", self.filename, d.pos)
        for param in getattr(d, 'type_params', ()):
            if param in PRIM_TYPES or param in ('List', 'ptr'):
                raise CheckError(
                    f"type parameter name '{param}' is reserved",
                    self.filename, d.pos)
        if d.type_params:
            fields = {}
            for (fname, _ftype, fpos) in d.fields:
                if fname in fields:
                    raise CheckError(f"duplicate field '{fname}'",
                                     self.filename, fpos)
                fields[fname] = True
            self.generic_structs[d.name] = GenericStructInfo(
                d.name, d.type_params, d.fields)
            return
        fields = {}
        for (fname, ftype, fpos) in d.fields:
            if fname in fields:
                raise CheckError(f"duplicate field '{fname}'", self.filename, fpos)
            fields[fname] = self._resolve_type(ftype)
        self.structs[d.name] = StructType(d.name, fields, builtin=False)

    def _register_enum(self, d):
        if (d.name in self.structs or d.name in self.enums
                or d.name in self.generic_enums
                or d.name in self.generic_structs
                or d.name in self.generic_functions):
            raise CheckError(f"duplicate type '{d.name}'", self.filename, d.pos)
        if d.name in self.functions:
            raise CheckError(f"type name '{d.name}' collides with function",
                             self.filename, d.pos)
        if d.name.startswith('FnPtr') and d.name[5:].isdigit():
            raise CheckError(
                f"type name '{d.name}' is reserved for generated function-pointer aliases",
                self.filename, d.pos)
        if d.name == 'List':
            raise CheckError("'List' is a reserved built-in type name", self.filename, d.pos)
        for param in d.type_params:
            if param in PRIM_TYPES or param in ('List', 'ptr'):
                raise CheckError(
                    f"type parameter name '{param}' is reserved",
                    self.filename, d.pos)
        members = {}
        used_values = {}
        next_value = 0
        for m in d.members:
            if m.name in members:
                raise CheckError(f"duplicate member '{m.name}'", self.filename, m.pos)
            value = next_value if m.value is None else m.value
            if not (-2147483648 <= value <= 2147483647):
                raise CheckError(
                    f"enum member value {value} is outside the i32 range",
                    self.filename, m.pos)
            if value in used_values:
                owner = used_values[value]
                raise CheckError(
                    f"enum '{d.name}' value {value} is already used by "
                    f"'{owner}'; member values must be unique",
                    self.filename, m.pos)
            members[m.name] = value
            used_values[value] = m.name
            next_value = value + 1
        if any(m.payload for m in d.members) and 'VantaTag' in members:
            member = next(m for m in d.members if m.name == 'VantaTag')
            raise CheckError(
                "member name 'VantaTag' is reserved in payload enums",
                self.filename, member.pos)

        if d.type_params:
            # Payloads stay unresolved until instantiation: a declaration
            # such as `enum Result<T, E>` cannot choose concrete layouts yet.
            payloads = {m.name: tuple(m.payload or []) for m in d.members}
            self.generic_enums[d.name] = GenericEnumInfo(
                d.name, d.type_params, members, payloads)
            return

        payloads = {}
        for m in d.members:
            payload = []
            for te in (m.payload or []):
                ptype = self._resolve_type(te)
                if _contains_noncopyable(ptype):
                    where = f"value {len(payload) + 1} of '{m.name}'"
                    raise CheckError(
                        f"enum payload {where} cannot be {ptype}: "
                        f"payload values must be copyable and non-void",
                        self.filename, te.pos)
                payload.append(ptype)
            payloads[m.name] = tuple(payload)
        self.enums[d.name] = EnumType(d.name, members, payloads)

    def _register_func(self, d):
        if d.name in self.functions or d.name in self.generic_functions:
            raise CheckError(f"duplicate function '{d.name}'", self.filename, d.pos)
        if (d.name in self.structs or d.name in self.enums
                or d.name in self.generic_enums
                or d.name in self.generic_structs
                or d.name in self.generic_functions):
            raise CheckError(f"function name '{d.name}' collides with type", self.filename, d.pos)
        for param in getattr(d, 'type_params', ()):
            if param in PRIM_TYPES or param in ('List', 'ptr'):
                raise CheckError(
                    f"type parameter name '{param}' is reserved",
                    self.filename, d.pos)
        if getattr(d, 'type_params', ()):
            self.generic_functions[d.name] = GenericFuncInfo(
                d.name, d.type_params, [(p.name, p.type) for p in d.params],
                d.ret, d.body, d.pos, is_system=d.is_system,
                is_public=d.is_public)
            return
        params = []
        for p in d.params:
            params.append((p.name, self._resolve_type(p.type)))
        ret = self._resolve_type(d.ret) if d.ret is not None else INFER
        self.functions[d.name] = FuncSig(d.name, params, ret, is_extern=False)

    def _register_const(self, c):
        if c.name in self.constants:
            raise CheckError(f"duplicate constant '{c.name}'", self.filename, c.pos)
        if (c.name in self.structs or c.name in self.enums
                or c.name in self.generic_enums or c.name in self.generic_structs
                or c.name in self.generic_functions):
            raise CheckError(f"constant '{c.name}' collides with type", self.filename, c.pos)
        if c.name in self.functions:
            raise CheckError(f"constant '{c.name}' collides with function", self.filename, c.pos)
        declared = self._resolve_type(c.type_ann) if c.type_ann is not None else None
        vt = self._check_expr(c.value, declared)
        if not self._is_constexpr(c.value):
            raise CheckError(
                f"constant initializer must be a compile-time expression",
                self.filename, c.pos)
        if declared is not None:
            self._coerce_value(c.value, vt, declared, c.pos, "constant initializer")
            vt = declared
        else:
            vt = self._default_type(vt, c.value)
        if vt is VOID:
            raise CheckError("constant cannot be void", self.filename, c.pos)
        if _contains_func_type(vt):
            raise CheckError("constant cannot hold a function value", self.filename, c.pos)
        self.constants[c.name] = vt

    def _register_extern(self, d: A.ExternDecl):
        for fd in d.funcs:
            if fd.name in self.functions:
                raise CheckError(f"duplicate function '{fd.name}'", self.filename, fd.pos)
            if (fd.name in self.structs or fd.name in self.enums
                    or fd.name in self.generic_enums
                    or fd.name in self.generic_structs):
                raise CheckError(f"function name '{fd.name}' collides with type", self.filename, fd.pos)
            params = []
            for p in fd.params:
                ptype = self._resolve_type(p.type)
                bad = _payload_enum_name(ptype)
                if bad is not None:
                    raise CheckError(
                        f"extern function '{fd.name}' cannot use payload enum "
                        f"'{bad}' in parameter '{p.name}'; payload enums have "
                        f"no C representation",
                        self.filename, fd.pos)
                params.append((p.name, ptype))
            ret = self._resolve_type(fd.ret) if fd.ret is not None else VOID
            bad_ret = _payload_enum_name(ret)
            if bad_ret is not None:
                raise CheckError(
                    f"extern function '{fd.name}' cannot return payload enum "
                    f"'{bad_ret}'; payload enums have no C representation",
                    self.filename, fd.pos)
            if _contains_func_type(ret) and not _is_function_pointer(ret):
                raise CheckError(
                    f"extern function '{fd.name}' can return a function type "
                    f"or a pointer to one, not {ret}",
                    self.filename, fd.pos)
            self.functions[fd.name] = FuncSig(fd.name, params, ret, is_extern=True)

    def _is_constexpr(self, expr) -> bool:
        if isinstance(expr, (A.IntLit, A.FloatLit, A.BoolLit, A.StringLit)):
            return True
        if isinstance(expr, A.Name):
            return True
        if isinstance(expr, A.BinOp):
            return self._is_constexpr(expr.left) and self._is_constexpr(expr.right)
        if isinstance(expr, A.UnaryOp):
            return self._is_constexpr(expr.operand)
        return False

    def _push(self):
        self.scopes.append({})

    def _pop(self):
        self.scopes.pop()

    def _declare(self, name, typ, mutable, pos=None):
        if self.scopes[-1].get(name) is not None:
            raise CheckError(f"'{name}' already declared in this scope",
                             self.filename, pos or A.Pos(0, 0))
        self.scopes[-1][name] = (typ, mutable)

    def _lookup(self, name):
        for scope in reversed(self.scopes):
            if name in scope:
                return scope[name]
        if name in self.constants:
            return (self.constants[name], False)
        return None

    def check(self):
        try:
            for d in self.program.decls:
                if isinstance(d, A.FuncDecl):
                    if getattr(d, 'type_params', ()):
                        continue
                    self._check_func(d)
                    if d.is_public and d.ret is None:
                        self._check_inferred_public(
                            d, self.functions[d.name].ret)
        except CheckError as exc:
            self._reraise_pretty(exc)

    def _check_func(self, fn: A.FuncDecl):
        sig = self.functions[fn.name]
        prev_ret = self.current_ret
        prev_rv = self.return_values
        self.current_ret = sig.ret
        self.return_values = []
        self._push()
        try:
            for (pname, ptype) in sig.params:
                if ptype is VOID:
                    raise CheckError(f"parameter '{pname}' cannot be void", self.filename, fn.pos)
                self._declare(pname, ptype, mutable=False)
            for stmt in fn.body:
                self._check_stmt(stmt)
            if isinstance(sig.ret, InferType):
                self._resolve_inferred_return(sig, fn)
        finally:
            self._pop()
            self.current_ret = prev_ret
            self.return_values = prev_rv

    def _resolve_inferred_return(self, sig, fn):
        has_bare = any(v is None for (v, _) in self.return_values)
        typed = [(v, t) for (v, t) in self.return_values if v is not None]
        if not self.return_values:
            sig.ret = VOID
            return
        if has_bare and typed:
            raise CheckError(
                f"function '{fn.name}': mixed bare 'return' and 'return value'",
                self.filename, fn.pos)
        if has_bare:
            sig.ret = VOID
            return
        types = [t for (_, t) in typed]
        concrete = [t for t in types if not (t is INT_LIT or t is FLOAT_LIT)]
        if concrete:
            base = concrete[0]
            for t in concrete[1:]:
                if t != base:
                    raise CheckError(
                        f"function '{fn.name}': inconsistent return types {base} and {t}",
                        self.filename, fn.pos)
        else:
            if all(t is INT_LIT for t in types):
                base = I32
            else:
                base = F32
        if isinstance(base, StructType) and base.name == "Arena":
            raise CheckError(f"function '{fn.name}': cannot return an Arena",
                             self.filename, fn.pos)
        sig.ret = base
        for (v, t) in typed:
            self._coerce_value(v, t, base, v.pos, "inferred return value")

    def _check_stmt(self, stmt):
        if isinstance(stmt, A.VarDecl):
            self._check_var_decl(stmt)
        elif isinstance(stmt, A.AssignStmt):
            self._check_assign(stmt)
        elif isinstance(stmt, A.ReturnStmt):
            self._check_return(stmt)
        elif isinstance(stmt, A.BreakStmt):
            if self.loop_depth == 0:
                raise CheckError("'break' outside loop", self.filename, stmt.pos)
        elif isinstance(stmt, A.ContinueStmt):
            if self.loop_depth == 0:
                raise CheckError("'continue' outside loop", self.filename, stmt.pos)
        elif isinstance(stmt, A.IfStmt):
            self._check_if(stmt)
        elif isinstance(stmt, A.WhileStmt):
            self._check_while(stmt)
        elif isinstance(stmt, A.ForRangeStmt):
            self._check_for(stmt)
        elif isinstance(stmt, A.ForEachStmt):
            self._check_foreach(stmt)
        elif isinstance(stmt, A.MatchStmt):
            self._check_match(stmt)
        elif isinstance(stmt, A.ExprStmt):
            self._check_expr(stmt.expr)
        else:
            raise CheckError(f"unsupported statement {type(stmt).__name__}", self.filename, stmt.pos)

    def _check_var_decl(self, v: A.VarDecl):
        declared = self._resolve_type(v.type_ann) if v.type_ann is not None else None
        vt = self._check_expr(v.value, declared)
        if declared is not None:
            self._coerce_value(v.value, vt, declared, v.pos, "initializer")
            vt = declared
        else:
            vt = self._default_type(vt, v.value)
        if vt is VOID:
            raise CheckError("cannot bind a variable to void", self.filename, v.pos)
        if isinstance(vt, StructType) and vt.name == "Arena":
            if not (isinstance(v.value, A.Call) and isinstance(v.value.func, A.Name)
                    and v.value.func.name == "Arena"):
                raise CheckError("Arena values cannot be copied or reassigned", self.filename, v.pos)
        self._declare(v.name, vt, v.mutable, v.pos)
        v.var_type = vt

    def _check_assign(self, a: A.AssignStmt):
        # Check the target first: that marks checked at() accesses and
        # indirect calls, which _is_assignable relies on.
        tt = self._check_expr(a.target)
        if not self._is_assignable(a.target):
            raise CheckError("invalid assignment target", self.filename, a.pos)
        vt = self._check_expr(a.value, tt)
        self._coerce_value(a.value, vt, tt, a.pos, "assignment")
        if isinstance(tt, StructType) and tt.name == "Arena":
            raise CheckError("Arena values cannot be assigned", self.filename, a.pos)

    def _is_assignable(self, expr) -> bool:
        # Walk the storage chain (field accesses, indexes, and checked at()
        # accesses) down to its root. An index applied to a pointer makes the
        # chain writable no matter how the binding was declared — pointer
        # memory is mutable through a plain `let`. In every other case the
        # root binding must be `mut`; parameters and `let` bindings are
        # immutable at any depth.
        node = expr
        while True:
            if isinstance(node, A.Index):
                ot = self._check_expr(node.obj)
                if isinstance(ot, (PtrType, ListType)):
                    return True
                node = node.obj
                continue
            if isinstance(node, A.Call):
                # A checked xs.at(i) is a storage location: keep walking
                # through its receiver. Any other call is a temporary. A
                # List is an indirection, so its elements are writable
                # through a plain `let` — like pointer memory.
                if getattr(node, 'is_checked_at', False):
                    recv = node.func.obj
                    if isinstance(self._check_expr(recv), (ListType, PtrType)):
                        return True
                    node = recv
                    continue
                return False
            if isinstance(node, A.Member):
                node = node.obj
                continue
            break
        if isinstance(node, A.Name):
            ent = self._lookup(node.name)
            return ent is not None and ent[1]
        return False

    def _check_return(self, r: A.ReturnStmt):
        if r.value is None:
            if not isinstance(self.current_ret, InferType) and self.current_ret is not VOID:
                raise CheckError("return without value in non-void function", self.filename, r.pos)
            self.return_values.append((None, VOID))
            return
        expected = None if isinstance(self.current_ret, InferType) else self.current_ret
        vt = self._check_expr(r.value, expected)
        if isinstance(vt, StructType) and vt.name == "Arena":
            raise CheckError("cannot return an Arena", self.filename, r.pos)
        if isinstance(self.current_ret, InferType):
            self.return_values.append((r.value, vt))
            return
        if self.current_ret is VOID:
            raise CheckError("cannot return a value from a void function", self.filename, r.pos)
        self._coerce_value(r.value, vt, self.current_ret, r.pos, "return value")

    def _check_if(self, i: A.IfStmt):
        self._check_cond(i.cond, i.pos)
        self._push(); [self._check_stmt(s) for s in i.then_body]; self._pop()
        for (c, body) in i.elif_branches:
            self._check_cond(c, i.pos)
            self._push(); [self._check_stmt(s) for s in body]; self._pop()
        if i.else_body is not None:
            self._push(); [self._check_stmt(s) for s in i.else_body]; self._pop()

    def _check_while(self, w: A.WhileStmt):
        self._check_cond(w.cond, w.pos)
        self._push()
        self.loop_depth += 1
        try:
            for s in w.body:
                self._check_stmt(s)
        finally:
            self.loop_depth -= 1
            self._pop()

    def _check_for(self, f: A.ForRangeStmt):
        st = self._check_expr(f.start)
        et = self._check_expr(f.end)
        self._coerce_value(f.start, st, I32, f.pos, "range start")
        self._coerce_value(f.end, et, I32, f.pos, "range end")
        if f.step is not None:
            sst = self._check_expr(f.step)
            self._coerce_value(f.step, sst, I32, f.pos, "range step")
            if isinstance(f.step, A.IntLit) and f.step.value == 0:
                raise CheckError("range step cannot be 0", self.filename, f.pos)
        self._push()
        self.scopes[-1][f.var] = (I32, False)
        self.loop_depth += 1
        try:
            for s in f.body:
                self._check_stmt(s)
        finally:
            self.loop_depth -= 1
            self._pop()

    def _check_foreach(self, f: A.ForEachStmt):
        it = self._check_expr(f.iterable)
        if isinstance(it, (ListType, ArrayType)):
            elem = it.inner
        else:
            raise CheckError(
                f"cannot iterate over {it}; for-each supports arrays and Lists",
                self.filename, f.pos)
        self._push()
        self.scopes[-1][f.var] = (elem, False)
        self.loop_depth += 1
        try:
            for s in f.body:
                self._check_stmt(s)
        finally:
            self.loop_depth -= 1
            self._pop()

    def _check_match(self, m: A.MatchStmt):
        vt = self._check_expr(m.value)
        if not isinstance(vt, EnumType):
            raise CheckError(f"match expects an enum value, got {vt}",
                             self.filename, m.pos)
        covered = []
        has_else = False
        for arm in m.arms:
            bindings = []
            if arm.is_else:
                has_else = True
            else:
                for pat in arm.patterns:
                    family = pat.enum_name
                    if family != vt.name and family != vt.family:
                        raise CheckError(
                            f"cannot match {self._display(family)}.{pat.member} "
                            f"against '{vt}'",
                            self.filename, pat.pos)
                    # Codegen spells tags against the concrete enum instance,
                    # not the source-level generic family name.
                    pat.enum_name = vt.name
                    if pat.member not in vt.members:
                        raise CheckError(f"enum '{vt.name}' has no member "
                                         f"'{pat.member}'",
                                         self.filename, pat.pos)
                    guarded = getattr(arm, 'guard', None) is not None
                    if pat.member in covered and not guarded:
                        raise CheckError(
                            f"duplicate match arm '{vt.name}.{pat.member}'",
                            self.filename, pat.pos)
                    if not guarded:
                        covered.append(pat.member)
                    payload = vt.payload_of(pat.member)
                    if pat.bindings is None:
                        if payload:
                            raise CheckError(
                                f"enum member '{vt.name}.{pat.member}' carries "
                                f"values; write {vt.name}.{pat.member}(...)",
                                self.filename, pat.pos)
                    elif len(pat.bindings) != len(payload):
                        raise CheckError(
                            f"'{vt.name}.{pat.member}' expects "
                            f"{len(payload)} binding(s), got "
                            f"{len(pat.bindings)}",
                            self.filename, pat.pos)
                    seen = set()
                    for bname, btype in zip(pat.bindings or [], payload):
                        if bname == '_':
                            continue
                        if bname in seen:
                            raise CheckError(
                                f"duplicate binding '{bname}' in match pattern",
                                self.filename, pat.pos)
                        seen.add(bname)
                        bindings.append((bname, btype, pat.pos))
                if len(arm.patterns) > 1 and bindings:
                    raise CheckError(
                        "a match arm with multiple patterns cannot bind payload "
                        "values; use one pattern per arm",
                        self.filename, arm.pos)
            self._push()
            for bname, btype, bpos in bindings:
                self._declare(bname, btype, False, bpos)
            if getattr(arm, 'guard', None) is not None:
                gtype = self._check_expr(arm.guard)
                if gtype is not BOOL:
                    raise CheckError(
                        f"match guard must be bool, got {gtype}",
                        self.filename, arm.pos)
            for s in arm.body:
                self._check_stmt(s)
            self._pop()
        if not has_else:
            missing = [mn for mn in vt.members if mn not in covered]
            if missing:
                names = ', '.join(f"'{mn}'" for mn in missing)
                word = 'member' if len(missing) == 1 else 'members'
                raise CheckError(
                    f"match on '{vt.name}' is missing {word} {names}; "
                    f"add an arm or an else branch", self.filename, m.pos)

    def _check_cond(self, cond, pos):
        ct = self._check_expr(cond)
        if ct is not BOOL:
            raise CheckError(f"condition must be bool, got {ct}", self.filename, pos)

    def _check_expr(self, expr, expected=None) -> Type:
        if isinstance(expr, A.IntLit):
            expr.type = INT_LIT; return INT_LIT
        if isinstance(expr, A.FloatLit):
            expr.type = FLOAT_LIT; return FLOAT_LIT
        if isinstance(expr, A.BoolLit):
            expr.type = BOOL; return BOOL
        if isinstance(expr, A.StringLit):
            expr.type = STR; return STR
        if isinstance(expr, A.ArrayLit):
            return self._check_array_lit(expr, expected)
        if isinstance(expr, A.Name):
            ent = self._lookup(expr.name)
            if ent is not None:
                expr.type = ent[0]
                return ent[0]
            if expr.name in ('len', 'print_fmt', 'write_fmt', 'assert', 'enum_to_i32',
                             'ptr_is_null', 'ptr_cast', 'ptr_offset', 'ptr_null'):
                raise CheckError(f"cannot use builtin '{expr.name}' as a value",
                                 self.filename, expr.pos)
            if (expr.name in self.structs or expr.name in self.enums
                    or expr.name in self.generic_enums
                    or expr.name in self.generic_structs
                    or expr.name in self.generic_functions
                    or expr.name == 'List'):
                raise CheckError(f"cannot use type '{expr.name}' as a value",
                                 self.filename, expr.pos)
            if expr.name in self.functions:
                sig = self.functions[expr.name]
                if isinstance(sig.ret, InferType):
                    raise CheckError(
                        f"cannot use '{expr.name}' as a value before its return "
                        f"type is inferred; add explicit '-> T' or move its "
                        f"declaration before this use",
                        self.filename, expr.pos)
                ft = self._func_type(tuple(t for (_, t) in sig.params), sig.ret)
                expr.type = ft
                expr.is_func_ref = True
                return ft
            raise CheckError(f"unknown name '{expr.name}'", self.filename, expr.pos)
        if isinstance(expr, A.BinOp):
            left_generic = self._is_generic_enum_expr(expr.left)
            right_generic = self._is_generic_enum_expr(expr.right)
            # Check the side that already knows its type first. A generic
            # constructor with a payload (Option.Some(5)) or explicit type
            # arguments can stand alone; a bare Option.None needs the other
            # side. This keeps `Option.None == Option.Some(5)` symmetric with
            # `Option.Some(5) == Option.None`.
            right_first = (
                (left_generic and not right_generic)
                or (left_generic and right_generic
                    and self._generic_enum_expr_self_describing(expr.right)
                    and not self._generic_enum_expr_self_describing(expr.left))
            )
            if right_first:
                rt = self._check_expr(expr.right)
                lt = self._check_expr(expr.left, rt)
            else:
                lt = self._check_expr(expr.left)
                rt = self._check_expr(expr.right, lt)
            t = self._check_binop(expr, lt, rt)
            expr.type = t
            return t
        if isinstance(expr, A.UnaryOp):
            t = self._check_expr(expr.operand)
            if expr.op == '-':
                if is_narrow(t):
                    # Reading a narrow value promotes it, so -u8 is an i32.
                    expr.type = I32; return I32
                if is_numeric(t):
                    expr.type = t; return t
                if isinstance(t, StructType) and t.name in ("Vec2", "Vec3"):
                    expr.type = t; return t
                raise CheckError(f"cannot negate {t}", self.filename, expr.pos)
            if expr.op == 'not':
                if t is not BOOL:
                    raise CheckError("'not' requires bool", self.filename, expr.pos)
                expr.type = BOOL; return BOOL
            raise CheckError(f"unknown unary '{expr.op}'", self.filename, expr.pos)
        if isinstance(expr, A.Call):
            return self._check_call(expr, expected)
        if isinstance(expr, A.Member):
            if (isinstance(expr.obj, A.Name) and self._lookup(expr.obj.name) is None
                    and expr.obj.name in self.enums):
                et = self.enums[expr.obj.name]
                if expr.field not in et.members:
                    raise CheckError(f"enum '{et.name}' has no member '{expr.field}'",
                                     self.filename, expr.pos)
                if et.payload_of(expr.field):
                    raise CheckError(
                        f"enum member '{et.name}.{expr.field}' carries values; "
                        f"construct it with {et.name}.{expr.field}(...)",
                        self.filename, expr.pos)
                expr.is_enum_member = True
                expr.type = et
                return et
            if (isinstance(expr.obj, A.Name) and self._lookup(expr.obj.name) is None
                    and expr.obj.name in self.generic_enums):
                return self._check_generic_enum_member(
                    self.generic_enums[expr.obj.name], expr, expected)
            ot = self._check_expr(expr.obj)
            if isinstance(ot, EnumType):
                raise CheckError(f"enum values have no fields; write {ot}.Member",
                                 self.filename, expr.pos)
            if isinstance(ot, StructType) and expr.field in ot.fields:
                t = ot.fields[expr.field]
                expr.type = t
                return t
            if expr.field == 'at' and isinstance(ot, PtrType):
                raise CheckError("'at' on a pointer must be called with an index "
                                 "and a size: p.at(i, size)",
                                 self.filename, expr.pos)
            if expr.field == 'at' and isinstance(ot, (ArrayType, ListType)):
                raise CheckError("'at' must be called with an index: xs.at(i)",
                                 self.filename, expr.pos)
            if isinstance(ot, ListType) and expr.field == 'push':
                raise CheckError("'push' must be called: xs.push(v)",
                                 self.filename, expr.pos)
            if isinstance(ot, ListType) and expr.field == 'pop':
                raise CheckError("'pop' must be called: xs.pop()",
                                 self.filename, expr.pos)
            if isinstance(ot, ListType) and expr.field == 'insert':
                raise CheckError("'insert' must be called: xs.insert(i, v)",
                                 self.filename, expr.pos)
            if isinstance(ot, ListType) and expr.field == 'remove':
                raise CheckError("'remove' must be called: xs.remove(i)",
                                 self.filename, expr.pos)
            if isinstance(ot, ListType) and expr.field == 'sort':
                raise CheckError("'sort' must be called: xs.sort(cmp)",
                                 self.filename, expr.pos)
            if isinstance(ot, ListType) and expr.field == 'len':
                raise CheckError("'len' is not a field of a List; write len(xs)",
                                 self.filename, expr.pos)
            if isinstance(ot, StructType) and ot.name == 'StrBuilder' and expr.field in (
                    'append_str', 'append_i32', 'append_u32', 'append_f32',
                    'append_f64', 'append_bool', 'to_str', 'clear'):
                raise CheckError(f"'{expr.field}' must be called: b.{expr.field}(...)",
                                 self.filename, expr.pos)
            raise CheckError(f"type {ot} has no field '{expr.field}'", self.filename, expr.pos)
        if isinstance(expr, A.Index):
            ot = self._check_expr(expr.obj)
            it = self._check_expr(expr.index)
            self._coerce_value(expr.index, it, I32, expr.pos, "index")
            if isinstance(ot, PtrType) and ot.inner is VOID:
                raise CheckError(
                    "cannot index a ptr<void> (it has no element type); "
                    "declare the pointer with the element type, e.g. ptr<i32>",
                    self.filename, expr.pos)
            if isinstance(ot, (PtrType, ArrayType, ListType)):
                expr.type = ot.inner
                return ot.inner
            raise CheckError(f"cannot index a value of type {ot}", self.filename, expr.pos)
        raise CheckError(f"unsupported expression {type(expr).__name__}", self.filename,
                         getattr(expr, 'pos', A.Pos(0, 0)))

    def _is_generic_enum_expr(self, expr) -> bool:
        """True when expr is a generic enum constructor or member value.

        Used by binary operators to try the non-generic side first, so a
        comparison such as `Result.Ok(7) == result` can infer T and E.
        """
        if isinstance(expr, A.Call):
            f = expr.func
        elif isinstance(expr, A.Member):
            f = expr
        else:
            return False
        return (isinstance(f, A.Member) and isinstance(f.obj, A.Name)
                and self._lookup(f.obj.name) is None
                and f.obj.name in self.generic_enums)

    def _generic_enum_expr_self_describing(self, expr) -> bool:
        """True when a generic enum call can infer its type by itself.

        A bare member (`Option.None`) cannot; a payload constructor or an
        explicit `::<...>` argument list can. Used only to choose which side
        of a comparison to check first.
        """
        if not isinstance(expr, A.Call):
            return False
        f = expr.func
        return (isinstance(f, A.Member) and isinstance(f.obj, A.Name)
                and self._lookup(f.obj.name) is None
                and f.obj.name in self.generic_enums
                and bool(expr.type_args or expr.args))

    def _check_array_lit(self, expr: A.ArrayLit, expected=None) -> Type:
        if not expr.elements:
            raise CheckError("empty array literal is not supported; use an explicit type",
                             self.filename, expr.pos)
        if isinstance(expected, ArrayType):
            if len(expr.elements) != expected.size:
                raise CheckError(
                    f"array literal has {len(expr.elements)} element(s), "
                    f"expected {expected.size}", self.filename, expr.pos)
            types = []
            for i, e in enumerate(expr.elements):
                et = self._check_expr(e, expected.inner)
                self._coerce_value(e, et, expected.inner, expr.pos,
                                   f"array element {i}")
                types.append(expected.inner)
            expr.element_types = list(types)
            expr.type = expected
            return expected
        types = [self._check_expr(e) for e in expr.elements]
        expr.element_types = list(types)
        concrete = [t for t in types if not (t is INT_LIT or t is FLOAT_LIT)]
        if concrete:
            base = concrete[0]
            for t in concrete[1:]:
                if t != base:
                    raise CheckError(
                        f"array literal has mixed element types {base} and {t}",
                        self.filename, expr.pos)
        else:
            if all(t is INT_LIT for t in types):
                base = I32
            else:
                base = F32
        for e in expr.elements:
            e.type = base
        t = ArrayType(base, len(expr.elements))
        expr.type = t
        return t

    def _check_binop(self, expr: A.BinOp, lt, rt) -> Type:
        op = expr.op
        lt, rt = self._coerce_binop_lits(expr, lt, rt)
        # Compile-time integer overflow guard for constant expressions.
        if (op in ('+', '-', '*') and isinstance(expr.left, A.IntLit)
                and isinstance(expr.right, A.IntLit) and is_int(lt)
                and is_int(rt)):
            a = expr.left.value
            b = expr.right.value
            if op == '+':
                value = a + b
            elif op == '-':
                value = a - b
            else:
                value = a * b
            target = lt
            if target is INT_LIT:
                target = I32
            if target is I32:
                bounds = (-2147483648, 2147483647)
            elif target is U32:
                bounds = (0, 4294967295)
            elif target in NARROW_RANGES:
                bounds = NARROW_RANGES[target]
            else:
                bounds = None
            if bounds is not None and not (bounds[0] <= value <= bounds[1]):
                raise CheckError(f"integer overflow in '{op}': {value} "
                                f"outside {target} range", self.filename,
                                expr.pos)
        # Reading a narrow integer promotes it to i32 (C's integer
        # promotion); the C++ backend promotes the same way for free.
        lt = I32 if is_narrow(lt) else lt
        rt = I32 if is_narrow(rt) else rt
        if op in ('and', 'or'):
            if lt is not BOOL or rt is not BOOL:
                raise CheckError(f"'{op}' requires bool operands", self.filename, expr.pos)
            return BOOL
        if op in ('==', '!=', '<', '<=', '>', '>='):
            if isinstance(lt, FuncType) or isinstance(rt, FuncType):
                if op in ('==', '!=') and isinstance(lt, FuncType) and lt == rt:
                    return BOOL
                if op in ('==', '!='):
                    raise CheckError(f"cannot compare {lt} and {rt} with '{op}'",
                                     self.filename, expr.pos)
                raise CheckError(
                    "ordering comparisons are not supported on function values; "
                    "use '==' or '!='",
                    self.filename, expr.pos)
            if isinstance(lt, EnumType) or isinstance(rt, EnumType):
                if lt == rt and op in ('==', '!='):
                    blocker = eq_blocker(lt)
                    if blocker is not None:
                        path, bt = blocker
                        raise CheckError(
                            f"cannot compare enum '{lt.name}' with '{op}': "
                            f"payload '{path}' ({bt}) has no equality",
                            self.filename, expr.pos)
                    return BOOL
                if lt == rt:
                    raise CheckError(
                        f"ordering comparisons are not supported on {lt}; use '==' or '!='",
                        self.filename, expr.pos)
                raise CheckError(f"cannot compare {lt} and {rt} with '{op}'", self.filename, expr.pos)
            if isinstance(lt, StructType) or isinstance(rt, StructType):
                if op in ('==', '!=') and isinstance(lt, StructType) and lt == rt:
                    if lt.name in ("Vec2", "Vec3"):
                        return BOOL
                    if lt.builtin:
                        raise CheckError(f"cannot compare {lt} and {rt} with '{op}'",
                                         self.filename, expr.pos)
                    blocker = eq_blocker(lt)
                    if blocker is None:
                        return BOOL
                    path, bt = blocker
                    raise CheckError(
                        f"cannot compare struct '{lt.name}' with '{op}': "
                        f"field '{path}' ({bt}) has no equality",
                        self.filename, expr.pos)
                raise CheckError(f"cannot compare {lt} and {rt} with '{op}'", self.filename, expr.pos)
            if lt is STR or rt is STR:
                if op in ('==', '!=') and lt is STR and rt is STR:
                    return BOOL
                raise CheckError(f"cannot compare str with '{op}'", self.filename, expr.pos)
            if lt != rt:
                raise CheckError(f"cannot compare {lt} and {rt}", self.filename, expr.pos)
            return BOOL
        if op in ('/', '%'):
            if isinstance(expr.right, A.IntLit) and expr.right.value == 0:
                raise CheckError("division by zero", self.filename, expr.pos)
            if isinstance(expr.right, A.FloatLit) and expr.right.value == 0.0:
                raise CheckError("division by zero", self.filename, expr.pos)
        if op in ('+', '-', '*', '/', '%'):
            if is_numeric(lt) and lt == rt:
                if op == '%' and is_float(lt):
                    raise CheckError("'%' requires integer operands", self.filename, expr.pos)
                return lt
            if isinstance(lt, StructType) and lt.name in ("Vec2", "Vec3"):
                if isinstance(rt, StructType) and rt == lt and op in ('+', '-', '*'):
                    return lt
                if is_float(rt) and op in ('*', '/'):
                    return lt
            if isinstance(rt, StructType) and rt.name in ("Vec2", "Vec3"):
                if is_float(lt) and op == '*':
                    return rt
            if op == '*' and isinstance(lt, StructType) and isinstance(rt, StructType):
                if lt.name == 'Matrix4' and rt.name == 'Matrix4':
                    return lt
                if lt.name == 'Matrix4' and rt.name == 'Vec3':
                    return rt
                if lt.name == 'Quat' and rt.name == 'Quat':
                    return lt
                if lt.name == 'Quat' and rt.name == 'Vec3':
                    return rt
                if lt.name == 'Vec3' and rt.name == 'Quat':
                    return lt
            raise CheckError(f"invalid operands for '{op}': {lt}, {rt}", self.filename, expr.pos)
        raise CheckError(f"unknown operator '{op}'", self.filename, expr.pos)

    def _coerce_binop_lits(self, expr, lt, rt):
        def lit_ok(concrete, lit):
            if lit is INT_LIT:
                return is_int(concrete) or is_float(concrete)
            if lit is FLOAT_LIT:
                return is_float(concrete)
            return False
        if lt is INT_LIT and rt is INT_LIT:
            expr.left.type = I32; expr.right.type = I32
            return I32, I32
        if lt is FLOAT_LIT and rt is FLOAT_LIT:
            expr.left.type = F32; expr.right.type = F32
            return F32, F32
        if lt in (INT_LIT, FLOAT_LIT) and lit_ok(rt, lt):
            self._check_literal_range(expr.left, rt)
            expr.left.type = rt
            return rt, rt
        if rt in (INT_LIT, FLOAT_LIT) and lit_ok(lt, rt):
            self._check_literal_range(expr.right, lt)
            expr.right.type = lt
            return lt, lt
        return lt, rt

    def _check_literal_range(self, expr, t, ctx=None):
        """A literal written where a narrow integer is expected must fit;
        computed values are still truncated silently."""
        if not is_narrow(t) or not isinstance(expr, A.IntLit):
            return
        lo, hi = NARROW_RANGES[t]
        if not (lo <= expr.value <= hi):
            msg = f"value {expr.value} out of range for {t}"
            if ctx:
                msg = f"{ctx}: {msg}"
            raise CheckError(msg, self.filename, expr.pos)

    def _coerce_value(self, expr, actual, expected, pos, ctx):
        if actual is expected or actual == expected:
            return
        if actual is INT_LIT and (is_int(expected) or is_float(expected)):
            self._check_literal_range(expr, expected, ctx)
            expr.type = expected
            return
        if actual is FLOAT_LIT and is_float(expected):
            expr.type = expected
            return
        if is_narrow(expected) and is_int(actual):
            # C-style truncation: assigning a wider integer to a narrow one
            # keeps the low bits.
            return
        if is_narrow(actual) and (expected is I32 or expected is U32):
            # Reading a narrow value promotes it to i32/u32 (value-preserving).
            return
        if isinstance(actual, ArrayType) and isinstance(expected, ArrayType):
            if actual.size != expected.size:
                raise CheckError(
                    f"{ctx}: array size mismatch ({actual.size} vs {expected.size})",
                    self.filename, pos)
            if actual.inner is expected.inner:
                return
            if isinstance(expr, A.ArrayLit) and hasattr(expr, 'element_types'):
                for i, e in enumerate(expr.elements):
                    raw = expr.element_types[i]
                    self._coerce_value(e, raw, expected.inner, pos, f"array element {i}")
                expr.type = expected
                return
            raise CheckError(f"{ctx}: cannot convert {actual} to {expected}",
                             self.filename, pos)
        if (isinstance(expected, PtrType) and expected.inner is VOID
                and isinstance(actual, PtrType)):
            # C-style widening: any T* is accepted where void* is expected.
            expr.type = expected
            return
        raise CheckError(f"{ctx}: cannot assign {actual} to {expected}", self.filename, pos)

    def _default_type(self, t: Type, expr) -> Type:
        if t is INT_LIT:
            expr.type = I32
            return I32
        if t is FLOAT_LIT:
            expr.type = F32
            return F32
        return t

    def _check_call(self, call: A.Call, expected=None) -> Type:
        f = call.func
        if (isinstance(f, A.Member) and isinstance(f.obj, A.Name)
                and self._lookup(f.obj.name) is None
                and f.obj.name in self.enums):
            return self._check_enum_ctor(self.enums[f.obj.name], f.field, call)
        if (isinstance(f, A.Member) and isinstance(f.obj, A.Name)
                and self._lookup(f.obj.name) is None
                and f.obj.name in self.generic_enums):
            return self._check_generic_enum_ctor(
                self.generic_enums[f.obj.name], f.field, call, expected)
        if isinstance(f, A.Name):
            name = f.name
            # A local binding (parameter or variable) shadows any function
            # or constructor of the same name.
            ent = self._lookup(name)
            if ent is not None:
                if isinstance(ent[0], FuncType):
                    return self._check_indirect_call(call, ent[0])
                raise CheckError(f"cannot call a value of type {ent[0]}",
                                 self.filename, call.pos)
            if name == 'len':
                return self._check_len(call)
            if name == 'enum_to_i32':
                return self._check_enum_to_i32(call)
            if name == 'ptr_is_null':
                return self._check_ptr_is_null(call)
            if name == 'ptr_cast':
                return self._check_ptr_cast(call)
            if name == 'ptr_offset':
                return self._check_ptr_offset(call)
            if name == 'ptr_null':
                return self._check_ptr_null(call)
            if name in ('print_fmt', 'write_fmt'):
                return self._check_fmt(call, name)
            if name in self.generic_functions:
                return self._check_generic_func_call(
                    self.generic_functions[name], call, expected)
            if name in self.generic_structs:
                return self._check_generic_struct_ctor(
                    self.generic_structs[name], call, expected)
            if name in self.structs:
                st = self.structs[name]
                if st.builtin:
                    return self._check_builtin_ctor(st, call)
                return self._check_user_struct_ctor(st, call)
            if name in self.functions:
                return self._check_func_call(name, call)
            if name in self.enums:
                raise CheckError(
                    f"cannot construct '{name}'; use its members, e.g. {name}.Member",
                    self.filename, call.pos)
            if name == 'List':
                raise CheckError("a List is created from an Arena: arena.list::<T>()",
                                 self.filename, call.pos)
            raise CheckError(f"unknown callable '{name}'", self.filename, call.pos)
        if isinstance(f, A.Member):
            ot = self._check_expr(f.obj)
            if isinstance(ot, StructType):
                if f.field in ot.fields:
                    ft = ot.fields[f.field]
                    if isinstance(ft, FuncType):
                        return self._check_indirect_call(call, ft)
                    raise CheckError(f"field '{f.field}' is not callable (type {ft})",
                                     self.filename, call.pos)
                return self._check_method(ot, f.field, call)
            if f.field == 'at':
                if isinstance(ot, PtrType):
                    return self._check_ptr_at(call, ot)
                if isinstance(ot, (ArrayType, ListType)):
                    return self._check_at(call, ot)
                raise CheckError(f"'at' requires an array, a List, or a pointer, got {ot}",
                                 self.filename, call.pos)
            if isinstance(ot, ListType):
                return self._check_list_method(ot, f.field, call)
            raise CheckError(f"type {ot} has no methods", self.filename, call.pos)
        # Any other expression evaluating to a function value, such as an
        # indexed element of an array of functions.
        t = self._default_type(self._check_expr(f), f)
        if isinstance(t, FuncType):
            return self._check_indirect_call(call, t)
        raise CheckError(f"cannot call a value of type {t}", self.filename, call.pos)

    def _check_generic_enum_member(self, info, expr, expected) -> Type:
        label = self._display(info.name)
        if expr.field not in info.members:
            raise CheckError(f"enum '{label}' has no member '{expr.field}'",
                             self.filename, expr.pos)
        if info.payloads.get(expr.field):
            raise CheckError(
                f"enum member '{label}.{expr.field}' carries values; "
                f"construct it with {label}.{expr.field}(...)",
                self.filename, expr.pos)
        if isinstance(expected, EnumType) and expected.family == info.name:
            et = expected
        else:
            params = ', '.join(info.type_params)
            raise CheckError(
                f"cannot infer type parameters for '{label}.{expr.field}'; "
                f"add a type annotation or write "
                f"{label}.{expr.field}::<{params}>()",
                self.filename, expr.pos)
        expr.is_enum_member = True
        expr.type = et
        expr.enum_instance = et
        return et

    def _bind_type_param(self, info, bindings, name, actual, pos):
        if actual is VOID:
            raise CheckError(
                f"cannot use void as type argument for '{name}'",
                self.filename, pos)
        old = bindings.get(name)
        if old is not None and old != actual:
            raise CheckError(
                f"conflicting types for '{name}': "
                f"{self._type_spelling(old)} and {self._type_spelling(actual)}",
                self.filename, pos)
        bindings[name] = actual

    def _infer_type_params(self, te, actual, info, bindings):
        """Infer generic type parameters from a payload or field type."""
        if te is None:
            return
        if te.kind == 'named':
            if te.name in info.type_params:
                self._bind_type_param(info, bindings, te.name, actual, te.pos)
                return
            if (te.args and te.name in self.generic_enums
                    and isinstance(actual, EnumType)
                    and actual.family == te.name
                    and len(te.args) == len(actual.type_args)):
                for sub_te, sub_actual in zip(te.args, actual.type_args):
                    self._infer_type_params(sub_te, sub_actual, info, bindings)
            if (te.args and te.name in self.generic_structs
                    and isinstance(actual, StructType)
                    and actual.family == te.name
                    and len(te.args) == len(actual.type_args)):
                for sub_te, sub_actual in zip(te.args, actual.type_args):
                    self._infer_type_params(sub_te, sub_actual, info, bindings)
            return
        if te.kind == 'ptr' and isinstance(actual, PtrType):
            self._infer_type_params(te.inner, actual.inner, info, bindings)
            return
        if te.kind == 'list' and isinstance(actual, ListType):
            self._infer_type_params(te.inner, actual.inner, info, bindings)
            return
        if te.kind == 'array' and isinstance(actual, ArrayType):
            self._infer_type_params(te.inner, actual.inner, info, bindings)
            return
        if te.kind == 'func' and isinstance(actual, FuncType):
            for sub_te, sub_actual in zip(te.params or [], actual.params):
                self._infer_type_params(sub_te, sub_actual, info, bindings)
            self._infer_type_params(te.inner, actual.ret, info, bindings)

    def _check_generic_enum_ctor(self, info, member, call, expected) -> Type:
        label = self._display(info.name)
        if call.arg_names and any(x is not None for x in call.arg_names):
            raise CheckError("enum constructors do not accept named arguments",
                             self.filename, call.pos)
        if member not in info.members:
            raise CheckError(f"enum '{label}' has no member '{member}'",
                             self.filename, call.pos)
        payload_exprs = tuple(info.payloads.get(member, ()))
        if len(call.args) != len(payload_exprs):
            if not payload_exprs:
                raise CheckError(f"'{label}.{member}' takes no values",
                                 self.filename, call.pos)
            raise CheckError(
                f"'{label}.{member}' expects {len(payload_exprs)} value(s), "
                f"got {len(call.args)}", self.filename, call.pos)

        params = list(info.type_params)
        bindings = {}
        if call.type_args:
            explicit = [self._resolve_type(te) for te in call.type_args]
            if len(explicit) != len(params):
                raise CheckError(
                    f"'{label}.{member}' expects {len(params)} type "
                    f"argument(s), got {len(explicit)}",
                    self.filename, call.pos)
            for pname, arg in zip(params, explicit):
                bindings[pname] = arg
        elif isinstance(expected, EnumType) and expected.family == info.name:
            for pname, arg in zip(params, expected.type_args):
                bindings[pname] = arg

        actuals = []
        if all(pname in bindings for pname in params):
            env = dict(bindings)
            for i, (arg, pte) in enumerate(zip(call.args, payload_exprs)):
                ptype = self._resolve_type(pte, env)
                at = self._check_expr(arg, ptype)
                self._coerce_value(
                    arg, at, ptype, call.pos,
                    f"value {i + 1} of '{label}.{member}'")
                actuals.append(at)
        else:
            for arg, pte in zip(call.args, payload_exprs):
                at = self._check_expr(arg)
                at = self._default_type(at, arg)
                actuals.append(at)
                self._infer_type_params(pte, at, info, bindings)
            missing = [pname for pname in params if pname not in bindings]
            if missing:
                names = ', '.join(f"'{pname}'" for pname in missing)
                word = 'parameter' if len(missing) == 1 else 'parameters'
                type_params = ', '.join(params)
                raise CheckError(
                    f"cannot infer type {word} {names} for "
                    f"'{label}.{member}'; add a type annotation or write "
                    f"{label}.{member}::<{type_params}>(...)",
                    self.filename, call.pos)
            env = dict(bindings)
            for i, (arg, pte) in enumerate(zip(call.args, payload_exprs)):
                ptype = self._resolve_type(pte, env)
                self._coerce_value(
                    arg, actuals[i], ptype, call.pos,
                    f"value {i + 1} of '{label}.{member}'")

        args = tuple(bindings[pname] for pname in params)
        et = self._instantiate_enum(info.name, args, call.pos)
        call.is_enum_ctor = True
        call.type = et
        call.enum_instance = et
        return et

    def _check_enum_ctor(self, et: EnumType, member: str, call: A.Call) -> Type:
        if call.type_args:
            raise CheckError("enum constructors do not accept type arguments",
                             self.filename, call.pos)
        if call.arg_names and any(x is not None for x in call.arg_names):
            raise CheckError("enum constructors do not accept named arguments",
                             self.filename, call.pos)
        if member not in et.members:
            raise CheckError(f"enum '{et.name}' has no member '{member}'",
                             self.filename, call.pos)
        payload = et.payload_of(member)
        if len(call.args) != len(payload):
            if not payload:
                raise CheckError(f"'{et.name}.{member}' takes no values",
                                 self.filename, call.pos)
            raise CheckError(
                f"'{et.name}.{member}' expects {len(payload)} value(s), "
                f"got {len(call.args)}", self.filename, call.pos)
        for i, (arg, ptype) in enumerate(zip(call.args, payload)):
            at = self._check_expr(arg, ptype)
            self._coerce_value(arg, at, ptype, call.pos,
                               f"value {i + 1} of '{et.name}.{member}'")
        call.is_enum_ctor = True
        call.type = et
        return et

    def _check_indirect_call(self, call: A.Call, ft: FuncType) -> Type:
        call.is_indirect_call = True
        if call.type_args:
            raise CheckError("function values do not take type arguments",
                             self.filename, call.pos)
        if call.arg_names and any(x is not None for x in call.arg_names):
            raise CheckError("function values do not accept named arguments",
                             self.filename, call.pos)
        if len(call.args) != len(ft.params):
            raise CheckError(
                f"function value expects {len(ft.params)} argument(s), got {len(call.args)}",
                self.filename, call.pos)
        for arg, ptype in zip(call.args, ft.params):
            at = self._check_expr(arg, ptype)
            if isinstance(at, StructType) and at.name == "Arena":
                raise CheckError("cannot pass Arena to a function", self.filename, call.pos)
            self._coerce_value(arg, at, ptype, call.pos, "argument")
        call.type = ft.ret
        return ft.ret

    def _check_len(self, call: A.Call) -> Type:
        if len(call.args) != 1:
            raise CheckError("len takes one argument", self.filename, call.pos)
        at = self._check_expr(call.args[0])
        if not isinstance(at, (ArrayType, ListType)) and not (
                isinstance(at, StructType) and at.name == "StrBuilder"):
            raise CheckError(f"len expects an array, a List, or a StrBuilder, got {at}",
                             self.filename, call.pos)
        call.type = I32
        return I32

    def _check_enum_to_i32(self, call: A.Call) -> Type:
        if call.type_args:
            raise CheckError("enum_to_i32 does not accept type arguments",
                             self.filename, call.pos)
        if call.arg_names and any(x is not None for x in call.arg_names):
            raise CheckError("enum_to_i32 does not accept named arguments",
                             self.filename, call.pos)
        if len(call.args) != 1:
            raise CheckError(f"enum_to_i32 takes one argument, got {len(call.args)}",
                             self.filename, call.pos)
        at = self._check_expr(call.args[0])
        if not isinstance(at, EnumType):
            raise CheckError(f"enum_to_i32 expects an enum value, got {at}",
                             self.filename, call.pos)
        call.type = I32
        return I32

    def _check_ptr_is_null(self, call: A.Call) -> Type:
        if call.type_args:
            raise CheckError("ptr_is_null does not accept type arguments",
                             self.filename, call.pos)
        if call.arg_names and any(x is not None for x in call.arg_names):
            raise CheckError("ptr_is_null does not accept named arguments",
                             self.filename, call.pos)
        if len(call.args) != 1:
            raise CheckError(f"ptr_is_null takes one argument, got {len(call.args)}",
                             self.filename, call.pos)
        at = self._check_expr(call.args[0])
        if not isinstance(at, (PtrType, FuncType)):
            raise CheckError(
                f"ptr_is_null expects a pointer or a function value, got {at}",
                self.filename, call.pos)
        call.type = BOOL
        return BOOL

    def _check_ptr_cast(self, call: A.Call) -> Type:
        if not call.type_args or len(call.type_args) != 1:
            raise CheckError("ptr_cast requires a type argument: ptr_cast::<T>(p)",
                             self.filename, call.pos)
        if call.arg_names and any(x is not None for x in call.arg_names):
            raise CheckError("ptr_cast does not accept named arguments",
                             self.filename, call.pos)
        if len(call.args) != 1:
            raise CheckError(f"ptr_cast takes one argument, got {len(call.args)}",
                             self.filename, call.pos)
        inner = self._resolve_type(call.type_args[0])
        if _contains_func_type(inner):
            raise CheckError("ptr_cast cannot target a function type",
                             self.filename, call.pos)
        at = self._check_expr(call.args[0])
        if not isinstance(at, PtrType):
            raise CheckError(f"ptr_cast expects a pointer, got {at}",
                             self.filename, call.pos)
        t = PtrType(inner)
        call.type = t
        return t

    def _check_ptr_offset(self, call: A.Call) -> Type:
        if call.type_args:
            raise CheckError("ptr_offset does not accept type arguments",
                             self.filename, call.pos)
        if call.arg_names and any(x is not None for x in call.arg_names):
            raise CheckError("ptr_offset does not accept named arguments",
                             self.filename, call.pos)
        if len(call.args) != 2:
            raise CheckError(f"ptr_offset takes two arguments, got {len(call.args)}",
                             self.filename, call.pos)
        at = self._check_expr(call.args[0])
        if not isinstance(at, PtrType):
            raise CheckError(f"ptr_offset expects a pointer, got {at}",
                             self.filename, call.pos)
        if at.inner is VOID:
            raise CheckError(
                "cannot offset a ptr<void> (it has no element size); "
                "ptr_cast it to a typed pointer first",
                self.filename, call.pos)
        it = self._check_expr(call.args[1])
        self._coerce_value(call.args[1], it, I32, call.pos, "offset")
        t = PtrType(at.inner)
        call.type = t
        return t

    def _check_ptr_null(self, call: A.Call) -> Type:
        if not call.type_args or len(call.type_args) != 1:
            raise CheckError("ptr_null requires a type argument: ptr_null::<T>()",
                             self.filename, call.pos)
        if call.arg_names and any(x is not None for x in call.arg_names):
            raise CheckError("ptr_null does not accept named arguments",
                             self.filename, call.pos)
        if call.args:
            raise CheckError(f"ptr_null takes no arguments, got {len(call.args)}",
                             self.filename, call.pos)
        inner = self._resolve_type(call.type_args[0])
        t = inner if isinstance(inner, FuncType) else PtrType(inner)
        call.type = t
        return t

    def _check_ptr_at(self, call: A.Call, ptr: PtrType) -> Type:
        if call.type_args:
            raise CheckError("'at' does not accept type arguments",
                             self.filename, call.pos)
        if call.arg_names and any(x is not None for x in call.arg_names):
            raise CheckError("'at' does not accept named arguments",
                             self.filename, call.pos)
        if ptr.inner is VOID:
            raise CheckError(
                "cannot use 'at' on a ptr<void> (it has no element type); "
                "ptr_cast it to a typed pointer first",
                self.filename, call.pos)
        if len(call.args) != 2:
            if len(call.args) == 1:
                raise CheckError(
                    "'at' on a pointer needs an index and a size: p.at(i, size)",
                    self.filename, call.pos)
            raise CheckError(
                f"'at' on a pointer expects an index and a size, got {len(call.args)} arguments",
                self.filename, call.pos)
        it = self._check_expr(call.args[0])
        self._coerce_value(call.args[0], it, I32, call.pos, "index")
        st = self._check_expr(call.args[1])
        self._coerce_value(call.args[1], st, I32, call.pos, "size")
        call.is_checked_at = True
        call.type = ptr.inner
        return ptr.inner

    def _check_at(self, call: A.Call, arr: ArrayType) -> Type:
        if call.type_args:
            raise CheckError("'at' does not accept type arguments",
                             self.filename, call.pos)
        if call.arg_names and any(x is not None for x in call.arg_names):
            raise CheckError("'at' does not accept named arguments",
                             self.filename, call.pos)
        if len(call.args) != 1:
            raise CheckError(f"'at' expects one index, got {len(call.args)}",
                             self.filename, call.pos)
        it = self._check_expr(call.args[0])
        self._coerce_value(call.args[0], it, I32, call.pos, "index")
        call.is_checked_at = True
        call.type = arr.inner
        return arr.inner

    def _check_list_method(self, lt: ListType, method: str, call: A.Call) -> Type:
        if method == 'push':
            if call.type_args:
                raise CheckError("'push' does not accept type arguments",
                                 self.filename, call.pos)
            if call.arg_names and any(x is not None for x in call.arg_names):
                raise CheckError("'push' does not accept named arguments",
                                 self.filename, call.pos)
            if len(call.args) != 1:
                raise CheckError(f"'push' expects one value, got {len(call.args)}",
                                 self.filename, call.pos)
            at = self._check_expr(call.args[0], lt.inner)
            if isinstance(at, StructType) and at.name == "Arena":
                raise CheckError("cannot store Arena in a List (it is non-copyable)",
                                 self.filename, call.pos)
            self._coerce_value(call.args[0], at, lt.inner, call.pos, "list element")
            call.type = VOID
            return VOID
        if method == 'pop':
            if call.type_args:
                raise CheckError("'pop' does not accept type arguments",
                                 self.filename, call.pos)
            if call.args:
                raise CheckError(f"'pop' takes no arguments, got {len(call.args)}",
                                 self.filename, call.pos)
            call.type = lt.inner
            return lt.inner
        if method == 'insert':
            if call.type_args:
                raise CheckError("'insert' does not accept type arguments",
                                 self.filename, call.pos)
            if call.arg_names and any(x is not None for x in call.arg_names):
                raise CheckError("'insert' does not accept named arguments",
                                 self.filename, call.pos)
            if len(call.args) != 2:
                raise CheckError(
                    f"'insert' expects an index and a value, got {len(call.args)}",
                    self.filename, call.pos)
            it = self._check_expr(call.args[0])
            self._coerce_value(call.args[0], it, I32, call.pos, "index")
            vt = self._check_expr(call.args[1], lt.inner)
            if isinstance(vt, StructType) and vt.name == "Arena":
                raise CheckError("cannot store Arena in a List (it is non-copyable)",
                                 self.filename, call.pos)
            self._coerce_value(call.args[1], vt, lt.inner, call.pos, "list element")
            call.type = VOID
            return VOID
        if method == 'remove':
            if call.type_args:
                raise CheckError("'remove' does not accept type arguments",
                                 self.filename, call.pos)
            if call.arg_names and any(x is not None for x in call.arg_names):
                raise CheckError("'remove' does not accept named arguments",
                                 self.filename, call.pos)
            if len(call.args) != 1:
                raise CheckError(f"'remove' expects one index, got {len(call.args)}",
                                 self.filename, call.pos)
            it = self._check_expr(call.args[0])
            self._coerce_value(call.args[0], it, I32, call.pos, "index")
            call.type = lt.inner
            return lt.inner
        if method == 'sort':
            if call.type_args:
                raise CheckError("'sort' does not accept type arguments",
                                 self.filename, call.pos)
            if call.arg_names and any(x is not None for x in call.arg_names):
                raise CheckError("'sort' does not accept named arguments",
                                 self.filename, call.pos)
            if len(call.args) != 1:
                raise CheckError(f"'sort' expects one comparator, got {len(call.args)}",
                                 self.filename, call.pos)
            ct = self._default_type(self._check_expr(call.args[0]), call.args[0])
            want = self._func_type((lt.inner, lt.inner), I32)
            if ct != want:
                raise CheckError(
                    f"'sort' expects a comparator "
                    f"func({lt.inner}, {lt.inner}) -> i32, got {ct}",
                    self.filename, call.pos)
            call.type = VOID
            return VOID
        if method == 'len':
            raise CheckError("'len' is not a List method; write len(xs)",
                             self.filename, call.pos)
        raise CheckError(f"List has no method '{method}'", self.filename, call.pos)

    def _check_fmt(self, call: A.Call, name: str) -> Type:
        if call.arg_names and any(x is not None for x in call.arg_names):
            raise CheckError(f"{name} does not accept named arguments", self.filename, call.pos)
        if not call.args:
            raise CheckError(f"{name} requires a format string", self.filename, call.pos)
        fmt = call.args[0]
        if not isinstance(fmt, A.StringLit):
            raise CheckError(f"{name} format must be a string literal", self.filename, call.pos)
        try:
            _pieces, n_ph = parse_format(fmt.value)
        except ValueError as e:
            raise CheckError(f"{name}: {e}", self.filename, call.pos)
        extra = call.args[1:]
        if len(extra) != n_ph:
            raise CheckError(
                f"{name}: format string has {n_ph} placeholder(s) "
                f"but {len(extra)} argument(s) were given",
                self.filename, call.pos)
        allowed = (I8, U8, I16, U16, I32, U32, F32, F64, BOOL, STR)
        for a in extra:
            at = self._default_type(self._check_expr(a), a)
            if not any(at is t for t in allowed):
                raise CheckError(
                    f"{name}: cannot format a value of type {at} "
                    f"(expected an integer, f32, f64, bool, or str)",
                    self.filename, call.pos)
        call.type = VOID
        return VOID

    def _check_builtin_ctor(self, st: StructType, call: A.Call) -> Type:
        n = st.name
        if n == "Vec2":
            self._check_fields_or_positional(call, ["x", "y"], F32)
        elif n == "Vec3":
            self._check_fields_or_positional(call, ["x", "y", "z"], F32)
        elif n == "Quat":
            if call.args:
                self._check_fields_or_positional(call, ["x", "y", "z", "w"], F32)
        elif n == "Matrix4":
            if call.args:
                raise CheckError("Matrix4() takes no arguments", self.filename, call.pos)
        elif n == "Arena":
            if len(call.args) != 1:
                raise CheckError("Arena(size) requires one argument", self.filename, call.pos)
            if call.arg_names and any(x is not None for x in call.arg_names):
                raise CheckError("Arena does not accept named arguments", self.filename, call.pos)
            at = self._check_expr(call.args[0])
            self._coerce_value(call.args[0], at, I32, call.pos, "Arena size")
        elif n == "StrBuilder":
            raise CheckError(
                "a StrBuilder is created from an Arena: arena.str_builder()",
                self.filename, call.pos)
        call.type = st
        return st

    def _check_fields_or_positional(self, call, fields, ftype):
        if call.arg_names and any(x is not None for x in call.arg_names):
            names = call.arg_names
            if any(x is None for x in names):
                raise CheckError("cannot mix named and positional arguments", self.filename, call.pos)
            seen = set()
            for nm, arg in zip(names, call.args):
                if nm not in fields:
                    raise CheckError(f"unknown field '{nm}'", self.filename, call.pos)
                if nm in seen:
                    raise CheckError(f"duplicate field '{nm}'", self.filename, call.pos)
                seen.add(nm)
                at = self._check_expr(arg, ftype)
                self._coerce_value(arg, at, ftype, call.pos, f"field '{nm}'")
            if len(seen) != len(fields):
                raise CheckError("missing fields in constructor", self.filename, call.pos)
            by_name = dict(zip(names, call.args))
            call.args = [by_name[f] for f in fields]
            call.arg_names = None
        else:
            if len(call.args) != len(fields):
                raise CheckError(f"expected {len(fields)} arguments, got {len(call.args)}", self.filename, call.pos)
            for arg in call.args:
                at = self._check_expr(arg, ftype)
                self._coerce_value(arg, at, ftype, call.pos, "argument")

    def _check_generic_struct_ctor(self, info, call, expected) -> Type:
        label = self._display(info.name)
        if not call.arg_names or any(x is None for x in call.arg_names):
            if len(call.args) != len(st.fields):
                raise CheckError("struct construction requires named arguments",
                                 self.filename, call.pos)
            out = []
            for f, arg in zip(st.fields, call.args):
                at = self._check_expr(arg, st.fields[f])
                self._coerce_value(arg, at, st.fields[f], call.pos,
                                   f"field '{f}'")
                out.append(arg)
            call.args = out
            call.arg_names = None
            call.type = st
            return st
        by_name = {}
        for nm, arg in zip(call.arg_names, call.args):
            if nm in by_name:
                raise CheckError(f"duplicate field '{nm}'",
                                 self.filename, call.pos)
            if nm not in {f[0] for f in info.fields}:
                raise CheckError(f"unknown field '{nm}'",
                                 self.filename, call.pos)
            by_name[nm] = arg
        missing = [f[0] for f in info.fields if f[0] not in by_name]
        if missing:
            raise CheckError(f"missing fields: {', '.join(missing)}",
                             self.filename, call.pos)

        params = list(info.type_params)
        bindings = {}
        if call.type_args:
            explicit = [self._resolve_type(te) for te in call.type_args]
            if len(explicit) != len(params):
                raise CheckError(
                    f"'{label}' expects {len(params)} type argument(s), "
                    f"got {len(explicit)}", self.filename, call.pos)
            for pname, arg in zip(params, explicit):
                bindings[pname] = arg
        elif isinstance(expected, StructType) and expected.family == info.name:
            for pname, arg in zip(params, expected.type_args):
                bindings[pname] = arg
        else:
            for fname, fte, _fpos in info.fields:
                arg = by_name[fname]
                at = self._check_expr(arg)
                at = self._default_type(at, arg)
                self._infer_type_params(fte, at, info, bindings)
            missing_params = [p for p in params if p not in bindings]
            if missing_params:
                names = ', '.join(f"'{p}'" for p in missing_params)
                word = 'parameter' if len(missing_params) == 1 else 'parameters'
                type_params = ', '.join(params)
                raise CheckError(
                    f"cannot infer type {word} {names} for '{label}'; "
                    f"add a type annotation or write "
                    f"{label}::<{type_params}>(...)",
                    self.filename, call.pos)

        args = tuple(bindings[pname] for pname in params)
        st = self._instantiate_struct(info.name, args, call.pos)
        ordered = [f[0] for f in info.fields]
        call.args = [by_name[n] for n in ordered]
        call.arg_names = list(ordered)
        result = self._check_user_struct_ctor(st, call)
        call.is_struct_ctor = True
        return result

    def _check_generic_func_call(self, info, call, expected) -> Type:
        label = self._display(info.name)
        if (call.arg_names and any(x is not None for x in call.arg_names)):
            by_name = {}
            for nm, arg in zip(call.arg_names, call.args):
                if nm in by_name:
                    raise CheckError(f"duplicate argument '{nm}'",
                                     self.filename, call.pos)
                by_name[nm] = arg
            params_list = list(info.params)
            args_list = [by_name[pname] for (pname, _) in params_list]
            call.args = args_list
            call.arg_names = None
        params_list = list(info.params)
        if len(call.args) != len(params_list):
            raise CheckError(
                f"'{label}' expects {len(params_list)} argument(s), "
                f"got {len(call.args)}", self.filename, call.pos)

        generic_params = list(info.type_params)
        bindings = {}
        if call.type_args:
            explicit = [self._resolve_type(te) for te in call.type_args]
            if len(explicit) != len(generic_params):
                raise CheckError(
                    f"'{label}' expects {len(generic_params)} type "
                    f"argument(s), got {len(explicit)}",
                    self.filename, call.pos)
            for pname, arg in zip(generic_params, explicit):
                bindings[pname] = arg
        elif not generic_params:
            pass
        else:
            for arg, (_, pte) in zip(call.args, params_list):
                at = self._check_expr(arg)
                at = self._default_type(at, arg)
                self._infer_type_params(pte, at, info, bindings)
            missing = [pname for pname in generic_params
                       if pname not in bindings]
            if missing:
                names = ', '.join(f"'{pname}'" for pname in missing)
                word = 'parameter' if len(missing) == 1 else 'parameters'
                type_params = ', '.join(generic_params)
                raise CheckError(
                    f"cannot infer type {word} {names} for '{label}'; "
                    f"add a type annotation or write "
                    f"{label}::<{type_params}>(...)",
                    self.filename, call.pos)

        args_tuple = tuple(bindings[pname] for pname in generic_params)
        concrete_name = self._instantiate_generic_func(info, args_tuple,
                                                      call.pos)
        sig = self.functions[concrete_name]
        for i, arg in enumerate(call.args):
            ptype = sig.params[i][1]
            at = getattr(arg, 'type', None)
            if at is None:
                at = self._check_expr(arg, ptype)
            self._coerce_value(arg, at, ptype, call.pos,
                               f"argument {i + 1} of '{label}'")
        call.type = sig.ret
        call.generic_func_instance = concrete_name
        return sig.ret

    def _instantiate_generic_func(self, info, args, pos) -> str:
        if not info.type_params and args:
            raise CheckError("too many type arguments", self.filename, pos)
        if len(args) != len(info.type_params):
            raise CheckError(
                f"'{self._display(info.name)}' expects "
                f"{len(info.type_params)} type argument(s), got {len(args)}",
                self.filename, pos)
        key = (info.name, tuple(args))
        existing = self.generic_func_instances.get(key)
        if existing is not None:
            return existing
        for arg, param in zip(args, info.type_params):
            if arg is VOID:
                raise CheckError(
                    f"type argument for '{param}' cannot be void",
                    self.filename, pos)
            if isinstance(arg, (InferType, IntLitType, FloatLitType)):
                raise CheckError(
                    f"type argument for '{param}' must be a concrete type, "
                    f"got {arg}", self.filename, pos)
        while True:
            self.generic_func_counter += 1
            internal = f"{info.name}__g{self.generic_func_counter - 1}"
            if (internal not in self.functions
                    and internal not in self.generic_functions):
                break
        env = dict(zip(info.type_params, args))
        clone = A.FuncDecl(
            name=internal,
            params=[A.Param(pname, ptype, info.pos)
                    for (pname, ptype) in info.params],
            ret=info.ret,
            body=info.body,
            is_system=info.is_system,
            pos=info.pos,
            is_public=info.is_public,
            type_params=[])
        # params in info are (name, TypeExpr), adapt
        self._current_type_env = env
        try:
            self.program.decls.append(clone)
            self._register_func(clone)
            self._check_func(clone)
        finally:
            self._current_type_env = None
        self.generic_func_instances[key] = internal
        return internal

    def _check_user_struct_ctor(self, st: StructType, call: A.Call) -> Type:
        if not call.arg_names or any(x is None for x in call.arg_names):
            raise CheckError("struct construction requires named arguments", self.filename, call.pos)
        seen = set()
        by_name = {}
        for nm, arg in zip(call.arg_names, call.args):
            if nm not in st.fields:
                raise CheckError(f"unknown field '{nm}'", self.filename, call.pos)
            if nm in seen:
                raise CheckError(f"duplicate field '{nm}'", self.filename, call.pos)
            seen.add(nm)
            at = self._check_expr(arg, st.fields[nm])
            self._coerce_value(arg, at, st.fields[nm], call.pos, f"field '{nm}'")
            by_name[nm] = arg
        if len(seen) != len(st.fields):
            missing = set(st.fields) - seen
            raise CheckError(f"missing fields: {', '.join(sorted(missing))}", self.filename, call.pos)
        call.args = [by_name[f] for f in st.fields]
        call.arg_names = None
        call.type = st
        return st

    def _check_func_call(self, name: str, call: A.Call) -> Type:
        sig = self.functions[name]
        if isinstance(sig.ret, InferType):
            raise CheckError(
                f"call to '{name}' before its return type is inferred; "
                f"add explicit '-> T' or move its declaration before this caller",
                self.filename, call.pos)
        if call.arg_names and any(x is not None for x in call.arg_names):
            raise CheckError(f"function '{name}' does not accept named arguments", self.filename, call.pos)
        if len(call.args) != len(sig.params):
            raise CheckError(f"'{name}' expects {len(sig.params)} arguments, got {len(call.args)}", self.filename, call.pos)
        for arg, (_, ptype) in zip(call.args, sig.params):
            at = self._check_expr(arg, ptype)
            if isinstance(at, StructType) and at.name == "Arena":
                raise CheckError("cannot pass Arena to a function", self.filename, call.pos)
            self._coerce_value(arg, at, ptype, call.pos, "argument")
        call.type = sig.ret
        return sig.ret

    def _check_method(self, st: StructType, method: str, call: A.Call) -> Type:
        if st.name == "Arena":
            if method == "reset":
                if call.args:
                    raise CheckError("reset() takes no arguments", self.filename, call.pos)
                call.type = VOID
                return VOID
            if method == "alloc":
                if not call.type_args or len(call.type_args) != 1:
                    raise CheckError("alloc requires a type argument: alloc::<T>(count)", self.filename, call.pos)
                if len(call.args) != 1:
                    raise CheckError("alloc::<T>(count) requires one argument", self.filename, call.pos)
                at = self._check_expr(call.args[0])
                self._coerce_value(call.args[0], at, I32, call.pos, "alloc count")
                inner = self._resolve_type(call.type_args[0])
                if inner is VOID:
                    raise CheckError("cannot allocate void", self.filename, call.pos)
                t = PtrType(inner)
                call.type = t
                return t
            if method == "list":
                if not call.type_args or len(call.type_args) != 1:
                    raise CheckError("list requires a type argument: list::<T>()",
                                     self.filename, call.pos)
                if call.args:
                    raise CheckError("list::<T>() takes no arguments",
                                     self.filename, call.pos)
                inner = self._resolve_type(call.type_args[0])
                t = self._make_list_type(inner, call.pos)
                call.type = t
                return t
            if method == "str_builder":
                if call.type_args:
                    raise CheckError("str_builder() does not accept type arguments",
                                     self.filename, call.pos)
                if call.args:
                    raise CheckError("str_builder() takes no arguments",
                                     self.filename, call.pos)
                t = self.structs["StrBuilder"]
                call.type = t
                return t
            raise CheckError(f"Arena has no method '{method}'", self.filename, call.pos)
        if st.name in ("Vec2", "Vec3"):
            if method == "dot":
                if len(call.args) != 1:
                    raise CheckError("dot takes one argument", self.filename, call.pos)
                at = self._check_expr(call.args[0])
                if at is not st:
                    raise CheckError(f"dot expects {st.name}", self.filename, call.pos)
                call.type = F32; return F32
            if method == "length":
                if call.args:
                    raise CheckError("length takes no arguments", self.filename, call.pos)
                call.type = F32; return F32
            if method == "cross" and st.name == "Vec3":
                if len(call.args) != 1:
                    raise CheckError("cross takes one argument", self.filename, call.pos)
                at = self._check_expr(call.args[0])
                if at is not st:
                    raise CheckError("cross expects Vec3", self.filename, call.pos)
                call.type = st; return st
            if method == "normalized":
                if call.args:
                    raise CheckError("normalized takes no arguments", self.filename, call.pos)
                call.type = st; return st
        if st.name == "Quat":
            if method == "length":
                if call.args:
                    raise CheckError("length takes no arguments", self.filename, call.pos)
                call.type = F32; return F32
            if method == "normalized":
                if call.args:
                    raise CheckError("normalized takes no arguments", self.filename, call.pos)
                call.type = st; return st
            if method == "dot":
                if len(call.args) != 1:
                    raise CheckError("dot takes one argument", self.filename, call.pos)
                at = self._check_expr(call.args[0])
                if at is not st:
                    raise CheckError("dot expects Quat", self.filename, call.pos)
                call.type = F32; return F32
        if st.name == "StrBuilder":
            return self._check_strbuilder_method(method, call)
        raise CheckError(f"type {st.name} has no method '{method}'", self.filename, call.pos)

    def _check_strbuilder_method(self, method: str, call: A.Call) -> Type:
        appends = {
            "append_str": STR,
            "append_i32": I32,
            "append_u32": U32,
            "append_f32": F32,
            "append_f64": F64,
            "append_bool": BOOL,
        }
        if method in appends:
            if call.type_args:
                raise CheckError(f"'{method}' does not accept type arguments",
                                 self.filename, call.pos)
            if call.arg_names and any(x is not None for x in call.arg_names):
                raise CheckError(f"'{method}' does not accept named arguments",
                                 self.filename, call.pos)
            if len(call.args) != 1:
                raise CheckError(f"'{method}' expects one value, got {len(call.args)}",
                                 self.filename, call.pos)
            at = self._check_expr(call.args[0])
            self._coerce_value(call.args[0], at, appends[method], call.pos, "append value")
            call.type = VOID
            return VOID
        if method == "to_str":
            if call.type_args:
                raise CheckError("'to_str' does not accept type arguments",
                                 self.filename, call.pos)
            if call.args:
                raise CheckError(f"'to_str' takes no arguments, got {len(call.args)}",
                                 self.filename, call.pos)
            call.type = STR
            return STR
        if method == "clear":
            if call.type_args:
                raise CheckError("'clear' does not accept type arguments",
                                 self.filename, call.pos)
            if call.args:
                raise CheckError(f"'clear' takes no arguments, got {len(call.args)}",
                                 self.filename, call.pos)
            call.type = VOID
            return VOID
        raise CheckError(f"StrBuilder has no method '{method}'", self.filename, call.pos)