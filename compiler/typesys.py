from dataclasses import dataclass, field
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
class ListType(Type):
    inner: Type
    def __repr__(self): return f"List<{self.inner}>"


@dataclass(frozen=True)
class InferType(Type):
    def __repr__(self): return "<infer>"


@dataclass(eq=False)
class StructType(Type):
    name: str
    fields: Dict[str, Type]
    builtin: bool = False
    # Generic struct instances carry the declaration family and the concrete
    # type arguments, mirroring EnumType. `display` is the source spelling
    # (e.g. Pair<i32>) used in diagnostics; `name` is the C++ tag.
    family: Optional[str] = None
    type_args: Tuple[Type, ...] = ()
    display: Optional[str] = None
    @property
    def is_generic_instance(self) -> bool:
        return self.family is not None
    def __eq__(self, other):
        return isinstance(other, StructType) and self.name == other.name
    def __hash__(self): return hash(self.name)
    def __repr__(self): return self.display or self.name


@dataclass(eq=False)
class EnumType(Type):
    name: str
    members: Dict[str, int]
    # Member name -> payload types. Members without a payload map to ().
    payloads: Dict[str, Tuple[Type, ...]] = field(default_factory=dict)
    # Generic enum instances carry the declaration family they came from and
    # the concrete type arguments. `display` is the source-level spelling
    # used in diagnostics (e.g. Option<i32>); C++ codegen keeps using `name`.
    family: Optional[str] = None
    type_args: Tuple[Type, ...] = ()
    display: Optional[str] = None
    @property
    def is_generic_instance(self) -> bool:
        return self.family is not None
    @property
    def has_payloads(self) -> bool:
        return any(self.payloads.values())
    def payload_of(self, member: str) -> Tuple[Type, ...]:
        return self.payloads.get(member, ())
    def __eq__(self, other):
        return isinstance(other, EnumType) and self.name == other.name
    def __hash__(self): return hash(self.name)
    def __repr__(self): return self.display or self.name


@dataclass(frozen=True)
class FuncType(Type):
    params: Tuple[Type, ...]
    ret: Type
    def __repr__(self):
        inner = ", ".join(repr(p) for p in self.params)
        if self.ret is VOID:
            return f"func({inner})"
        return f"func({inner}) -> {self.ret}"


I8 = PrimType("i8")
U8 = PrimType("u8")
I16 = PrimType("i16")
U16 = PrimType("u16")
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
    "i8": I8, "u8": U8, "i16": I16, "u16": U16,
    "i32": I32, "u32": U32, "f32": F32, "f64": F64,
    "bool": BOOL, "void": VOID, "str": STR,
}

# Narrow integers: stored with their exact width, promoted to i32 when read.
NARROW_RANGES = {
    I8: (-128, 127), U8: (0, 255), I16: (-32768, 32767), U16: (0, 65535),
}


def is_narrow(t): return t in NARROW_RANGES
def is_int(t): return t is I32 or t is U32 or is_narrow(t)
def is_float(t): return t is F32 or t is F64
def is_numeric(t): return is_int(t) or is_float(t)


def eq_blocker(t, path=""):
    """Walk t looking for a value that '==' cannot compare. Returns a
    (path, type) pair naming the first blocker, or None when t has equality.
    Only Vec2 and Vec3 have equality among the builtin structs."""
    if isinstance(t, (PrimType, FuncType)):
        return None
    if isinstance(t, EnumType):
        # Payload enums compare their tag and the active payload. A payload
        # that cannot be compared makes the whole enum incomparable.
        for mname, payload in t.payloads.items():
            for i, ptype in enumerate(payload):
                sub = eq_blocker(
                    ptype, f"{path}.{mname}[{i}]" if path else f"{mname}[{i}]")
                if sub is not None:
                    return sub
        return None
    if isinstance(t, StructType):
        if t.builtin:
            return None if t.name in ("Vec2", "Vec3") else (path, t)
        for fname, ftype in t.fields.items():
            sub = eq_blocker(ftype, f"{path}.{fname}" if path else fname)
            if sub is not None:
                return sub
        return None
    if isinstance(t, ArrayType):
        return eq_blocker(t.inner, f"{path}[N]")
    return (path, t)