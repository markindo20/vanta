from . import ast_nodes as A
from .typesys import (
    Type, PrimType, IntLitType, FloatLitType, PtrType, ArrayType, InferType,
    StructType,
    I32, U32, F32, F64, BOOL, VOID, STR, INT_LIT, FLOAT_LIT, INFER,
    PRIM_TYPES, is_int, is_float, is_numeric,
)


class CheckError(Exception):
    def __init__(self, msg, filename, pos):
        self.msg = msg; self.filename = filename; self.pos = pos
        super().__init__(f"{filename}:{pos.line}:{pos.col}: {msg}")


class FuncSig:
    def __init__(self, name, params, ret):
        self.name = name; self.params = params; self.ret = ret


class TypeChecker:
    def __init__(self, program: A.Program, filename="<input>"):
        self.program = program
        self.filename = filename
        self.structs: dict[str, StructType] = {}
        self.functions: dict[str, FuncSig] = {}
        self.constants: dict[str, Type] = {}
        self.scopes = []
        self.current_ret: Type = VOID
        self.loop_depth = 0
        self.return_values: list = []
        self._register_builtins()

    def _register_builtins(self):
        self.structs["Vec2"] = StructType("Vec2", {"x": F32, "y": F32}, builtin=True)
        self.structs["Vec3"] = StructType("Vec3", {"x": F32, "y": F32, "z": F32}, builtin=True)
        self.structs["Quat"] = StructType("Quat", {"x": F32, "y": F32, "z": F32, "w": F32}, builtin=True)
        self.structs["Matrix4"] = StructType("Matrix4", {}, builtin=True)
        self.structs["Arena"] = StructType("Arena", {}, builtin=True)

        def bf(name, params, ret):
            self.functions[name] = FuncSig(name, params, ret)

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
        bf("assert", [("cond", BOOL)], VOID)
        bf("translation", [("x", F32), ("y", F32), ("z", F32)], self.structs["Matrix4"])
        bf("scale", [("s", F32)], self.structs["Matrix4"])
        bf("from_quat", [("q", self.structs["Quat"])], self.structs["Matrix4"])

    def _resolve_type(self, te: A.TypeExpr) -> Type:
        if te.kind == 'ptr':
            return PtrType(self._resolve_type(te.inner))
        if te.kind == 'array':
            if te.size is None or te.size <= 0:
                raise CheckError("array size must be a positive integer", self.filename, te.pos)
            return ArrayType(self._resolve_type(te.inner), te.size)
        n = te.name
        if n in PRIM_TYPES:
            return PRIM_TYPES[n]
        if n in self.structs:
            return self.structs[n]
        raise CheckError(f"unknown type '{n}'", self.filename, te.pos)

    def register(self):
        for d in self.program.decls:
            if isinstance(d, A.StructDecl):
                self._register_struct(d)
            elif isinstance(d, A.FuncDecl):
                self._register_func(d)
            elif isinstance(d, A.ConstDecl):
                self._register_const(d)

    def _register_struct(self, d):
        if d.name in self.structs:
            raise CheckError(f"duplicate type '{d.name}'", self.filename, d.pos)
        fields = {}
        for (fname, ftype, fpos) in d.fields:
            if fname in fields:
                raise CheckError(f"duplicate field '{fname}'", self.filename, fpos)
            fields[fname] = self._resolve_type(ftype)
        self.structs[d.name] = StructType(d.name, fields, builtin=False)

    def _register_func(self, d):
        if d.name in self.functions:
            raise CheckError(f"duplicate function '{d.name}'", self.filename, d.pos)
        if d.name in self.structs:
            raise CheckError(f"function name '{d.name}' collides with type", self.filename, d.pos)
        params = []
        for p in d.params:
            params.append((p.name, self._resolve_type(p.type)))
        ret = self._resolve_type(d.ret) if d.ret is not None else INFER
        self.functions[d.name] = FuncSig(d.name, params, ret)

    def _register_const(self, c):
        if c.name in self.constants:
            raise CheckError(f"duplicate constant '{c.name}'", self.filename, c.pos)
        if c.name in self.structs:
            raise CheckError(f"constant '{c.name}' collides with type", self.filename, c.pos)
        if c.name in self.functions:
            raise CheckError(f"constant '{c.name}' collides with function", self.filename, c.pos)
        vt = self._check_expr(c.value)
        if not self._is_constexpr(c.value):
            raise CheckError(
                f"constant initializer must be a compile-time expression",
                self.filename, c.pos)
        if c.type_ann is not None:
            declared = self._resolve_type(c.type_ann)
            self._coerce_value(c.value, vt, declared, c.pos, "constant initializer")
            vt = declared
        else:
            vt = self._default_type(vt, c.value)
        if vt is VOID:
            raise CheckError("constant cannot be void", self.filename, c.pos)
        self.constants[c.name] = vt

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
        for d in self.program.decls:
            if isinstance(d, A.FuncDecl):
                self._check_func(d)

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
        elif isinstance(stmt, A.ExprStmt):
            self._check_expr(stmt.expr)
        else:
            raise CheckError(f"unsupported statement {type(stmt).__name__}", self.filename, stmt.pos)

    def _check_var_decl(self, v: A.VarDecl):
        vt = self._check_expr(v.value)
        if v.type_ann is not None:
            declared = self._resolve_type(v.type_ann)
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
        if not self._is_assignable(a.target):
            raise CheckError("invalid assignment target", self.filename, a.pos)
        tt = self._check_expr(a.target)
        vt = self._check_expr(a.value)
        self._coerce_value(a.value, vt, tt, a.pos, "assignment")
        if isinstance(tt, StructType) and tt.name == "Arena":
            raise CheckError("Arena values cannot be assigned", self.filename, a.pos)

    def _is_assignable(self, expr) -> bool:
        if isinstance(expr, A.Name):
            ent = self._lookup(expr.name)
            return ent is not None and ent[1]
        if isinstance(expr, A.Member):
            base = expr.obj
            if isinstance(base, A.Name):
                ent = self._lookup(base.name)
                return ent is not None and ent[1]
            if isinstance(base, A.Index):
                bt = self._check_expr(base.obj)
                return isinstance(bt, PtrType)
            return False
        if isinstance(expr, A.Index):
            ot = self._check_expr(expr.obj)
            if isinstance(ot, PtrType):
                return True
            if isinstance(ot, ArrayType):
                base = expr.obj
                while isinstance(base, A.Index):
                    base = base.obj
                if isinstance(base, A.Name):
                    ent = self._lookup(base.name)
                    return ent is not None and ent[1]
                return False
            return False
        return False

    def _check_return(self, r: A.ReturnStmt):
        if r.value is None:
            if not isinstance(self.current_ret, InferType) and self.current_ret is not VOID:
                raise CheckError("return without value in non-void function", self.filename, r.pos)
            self.return_values.append((None, VOID))
            return
        vt = self._check_expr(r.value)
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

    def _check_cond(self, cond, pos):
        ct = self._check_expr(cond)
        if ct is not BOOL:
            raise CheckError(f"condition must be bool, got {ct}", self.filename, pos)

    def _check_expr(self, expr) -> Type:
        if isinstance(expr, A.IntLit):
            expr.type = INT_LIT; return INT_LIT
        if isinstance(expr, A.FloatLit):
            expr.type = FLOAT_LIT; return FLOAT_LIT
        if isinstance(expr, A.BoolLit):
            expr.type = BOOL; return BOOL
        if isinstance(expr, A.StringLit):
            expr.type = STR; return STR
        if isinstance(expr, A.ArrayLit):
            return self._check_array_lit(expr)
        if isinstance(expr, A.Name):
            ent = self._lookup(expr.name)
            if ent is None:
                raise CheckError(f"unknown name '{expr.name}'", self.filename, expr.pos)
            expr.type = ent[0]
            return ent[0]
        if isinstance(expr, A.BinOp):
            lt = self._check_expr(expr.left)
            rt = self._check_expr(expr.right)
            t = self._check_binop(expr, lt, rt)
            expr.type = t
            return t
        if isinstance(expr, A.UnaryOp):
            t = self._check_expr(expr.operand)
            if expr.op == '-':
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
            return self._check_call(expr)
        if isinstance(expr, A.Member):
            ot = self._check_expr(expr.obj)
            if isinstance(ot, StructType) and expr.field in ot.fields:
                t = ot.fields[expr.field]
                expr.type = t
                return t
            raise CheckError(f"type {ot} has no field '{expr.field}'", self.filename, expr.pos)
        if isinstance(expr, A.Index):
            ot = self._check_expr(expr.obj)
            it = self._check_expr(expr.index)
            self._coerce_value(expr.index, it, I32, expr.pos, "index")
            if isinstance(ot, PtrType):
                expr.type = ot.inner
                return ot.inner
            if isinstance(ot, ArrayType):
                expr.type = ot.inner
                return ot.inner
            raise CheckError(f"cannot index non-pointer/non-array type {ot}", self.filename, expr.pos)
        raise CheckError(f"unsupported expression {type(expr).__name__}", self.filename,
                         getattr(expr, 'pos', A.Pos(0, 0)))

    def _check_array_lit(self, expr: A.ArrayLit) -> Type:
        if not expr.elements:
            raise CheckError("empty array literal is not supported; use an explicit type",
                             self.filename, expr.pos)
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
        if op in ('and', 'or'):
            if lt is not BOOL or rt is not BOOL:
                raise CheckError(f"'{op}' requires bool operands", self.filename, expr.pos)
            return BOOL
        if op in ('==', '!=', '<', '<=', '>', '>='):
            if isinstance(lt, StructType) or isinstance(rt, StructType):
                if (op in ('==', '!=') and isinstance(lt, StructType)
                        and lt == rt and lt.name in ("Vec2", "Vec3")):
                    return BOOL
                raise CheckError(f"cannot compare {lt} and {rt} with '{op}'", self.filename, expr.pos)
            if lt is STR or rt is STR:
                if op in ('==', '!=') and lt is STR and rt is STR:
                    return BOOL
                raise CheckError(f"cannot compare str with '{op}'", self.filename, expr.pos)
            if lt != rt:
                raise CheckError(f"cannot compare {lt} and {rt}", self.filename, expr.pos)
            return BOOL
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
            expr.left.type = rt
            return rt, rt
        if rt in (INT_LIT, FLOAT_LIT) and lit_ok(lt, rt):
            expr.right.type = lt
            return lt, lt
        return lt, rt

    def _coerce_value(self, expr, actual, expected, pos, ctx):
        if actual is expected or actual == expected:
            return
        if actual is INT_LIT and (is_int(expected) or is_float(expected)):
            expr.type = expected
            return
        if actual is FLOAT_LIT and is_float(expected):
            expr.type = expected
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
        raise CheckError(f"{ctx}: cannot assign {actual} to {expected}", self.filename, pos)

    def _default_type(self, t: Type, expr) -> Type:
        if t is INT_LIT:
            expr.type = I32
            return I32
        if t is FLOAT_LIT:
            expr.type = F32
            return F32
        return t

    def _check_call(self, call: A.Call) -> Type:
        f = call.func
        if isinstance(f, A.Name):
            name = f.name
            if name == 'len':
                return self._check_len(call)
            if name in self.structs:
                st = self.structs[name]
                if st.builtin:
                    return self._check_builtin_ctor(st, call)
                return self._check_user_struct_ctor(st, call)
            if name in self.functions:
                return self._check_func_call(name, call)
            raise CheckError(f"unknown callable '{name}'", self.filename, call.pos)
        if isinstance(f, A.Member):
            ot = self._check_expr(f.obj)
            if isinstance(ot, StructType):
                return self._check_method(ot, f.field, call)
            raise CheckError(f"type {ot} has no methods", self.filename, call.pos)
        raise CheckError("cannot call expression", self.filename, call.pos)

    def _check_len(self, call: A.Call) -> Type:
        if len(call.args) != 1:
            raise CheckError("len takes one argument", self.filename, call.pos)
        at = self._check_expr(call.args[0])
        if not isinstance(at, ArrayType):
            raise CheckError(f"len expects an array, got {at}", self.filename, call.pos)
        call.type = I32
        return I32

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
                at = self._check_expr(arg)
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
                at = self._check_expr(arg)
                self._coerce_value(arg, at, ftype, call.pos, "argument")

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
            at = self._check_expr(arg)
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
            at = self._check_expr(arg)
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
                t = PtrType(inner)
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
        raise CheckError(f"type {st.name} has no method '{method}'", self.filename, call.pos)