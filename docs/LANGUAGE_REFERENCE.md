# Vanta Language Reference (v0.1)

See the grammar and type rules in the main README. This file supplements with worked examples.

## Values and Mutability

## Constants (v0.1.2)


Constants are compile-time values (C++ `constexpr`). Their initializer must be
a literal, a previous constant, or arithmetic on those. They cannot be assigned
to. `const X = 5` infers `i32`; `const Y = 9.8` infers `f32`.

## Assertions (v0.1.2)


`assert(cond)` requires a `bool`. If `cond` is false at runtime, prints
`vanta: assertion failed at line N` to stderr and exits with code 1.

## Return type inference (v0.1.2)


When `-> T` is omitted, the return type is inferred from the body's `return`
statements. All returns must agree on a type. If a function with inferred
return type is called before its declaration, the compiler errors — reorder
or add `-> T` explicitly.

## Stepped ranges (v0.1.2)


The third argument is the step (must be nonzero). Negative steps count down.

## Vector equality (v0.1.2)

`Vec2 == Vec2`, `Vec3 == Vec3`, and `!=` work element-wise.

## Matrix4 × Vec3 (v0.1.2)

`Matrix4 * Vec3` returns a `Vec3` using homogeneous coordinates (`w = 1`).
Matrix4 is row-major; `Matrix4()` produces the identity.
