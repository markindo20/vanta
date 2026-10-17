from dataclasses import dataclass
from typing import Dict, Optional


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
class InferType(Type):
    """Placeholder for an inferred function return type.
    Never appears at codegen time (check() always resolves it)."""
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


I32 = PrimType("i32")
U32 = PrimType("u32")
F32 = PrimType("f32")
F64 = PrimType("f64")
BOOL = PrimType("bool")
VOID = PrimType("void")
INT_LIT = IntLitType()
FLOAT_LIT = FloatLitType()
INFER = InferType()

PRIM_TYPES = {"i32": I32, "u32": U32, "f32": F32, "f64": F64, "bool": BOOL, "void": VOID}


def is_int(t): return t is I32 or t is U32
def is_float(t): return t is F32 or t is F64
def is_numeric(t): return is_int(t) or is_float(t)