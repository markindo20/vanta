from . import ast_nodes as A
from . import VERSION
from .formats import parse_format
from .typesys import (
    PrimType, IntLitType, FloatLitType, PtrType, ArrayType, ListType, InferType,
    StructType, EnumType, FuncType,
    I8, U8, I16, U16, I32, U32, F32, F64, BOOL, VOID, STR, INT_LIT, FLOAT_LIT,
    is_narrow, eq_blocker,
)


BUILTIN_FN = {
    'print_i32': 'vanta::print_i32', 'print_u32': 'vanta::print_u32',
    'print_f32': 'vanta::print_f32', 'print_f64': 'vanta::print_f64',
    'print_bool': 'vanta::print_bool', 'print_str': 'vanta::print_str',
    'write_i32': 'vanta::write_i32', 'write_u32': 'vanta::write_u32',
    'write_f32': 'vanta::write_f32', 'write_f64': 'vanta::write_f64',
    'write_bool': 'vanta::write_bool', 'write_str': 'vanta::write_str',
    'print_newline': 'vanta::print_newline',
    'sqrt_f32': 'vanta::sqrt_f32', 'sqrt_f64': 'vanta::sqrt_f64',
    'sin_f32': 'vanta::sin_f32', 'sin_f64': 'vanta::sin_f64',
    'cos_f32': 'vanta::cos_f32', 'cos_f64': 'vanta::cos_f64',
    'tan_f32': 'vanta::tan_f32', 'tan_f64': 'vanta::tan_f64',
    'atan2_f32': 'vanta::atan2_f32', 'atan2_f64': 'vanta::atan2_f64',
    'abs_i32': 'vanta::abs_i32', 'abs_f32': 'vanta::abs_f32',
    'min_i32': 'vanta::min_i32', 'max_i32': 'vanta::max_i32',
    'min_f32': 'vanta::min_f32', 'max_f32': 'vanta::max_f32',
    'floor_f32': 'vanta::floor_f32', 'ceil_f32': 'vanta::ceil_f32',
    'i32_to_f32': 'vanta::i32_to_f32', 'f32_to_i32': 'vanta::f32_to_i32',
    'rand_f32': 'vanta::rand_f32', 'rand_seed': 'vanta::rand_seed',
    'arg_count': 'vanta::arg_count', 'arg_str': 'vanta::arg_str',
    'str_concat': 'vanta::str_concat', 'str_len': 'vanta::str_len',
    'str_to_i32': 'vanta::str_to_i32', 'str_to_f32': 'vanta::str_to_f32',
    'to_str_i32': 'vanta::to_str_i32', 'to_str_f32': 'vanta::to_str_f32',
    'to_str_bool': 'vanta::to_str_bool', 'str_pool_reset': 'vanta::str_pool_reset',
    'file_exists': 'vanta::file_exists', 'file_write': 'vanta::file_write',
    'file_read': 'vanta::file_read',
}


# printf conversion for each formattable Vanta type. Narrow integers are
# promoted to int by the C varargs rules, so %d is right for all of them.
FMT_SPEC = {
    'i8': '%d', 'u8': '%d', 'i16': '%d', 'u16': '%d',
    'i32': '%d', 'u32': '%u', 'f32': '%f', 'f64': '%lf',
    'bool': '%s', 'str': '%s',
}


def _c_escape(s: str) -> str:
    """Escape literal format text for a C string, including printf's '%'."""
    out = []
    for ch in s:
        if ch == '\\':
            out.append('\\\\')
        elif ch == '"':
            out.append('\\"')
        elif ch == '\n':
            out.append('\\n')
        elif ch == '\t':
            out.append('\\t')
        elif ch == '\r':
            out.append('\\r')
        elif ch == '%':
            out.append('%%')
        else:
            out.append(ch)
    return ''.join(out)


def build_fmt_c_string(fmt: str, arg_type_names, newline: bool) -> str:
    """Turn a Vanta format literal plus argument types into a printf format."""
    pieces, _n = parse_format(fmt)
    parts = []
    for i, piece in enumerate(pieces):
        parts.append(_c_escape(piece))
        if i < len(arg_type_names):
            parts.append(FMT_SPEC[arg_type_names[i]])
    if newline:
        parts.append('\\n')
    return ''.join(parts)

BUILTIN_MATH_CTOR = {
    'translation': 'vanta::mat4_translation',
    'scale': 'vanta::mat4_scale',
    'from_quat': 'vanta::mat4_from_quat',
}


def cpp_type(t):
    if t is I8: return 'int8_t'
    if t is U8: return 'uint8_t'
    if t is I16: return 'int16_t'
    if t is U16: return 'uint16_t'
    if t is I32: return 'int32_t'
    if t is U32: return 'uint32_t'
    if t is F32: return 'float'
    if t is F64: return 'double'
    if t is BOOL: return 'bool'
    if t is VOID: return 'void'
    if t is STR: return 'const char*'
    if t is INT_LIT: return 'int32_t'
    if t is FLOAT_LIT: return 'float'
    if isinstance(t, FuncType):
        raise ValueError("internal: function types must go through CodeGen._ctype")
    if isinstance(t, PtrType): return cpp_type(t.inner) + '*'
    if isinstance(t, ArrayType): return f'std::array<{cpp_type(t.inner)}, {t.size}>'
    if isinstance(t, ListType): return f'vanta::List<{cpp_type(t.inner)}>'
    if isinstance(t, StructType):
        if t.builtin: return 'vanta::' + t.name
        return t.name
    if isinstance(t, EnumType): return t.name
    raise ValueError(f"unknown type {t}")


def _func_types_in(t):
    """Yield function types appearing inside t (directly or wrapped)."""
    if isinstance(t, FuncType):
        yield t
    elif isinstance(t, PtrType):
        yield from _func_types_in(t.inner)
    elif isinstance(t, ArrayType):
        yield from _func_types_in(t.inner)
    elif isinstance(t, ListType):
        yield from _func_types_in(t.inner)


def _escape_cpp_string(s: str) -> str:
    out = ['"']
    for ch in s:
        if ch == '\\': out.append('\\\\')
        elif ch == '"': out.append('\\"')
        elif ch == '\n': out.append('\\n')
        elif ch == '\t': out.append('\\t')
        elif ch == '\r': out.append('\\r')
        elif ch == '\0': out.append('\\0')
        elif ord(ch) < 32: out.append(f'\\x{ord(ch):02x}')
        else: out.append(ch)
    out.append('"')
    return ''.join(out)


class CodeGen:
    def __init__(self, program: A.Program, tc):
        self.program = program
        self.tc = tc
        self.lines = []
        self.indent = 0
        self.temp_counter = 0

    def emit(self, s=''):
        self.lines.append('    ' * self.indent + s)

    def _ctype(self, t) -> str:
        """C++ spelling of a Vanta type, resolving function-type aliases."""
        if isinstance(t, FuncType):
            try:
                return self.tc.func_types[t]
            except KeyError:
                raise RuntimeError(f"internal: function type {t} was never registered")
        if isinstance(t, PtrType):
            return self._ctype(t.inner) + '*'
        if isinstance(t, ArrayType):
            return f'std::array<{self._ctype(t.inner)}, {t.size}>'
        if isinstance(t, ListType):
            return f'vanta::List<{self._ctype(t.inner)}>'
        return cpp_type(t)

    def _func_target(self, t):
        """(function type, extra pointer levels) for a function type or a
        chain of pointers to one; (None, 0) otherwise."""
        stars = 0
        while isinstance(t, PtrType):
            stars += 1
            t = t.inner
        if not isinstance(t, FuncType):
            return None, 0
        return t, stars

    def _ctype_c(self, t) -> str:
        """C spelling for extern signatures: function types expand inline
        (the FnPtr aliases live inside the namespace and come later), and
        user structs are qualified (their tags are forward-declared above)."""
        ft, _stars = self._func_target(t)
        if ft is not None:
            return self._declarator_c(t, '')
        if isinstance(t, PtrType):
            return self._ctype_c(t.inner) + '*'
        if isinstance(t, ArrayType):
            return f'std::array<{self._ctype_c(t.inner)}, {t.size}>'
        if isinstance(t, ListType):
            return f'vanta::List<{self._ctype_c(t.inner)}>'
        if isinstance(t, StructType) and not t.builtin:
            return f'vanta_user::{t.name}'
        if isinstance(t, EnumType):
            return f'vanta_user::{t.name}'
        return cpp_type(t)

    def _declarator_c(self, t, name: str) -> str:
        """C declarator for a value called `name`: a function type folds the
        name into its stars, and a function-typed return nests around it —
        'int32_t(*v_f)(int32_t)', 'int32_t(*(*get())(void))(void)'."""
        ft, stars = self._func_target(t)
        if ft is None:
            sep = '' if name.startswith('(') else ' '
            return f'{self._ctype_c(t)}{sep}{name}'
        params = ', '.join(self._ctype_c(p) for p in ft.params)
        return self._declarator_c(ft.ret, f'(*{"*" * stars}{name})({params})')

    def _ordered_func_types(self):
        """Registered function types, innermost first so aliases can nest."""
        ordered, seen = [], set()

        def visit(ft):
            if ft in seen:
                return
            seen.add(ft)
            for p in ft.params:
                for inner in _func_types_in(p):
                    visit(inner)
            for inner in _func_types_in(ft.ret):
                visit(inner)
            ordered.append(ft)

        for ft in self.tc.func_types:
            visit(ft)
        return ordered

    def generate(self) -> str:
        self.emit(f'// Generated by Vanta {VERSION} — do not edit.')
        self.emit('#include "vanta_runtime.hpp"')
        self.emit('#include <cstdint>')
        self.emit('#include <array>')
        self.emit('')

        # Extern declarations (outside namespace)
        externs = [d for d in self.program.decls if isinstance(d, A.ExternDecl)]
        structs = [d for d in self.program.decls if isinstance(d, A.StructDecl)]
        enums = [d for d in self.program.decls if isinstance(d, A.EnumDecl)]

        # Tags ahead of the extern block: an extern signature may mention a
        # user struct or enum (a callback carrying a ptr<State>, say), and
        # the definitions live inside the namespace below.
        if externs and (structs or enums):
            self.emit('namespace vanta_user {')
            self.indent += 1
            for ed in enums:
                self.emit(f'enum class {ed.name} : int32_t;')
            for sd in structs:
                self.emit(f'struct {sd.name};')
            self.indent -= 1
            self.emit('}')
            self.emit('')

        for ed in externs:
            self._gen_extern(ed)
        if externs:
            self.emit('')

        self.emit('namespace vanta_user {')
        self.indent += 1

        # Enums first: structs, constants, and signatures may use them.
        for ed in [d for d in self.program.decls if isinstance(d, A.EnumDecl)]:
            self._gen_enum(ed)

        # Struct tags come before the function-pointer aliases: an alias may
        # mention a struct by value (a comparator func(Item, Item) -> i32),
        # and the struct definitions come after the aliases because a struct
        # field may hold a function value.
        for sd in structs:
            self.emit(f'struct {sd.name};')
        self.emit('')

        # Function-pointer aliases, innermost first.
        if self.tc.func_types:
            for ft in self._ordered_func_types():
                params = ', '.join(self._ctype(p) for p in ft.params)
                self.emit(f'using {self.tc.func_types[ft]} = {self._ctype(ft.ret)}(*)({params});')
            self.emit('')

        consts = [d for d in self.program.decls if isinstance(d, A.ConstDecl)]
        for cd in consts:
            t = self.tc.constants[cd.name]
            self.emit(f'constexpr {self._ctype(t)} v_{cd.name} = {self._expr(cd.value)};')
        if consts:
            self.emit('')

        for sd in structs:
            self._gen_struct(sd)
        self._gen_struct_eq(structs)
        funcs = [d for d in self.program.decls if isinstance(d, A.FuncDecl)]
        for fd in funcs:
            self.emit(self._func_sig(fd) + ';')
        self.emit('')
        for fd in funcs:
            self._gen_func(fd)
        self.indent -= 1
        self.emit('}  // namespace vanta_user')
        self.emit('')
        main = next((f for f in funcs if f.name == 'main'), None)
        if main is not None:
            self.emit('int main(int argc, char** argv) {')
            self.indent += 1
            self.emit('vanta::set_args(argc, argv);')
            self.emit('vanta_user::fn_main();')
            self.emit('return 0;')
            self.indent -= 1
            self.emit('}')
        return '\n'.join(self.lines) + '\n'

    def _func_sig(self, fn: A.FuncDecl, extern=False):
        sig = self.tc.functions[fn.name]
        ret = sig.ret
        if isinstance(ret, InferType):
            raise RuntimeError(f"internal: return type of '{fn.name}' was not inferred")
        if extern:
            # Extern signatures are spelled in plain C terms: no aliases.
            # A function-typed return folds the declarator into the name:
            # int32_t(*get())(int32_t), not a bare type before the name.
            params = ', '.join(self._declarator_c(sig.params[i][1], f'v_{p.name}')
                               for i, p in enumerate(fn.params))
            return self._declarator_c(ret, f'{fn.name}({params})')
        ret_s = self._ctype(ret)
        params = ', '.join(f'{self._ctype(sig.params[i][1])} v_{p.name}'
                           for i, p in enumerate(fn.params))
        return f'{ret_s} fn_{fn.name}({params})'

    def _gen_enum(self, ed: A.EnumDecl):
        et = self.tc.enums[ed.name]
        body = ', '.join(f'{m} = {v}' for m, v in et.members.items())
        self.emit(f'enum class {ed.name} : int32_t {{ {body} }};')
        self.emit('')

    def _gen_struct(self, sd: A.StructDecl):
        st = self.tc.structs[sd.name]
        self.emit(f'struct {sd.name} {{')
        self.indent += 1
        for fname, ftype in st.fields.items():
            self.emit(f'{self._ctype(ftype)} v_{fname};')
        self.indent -= 1
        self.emit('};')
        self.emit('')

    def _equality_fields(self, sd: A.StructDecl):
        st = self.tc.structs[sd.name]
        if st.builtin or eq_blocker(st) is not None:
            return None
        return st

    def _gen_struct_eq(self, structs):
        """Component-wise == and != for user structs whose fields all have
        equality. Declarations come first so nested structs can refer to
        each other's operators in any declaration order."""
        eqs = [st for st in (self._equality_fields(sd) for sd in structs)
               if st is not None]
        if not eqs:
            return
        for st in eqs:
            self.emit(f'inline bool operator==(const {st.name}& a, const {st.name}& b);')
            self.emit(f'inline bool operator!=(const {st.name}& a, const {st.name}& b);')
        self.emit('')
        for st in eqs:
            terms = [self._eq_expr(ft, f'a.v_{fn}', f'b.v_{fn}')
                     for fn, ft in st.fields.items()]
            body = ' && '.join(terms) if terms else 'true'
            self.emit(f'inline bool operator==(const {st.name}& a, const {st.name}& b) {{')
            self.indent += 1
            self.emit(f'return {body};')
            self.indent -= 1
            self.emit('}')
            self.emit(f'inline bool operator!=(const {st.name}& a, const {st.name}& b) '
                      f'{{ return !(a == b); }}')
            self.emit('')

    def _eq_expr(self, t, lhs, rhs) -> str:
        """A C++ expression comparing two values of type t with Vanta
        semantics (str compares by content, arrays element-wise)."""
        if t is STR:
            return f'vanta::str_eq({lhs}, {rhs})'
        if isinstance(t, ArrayType):
            parts = [self._eq_expr(t.inner, f'{lhs}[{i}]', f'{rhs}[{i}]')
                     for i in range(t.size)]
            return '(' + ' && '.join(parts) + ')'
        return f'({lhs} == {rhs})'

    def _init_expr(self, e, target) -> str:
        """An element of a braced initializer. C++ rejects narrowing inside
        braces, so an integer expression headed for a narrow field or
        element gets an explicit truncating cast."""
        et = getattr(e, 'type', None)
        if is_narrow(target) and isinstance(et, PrimType) and et is not target:
            return f'static_cast<{self._ctype(target)}>({self._expr(e)})'
        return self._expr(e)

    def _gen_func(self, fn: A.FuncDecl):
        sig = self._func_sig(fn)
        self.emit(sig + ' {')
        self.indent += 1
        for stmt in fn.body:
            self._gen_stmt(stmt)
        ret_type = self.tc.functions[fn.name].ret
        if ret_type is not VOID:
            if ret_type is STR:
                self.emit('return "";')
            elif isinstance(ret_type, PtrType):
                self.emit('return nullptr;')
            else:
                self.emit(f'return {self._ctype(ret_type)}{{}};')
        self.indent -= 1
        self.emit('}')
        self.emit('')

    def _gen_extern(self, ed: A.ExternDecl):
        self.emit(f'extern "C" {{')
        self.indent += 1
        for fd in ed.funcs:
            sig = self._func_sig(fd, extern=True)
            self.emit(sig + ';')
        self.indent -= 1
        self.emit('}')
        self.emit('')

    def _gen_stmt(self, stmt):
        if isinstance(stmt, A.VarDecl):
            tt = getattr(stmt, 'var_type', None)
            self.emit(f'{self._ctype(tt)} v_{stmt.name} = {self._expr(stmt.value)};')
        elif isinstance(stmt, A.AssignStmt):
            self.emit(f'{self._lvalue(stmt.target)} = {self._expr(stmt.value)};')
        elif isinstance(stmt, A.ReturnStmt):
            if stmt.value is None:
                self.emit('return;')
            else:
                self.emit(f'return {self._expr(stmt.value)};')
        elif isinstance(stmt, A.BreakStmt):
            self.emit('break;')
        elif isinstance(stmt, A.ContinueStmt):
            self.emit('continue;')
        elif isinstance(stmt, A.IfStmt):
            self.emit(f'if ({self._expr(stmt.cond)}) {{')
            self.indent += 1
            for s in stmt.then_body: self._gen_stmt(s)
            self.indent -= 1
            for (c, body) in stmt.elif_branches:
                self.emit(f'}} else if ({self._expr(c)}) {{')
                self.indent += 1
                for s in body: self._gen_stmt(s)
                self.indent -= 1
            if stmt.else_body is not None:
                self.emit('} else {')
                self.indent += 1
                for s in stmt.else_body: self._gen_stmt(s)
                self.indent -= 1
            self.emit('}')
        elif isinstance(stmt, A.WhileStmt):
            self.emit(f'while ({self._expr(stmt.cond)}) {{')
            self.indent += 1
            for s in stmt.body: self._gen_stmt(s)
            self.indent -= 1
            self.emit('}')
        elif isinstance(stmt, A.ForRangeStmt):
            self._gen_for(stmt)
        elif isinstance(stmt, A.ForEachStmt):
            self._gen_foreach(stmt)
        elif isinstance(stmt, A.MatchStmt):
            self._gen_match(stmt)
        elif isinstance(stmt, A.ExprStmt):
            self.emit(f'{self._expr(stmt.expr)};')
        else:
            raise RuntimeError(f"cannot codegen {type(stmt).__name__}")

    def _gen_for(self, stmt):
        if stmt.step is None:
            self.emit(f'for (int32_t v_{stmt.var} = {self._expr(stmt.start)}; '
                      f'v_{stmt.var} < {self._expr(stmt.end)}; '
                      f'v_{stmt.var} = v_{stmt.var} + 1) {{')
            self.indent += 1
            for s in stmt.body: self._gen_stmt(s)
            self.indent -= 1
            self.emit('}')
        else:
            self.temp_counter += 1
            n = self.temp_counter
            self.emit('{')
            self.indent += 1
            self.emit(f'const int32_t __end_{n} = {self._expr(stmt.end)};')
            self.emit(f'const int32_t __step_{n} = {self._expr(stmt.step)};')
            self.emit(f'for (int32_t v_{stmt.var} = {self._expr(stmt.start)}; '
                      f'(__step_{n} > 0 ? v_{stmt.var} < __end_{n} : v_{stmt.var} > __end_{n}); '
                      f'v_{stmt.var} = v_{stmt.var} + __step_{n}) {{')
            self.indent += 1
            for s in stmt.body: self._gen_stmt(s)
            self.indent -= 1
            self.emit('}')
            self.indent -= 1
            self.emit('}')

    def _gen_foreach(self, stmt):
        it = getattr(stmt.iterable, 'type', None)
        self.temp_counter += 1
        n = self.temp_counter
        self.emit('{')
        self.indent += 1
        elem = self._ctype(it.inner)
        if isinstance(it, ListType):
            # Bind the handle once; the loop re-reads the length like the C
            # it compiles to (don't grow the list while iterating it).
            self.emit(f'{self._ctype(it)} __it_{n} = {self._expr(stmt.iterable)};')
            self.emit(f'for (int32_t __i_{n} = 0; __i_{n} < __it_{n}.h->len; '
                      f'__i_{n} += 1) {{')
            self.indent += 1
            self.emit(f'{elem} v_{stmt.var} = __it_{n}.h->data[__i_{n}];')
        else:
            self.emit(f'const {self._ctype(it)}& __it_{n} = {self._expr(stmt.iterable)};')
            self.emit(f'for (int32_t __i_{n} = 0; __i_{n} < {it.size}; '
                      f'__i_{n} += 1) {{')
            self.indent += 1
            self.emit(f'{elem} v_{stmt.var} = __it_{n}[__i_{n}];')
        for s in stmt.body:
            self._gen_stmt(s)
        self.indent -= 1
        self.emit('}')
        self.indent -= 1
        self.emit('}')

    def _gen_match(self, stmt):
        # Bind the matched value once, then test the arms as an if/else
        # chain. A C++ switch would capture `break` written in an arm body,
        # so the chain is what keeps break/continue meaning the enclosing
        # loop, as they do everywhere else in the language.
        self.temp_counter += 1
        n = self.temp_counter
        self.emit('{')
        self.indent += 1
        self.emit(f'const auto __match_{n} = {self._expr(stmt.value)};')
        for i, arm in enumerate(stmt.arms):
            if arm.is_else:
                if i == 0:
                    self.emit('{')
                else:
                    self.emit('} else {')
            else:
                cond = ' || '.join(f'__match_{n} == {tn}::{mn}'
                                   for (tn, mn, _pos) in arm.patterns)
                if len(arm.patterns) > 1:
                    cond = f'({cond})'
                if i == 0:
                    self.emit(f'if ({cond}) {{')
                else:
                    self.emit(f'}} else if ({cond}) {{')
            self.indent += 1
            for s in arm.body:
                self._gen_stmt(s)
            self.indent -= 1
        self.emit('}')
        self.indent -= 1
        self.emit('}')

    def _lvalue(self, expr) -> str:
        if isinstance(expr, A.Name):
            return f'v_{expr.name}'
        if isinstance(expr, A.Member):
            obj_t = expr.obj.type if hasattr(expr.obj, 'type') else None
            # Recurse through _lvalue, not _expr: a checked at() receiver
            # must be emitted as a reference so writes reach the array.
            base = self._lvalue(expr.obj)
            if isinstance(obj_t, StructType) and obj_t.builtin:
                return f'{base}.{expr.field}'
            return f'{base}.v_{expr.field}'
        if isinstance(expr, A.Index):
            if isinstance(getattr(expr.obj, 'type', None), ListType):
                return (f'{self._lvalue(expr.obj)}.h->data'
                        f'[{self._expr(expr.index)}]')
            return f'{self._lvalue(expr.obj)}[{self._expr(expr.index)}]'
        if isinstance(expr, A.Call) and getattr(expr, 'is_checked_at', False):
            f = expr.func
            line = expr.pos.line if expr.pos else 0
            recv = f.obj
            if isinstance(getattr(recv, 'type', None), ListType):
                return (f'vanta::list_at_checked_ref({self._lvalue(recv)}, '
                        f'{self._expr(expr.args[0])}, {line})')
            return (f'vanta::at_checked_ref({self._lvalue(recv)}, '
                    f'{self._expr(expr.args[0])}, {line})')
        raise RuntimeError(f"invalid lvalue {type(expr).__name__}")

    def _expr(self, e) -> str:
        if isinstance(e, A.IntLit):
            t = getattr(e, 'type', I32)
            if t is F32: return f'{e.value}.0f'
            if t is F64: return f'{e.value}.0'
            if t is U32: return f'{e.value}u'
            return str(e.value)
        if isinstance(e, A.FloatLit):
            t = getattr(e, 'type', F32)
            if t is F64: return repr(e.value)
            return f'{e.value}f'
        if isinstance(e, A.BoolLit):
            return 'true' if e.value else 'false'
        if isinstance(e, A.StringLit):
            return _escape_cpp_string(e.value)
        if isinstance(e, A.ArrayLit):
            t = e.type
            inner_t = self._ctype(t.inner)
            N = t.size
            elems = ', '.join(self._init_expr(el, t.inner) for el in e.elements)
            return f'std::array<{inner_t}, {N}>{{{elems}}}'
        if isinstance(e, A.Name):
            if getattr(e, 'is_func_ref', False):
                if e.name in BUILTIN_FN:
                    return BUILTIN_FN[e.name]
                if e.name in BUILTIN_MATH_CTOR:
                    return BUILTIN_MATH_CTOR[e.name]
                sig = self.tc.functions.get(e.name)
                prefix = '' if (sig is not None and sig.is_extern) else 'fn_'
                return f'{prefix}{e.name}'
            return f'v_{e.name}'
        if isinstance(e, A.BinOp):
            op = e.op
            lt = getattr(e.left, 'type', None)
            rt = getattr(e.right, 'type', None)
            if op in ('==', '!=') and lt is STR and rt is STR:
                neg = '' if op == '==' else '!'
                return f'({neg}vanta::str_eq({self._expr(e.left)}, {self._expr(e.right)}))'
            if op == 'and': op = '&&'
            elif op == 'or': op = '||'
            return f'({self._expr(e.left)} {op} {self._expr(e.right)})'
        if isinstance(e, A.UnaryOp):
            if e.op == 'not':
                return f'(!{self._expr(e.operand)})'
            return f'(-{self._expr(e.operand)})'
        if isinstance(e, A.Member):
            if getattr(e, 'is_enum_member', False):
                return f'{e.obj.name}::{e.field}'
            obj_t = getattr(e.obj, 'type', None)
            base = self._expr(e.obj)
            if isinstance(obj_t, StructType) and obj_t.builtin:
                return f'{base}.{e.field}'
            return f'{base}.v_{e.field}'
        if isinstance(e, A.Index):
            if isinstance(getattr(e.obj, 'type', None), ListType):
                return f'{self._expr(e.obj)}.h->data[{self._expr(e.index)}]'
            return f'{self._expr(e.obj)}[{self._expr(e.index)}]'
        if isinstance(e, A.Call):
            return self._call(e)
        raise RuntimeError(f"cannot codegen expression {type(e).__name__}")

    def _fmt_call(self, c: A.Call, name: str) -> str:
        fmt_lit = c.args[0]
        type_names = []
        rendered = []
        for a in c.args[1:]:
            t = getattr(a, 'type', None)
            tname = t.name if isinstance(t, PrimType) else None
            if tname not in FMT_SPEC:
                raise RuntimeError(f"internal: unformattable type {t} in {name}")
            type_names.append(tname)
            if tname == 'bool':
                rendered.append(f'({self._expr(a)} ? "true" : "false")')
            else:
                rendered.append(self._expr(a))
        fmt = build_fmt_c_string(fmt_lit.value, type_names, newline=(name == 'print_fmt'))
        args = ', '.join([f'"{fmt}"'] + rendered)
        return f'vanta::print_fmt_impl({args})'

    def _call(self, c: A.Call) -> str:
        f = c.func
        if getattr(c, 'is_indirect_call', False):
            # The checker resolved this through a function value: a variable,
            # a struct field, an indexed element, or another call.
            args = ', '.join(self._expr(a) for a in c.args)
            return f'{self._expr(f)}({args})'
        if isinstance(f, A.Name):
            name = f.name
            if name == 'len':
                t = getattr(c.args[0], 'type', None)
                if isinstance(t, ListType) or (
                        isinstance(t, StructType) and t.name == 'StrBuilder'):
                    return f'int32_t(({self._expr(c.args[0])}).h->len)'
                return f'int32_t(({self._expr(c.args[0])}).size())'
            if name == 'enum_to_i32':
                return f'static_cast<int32_t>({self._expr(c.args[0])})'
            if name == 'ptr_is_null':
                return f'(({self._expr(c.args[0])}) == nullptr)'
            if name in ('print_fmt', 'write_fmt'):
                return self._fmt_call(c, name)
            if name == 'assert':
                line = c.pos.line if c.pos else 0
                return f'vanta::assert_impl({self._expr(c.args[0])}, {line})'
            if name == 'ptr_cast':
                return (f'reinterpret_cast<{self._ctype(c.type)}>'
                        f'({self._expr(c.args[0])})')
            if name == 'ptr_offset':
                return f'(({self._expr(c.args[0])}) + ({self._expr(c.args[1])}))'
            if name == 'ptr_null':
                return 'nullptr'
            if name in BUILTIN_MATH_CTOR:
                args = ', '.join(self._expr(a) for a in c.args)
                return f'{BUILTIN_MATH_CTOR[name]}({args})'
            if name in ('Vec2', 'Vec3', 'Quat', 'Matrix4', 'Arena'):
                args = ', '.join(self._expr(a) for a in c.args)
                return f'vanta::{name}({args})'
            st = self.tc.structs.get(name)
            if st is not None and not st.builtin:
                args = ', '.join(self._init_expr(a, ft)
                                 for a, ft in zip(c.args, st.fields.values()))
                return f'{name}{{{args}}}'
            if name in BUILTIN_FN:
                args = ', '.join(self._expr(a) for a in c.args)
                return f'{BUILTIN_FN[name]}({args})'
            # User-defined or extern function, or a local variable holding
            # a function value.
            fn_sig = self.tc.functions.get(name)
            args = ', '.join(self._expr(a) for a in c.args)
            if fn_sig is None:
                return f'v_{name}({args})'
            prefix = '' if fn_sig.is_extern else 'fn_'
            return f'{prefix}{name}({args})'
        if isinstance(f, A.Member):
            if getattr(c, 'is_checked_at', False):
                line = c.pos.line if c.pos else 0
                if isinstance(getattr(f.obj, 'type', None), ListType):
                    return (f'vanta::list_at_checked({self._expr(f.obj)}, '
                            f'{self._expr(c.args[0])}, {line})')
                return (f'vanta::at_checked({self._expr(f.obj)}, '
                        f'{self._expr(c.args[0])}, {line})')
            ot = getattr(f.obj, 'type', None)
            base = self._expr(f.obj)
            m = f.field
            if isinstance(ot, StructType) and ot.name == 'Arena':
                if m == 'reset':
                    return f'{base}.reset()'
                if m == 'alloc':
                    ta = c.type_args[0]
                    inner = self.tc._resolve_type(ta)
                    return f'{base}.alloc<{self._ctype(inner)}>({self._expr(c.args[0])})'
                if m == 'list':
                    ta = c.type_args[0]
                    inner = self.tc._resolve_type(ta)
                    return f'vanta::list_new<{self._ctype(inner)}>({base})'
                if m == 'str_builder':
                    return f'vanta::strb_new({base})'
            if isinstance(ot, ListType):
                elem_t = self._ctype(ot.inner)
                if m == 'push':
                    return (f'vanta::list_push<{elem_t}>({base}, '
                            f'{self._expr(c.args[0])})')
                if m == 'pop':
                    line = c.pos.line if c.pos else 0
                    return f'vanta::list_pop({base}, {line})'
                if m == 'insert':
                    line = c.pos.line if c.pos else 0
                    return (f'vanta::list_insert<{elem_t}>({base}, '
                            f'{self._expr(c.args[0])}, {self._expr(c.args[1])}, {line})')
                if m == 'remove':
                    line = c.pos.line if c.pos else 0
                    return f'vanta::list_remove({base}, {self._expr(c.args[0])}, {line})'
                if m == 'sort':
                    return f'vanta::list_sort({base}, {self._expr(c.args[0])})'
            if isinstance(ot, StructType) and ot.name in ('Vec2', 'Vec3'):
                if m == 'dot':
                    return f'vanta::dot({base}, {self._expr(c.args[0])})'
                if m == 'length':
                    return f'vanta::length({base})'
                if m == 'cross':
                    return f'vanta::cross({base}, {self._expr(c.args[0])})'
                if m == 'normalized':
                    return f'vanta::normalize({base})'
            if isinstance(ot, StructType) and ot.name == 'Quat':
                if m == 'length':
                    return f'vanta::length({base})'
                if m == 'normalized':
                    return f'vanta::normalize({base})'
                if m == 'dot':
                    return f'vanta::dot({base}, {self._expr(c.args[0])})'
            if isinstance(ot, StructType) and ot.name == 'StrBuilder':
                if m == 'append_str':
                    return f'vanta::strb_append_str({base}, {self._expr(c.args[0])})'
                if m == 'append_i32':
                    return f'vanta::strb_append_i32({base}, {self._expr(c.args[0])})'
                if m == 'append_u32':
                    return f'vanta::strb_append_u32({base}, {self._expr(c.args[0])})'
                if m == 'append_f32':
                    return f'vanta::strb_append_f32({base}, {self._expr(c.args[0])})'
                if m == 'append_f64':
                    return f'vanta::strb_append_f64({base}, {self._expr(c.args[0])})'
                if m == 'append_bool':
                    return f'vanta::strb_append_bool({base}, {self._expr(c.args[0])})'
                if m == 'to_str':
                    return f'vanta::strb_to_str({base})'
                if m == 'clear':
                    return f'vanta::strb_clear({base})'
        # Indirect call through a function value: a variable, a struct field,
        # an indexed element, or the result of another call.
        args = ', '.join(self._expr(a) for a in c.args)
        return f'{self._expr(f)}({args})'