from .tokens import TT, Token
from . import ast_nodes as A


class ParseError(Exception):
    def __init__(self, msg, filename, pos):
        self.msg = msg; self.filename = filename; self.pos = pos
        super().__init__(f"{filename}:{pos.line}:{pos.col}: {msg}")


BIN_PREC = {
    TT.OR: 1, TT.AND: 2,
    TT.EQ: 3, TT.NEQ: 3,
    TT.LT: 4, TT.LTE: 4, TT.GT: 4, TT.GTE: 4,
    TT.PLUS: 5, TT.MINUS: 5,
    TT.STAR: 6, TT.SLASH: 6, TT.PERCENT: 6,
}

COMPOUND_OPS = {
    TT.PLUS_EQ: '+', TT.MINUS_EQ: '-',
    TT.STAR_EQ: '*', TT.SLASH_EQ: '/',
}


class Parser:
    def __init__(self, tokens, filename="<input>"):
        self.tokens = tokens
        self.i = 0
        self.filename = filename
        # Diagnostics collected by recoverable parser boundaries. parse_program
        # keeps checking later independent declarations where a safe boundary
        # can be found; callers should inspect this list.
        self.errors = []

    def peek(self, off=0):
        p = self.i + off
        return self.tokens[p] if p < len(self.tokens) else self.tokens[-1]

    def advance(self):
        tok = self.tokens[self.i]
        self.i += 1
        return tok

    def check(self, tt):
        return self.peek().type == tt

    def match(self, tt):
        if self.check(tt):
            return self.advance()
        return None

    def expect(self, tt, msg=None):
        t = self.peek()
        if t.type != tt:
            raise ParseError(msg or f"expected {tt.name}, got {t.type.name}", self.filename, A.Pos(t.line, t.col))
        return self.advance()

    def error(self, msg, tok=None):
        tok = tok or self.peek()
        raise ParseError(msg, self.filename, A.Pos(tok.line, tok.col))

    def parse_program(self):
        decls = []
        while not self.check(TT.EOF):
            if self.check(TT.NEWLINE):
                self.advance(); continue
            try:
                decl = self.parse_top_level()
                decls.append(decl)
                continue
            except ParseError as exc:
                self.errors.append(exc)
            # Synchronize to a later top-level boundary before resuming.
            while (not self.check(TT.EOF) and
                   not self.check(TT.NEWLINE)):
                self.advance()
            while self.check(TT.NEWLINE):
                self.advance()
        program = A.Program(decls)
        program.parse_errors = list(self.errors)
        if self.errors:
            raise self.errors[0]
        return program

    def parse_top_level(self):
        decorators = []
        while self.check(TT.AT):
            decorators.append(self._parse_decorator())
        t = self.peek()
        if t.type == TT.PUB:
            pub = self.advance()
            if self.peek().type in (TT.IMPORT, TT.MODULE, TT.PUB, TT.AT):
                self.error("'pub' must precede a declaration", pub)
            decl = self._parse_decl()
            if not hasattr(decl, 'is_public'):
                self.error("'pub' cannot be applied to this declaration", pub)
            decl.is_public = True
            if decorators:
                decl.decorators.extend(decorators)
                if "@export" in decorators:
                    decl.is_exported = True
            return decl
        decl = self._parse_decl()
        if decorators:
            if not hasattr(decl, 'decorators'):
                self.error("decorator cannot be applied to this declaration",
                           self.peek())
            decl.decorators.extend(decorators)
            if "@export" in decorators:
                decl.is_exported = True
        return decl

    def _parse_decl(self):
        t = self.peek()
        if t.type == TT.MODULE:
            return self.parse_module()
        if t.type == TT.FUNC:
            return self.parse_func(False)
        if t.type == TT.SYSTEM:
            return self.parse_func(True)
        if t.type == TT.STRUCT:
            return self.parse_struct(False)
        if t.type == TT.COMPONENT:
            return self.parse_struct(True)
        if t.type == TT.ENUM:
            return self.parse_enum()
        if t.type == TT.CLASS:
            return self.parse_class()
        if t.type == TT.EXTERN:
            return self.parse_extern()
        if t.type == TT.CONST:
            return self.parse_const()
        if t.type == TT.LET or t.type == TT.MUT:
            return self.parse_var_decl()
        if t.type == TT.IMPORT:
            return self.parse_import()
        self.error(f"expected top-level declaration, got {t.type.name}")

    def parse_module(self):
        tok = self.advance()
        parts = [self.expect(TT.IDENT, "expected a module name").value]
        while self.match(TT.DOT):
            parts.append(self.expect(TT.IDENT, "expected a module name").value)
        name = '.'.join(parts)
        return A.ModuleDecl(name, A.Pos(tok.line, tok.col))

    def _parse_decorator(self):
        self.advance()  # AT
        name = self.expect(TT.IDENT).value
        self.expect(TT.NEWLINE)
        return "@" + name

    def parse_const(self):
        tok = self.advance()
        name = self.expect(TT.IDENT).value
        ann = None
        if self.match(TT.COLON):
            ann = self.parse_type()
        self.expect(TT.ASSIGN)
        val = self.parse_expr()
        self.expect(TT.NEWLINE)
        return A.ConstDecl(name, ann, val, A.Pos(tok.line, tok.col))

    def parse_extern(self):
        tok = self.advance()
        lib_name = self.expect(TT.STRING).value
        self.expect(TT.LBRACE)
        self.expect(TT.NEWLINE)
        funcs = []
        while not self.check(TT.RBRACE) and not self.check(TT.EOF):
            if self.check(TT.NEWLINE) or self.check(TT.INDENT) or self.check(TT.DEDENT):
                self.advance()
                continue
            funcs.append(self.parse_func_decl())
        self.expect(TT.RBRACE)
        self.expect(TT.NEWLINE)
        return A.ExternDecl(lib_name, funcs, A.Pos(tok.line, tok.col))

    def parse_import(self):
        tok = self.advance()
        path = self.expect(TT.STRING, "expected a path string after 'import'").value
        alias = None
        if self.match(TT.AS):
            alias = self.expect(TT.IDENT, "expected an import alias").value
        self.expect(TT.NEWLINE)
        return A.ImportDecl(path, A.Pos(tok.line, tok.col), alias)

    def parse_func_decl(self):
        tok = self.advance()  # consume FUNC
        name = self.expect(TT.IDENT).value
        type_params, type_param_constraints = self._parse_type_params()
        self.expect(TT.LPAREN)
        params = []
        if not self.check(TT.RPAREN):
            while True:
                pn = self.expect(TT.IDENT)
                self.expect(TT.COLON)
                pt = self.parse_type()
                params.append(A.Param(pn.value, pt, A.Pos(pn.line, pn.col)))
                if self.match(TT.COMMA):
                    continue
                break
        self.expect(TT.RPAREN)
        ret = None
        if self.match(TT.ARROW):
            ret = self.parse_type()
        self.expect(TT.NEWLINE)
        return A.FuncDecl(name, params, ret, [], False, A.Pos(tok.line, tok.col),
                          type_params=type_params,
                          type_param_constraints=type_param_constraints)

    def parse_func(self, is_system, is_public=False):
        tok = self.advance()
        name = self.expect(TT.IDENT).value
        type_params, type_param_constraints = self._parse_type_params()
        self.expect(TT.LPAREN)
        params = []
        if not self.check(TT.RPAREN):
            while True:
                pn = self.expect(TT.IDENT)
                self.expect(TT.COLON)
                pt = self.parse_type()
                params.append(A.Param(pn.value, pt, A.Pos(pn.line, pn.col)))
                if self.match(TT.COMMA):
                    continue
                break
        self.expect(TT.RPAREN)  
        ret = None
        if self.match(TT.ARROW):
            ret = self.parse_type()
        self.expect(TT.COLON)  
        body = self.parse_block()
        return A.FuncDecl(name, params, ret, body, is_system, A.Pos(tok.line, tok.col),
                          type_params=type_params,
                          type_param_constraints=type_param_constraints,
                          is_public=is_public)

    def _parse_type_params(self):
        """Parse an optional `<T, U>` or `<T: Copyable + Eq, U>` list after a
        declaration name. Returns (param_names, constraints_dict). The `+`
        separates multiple constraints on one type parameter; `,` separates
        type parameters."""
        params = []
        constraints = {}
        if not self.match(TT.LT):
            return params, constraints
        while True:
            ptok = self.expect(TT.IDENT, "expected a type parameter")
            if ptok.value in params:
                self.error(f"duplicate type parameter '{ptok.value}'", ptok)
            params.append(ptok.value)
            cons = []
            if self.match(TT.COLON):
                ctok = self.expect(TT.IDENT, "expected a constraint name")
                cons.append(ctok.value)
                while self.match(TT.PLUS):
                    ctok = self.expect(TT.IDENT, "expected a constraint name")
                    cons.append(ctok.value)
            constraints[ptok.value] = cons
            if self.match(TT.COMMA):
                continue
            break
        self.expect(TT.GT)
        return params, constraints

    def parse_struct(self, is_component):
        tok = self.advance()
        name = self.expect(TT.IDENT).value
        type_params, type_param_constraints = self._parse_type_params()
        self.expect(TT.COLON)
        self.expect(TT.NEWLINE)
        self.expect(TT.INDENT)
        fields = []
        while not self.check(TT.DEDENT):
            decorators = []
            while self.check(TT.AT):
                decorators.append(self._parse_decorator())
            is_public = False
            if self.check(TT.PUB):
                self.advance()
                is_public = True
            fn = self.expect(TT.IDENT)
            self.expect(TT.COLON)
            ft = self.parse_type()
            self.expect(TT.NEWLINE)
            fields.append((fn.value, ft, A.Pos(fn.line, fn.col), is_public, decorators))
        self.expect(TT.DEDENT)
        return A.StructDecl(name, fields, is_component,
                            A.Pos(tok.line, tok.col),
                            type_params=type_params,
                            type_param_constraints=type_param_constraints)

    def parse_enum(self):
        tok = self.advance()
        name = self.expect(TT.IDENT).value
        type_params, type_param_constraints = self._parse_type_params()
        self.expect(TT.COLON)
        self.expect(TT.NEWLINE)
        self.expect(TT.INDENT)
        members = []
        while not self.check(TT.DEDENT):
            mn = self.expect(TT.IDENT)
            payload = None
            if self.match(TT.LPAREN):
                payload = []
                if not self.check(TT.RPAREN):
                    while True:
                        payload.append(self.parse_type())
                        if self.match(TT.COMMA):
                            continue
                        break
                self.expect(TT.RPAREN)
            value = None
            if self.match(TT.ASSIGN):
                sign = -1 if self.match(TT.MINUS) else 1
                vt = self.expect(TT.INT)
                value = sign * vt.value
            self.expect(TT.NEWLINE)
            members.append(A.EnumMember(
                mn.value, payload, value, A.Pos(mn.line, mn.col)))
        self.expect(TT.DEDENT)
        return A.EnumDecl(name, members, A.Pos(tok.line, tok.col),
                          type_params=type_params,
                          type_param_constraints=type_param_constraints)

        """Parse a comma-separated type argument list, without the brackets."""
        args = []
        while True:
            args.append(self.parse_type())
            if self.match(TT.COMMA):
                continue
            break
        return args

        return A.EnumDecl(name, members, A.Pos(tok.line, tok.col),
                          type_params=type_params)

    def parse_class(self):
        tok = self.advance()  # class
        name = self.expect(TT.IDENT).value
        parent = None
        if self.match(TT.EXTENDS):
            parent = self.expect(TT.IDENT).value
        self.expect(TT.COLON)
        self.expect(TT.NEWLINE)
        self.expect(TT.INDENT)
        fields = []
        signals = []
        methods = []
        while not self.check(TT.DEDENT):
            decorators = []
            while self.check(TT.AT):
                decorators.append(self._parse_decorator())
            if self.check(TT.IDENT) and self.peek().value == "signal":
                self.advance()
                name_tok = self.expect(TT.IDENT)
                params = []
                if self.match(TT.LPAREN):
                    if not self.check(TT.RPAREN):
                        while True:
                            p_tok = self.expect(TT.IDENT)
                            self.expect(TT.COLON)
                            ptype = self.parse_type()
                            params.append(A.Param(p_tok.value, ptype,
                                                  A.Pos(p_tok.line, p_tok.col)))
                            if not self.match(TT.COMMA):
                                break
                    self.expect(TT.RPAREN)
                ret = None
                if self.match(TT.ARROW):
                    ret = self.parse_type()
                self.expect(TT.COLON)
                self.expect(TT.NEWLINE)
                signal = A.SignalDecl(name_tok.value, params, ret,
                                      A.Pos(name_tok.line, name_tok.col))
                if decorators:
                    signal.decorators.extend(decorators)
                    if "@export" in decorators:
                        signal.is_exported = True
                signals.append(signal)
                continue
            if self.check(TT.FUNC):
                fd = self.parse_func(False)
                if decorators:
                    fd.decorators.extend(decorators)
                    if "@export" in decorators:
                        fd.is_exported = True
                methods.append(fd)
            elif self.check(TT.PUB) and self.peek(1).type == TT.FUNC:
                self.advance()  # pub
                fd = self.parse_func(False, True)
                if decorators:
                    fd.decorators.extend(decorators)
                    if "@export" in decorators:
                        fd.is_exported = True
                methods.append(fd)
            else:
                is_public = False
                if self.check(TT.PUB):
                    self.advance()
                    is_public = True
                fn = self.expect(TT.IDENT)
                self.expect(TT.COLON)
                ft = self.parse_type()
                self.expect(TT.NEWLINE)
                fields.append((fn.value, ft, A.Pos(fn.line, fn.col), is_public, decorators))
        self.expect(TT.DEDENT)
        return A.ClassDecl(name, parent, fields, methods,
                           A.Pos(tok.line, tok.col), signals=signals)
        """Parse a comma-separated type argument list, without the brackets."""
        args = []
        while True:
            args.append(self.parse_type())
            if self.match(TT.COMMA):
                continue
            break
        return args

    def parse_type_args(self):
        args = []
        while True:
            args.append(self.parse_type())
            if self.match(TT.COMMA):
                continue
            break
        return args

    def parse_type(self):
        t = self.peek()
        if t.type == TT.LBRACKET:
            self.advance()
            inner = self.parse_type()
            self.expect(TT.COMMA)
            size_tok = self.expect(TT.INT)
            if size_tok.value <= 0:
                self.error("array size must be a positive integer", size_tok)
            self.expect(TT.RBRACKET)
            return A.TypeExpr('array', inner=inner, size=size_tok.value, pos=A.Pos(t.line, t.col))
        if t.type == TT.FUNC:
            self.advance()
            self.expect(TT.LPAREN)
            params = []
            if not self.check(TT.RPAREN):
                while True:
                    params.append(self.parse_type())
                    if self.match(TT.COMMA):
                        continue
                    break
            self.expect(TT.RPAREN)
            ret = None
            if self.match(TT.ARROW):
                ret = self.parse_type()
            return A.TypeExpr('func', params=params, inner=ret, pos=A.Pos(t.line, t.col))
        if t.type != TT.IDENT:
            self.error("expected type name")
        self.advance()
        if t.value == 'ptr' and self.check(TT.LT):
            self.advance()
            inner = self.parse_type()
            self.expect(TT.GT)
            return A.TypeExpr('ptr', inner=inner, pos=A.Pos(t.line, t.col))
        if t.value == 'List' and self.check(TT.LT):
            self.advance()
            inner = self.parse_type()
            self.expect(TT.GT)
            return A.TypeExpr('list', inner=inner, pos=A.Pos(t.line, t.col))
        name = t.value
        while self.match(TT.DOT):
            name += '.' + self.expect(TT.IDENT, "expected a type name after '.'").value
        args = None
        if self.match(TT.LT):
            args = self.parse_type_args()
            self.expect(TT.GT)
        return A.TypeExpr('named', name=name, args=args,
                          pos=A.Pos(t.line, t.col))

    def parse_block(self):
        self.expect(TT.NEWLINE)
        self.expect(TT.INDENT)
        stmts = []
        while not self.check(TT.DEDENT) and not self.check(TT.EOF):
            stmts.append(self.parse_stmt())
        self.expect(TT.DEDENT)
        return stmts

    def parse_stmt(self):
        t = self.peek()
        if t.type in (TT.LET, TT.MUT):
            return self.parse_var_decl()
        if t.type == TT.RETURN:
            return self.parse_return()
        if t.type == TT.BREAK:
            tok = self.advance()
            self.expect(TT.NEWLINE)
            return A.BreakStmt(A.Pos(tok.line, tok.col))
        if t.type == TT.CONTINUE:
            tok = self.advance()
            self.expect(TT.NEWLINE)
            return A.ContinueStmt(A.Pos(tok.line, tok.col))
        if t.type == TT.IF:
            return self.parse_if()
        if t.type == TT.WHILE:
            return self.parse_while()
        if t.type == TT.FOR:
            return self.parse_for()
        if t.type == TT.MATCH:
            return self.parse_match()
        if t.type == TT.EMIT:
            return self.parse_emit()
        return self.parse_expr_or_assign()

    def parse_emit(self):
        tok = self.advance()  # emit
        signal = self.expect(TT.IDENT).value
        args = []
        if self.match(TT.LPAREN):
            if not self.check(TT.RPAREN):
                while True:
                    args.append(self.parse_expr())
                    if not self.match(TT.COMMA):
                        break
            self.expect(TT.RPAREN)
        if self.check(TT.NEWLINE):
            self.advance()
        return A.EmitStmt(signal, args, A.Pos(tok.line, tok.col))

    def parse_var_decl(self):
        tok = self.advance()
        mutable = tok.type == TT.MUT
        name = self.expect(TT.IDENT).value
        ann = None
        if self.match(TT.COLON):
            ann = self.parse_type()
        self.expect(TT.ASSIGN)
        val = self.parse_expr()
        if self.check(TT.NEWLINE):
            self.advance()
        return A.VarDecl(name, ann, mutable, val, A.Pos(tok.line, tok.col))

    def parse_return(self):
        tok = self.advance()
        val = None
        if not self.check(TT.NEWLINE) and not self.check(TT.DEDENT):
            val = self.parse_expr()
        if self.check(TT.NEWLINE):
            self.advance()
        return A.ReturnStmt(val, A.Pos(tok.line, tok.col))

    def parse_if(self):
        tok = self.advance()
        cond = self.parse_expr()
        self.expect(TT.COLON)
        then_body = self.parse_block()
        elifs = []
        while self.check(TT.ELIF):
            self.advance()
            c = self.parse_expr()
            self.expect(TT.COLON)
            elifs.append((c, self.parse_block()))
        else_body = None
        if self.check(TT.ELSE):
            self.advance()
            self.expect(TT.COLON)
            else_body = self.parse_block()
        return A.IfStmt(cond, then_body, elifs, else_body, A.Pos(tok.line, tok.col))

    def parse_while(self):
        tok = self.advance()
        cond = self.parse_expr()
        self.expect(TT.COLON)
        body = self.parse_block()
        return A.WhileStmt(cond, body, A.Pos(tok.line, tok.col))

    def parse_for(self):
        tok = self.advance()
        var = self.expect(TT.IDENT).value
        self.expect(TT.IN)
        if (self.check(TT.IDENT) and self.peek().value == 'range'
                and self.peek(1).type == TT.LPAREN):
            self.advance()  # 'range'
            self.expect(TT.LPAREN)
            start = self.parse_expr()
            self.expect(TT.COMMA)
            end = self.parse_expr()
            step = None
            if self.match(TT.COMMA):
                step = self.parse_expr()
            self.expect(TT.RPAREN)
            self.expect(TT.COLON)
            body = self.parse_block()
            return A.ForRangeStmt(var, start, end, step, body, A.Pos(tok.line, tok.col))
        # for x in <expr>: iterate a List or array element by element.
        iterable = self.parse_expr()
        self.expect(TT.COLON)
        body = self.parse_block()
        return A.ForEachStmt(var, iterable, body, A.Pos(tok.line, tok.col))

    def parse_match(self):
        tok = self.advance()
        value = self.parse_expr()
        self.expect(TT.COLON)
        self.expect(TT.NEWLINE)
        self.expect(TT.INDENT)
        arms = []
        while not self.check(TT.DEDENT) and not self.check(TT.EOF):
            arm = self.parse_match_arm()
            if arm.is_else and not (self.check(TT.DEDENT) or self.check(TT.EOF)):
                self.error("'else' must be the last match arm")
            arms.append(arm)
        self.expect(TT.DEDENT)
        return A.MatchStmt(value, arms, A.Pos(tok.line, tok.col))

    def parse_match_arm(self):
        t = self.peek()
        if t.type == TT.ELSE:
            self.advance()
            self.expect(TT.COLON)
            return A.MatchArm([], True, self.parse_block(), A.Pos(t.line, t.col))
        patterns = []
        while True:
            parts = [self.expect(TT.IDENT)]
            while self.match(TT.DOT):
                parts.append(self.expect(TT.IDENT))
            if len(parts) < 2:
                self.error("match patterns are written Enum.Member", parts[0])
            tn = parts[0]
            mn = parts[-1]
            bindings = None
            if self.match(TT.LPAREN):
                bindings = []
                if not self.check(TT.RPAREN):
                    while True:
                        b = self.expect(TT.IDENT)
                        bindings.append(b.value)
                        if self.match(TT.COMMA):
                            continue
                        break
                self.expect(TT.RPAREN)
            patterns.append(A.MatchPattern(
                '.'.join(p.value for p in parts[:-1]), mn.value, bindings,
                A.Pos(tn.line, tn.col)))
            if not self.match(TT.COMMA):
                break
        guard = None
        if self.match(TT.IF):
            guard = self.parse_expr()
        self.expect(TT.COLON)
        return A.MatchArm(patterns, False, self.parse_block(), A.Pos(t.line, t.col),
                          guard=guard)

    def parse_expr_or_assign(self):
        tok = self.peek()
        expr = self.parse_expr()
        if self.peek().type in COMPOUND_OPS:
            op_tok = self.advance()
            op = COMPOUND_OPS[op_tok.type]
            val = self.parse_expr()
            self.expect(TT.NEWLINE)
            return A.AssignStmt(
                expr,
                A.BinOp(op, expr, val, A.Pos(op_tok.line, op_tok.col)),
                A.Pos(tok.line, tok.col),
            )
        if self.check(TT.ASSIGN):
            self.advance()
            val = self.parse_expr()
            self.expect(TT.NEWLINE)
            return A.AssignStmt(expr, val, A.Pos(tok.line, tok.col))
        if self.check(TT.NEWLINE):
            self.advance()
        return A.ExprStmt(expr, A.Pos(tok.line, tok.col))

    def parse_expr(self, min_prec=0):
        left = self.parse_unary()
        while True:
            t = self.peek()
            if t.type in BIN_PREC and BIN_PREC[t.type] > min_prec:
                op = self.advance()
                prec = BIN_PREC[op.type]
                right = self.parse_expr(prec)
                left = A.BinOp(op.value, left, right, A.Pos(op.line, op.col))
            else:
                break
        return left

    def parse_unary(self):
        t = self.peek()
        if t.type == TT.MINUS:
            tok = self.advance()
            operand = self.parse_unary()
            if isinstance(operand, A.IntLit):
                return A.IntLit(-operand.value, A.Pos(tok.line, tok.col))
            if isinstance(operand, A.FloatLit):
                return A.FloatLit(-operand.value, A.Pos(tok.line, tok.col))
            return A.UnaryOp('-', operand, A.Pos(tok.line, tok.col))
        if t.type == TT.NOT:
            tok = self.advance()
            return A.UnaryOp('not', self.parse_unary(), A.Pos(tok.line, tok.col))
        return self.parse_postfix()

    def parse_postfix(self):
        expr = self.parse_primary()
        while True:
            t = self.peek()
            if t.type == TT.DOT:
                self.advance()
                field = self.expect(TT.IDENT)
                if self.check(TT.COLONCOLON):
                    self.advance()
                    self.expect(TT.LT)
                    type_args = self.parse_type_args()
                    self.expect(TT.GT)
                    self.expect(TT.LPAREN)
                    args, names = self._parse_args_until_rparen()
                    self.expect(TT.RPAREN)
                    expr = A.Call(
                        A.Member(expr, field.value, A.Pos(t.line, t.col)),
                        args, names, type_args, A.Pos(t.line, t.col)
                    )
                elif self.check(TT.LPAREN):
                    self.advance()
                    args, names = self._parse_args_until_rparen()
                    self.expect(TT.RPAREN)
                    expr = A.Call(
                        A.Member(expr, field.value, A.Pos(t.line, t.col)),
                        args, names, None, A.Pos(t.line, t.col)
                    )
                else:
                    expr = A.Member(expr, field.value, A.Pos(t.line, t.col))
            elif t.type == TT.LBRACKET:
                self.advance()
                idx = self.parse_expr()
                self.expect(TT.RBRACKET)
                expr = A.Index(expr, idx, A.Pos(t.line, t.col))
            elif t.type == TT.LPAREN:
                # Calling a non-name expression: an indexed element, a
                # parenthesized value, or the result of another call.
                self.advance()
                args, names = self._parse_args_until_rparen()
                self.expect(TT.RPAREN)
                expr = A.Call(expr, args, names, None, A.Pos(t.line, t.col))
            else:
                break
        return expr

    def parse_primary(self):
        t = self.peek()
        if t.type == TT.FUNC and self.peek(1).type == TT.LPAREN:
            self.advance()  # func
            self.expect(TT.LPAREN)
            params = []
            if not self.check(TT.RPAREN):
                while True:
                    pn = self.expect(TT.IDENT)
                    self.expect(TT.COLON)
                    pt = self.parse_type()
                    params.append(
                        A.Param(pn.value, pt, A.Pos(pn.line, pn.col)))
                    if self.match(TT.COMMA):
                        continue
                    break
            self.expect(TT.RPAREN)
            ret = None
            if self.match(TT.ARROW):
                ret = self.parse_type()
            self.expect(TT.COLON)
            body = self.parse_block()
            return A.LambdaExpr(params, ret, body,
                                A.Pos(t.line, t.col))
        if t.type == TT.INT:
            self.advance(); return A.IntLit(t.value, A.Pos(t.line, t.col))
        if t.type == TT.FLOAT:
            self.advance(); return A.FloatLit(t.value, A.Pos(t.line, t.col))
        if t.type == TT.STRING:
            self.advance(); return A.StringLit(t.value, A.Pos(t.line, t.col))
        if t.type == TT.TRUE:
            self.advance(); return A.BoolLit(True, A.Pos(t.line, t.col))
        if t.type == TT.FALSE:
            self.advance(); return A.BoolLit(False, A.Pos(t.line, t.col))
        if t.type == TT.LBRACKET:
            self.advance()
            elements = []
            if not self.check(TT.RBRACKET):
                while True:
                    elements.append(self.parse_expr())
                    if self.match(TT.COMMA):
                        continue
                    break
            self.expect(TT.RBRACKET)
            return A.ArrayLit(elements, A.Pos(t.line, t.col))
        if t.type == TT.IDENT:
            self.advance()
            name_pos = A.Pos(t.line, t.col)
            if self.check(TT.COLONCOLON):
                self.advance()
                self.expect(TT.LT)
                type_args = self.parse_type_args()
                self.expect(TT.GT)
                self.expect(TT.LPAREN)
                args, names = self._parse_args_until_rparen()
                self.expect(TT.RPAREN)
                return A.Call(A.Name(t.value, name_pos), args, names, type_args, name_pos)
            if self.check(TT.LPAREN):
                self.advance()
                args, names = self._parse_args_until_rparen()
                self.expect(TT.RPAREN)
                return A.Call(A.Name(t.value, name_pos), args, names, None, name_pos)
            return A.Name(t.value, name_pos)
        if t.type == TT.LPAREN:
            self.advance()
            e = self.parse_expr()
            self.expect(TT.RPAREN)
            return e
        self.error(f"unexpected token {t.type.name}")

    def _parse_args_until_rparen(self):
        args, names = [], []
        if self.check(TT.RPAREN):
            return args, None
        has_named = False
        while True:
            if self.check(TT.IDENT) and self.peek(1).type == TT.COLON:
                name_tok = self.advance()
                self.expect(TT.COLON)
                e = self.parse_expr()
                args.append(e)
                names.append(name_tok.value)
                has_named = True
            else:
                e = self.parse_expr()
                args.append(e)
                names.append(None)
            if self.match(TT.COMMA):
                continue
            break
        return args, (names if has_named else None)


def parse(tokens, filename="<input>"):
    return Parser(tokens, filename).parse_program()
