from dataclasses import dataclass, field
from typing import Optional, List, Any, Dict


@dataclass
class Pos:
    line: int
    col: int
    file: Optional[str] = None


@dataclass
class Program:
    decls: List[Any]
    # Internal C++ name -> source name, used to keep diagnostics readable
    # after module-scoped declarations are given unique names.
    display_names: dict = field(default_factory=dict)
    # Internal names of types that are private to their module. The type
    # checker uses this for inferred public signatures, where the loader has
    # no explicit TypeExpr to inspect.
    private_types: set = field(default_factory=set)


@dataclass
class ModuleDecl:
    name: str
    pos: Pos


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
    # For kind == 'named': generic arguments, e.g. Option<i32>. None when the
    # type name was written without angle brackets.
    args: Optional[List['TypeExpr']] = None


@dataclass
class Param:
    name: str
    type: TypeExpr
    pos: Pos


@dataclass
class LambdaExpr:
    # An anonymous function literal. If it captures variables from its
    # enclosing scope it becomes a closure: the checker generates a wrapper
    # function taking a context pointer and a closure struct type bundling
    # the invoke function pointer with the captured values.
    params: List[Param]
    ret: Optional[TypeExpr]
    body: List[Any]
    pos: Pos
    name: str = ''  # filled in by the checker
    is_closure: bool = False  # True when the lambda captures variables
    captured_names: List[str] = field(default_factory=list)  # names captured from enclosing scope
    invoke_name: str = ''  # generated wrapper function name (closure only)
    ctx_struct_name: str = ''  # generated closure context struct name (closure only)

@dataclass
class FuncDecl:
    name: str
    params: List[Param]
    ret: Optional[TypeExpr]
    body: List[Any]
    is_system: bool
    pos: Pos
    is_public: bool = False
    # Type parameters for a generic function, e.g. ['T'] for identity<T>.
    type_params: List[str] = field(default_factory=list)
    # Type parameter name -> list of constraint names, e.g. {'T': ['Copyable']}.
    type_param_constraints: Dict[str, List[str]] = field(default_factory=dict)


@dataclass
class StructDecl:
    name: str
    fields: List[Any]
    is_component: bool
    pos: Pos
    is_public: bool = False
    # Type parameters for a generic struct, e.g. ['T', 'U'] for Pair<T, U>.
    type_params: List[str] = field(default_factory=list)
    # Type parameter name -> list of constraint names.
    type_param_constraints: Dict[str, List[str]] = field(default_factory=dict)


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
    is_public: bool = False
    # Type parameters for a generic enum, e.g. ['T', 'E'] for Result<T, E>.
    type_params: List[str] = field(default_factory=list)
    # Type parameter name -> list of constraint names.
    type_param_constraints: Dict[str, List[str]] = field(default_factory=dict)


@dataclass
class ClassDecl:
    # A class with methods and optional single inheritance.
    name: str
    parent: Optional[str]  # parent class name, or None
    fields: List[Any]      # (name, TypeExpr, Pos)
    methods: List[FuncDecl]  # each method's first param is `self`
    pos: Pos
    is_public: bool = False
    type_params: List[str] = field(default_factory=list)
    # Type parameter name -> list of constraint names.
    type_param_constraints: Dict[str, List[str]] = field(default_factory=dict)


@dataclass
class ExternDecl:
    lib_name: str
    funcs: List['FuncDecl']
    pos: Pos
    is_public: bool = False


@dataclass
class ImportDecl:
    path: str
    pos: Pos
    alias: Optional[str] = None


@dataclass
class ConstDecl:
    name: str
    type_ann: Optional[TypeExpr]
    value: Any
    pos: Pos
    is_public: bool = False


@dataclass
class VarDecl:
    name: str
    type_ann: Optional[TypeExpr]
    mutable: bool
    value: Any
    pos: Pos
    is_public: bool = False


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
    # Optional `if expr` guard evaluated after the tag check.
    guard: Any = None


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