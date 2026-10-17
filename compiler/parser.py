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

    # ---------------- Top level ----------------
    def parse_program(self):
        decls = []
        while not self.check(TT.EOF):
            if self.check(TT.NEWLINE):
                self.advance(); continue
            decls.append(self.parse_top_level())
        return A.Program(decls)

    def parse_top_level(self):
        t = self.peek()
        if t.type == TT.FUNC:
            return self.parse_func(False)
        if t.type == TT.SYSTEM:
            return self.parse_func(True)
        if t.type == TT.STRUCT:
            return self.parse_struct(False)
        if t.type == TT.COMPONENT:
            return self.parse_struct(True)
        self.error(f"expected top-level declaration, got {t.type.name}")

    def parse_func(self, is_system):
        tok = self.advance()
        name = self.expect(TT.IDENT).value
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
        return A.FuncDecl(name, params, ret, body, is_system, A.Pos(tok.line, tok.col))

    def parse_struct(self, is_component):
        tok = self.advance()
        name = self.expect(TT.IDENT).value
        self.expect(TT.COLON)
        self.expect(TT.NEWLINE)
        self.expect(TT.INDENT)
        fields = []
        while not self.check(TT.DEDENT):
            fn = self.expect(TT.IDENT)
            self.expect(TT.COLON)
            ft = self.parse_type()
            self.expect(TT.NEWLINE)
            fields.append((fn.value, ft, A.Pos(fn.line, fn.col)))
        self.expect(TT.DEDENT)
        return A.StructDecl(name, fields, is_component, A.Pos(tok.line, tok.col))

    def parse_type(self):
        t = self.peek()
        if t.type != TT.IDENT:
            self.error("expected type name")
        self.advance()
        if t.value == 'ptr' and self.check(TT.LT):
            self.advance()
            inner = self.parse_type()
            self.expect(TT.GT)
            return A.TypeExpr('ptr', inner=inner, pos=A.Pos(t.line, t.col))
        return A.TypeExpr('named', name=t.value, pos=A.Pos(t.line, t.col))

    # ---------------- Statements ----------------
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
        return self.parse_expr_or_assign()

    def parse_var_decl(self):
        tok = self.advance()
        mutable = tok.type == TT.MUT
        name = self.expect(TT.IDENT).value
        ann = None
        if self.match(TT.COLON):
            ann = self.parse_type()
        self.expect(TT.ASSIGN)
        val = self.parse_expr()
        self.expect(TT.NEWLINE)
        return A.VarDecl(name, ann, mutable, val, A.Pos(tok.line, tok.col))

    def parse_return(self):
        tok = self.advance()
        val = None
        if not self.check(TT.NEWLINE):
            val = self.parse_expr()
        self.expect(TT.NEWLINE)
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
        rng = self.expect(TT.IDENT)
        if rng.value != 'range':
            self.error("expected 'range' after 'in'", rng)
        self.expect(TT.LPAREN)
        start = self.parse_expr()
        self.expect(TT.COMMA)
        end = self.parse_expr()
        self.expect(TT.RPAREN)
        self.expect(TT.COLON)
        body = self.parse_block()
        return A.ForRangeStmt(var, start, end, body, A.Pos(tok.line, tok.col))

    def parse_expr_or_assign(self):
        tok = self.peek()
        expr = self.parse_expr()

        # Compound assignment desugars: `x += v` becomes `x = x + v`.
        # NOTE: the target expression is evaluated twice at runtime. Safe for
        # simple lvalues like `a`, `a.b`, `a[i]` (no side effects). Not safe
        # if the target involves a function call, but such targets are
        # rejected by the type checker's _is_assignable anyway.
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
        self.expect(TT.NEWLINE)
        return A.ExprStmt(expr, A.Pos(tok.line, tok.col))

    # ---------------- Expressions ----------------
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
                    type_arg = self.parse_type()
                    self.expect(TT.GT)
                    self.expect(TT.LPAREN)
                    args, names = self._parse_args_until_rparen()
                    self.expect(TT.RPAREN)
                    expr = A.Call(
                        A.Member(expr, field.value, A.Pos(t.line, t.col)),
                        args, names, [type_arg], A.Pos(t.line, t.col)
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
            else:
                break
        return expr

    def parse_primary(self):
        t = self.peek()
        if t.type == TT.INT:
            self.advance(); return A.IntLit(t.value, A.Pos(t.line, t.col))
        if t.type == TT.FLOAT:
            self.advance(); return A.FloatLit(t.value, A.Pos(t.line, t.col))
        if t.type == TT.TRUE:
            self.advance(); return A.BoolLit(True, A.Pos(t.line, t.col))
        if t.type == TT.FALSE:
            self.advance(); return A.BoolLit(False, A.Pos(t.line, t.col))
        if t.type == TT.IDENT:
            self.advance()
            name_pos = A.Pos(t.line, t.col)
            if self.check(TT.COLONCOLON):
                self.advance()
                self.expect(TT.LT)
                type_arg = self.parse_type()
                self.expect(TT.GT)
                self.expect(TT.LPAREN)
                args, names = self._parse_args_until_rparen()
                self.expect(TT.RPAREN)
                return A.Call(A.Name(t.value, name_pos), args, names, [type_arg], name_pos)
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