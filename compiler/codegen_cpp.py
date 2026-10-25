import os

from . import ast_nodes as A
from . import VERSION
from .formats import parse_format
from .typesys import (
    PrimType, IntLitType, FloatLitType, PtrType, ArrayType, ListType, InferType,
    StructType, EnumType, ClassType, FuncType,
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
    'str_contains': 'vanta::str_contains',
    'str_starts_with': 'vanta::str_starts_with',
    'str_ends_with': 'vanta::str_ends_with',
    'str_to_i32': 'vanta::str_to_i32', 'str_to_f32': 'vanta::str_to_f32',
    'to_str_i32': 'vanta::to_str_i32', 'to_str_f32': 'vanta::to_str_f32',
    'to_str_bool': 'vanta::to_str_bool', 'str_pool_reset': 'vanta::str_pool_reset',
    'str_sub': 'vanta::str_sub', 'str_repeat': 'vanta::str_repeat',
    'str_to_upper': 'vanta::str_to_upper', 'str_to_lower': 'vanta::str_to_lower',
    'str_trim': 'vanta::str_trim', 'str_index_of': 'vanta::str_index_of',
    'str_sub': 'vanta::str_sub', 'str_repeat': 'vanta::str_repeat',
    'str_to_upper': 'vanta::str_to_upper', 'str_to_lower': 'vanta::str_to_lower',
    'str_trim': 'vanta::str_trim', 'str_index_of': 'vanta::str_index_of',
    'signal_emit': 'vanta::signal_emit', 'signal_on': 'vanta::signal_on',
    'signal_emit_str': 'vanta::signal_emit_str',
    'signal_on_str': 'vanta::signal_on_str',
    'signal_on_once': 'vanta::signal_on_once',
    'file_exists': 'vanta::file_exists', 'file_write': 'vanta::file_write',
    'file_read': 'vanta::file_read',
    'state_arena': 'vanta::state_arena',
    'hot_should_reload': 'vanta::hot_should_reload',
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
    if t is STR: return 'vanta::Str'
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


def _contains_str(t):
    """True when t has a str anywhere in its layout; such values are not
    C++ literal types, so namespace constants holding them use `const`."""
    if t is STR:
        return True
    if isinstance(t, (PtrType, ArrayType, ListType)):
        return _contains_str(t.inner)
    if isinstance(t, EnumType):
        return any(_contains_str(pt)
                   for payload in t.payloads.values() for pt in payload)
    if isinstance(t, FuncType):
        return any(_contains_str(p) for p in t.params) or _contains_str(t.ret)
    if isinstance(t, StructType) and not t.builtin:
        return any(_contains_str(ft) for ft in t.fields.values())
    return False


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
    elif isinstance(t, EnumType):
        for payload in t.payloads.values():
            for pt in payload:
                yield from _func_types_in(pt)


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
    def __init__(self, program: A.Program, tc, debug=False, debug_filename=None,
                 checked=False, shared=False):
        self.program = program
        self.tc = tc
        self.debug = debug
        self.debug_filename = debug_filename
        self.checked = checked
        self.shared = shared
        self.lines = []
        self.indent = 0
        self.temp_counter = 0
        # ABI adapters are registered only when an expression actually uses
        # one, so programs that never cross the C/str boundary do not emit a
        # pile of unused wrapper functions.
        self.wrapper_specs = {}
        self.wrapper_order = []
        self.wrapper_decl_index = None
        self._class_vtables = {}

    def emit(self, s=''):
        self.lines.append('    ' * self.indent + s)

    def _mark(self, pos):
        """Emit a #line marker so native debuggers see Vanta locations.

        This is only enabled for debug builds.  The marker deliberately lives
        at column zero: a preprocessor directive is not valid after the code
        generator's normal indentation.
        """
        if not self.debug or pos is None:
            return
        filename = getattr(pos, 'file', None)
        line = getattr(pos, 'line', None)
        if not filename or not line:
            return
        # Forward slashes keep the directive portable and are understood by
        # both GDB and the C++ preprocessor on Windows.
        path = os.path.abspath(filename).replace('\\', '/')
        self.lines.append(f'#line {line} {_escape_cpp_string(path)}')

    def _generated_line(self, line=1):
        """Return debug locations to the generated C++ file.

        Wrapper helpers and the native entry point are compiler-generated
        plumbing; a stack trace should identify them as generated code rather
        than leave them attributed to the last Vanta statement.
        """
        if self.debug:
            name = self.debug_filename or 'vanta_generated.cpp'
            name = os.path.abspath(name).replace('\\', '/')
            self.lines.append(f'#line {line} {_escape_cpp_string(name)}')

    def _entry_line(self, fd):
        """Attribute the native entry point to the Vanta source.

        GDB takes the program's current source file from its entry point, so
        pointing it at the Vanta file makes `break 3` and `list` work on the
        Vanta source from the very first prompt.  The entry point itself is
        still generated code; only the file it is reported in changes.
        """
        if not self.debug:
            return
        pos = getattr(fd, 'pos', None)
        file = getattr(pos, 'file', None)
        line = getattr(pos, 'line', None) or 1
        if not file:
            self._generated_line()
            return
        path = os.path.abspath(file).replace('\\', '/')
        self.lines.append(f'#line {line} {_escape_cpp_string(path)}')

    def _ctype(self, t) -> str:
        """C++ spelling of a Vanta type, resolving function-type aliases."""
        if isinstance(t, FuncType):
            try:
                return self.tc.func_types[t]
            except KeyError:
                raise RuntimeError(f"internal: function type {t} was never registered")
        if isinstance(t, ClassType): return t.name
        if isinstance(t, PtrType) and isinstance(t.inner, ClassType):
            return t.inner.name + '*'
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
        user structs are qualified (their tags are forward-declared above).
        `str` is still a bare C string at the extern boundary."""
        if t is STR:
            return 'const char*'
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

    def _simple_str_boundary(self, sig) -> bool:
        """True when str appears only as a direct parameter or return type.
        Nested str (inside a function type, array, List, pointer, or struct)
        would need a second representation conversion that these small ABI
        adapters do not attempt."""
        param_types = [pt for _, pt in sig.params]
        if not any(_contains_str(pt) for pt in param_types) and not _contains_str(sig.ret):
            return False
        for pt in param_types:
            if pt is not STR and _contains_str(pt):
                return False
        return sig.ret is STR or not _contains_str(sig.ret)

    def _register_wrapper(self, kind: str, name: str):
        key = (kind, name)
        if key in self.wrapper_specs:
            return
        sig = self.tc.functions.get(name)
        if sig is None or not self._simple_str_boundary(sig):
            return
        self.wrapper_specs[key] = sig
        self.wrapper_order.append(key)

    def _wrapper_name(self, key) -> str:
        kind, name = key
        if kind == 'builtin':
            return f'vanta_cb_builtin_{name}'
        if kind == 'vanta':
            return f'vanta_cb_fn_{name}'
        return f'vanta_ev_{name}'

    def _wrapper_decl(self, key) -> str:
        kind, name = key
        sig = self.wrapper_specs[key]
        wrapper = self._wrapper_name(key)
        if kind == 'extern':
            params = ', '.join(f'{self._ctype(pt)} v_{pname}'
                               for pname, pt in sig.params)
            return f'{self._ctype(sig.ret)} {wrapper}({params});'
        params = ', '.join(self._declarator_c(pt, f'v_{pname}')
                           for pname, pt in sig.params)
        return f'{self._declarator_c(sig.ret, f"{wrapper}({params})")};'

    def _emit_wrapper_decls(self):
        if not self.wrapper_order:
            return
        decls = ['    ' * self.indent + self._wrapper_decl(key)
                 for key in self.wrapper_order]
        decls.append('')
        self.lines[self.wrapper_decl_index:self.wrapper_decl_index] = decls

    def _emit_wrapper_defs(self):
        if not self.wrapper_order:
            return
        for key in self.wrapper_order:
            kind, name = key
            sig = self.wrapper_specs[key]
            wrapper = self._wrapper_name(key)
            if kind == 'extern':
                self._gen_vanta_wrapper(sig, name, wrapper)
            elif kind == 'builtin':
                self._gen_c_wrapper(sig, BUILTIN_FN[name], wrapper)
            else:
                self._gen_c_wrapper(sig, f'fn_{name}', wrapper)
        self.emit('')

    def _c_callback_expr(self, a) -> str:
        """Spell a function value for a C callback parameter. Named Vanta
        functions and builtins with str need their C-ABI adapter; externs
        already have the C signature."""
        if not isinstance(a, A.Name) or not getattr(a, 'is_func_ref', False):
            return self._expr(a)
        if a.name in BUILTIN_FN:
            self._register_wrapper('builtin', a.name)
            return f'vanta_cb_builtin_{a.name}'
        sig = self.tc.functions.get(a.name)
        if sig is None:
            return self._expr(a)
        if sig.is_extern:
            return a.name
        if self._simple_str_boundary(sig):
            self._register_wrapper('vanta', a.name)
            return f'vanta_cb_fn_{a.name}'
        return self._expr(a)

    def _gen_c_wrapper(self, sig, callee: str, wrapper: str):
        """Emit a C-ABI adapter for a Vanta/builtin function taking str.

        The C side sees const char*; the Vanta side sees owned Str values.
        A str return uses a thread-local holder: C must copy it if it needs
        the pointer after the callback returns.
        """
        params = ', '.join(self._declarator_c(pt, f'v_{name}')
                           for name, pt in sig.params)
        self.emit(f'{self._declarator_c(sig.ret, f"{wrapper}({params})")} {{')
        self.indent += 1
        args = ', '.join(
            f'vanta::Str::from_cstr(v_{name})' if pt is STR else f'v_{name}'
            for name, pt in sig.params)
        call = f'{callee}({args})'
        if sig.ret is VOID:
            self.emit(f'{call};')
        elif sig.ret is STR:
            self.emit('static thread_local vanta::Str v_result;')
            self.emit(f'v_result = {call};')
            self.emit('return v_result.c_str();')
        else:
            self.emit(f'return {call};')
        self.indent -= 1
        self.emit('}')

    def _gen_vanta_wrapper(self, sig, callee: str, wrapper: str):
        """Emit a Vanta-ABI adapter around an extern function that uses str.

        This is what makes an extern such as `puts` usable as a
        `func(str) -> i32` value: the C call still receives const char*.
        """
        params = ', '.join(f'{self._ctype(pt)} v_{name}'
                           for name, pt in sig.params)
        self.emit(f'{self._ctype(sig.ret)} {wrapper}({params}) {{')
        self.indent += 1
        args = ', '.join(f'v_{name}.c_str()' if pt is STR else f'v_{name}'
                         for name, pt in sig.params)
        call = f'{callee}({args})'
        if sig.ret is STR:
            self.emit(f'return vanta::Str::from_cstr({call});')
        elif sig.ret is VOID:
            self.emit(f'{call};')
        else:
            self.emit(f'return {call};')
        self.indent -= 1
        self.emit('}')

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
        classes = [d for d in self.program.decls if isinstance(d, A.ClassDecl)]
        # `tc.structs` holds declaration structs plus every monomorphized
        # generic instance. Builtins are emitted by the runtime header.
        struct_types = [st for st in self.tc.structs.values()
                        if not st.builtin]
        # `tc.enums` holds every concrete enum: ordinary declarations and
        # each monomorphized generic instance.
        enums = list(self.tc.enums.values())
        # `tc.classes` holds every concrete class.
        class_types = [ct for ct in self.tc.classes.values()
                       if not ct.builtin]

        # Tags ahead of the extern block: an extern signature may mention a
        # user struct or enum (a callback carrying a ptr<State>, say), and
        # the definitions live inside the namespace below.
        if externs and (struct_types or enums or class_types):
            self.emit('namespace vanta_user {')
            self.indent += 1
            for et in enums:
                if et.has_payloads:
                    self.emit(f'struct {et.name};')
                else:
                    self.emit(f'enum class {et.name} : int32_t;')
            for st in struct_types:
                self.emit(f'struct {st.name};')
            for ct in class_types:
                self.emit(f'struct {ct.name};')
                self.emit(f'struct {ct.name}_vtable;')
            self.indent -= 1
            self.emit('}')
            self.emit('')

        for ed in externs:
            self._gen_extern(ed)
        if externs:
            self.emit('')

        self.emit('namespace vanta_user {')
        self.indent += 1

        # Forward declarations come before the function-pointer aliases: an
        # alias may mention a struct or enum by value (a comparator
        # func(Item, Item) -> i32), and the definitions come after the
        # aliases because a struct field may hold a function value.
        for et in enums:
            if et.has_payloads:
                self.emit(f'struct {et.name};')
            else:
                self.emit(f'enum class {et.name} : int32_t;')
        for st in struct_types:
            self.emit(f'struct {st.name};')
        for ct in class_types:
            self.emit(f'struct {ct.name};')
            self.emit(f'struct {ct.name}_vtable;')
        self.emit('')

        # Function-pointer aliases, innermost first.
        if self.tc.func_types:
            for ft in self._ordered_func_types():
                params = ', '.join(self._ctype(p) for p in ft.params)
                self.emit(f'using {self.tc.func_types[ft]} = {self._ctype(ft.ret)}(*)({params});')
            self.emit('')

        # Type definitions in dependency order. Source order is enough for
        # non-generic declarations, but a generic instance can be created
        # while resolving a field or signature and may depend on a type
        # declared later in the file.
        user_types = list(struct_types) + list(enums)
        for ct in class_types:
            user_types.append(ct)
        for t in self._ordered_user_types(user_types):
            if isinstance(t, StructType):
                self._gen_struct(t)
            elif isinstance(t, ClassType):
                self._gen_class(t)
            else:
                self._gen_enum(t)

        consts = [d for d in self.program.decls if isinstance(d, A.ConstDecl)]
        for cd in consts:
            t = self.tc.constants[cd.name]
            qual = 'const' if _contains_str(t) else 'constexpr'
            self.emit(f'{qual} {self._ctype(t)} v_{cd.name} = {self._expr(cd.value)};')
        if consts:
            self.emit('')

        self._gen_equality(struct_types, enums)
        funcs = [d for d in self.program.decls if isinstance(d, A.FuncDecl) and not getattr(d, 'type_params', ())]
        # Classes contribute one function per method under a qualified name.
        for cd in classes:
            for fd in getattr(cd, 'methods', []):
                synth = A.FuncDecl(
                    name=f"{cd.name}_{fd.name}", params=fd.params,
                    ret=fd.ret, body=fd.body, is_system=fd.is_system,
                    pos=fd.pos, is_public=fd.is_public)
                funcs.append(synth)
        for fd in funcs:
            self.emit(self._func_sig(fd) + ';')
        self.emit('')
        self.wrapper_decl_index = len(self.lines)
        for fd in funcs:
            self._gen_func(fd)
        for ct in class_types:
            visited = set()
            all_m = {}
            cur = ct
            while cur is not None and cur.name not in visited:
                visited.add(cur.name)
                for m in cur.methods:
                    if m not in all_m:
                        all_m[m] = (cur, cur.methods[m])
                cur = self.tc.classes.get(cur.parent) if cur.parent else None
            if False and all_m:
                self.emit(f'static {ct.name}_vtable {ct.name}_vtable_inst = {{')
                self.indent += 1
                for m, (owner, mft) in all_m.items():
                    self.emit(f'&fn_{owner.name}_{m},')
                self.indent -= 1
                self.emit('};')
                self.emit('')
        self._generated_line()
        self._emit_wrapper_defs()
        self._emit_wrapper_decls()
        self.indent -= 1
        self.emit('}  // namespace vanta_user')
        self.emit('')
        main = next((f for f in funcs if f.name == 'main'), None)
        if self.shared:
            self.emit('')
            self.emit('#ifndef VANTA_EXPORT')
            self.emit('#  if defined(_WIN32)')
            self.emit('#    define VANTA_EXPORT __declspec(dllexport)')
            self.emit('#  else')
            self.emit('#    define VANTA_EXPORT')
            self.emit('#  endif')
            self.emit('#endif')
            self.emit('extern "C" VANTA_EXPORT int vanta_run_main(void) {')
            self.indent += 1
            self._generated_line()
            if (main is not None and (main.ret is None or (getattr(main.ret, 'kind', '') == 'named'
                                                          and getattr(main.ret, 'name', '') == 'void'))):
                self.emit('vanta_user::fn_main();')
                self.emit('return 0;')
            elif main is not None:
                self.emit('return vanta_user::fn_main();')
            else:
                self.emit('return 0;')
            self.indent -= 1
            self.emit('}')
            self.emit('extern "C" VANTA_EXPORT void vanta_bind_state'
                      '(void* base, int32_t bytes) {')
            self.indent += 1
            self._generated_line()
            self.emit('vanta::bind_host_state(base, bytes);')
            self.indent -= 1
            self.emit('}')
            self.emit('extern "C" VANTA_EXPORT void vanta_request_reload(void) {')
            self.indent += 1
            self._generated_line()
            self.emit('vanta::request_host_reload();')
            self.indent -= 1
            self.emit('}')
            self.emit('extern "C" VANTA_EXPORT void vanta_set_hot(int32_t on) {')
            self.indent += 1
            self._generated_line()
            self.emit('vanta::set_hot_mode(on != 0);')
            self.indent -= 1
            self.emit('}')
            self.emit('extern "C" VANTA_EXPORT void vanta_migrate(void* prev) {')
            self.indent += 1
            self._generated_line()
            reload_fn = next((f for f in funcs if f.name == '__reload'), None)
            if reload_fn is not None:
                self.emit('vanta_user::fn___reload(prev);')
            else:
                self.emit('(void)prev;')
            self.indent -= 1
            self.emit('}')
            self.emit('')
        if main is not None and not self.shared:
            self._entry_line(main)
            self.emit('int main(int argc, char** argv) {')
            # Only the entry point itself belongs to the Vanta file; the
            # body is generated plumbing again.
            self._generated_line()
            self.indent += 1
            self.emit('vanta::set_args(argc, argv);')
            if (main.ret is None or (getattr(main.ret, 'kind', '') == 'named'
                                     and getattr(main.ret, 'name', '') == 'void')):
                self.emit('vanta_user::fn_main();')
                self.emit('return 0;')
            else:
                self.emit('return vanta_user::fn_main();')
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

    def _gen_class(self, ct: ClassType):
        # Fields + inherited fields. Walk the parent chain.
        fields = []
        visited = set()
        cur = ct
        while cur is not None and cur.name not in visited:
            visited.add(cur.name)
            order_fn = reversed(list(cur.fields.items()))
            fields = list(order_fn) + fields
            cur = self.tc.classes.get(cur.parent) if cur.parent else None
        # Deduplicate inherited fields by name (subclass overrides field? no - use all)
        # Emit struct.
        self.emit(f'struct {ct.name} {{')
        self.indent += 1
        # V table pointer at end
        for fname, (ftype, _pub) in fields:
            self.emit(f'{self._ctype(ftype)} v_{fname};')
        self.emit(f'{ct.name}_vtable* vtable;')
        self.indent -= 1
        self.emit('};')
        self.emit('')

        # Method function pointer table struct.
        visited = set()
        all_m = {}
        cur = ct
        while cur is not None and cur.name not in visited:
            visited.add(cur.name)
            for m, t in cur.methods.items():
                if m not in all_m:
                    all_m[m] = (cur, t)
            cur = self.tc.classes.get(cur.parent) if cur.parent else None
        # Emit vtable struct.
        self.emit(f'struct {ct.name}_vtable {{')
        self.indent += 1
        for m in all_m:
            _ct, ft = all_m[m]
            # ft.params[0] is self type (ClassType or PtrType(ClassType)).
            params = [self._ctype(ft.params[i]) for i in range(len(ft.params))]
            sig_params = '*, '.join(params[1:] + [''])  # placeholder
            # Make signature: ret (*m)(ct.name*, arg_types...)
            rest = ', '.join(f'{params[i]} arg{i}' for i in range(1, len(params)))
            self.emit(f'{self._ctype(ft.ret)} (*{m})({ct.name}* self' +
                      (', ' + rest if rest else '') + ');')
        self.indent -= 1
        self.emit('};')
        self.emit('')
        # Emit static vtable instance after methods are defined (deferred).
        self._class_vtables[ct.name] = all_m

    # Method emission happens outside this loop from program's classes.

    def _gen_class(self, ct: ClassType):
        # Struct def: fields (own only? For correct compilation and relative
        # simplicity, store own fields; inherited field lookup in type-checker
        # still reads parent CT for type inference).
        self.emit(f'struct {ct.name} {{')
        self.indent += 1
        for fname, (ftype, _pub) in ct.fields.items():
            self.emit(f'{self._ctype(ftype)} v_{fname};')
        self.emit(f'{ct.name}_vtable* vtable;')
        self.indent -= 1
        self.emit('};')
        self.emit('')
        # Forward-declare vtable struct with all inherited methods.
        visited = set()
        all_m = {}
        cur = ct
        while cur is not None and cur.name not in visited:
            visited.add(cur.name)
            for m in cur.methods:
                if m not in all_m:
                    all_m[m] = (cur, cur.methods[m])
            cur = self.tc.classes.get(cur.parent) if cur.parent else None
        self.emit(f'struct {ct.name}_vtable {{')
        self.indent += 1
        for m, (_owner, ft) in all_m.items():
            rest = ', '.join(f'{self._ctype(ft.params[i][1])} arg{i}'
                              for i in range(1, len(ft.params)))
            self.emit(f'{self._ctype(ft.ret)} (*{m})({ct.name}* self'
                      + (', ' + rest if rest else '') + ');')
        self.indent -= 1
        self.emit('};')
        self.emit('')
        self._class_vtables[ct.name] = all_m

    def _ordered_user_types(self, types):
        """Order concrete user types so by-value fields are complete first.

        Pointers and Lists are handles and do not require the element type to
        be complete, so they do not create an ordering edge. Arrays do, and
        a direct struct/enum field does.
        """
        def direct_deps(t):
            if isinstance(t, StructType):
                if t.builtin:
                    return ()
                return tuple(ft for (ft, _pub) in t.fields.values())
            if isinstance(t, ClassType):
                if t.builtin:
                    return ()
                return tuple(ft for (ft, _pub) in t.fields.values())
            if isinstance(t, EnumType):
                return tuple(pt for payload in t.payloads.values()
                             for pt in payload)
            if isinstance(t, ArrayType):
                return (t.inner,)
            return ()

        def type_deps(t):
            out = []
            for dep in direct_deps(t):
                if isinstance(dep, (StructType, EnumType, ClassType)) and not getattr(
                        dep, 'builtin', False):
                    out.append(dep)
                elif isinstance(dep, ArrayType):
                    out.extend(type_deps(dep))
            return out

        remaining = list(types)
        known = set(remaining)
        ordered = []
        emitted = set()
        while remaining:
            progressed = False
            for t in list(remaining):
                deps = [d for d in type_deps(t)
                        if d in known and d is not t]
                if all(d in emitted for d in deps):
                    ordered.append(t)
                    emitted.add(t)
                    remaining.remove(t)
                    progressed = True
            if not progressed:
                # A by-value cycle cannot be represented in C++ either.
                # Leave the rest in declaration order so the compiler can
                # report the offending field rather than looping here.
                ordered.extend(remaining)
                break
        return ordered

    def _gen_enum(self, et: EnumType):
        body = ', '.join(f'{m} = {v}' for m, v in et.members.items())
        if not et.has_payloads:
            self.emit(f'enum class {et.name} : int32_t {{ {body} }};')
            self.emit('')
            return

        self.emit(f'struct {et.name} {{')
        self.indent += 1
        self.emit(f'enum class VantaTag : int32_t {{ {body} }};')
        self.emit('VantaTag v_tag;')
        for member, payload in et.payloads.items():
            for i, ptype in enumerate(payload):
                self.emit(f'{self._ctype(ptype)} p_{member}_{i};')
        self.indent -= 1
        self.emit('};')
        self.emit('')

        for member, payload in et.payloads.items():
            params = ', '.join(f'{self._ctype(ptype)} a{i}'
                               for i, ptype in enumerate(payload))
            self.emit(f'inline {et.name} make_{et.name}_{member}({params}) {{')
            self.indent += 1
            self.emit(f'{et.name} v{{}};')
            self.emit(f'v.v_tag = {et.name}::VantaTag::{member};')
            for i, _ptype in enumerate(payload):
                self.emit(f'v.p_{member}_{i} = a{i};')
            self.emit('return v;')
            self.indent -= 1
            self.emit('}')
        self.emit('')

    def _gen_struct(self, st: StructType):
        self.emit(f'struct {st.name} {{')
        self.indent += 1
        for fname, (ftype, _pub) in st.fields.items():
            self.emit(f'{self._ctype(ftype)} v_{fname};')
        self.indent -= 1
        self.emit('};')
        self.emit('')

    def _equality_fields(self, st: StructType):
        if st.builtin or eq_blocker(st) is not None:
            return None
        return st

    def _gen_equality(self, structs, enums):
        """Component-wise == and != for user structs and payload enums whose
        values all have equality. Declarations come first so nested types
        can refer to each other's operators in any declaration order."""
        struct_eqs = [st for st in (self._equality_fields(sd) for sd in structs)
                      if st is not None]
        enum_eqs = [et for et in enums
                    if et.has_payloads and eq_blocker(et) is None]
        if not struct_eqs and not enum_eqs:
            return
        for st in struct_eqs:
            self.emit(f'inline bool operator==(const {st.name}& a, const {st.name}& b);')
            self.emit(f'inline bool operator!=(const {st.name}& a, const {st.name}& b);')
        for et in enum_eqs:
            self.emit(f'inline bool operator==(const {et.name}& a, const {et.name}& b);')
            self.emit(f'inline bool operator!=(const {et.name}& a, const {et.name}& b);')
        self.emit('')
        for et in enum_eqs:
            self.emit(f'inline bool operator==(const {et.name}& a, const {et.name}& b) {{')
            self.indent += 1
            self.emit('if (a.v_tag != b.v_tag) return false;')
            self.emit('switch (a.v_tag) {')
            self.indent += 1
            for member, payload in et.payloads.items():
                terms = [self._eq_expr(pt, f'a.p_{member}_{i}', f'b.p_{member}_{i}')
                         for i, pt in enumerate(payload)]
                body = ' && '.join(terms) if terms else 'true'
                self.emit(f'case {et.name}::VantaTag::{member}: return {body};')
            self.indent -= 1
            self.emit('}')
            self.emit('return false;')
            self.indent -= 1
            self.emit('}')
            self.emit(f'inline bool operator!=(const {et.name}& a, const {et.name}& b) '
                      f'{{ return !(a == b); }}')
            self.emit('')
        for st in struct_eqs:
            terms = [self._eq_expr(ft, f'a.v_{fn}', f'b.v_{fn}')
                     for fn, (ft, _pub) in st.fields.items()]
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
        self._mark(fn.pos)
        sig = self._func_sig(fn)
        self.emit(sig + ' {')
        self.indent += 1
        for stmt in fn.body:
            self._gen_stmt(stmt)
        ret_type = self.tc.functions[fn.name].ret
        if ret_type is not VOID:
            if ret_type is STR:
                self.emit('return vanta::Str();')
            elif isinstance(ret_type, PtrType):
                self.emit('return nullptr;')
            elif isinstance(ret_type, EnumType):
                first = next(iter(ret_type.members))
                if ret_type.has_payloads:
                    self.emit(f'return {ret_type.name}'
                              f'{{{ret_type.name}::VantaTag::{first}}};')
                else:
                    self.emit(f'return {ret_type.name}::{first};')
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
        self._mark(getattr(stmt, 'pos', None))
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
                self._mark(getattr(c, 'pos', None))
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
        vt = getattr(stmt.value, 'type', None)
        is_payload = isinstance(vt, EnumType) and vt.has_payloads
        self.temp_counter += 1
        n = self.temp_counter
        self.emit('{')
        self.indent += 1
        self.emit(f'const auto __match_{n} = {self._expr(stmt.value)};')
        for i, arm in enumerate(stmt.arms):
            self._mark(getattr(arm, 'pos', None))
            if arm.is_else:
                if i == 0:
                    self.emit('{')
                else:
                    self.emit('} else {')
            else:
                if is_payload:
                    cond = ' || '.join(
                        f'__match_{n}.v_tag == {pat.enum_name}::VantaTag::{pat.member}'
                        for pat in arm.patterns)
                else:
                    cond = ' || '.join(
                        f'__match_{n} == {pat.enum_name}::{pat.member}'
                        for pat in arm.patterns)
                if len(arm.patterns) > 1:
                    cond = f'({cond})'
                if getattr(arm, 'guard', None) is not None:
                    guard_expr = self._expr(arm.guard)
                    cond = f'({cond}) && {guard_expr}'
                if i == 0:
                    self.emit(f'if ({cond}) {{')
                else:
                    self.emit(f'}} else if ({cond}) {{')
            self.indent += 1
            if is_payload:
                for pat in arm.patterns:
                    for bind_i, bname in enumerate(pat.bindings or []):
                        if bname == '_':
                            continue
                        self.emit(f'const auto& v_{bname} = '
                                  f'__match_{n}.p_{pat.member}_{bind_i};')
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
            if isinstance(obj_t, PtrType) and isinstance(obj_t.inner, ClassType):
                return f'{base}->v_{expr.field}'
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
            recv_t = getattr(recv, 'type', None)
            if isinstance(recv_t, ListType):
                return (f'vanta::list_at_checked_ref({self._lvalue(recv)}, '
                        f'{self._expr(expr.args[0])}, {line})')
            if isinstance(recv_t, PtrType):
                # The helper takes the pointer by value and returns a reference
                # to the element, so even a temporary pointer result can write.
                return (f'vanta::ptr_at_checked_ref({self._expr(recv)}, '
                        f'{self._expr(expr.args[0])}, '
                        f'{self._expr(expr.args[1])}, {line})')
            return (f'vanta::at_checked_ref({self._lvalue(recv)}, '
                    f'{self._expr(expr.args[0])}, {line})')
        raise RuntimeError(f"invalid lvalue {type(expr).__name__}")

    def _expr(self, e) -> str:
        if isinstance(e, A.LambdaExpr):
            return f'vanta_user::fn_{e.name}'
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
            # Keep literals zero-copy: the runtime tags this as a static view.
            n = len(e.value.encode('utf-8'))
            return f'vanta::Str::literal({_escape_cpp_string(e.value)}, {n})'
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
                if sig is not None and sig.is_extern:
                    # A str-bearing extern needs the Vanta-ABI adapter so the
                    # value can live in a func(str) variable or array.
                    if self._simple_str_boundary(sig):
                        self._register_wrapper('extern', e.name)
                        return f'vanta_ev_{e.name}'
                    return e.name
                return f'fn_{e.name}'
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
            prims = {'i8', 'u8', 'i16', 'u16', 'i32', 'u32'}
            if self.checked and op in ('+', '-', '*') and lt is rt \
                    and isinstance(lt, PrimType) and lt.name in prims:
                which = {'+': 'ADD', '-': 'SUB', '*': 'MUL'}[op]
                pn = lt.name.upper()
                left = self._expr(e.left)
                right = self._expr(e.right)
                return ('(VANTA_CK_%s_%s(%s, %s))'
                        % (pn, which, left, right))
            return f'({self._expr(e.left)} {op} {self._expr(e.right)})'
        if isinstance(e, A.UnaryOp):
            if e.op == 'not':
                return f'(!{self._expr(e.operand)})'
            return f'(-{self._expr(e.operand)})'
        if isinstance(e, A.Member):
            if getattr(e, 'is_enum_member', False):
                et = getattr(e, 'type', None)
                if isinstance(et, EnumType) and et.has_payloads:
                    return f'make_{et.name}_{e.field}()'
                if isinstance(et, EnumType):
                    return f'{et.name}::{e.field}'
                return f'{e.obj.name}::{e.field}'
            obj_t = getattr(e.obj, 'type', None)
            base = self._expr(e.obj)
            if isinstance(obj_t, StructType) and obj_t.builtin:
                return f'{base}.{e.field}'
            if isinstance(obj_t, PtrType) and isinstance(obj_t.inner, ClassType):
                return f'{base}->v_{e.field}'
            if isinstance(obj_t, ClassType):
                # Fields are kept inline (inherited flattened into the struct).
                return f'{base}.v_{e.field}'
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
            elif tname == 'str':
                rendered.append(f'({self._expr(a)}).c_str()')
            else:
                rendered.append(self._expr(a))
        newline = (name == 'print_fmt')
        fmt = build_fmt_c_string(fmt_lit.value, type_names, newline=newline)
        args = ', '.join([f'"{fmt}"'] + rendered)
        if name == 'str_fmt':
            return f'vanta::str_fmt_impl({args})'
        return f'vanta::print_fmt_impl({args})'

    def _call(self, c: A.Call) -> str:
        f = c.func
        if getattr(c, 'is_enum_ctor', False):
            et = c.type
            args = ', '.join(self._expr(a) for a in c.args)
            if isinstance(et, EnumType) and et.has_payloads:
                return f'make_{et.name}_{f.field}({args})'
            return f'{et.name}::{f.field}'
        if getattr(c, 'is_indirect_call', False):
            # The checker resolved this through a function value: a variable,
            # a struct field, an indexed element, or another call.
            args = ', '.join(self._expr(a) for a in c.args)
            return f'{self._expr(f)}({args})'
        instance_name = getattr(c, 'generic_func_instance', None)
        if isinstance(f, A.Name) and instance_name:
            args = ', '.join(self._expr(a) for a in c.args)
            return f'vanta_user::fn_{instance_name}({args})'
        if isinstance(f, A.Name):
            name = f.name
            if name == 'len':
                t = getattr(c.args[0], 'type', None)
                if isinstance(t, ListType) or (
                        isinstance(t, StructType) and t.name == 'StrBuilder'):
                    return f'int32_t(({self._expr(c.args[0])}).h->len)'
                return f'int32_t(({self._expr(c.args[0])}).size())'
            if name == 'enum_to_i32':
                at = getattr(c.args[0], 'type', None)
                if isinstance(at, EnumType) and at.has_payloads:
                    return f'static_cast<int32_t>(({self._expr(c.args[0])}).v_tag)'
                return f'static_cast<int32_t>({self._expr(c.args[0])})'
            if name == 'ptr_is_null':
                return f'(({self._expr(c.args[0])}) == nullptr)'
            if name in ('print_fmt', 'write_fmt', 'str_fmt'):
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
            if getattr(c, 'is_struct_ctor', False):
                st = c.type
                args = ', '.join(self._init_expr(a, ft)
                                 for a, (ft, _pub) in zip(c.args, st.fields.values()))
                return f'{st.name}{{{args}}}'
            st = self.tc.structs.get(name)
            if st is not None and not st.builtin:
                args = ', '.join(self._init_expr(a, ft)
                                 for a, (ft, _pub) in zip(c.args, st.fields.values()))
                return f'{name}{{{args}}}'
            if name in self.tc.classes:
                ct = self.tc.classes[name]
                args = ', '.join(self._init_expr(a, ft)
                                 for a, (ft, _pub) in zip(c.args, ct.fields.values()))
                return f'{name}{{{args}}}'
            if name in BUILTIN_FN:
                args = ', '.join(self._expr(a) for a in c.args)
                return f'{BUILTIN_FN[name]}({args})'
            # User-defined or extern function, or a local variable holding
            # a function value.
            fn_sig = self.tc.functions.get(name)
            if fn_sig is None:
                args = ', '.join(self._expr(a) for a in c.args)
                return f'v_{name}({args})'
            if fn_sig.is_extern:
                # The C boundary is raw const char*: spell the conversion out
                # rather than relying on an implicit operator.
                rendered = []
                for a, (_, pt) in zip(c.args, fn_sig.params):
                    if pt is STR:
                        rendered.append(f'({self._expr(a)}).c_str()')
                    elif isinstance(pt, FuncType) and _contains_str(pt):
                        rendered.append(self._c_callback_expr(a))
                    else:
                        rendered.append(self._expr(a))
                args = ', '.join(rendered)
                call_expr = f'{name}({args})'
                # A C function returns a borrowed char*; copy it into an owned
                # Str before it can escape the call.
                if getattr(c, 'type', None) is STR:
                    return f'vanta::Str::from_cstr({call_expr})'
                return call_expr
            args = ', '.join(self._expr(a) for a in c.args)
            return f'fn_{name}({args})'
        if isinstance(f, A.Member):
            if getattr(c, 'is_checked_at', False):
                line = c.pos.line if c.pos else 0
                recv_t = getattr(f.obj, 'type', None)
                if isinstance(recv_t, ListType):
                    return (f'vanta::list_at_checked({self._expr(f.obj)}, '
                            f'{self._expr(c.args[0])}, {line})')
                if isinstance(recv_t, PtrType):
                    return (f'vanta::ptr_at_checked({self._expr(f.obj)}, '
                            f'{self._expr(c.args[0])}, '
                            f'{self._expr(c.args[1])}, {line})')
                return (f'vanta::at_checked({self._expr(f.obj)}, '
                        f'{self._expr(c.args[0])}, {line})')
            ot = getattr(f.obj, 'type', None)
            base = self._expr(f.obj)
            m = f.field
            if isinstance(ot, ClassType):
                # Resolve the declaring class walking the inheritance chain
                decl = ot
                visited = set()
                while decl is not None and decl.name not in visited:
                    visited.add(decl.name)
                    if m in getattr(decl, 'methods', {}):
                        break
                    decl = self.tc.classes.get(decl.parent) if decl.parent else None
                if decl is None:
                    decl = ot
                # `base` is the receiver value; pass a pointer to its (possibly
                # upcast) declaring class for `self`.
                args = ', '.join(self._expr(a) for a in c.args)
                caster = f'reinterpret_cast<{decl.name}*>'
                call_self = f'{caster}(&{base})'
                return (f'fn_{decl.name}_{m}({call_self}, {args})' if args else
                       f'fn_{decl.name}_{m}({call_self})')
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