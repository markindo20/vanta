from dataclasses import dataclass
from typing import Dict, Optional, Tuple


class Type:
    pass


@dataclass(frozen=True)
class PrimType(Type):
    name: str
    def __repr__(self): return self.name


@dataclass(frozen=True)
class IntLitType(Type):
    def __repr__(self): return "<int-lit>"


@dataclass(frozen=True)
class FloatLitType(Type):
    def __repr__(self): return "<float-lit>"


@dataclass(frozen=True)
class PtrType(Type):
    inner: Type
    def __repr__(self): return f"ptr<{self.inner}>"


@dataclass(frozen=True)
class ArrayType(Type):
    inner: Type
    size: int
    def __repr__(self): return f"[{self.inner}, {self.size}]"


@dataclass(frozen=True)
class InferType(Type):
    def __repr__(self): return "<infer>"


@dataclass(eq=False)
class StructType(Type):
    name: str
    fields: Dict[str, Type]
    builtin: bool = False
    def __eq__(self, other):
        return isinstance(other, StructType) and self.name == other.name
    def __hash__(self): return hash(self.name)
    def __repr__(self): return self.name


@dataclass(frozen=True)
class FuncType(Type):
    params: Tuple[Type, ...]
    ret: Type
    def __repr__(self):
        inner = ", ".join(repr(p) for p in self.params)
        if self.ret is VOID:
            return f"func({inner})"
        return f"func({inner}) -> {self.ret}"


I32 = PrimType("i32")
U32 = PrimType("u32")
F32 = PrimType("f32")
F64 = PrimType("f64")
BOOL = PrimType("bool")
VOID = PrimType("void")
STR = PrimType("str")
INT_LIT = IntLitType()
FLOAT_LIT = FloatLitType()
INFER = InferType()

PRIM_TYPES = {
    "i32": I32, "u32": U32, "f32": F32, "f64": F64,
    "bool": BOOL, "void": VOID, "str": STR,
}


def is_int(t): return t is I32 or t is U32
def is_float(t): return t is F32 or t is F64
def is_numeric(t): return is_int(t) or is_float(t)