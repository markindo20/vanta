from dataclasses import dataclass
from enum import Enum, auto


class TT(Enum):
    INT = auto(); FLOAT = auto(); STRING = auto(); IDENT = auto()
    FUNC = auto(); LET = auto(); MUT = auto(); RETURN = auto(); CONST = auto()
    STRUCT = auto(); COMPONENT = auto(); SYSTEM = auto(); EXTERN = auto(); ENUM = auto()
    IMPORT = auto()
    IF = auto(); ELIF = auto(); ELSE = auto()
    WHILE = auto(); FOR = auto(); IN = auto()
    BREAK = auto(); CONTINUE = auto()
    TRUE = auto(); FALSE = auto()
    AND = auto(); OR = auto(); NOT = auto()
    PLUS = auto(); MINUS = auto(); STAR = auto(); SLASH = auto(); PERCENT = auto()
    EQ = auto(); NEQ = auto(); LT = auto(); LTE = auto(); GT = auto(); GTE = auto()
    ASSIGN = auto(); PLUS_EQ = auto(); MINUS_EQ = auto(); STAR_EQ = auto(); SLASH_EQ = auto()
    ARROW = auto()
    LPAREN = auto(); RPAREN = auto(); LBRACKET = auto(); RBRACKET = auto()
    LBRACE = auto(); RBRACE = auto()
    COLON = auto(); COMMA = auto(); DOT = auto(); COLONCOLON = auto()
    NEWLINE = auto(); INDENT = auto(); DEDENT = auto(); EOF = auto()


KEYWORDS = {
    'func': TT.FUNC, 'let': TT.LET, 'mut': TT.MUT, 'return': TT.RETURN,
    'const': TT.CONST,
    'struct': TT.STRUCT, 'component': TT.COMPONENT, 'system': TT.SYSTEM,
    'enum': TT.ENUM,
    'extern': TT.EXTERN, 'import': TT.IMPORT,
    'if': TT.IF, 'elif': TT.ELIF, 'else': TT.ELSE,
    'while': TT.WHILE, 'for': TT.FOR, 'in': TT.IN,
    'break': TT.BREAK, 'continue': TT.CONTINUE,
    'true': TT.TRUE, 'false': TT.FALSE,
    'and': TT.AND, 'or': TT.OR, 'not': TT.NOT,
}


@dataclass
class Token:
    type: TT
    value: object
    line: int
    col: int

    def __repr__(self):
        return f"Token({self.type.name}, {self.value!r}, {self.line}:{self.col})"