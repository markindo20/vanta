from .tokens import TT, Token, KEYWORDS


class LexError(Exception):
    def __init__(self, msg, filename, line, col):
        self.msg = msg; self.filename = filename; self.line = line; self.col = col
        super().__init__(f"{filename}:{line}:{col}: {msg}")


class Lexer:
    def __init__(self, source: str, filename: str = "<input>"):
        self.source = source
        self.filename = filename
        self.pos = 0
        self.line = 1
        self.col = 1
        self.indent_stack = [0]
        self.tokens: list[Token] = []

    def _err(self, msg, line=None, col=None):
        raise LexError(msg, self.filename, line or self.line, col or self.col)

    def _peek(self, off=0):
        p = self.pos + off
        return self.source[p] if p < len(self.source) else ''

    def _adv(self):
        ch = self.source[self.pos]
        self.pos += 1
        if ch == '\n':
            self.line += 1
            self.col = 1
        else:
            self.col += 1
        return ch

    def _emit(self, tt, value=None, line=None, col=None):
        self.tokens.append(Token(tt, value, line or self.line, col or self.col))

    def tokenize(self):
        at_line_start = True
        while self.pos < len(self.source):
            if at_line_start:
                indent = 0
                while self._peek() in (' ', '\t'):
                    if self._peek() == '\t':
                        self._err("tabs are not permitted in indentation; use spaces")
                    indent += 1
                    self._adv()
                if self.pos >= len(self.source):
                    break
                if self._peek() == '\n':
                    self._adv(); continue
                if self._peek() == '#':
                    while self.pos < len(self.source) and self._peek() != '\n':
                        self._adv()
                    if self.pos < len(self.source):
                        self._adv()
                    continue
                if indent > self.indent_stack[-1]:
                    self.indent_stack.append(indent)
                    self._emit(TT.INDENT, indent, self.line, 1)
                elif indent < self.indent_stack[-1]:
                    while self.indent_stack and self.indent_stack[-1] > indent:
                        self.indent_stack.pop()
                        self._emit(TT.DEDENT, indent, self.line, 1)
                    if self.indent_stack[-1] != indent:
                        self._err("inconsistent indentation")
                at_line_start = False
                continue

            ch = self._peek()
            if ch == '\n':
                self._emit(TT.NEWLINE, '\n'); self._adv(); at_line_start = True; continue
            if ch in (' ', '\t'):
                self._adv(); continue
            if ch == '#':
                while self.pos < len(self.source) and self._peek() != '\n':
                    self._adv()
                continue
            if ch == '"':
                self._lex_string(); continue
            if ch.isdigit():
                self._lex_number(); continue
            if ch.isalpha() or ch == '_':
                self._lex_ident(); continue
            self._lex_op()

        if self.tokens and self.tokens[-1].type not in (TT.NEWLINE, TT.DEDENT):
            self._emit(TT.NEWLINE, '\n')
        while len(self.indent_stack) > 1:
            self.indent_stack.pop()
            self._emit(TT.DEDENT, 0)
        self._emit(TT.EOF)
        return self.tokens

    def _lex_number(self):
        line, col = self.line, self.col
        num = ''
        while self._peek().isdigit():
            num += self._adv()
        if self._peek() == '.' and self._peek(1).isdigit():
            num += self._adv()
            while self._peek().isdigit():
                num += self._adv()
            self._emit(TT.FLOAT, float(num), line, col)
        else:
            self._emit(TT.INT, int(num), line, col)

    def _lex_ident(self):
        line, col = self.line, self.col
        name = ''
        while self._peek().isalnum() or self._peek() == '_':
            name += self._adv()
        self._emit(KEYWORDS.get(name, TT.IDENT), name, line, col)

    def _lex_string(self):
        line, col = self.line, self.col
        self._adv()  # opening "
        buf = []
        while True:
            c = self._peek()
            if c == '':
                self._err("unterminated string literal", line, col)
            if c == '\n':
                self._err("unterminated string literal", line, col)
            if c == '"':
                self._adv()
                break
            if c == '\\':
                self._adv()
                esc = self._peek()
                if esc == '':
                    self._err("unterminated escape sequence", line, col)
                self._adv()
                if esc == 'n': buf.append('\n')
                elif esc == 't': buf.append('\t')
                elif esc == 'r': buf.append('\r')
                elif esc == '\\': buf.append('\\')
                elif esc == '"': buf.append('"')
                elif esc == '0': buf.append('\0')
                else: self._err(f"unknown escape sequence '\\{esc}'", line, col)
            else:
                buf.append(c)
                self._adv()
        self._emit(TT.STRING, ''.join(buf), line, col)

    def _lex_op(self):
        line, col = self.line, self.col
        ch = self._adv()
        two = ch + self._peek()
        two_map = {
            '->': TT.ARROW, '==': TT.EQ, '!=': TT.NEQ,
            '<=': TT.LTE, '>=': TT.GTE, '::': TT.COLONCOLON,
            '+=': TT.PLUS_EQ, '-=': TT.MINUS_EQ,
            '*=': TT.STAR_EQ, '/=': TT.SLASH_EQ,
        }
        if two in two_map:
            self._adv()
            self._emit(two_map[two], two, line, col)
            return
        single = {
            '+': TT.PLUS, '-': TT.MINUS, '*': TT.STAR, '/': TT.SLASH,
            '%': TT.PERCENT, '<': TT.LT, '>': TT.GT, '=': TT.ASSIGN,
            '(': TT.LPAREN, ')': TT.RPAREN, '[': TT.LBRACKET, ']': TT.RBRACKET,
            '{': TT.LBRACE, '}': TT.RBRACE,
            ':': TT.COLON, ',': TT.COMMA, '.': TT.DOT,
        }
        if ch in single:
            self._emit(single[ch], ch, line, col)
            return
        self._err(f"unexpected character {ch!r}", line, col)