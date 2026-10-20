from dataclasses import dataclass
from typing import Optional, List, Any


@dataclass
class Pos:
    line: int
    col: int
    file: Optional[str] = None


@dataclass
class Program:
    decls: List[Any]


@dataclass
class TypeExpr:
    kind: str
    name: Optional[str] = None
    inner: Optional['TypeExpr'] = None
    size: Optional[int] = None
    pos: Optional[Pos] = None
    # For kind == 'func': the parameter type expressions. `inner` holds the
    # return type, or None for void.
    params: Optional[List['TypeExpr']] = None


@dataclass
class Param:
    name: str
    type: TypeExpr
    pos: Pos


@dataclass
class FuncDecl:
    name: str
    params: List[Param]
    ret: Optional[TypeExpr]
    body: List[Any]
    is_system: bool
    pos: Pos


@dataclass
class StructDecl:
    name: str
    fields: List[Any]
    is_component: bool
    pos: Pos


@dataclass
class EnumMember:
    name: str
    # None when the member has no parentheses; [] for an explicit `Member()`.
    payload: Optional[List[TypeExpr]]
    value: Optional[int]
    pos: Pos


@dataclass
class EnumDecl:
    name: str
    members: List[EnumMember]
    pos: Pos


@dataclass
class ExternDecl:
    lib_name: str
    funcs: List['FuncDecl']
    pos: Pos


@dataclass
class ImportDecl:
    path: str
    pos: Pos


@dataclass
class ConstDecl:
    name: str
    type_ann: Optional[TypeExpr]
    value: Any
    pos: Pos


@dataclass
class VarDecl:
    name: str
    type_ann: Optional[TypeExpr]
    mutable: bool
    value: Any
    pos: Pos


@dataclass
class AssignStmt:
    target: Any
    value: Any
    pos: Pos


@dataclass
class ReturnStmt:
    value: Optional[Any]
    pos: Pos


@dataclass
class BreakStmt:
    pos: Pos


@dataclass
class ContinueStmt:
    pos: Pos


@dataclass
class IfStmt:
    cond: Any
    then_body: List[Any]
    elif_branches: List[Any]
    else_body: Optional[List[Any]]
    pos: Pos


@dataclass
class MatchPattern:
    enum_name: str
    member: str
    # None when the pattern has no parentheses; a list of binding names
    # (including `_`) when it does.
    bindings: Optional[List[str]]
    pos: Pos


@dataclass
class MatchArm:
    # One MatchPattern per pattern; empty for else.
    patterns: List[MatchPattern]
    is_else: bool
    body: List[Any]
    pos: Pos


@dataclass
class MatchStmt:
    value: Any
    arms: List[Any]
    pos: Pos


@dataclass
class WhileStmt:
    cond: Any
    body: List[Any]
    pos: Pos


@dataclass
class ForRangeStmt:
    var: str
    start: Any
    end: Any
    step: Optional[Any]
    body: List[Any]
    pos: Pos


@dataclass
class ForEachStmt:
    var: str
    iterable: Any
    body: List[Any]
    pos: Pos


@dataclass
class ExprStmt:
    expr: Any
    pos: Pos


@dataclass
class IntLit:
    value: int
    pos: Pos


@dataclass
class FloatLit:
    value: float
    pos: Pos


@dataclass
class BoolLit:
    value: bool
    pos: Pos


@dataclass
class StringLit:
    value: str
    pos: Pos


@dataclass
class ArrayLit:
    elements: List[Any]
    pos: Pos


@dataclass
class Name:
    name: str
    pos: Pos


@dataclass
class BinOp:
    op: str
    left: Any
    right: Any
    pos: Pos


@dataclass
class UnaryOp:
    op: str
    operand: Any
    pos: Pos


@dataclass
class Call:
    func: Any
    args: List[Any]
    arg_names: Optional[List[Optional[str]]] = None
    type_args: Optional[List[TypeExpr]] = None
    pos: Optional[Pos] = None


@dataclass
class Member:
    obj: Any
    field: str
    pos: Pos


@dataclass
class Index:
    obj: Any
    index: Any
    pos: Pos