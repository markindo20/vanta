@'
# Changelog

## v0.1.1 — 2024-XX-XX
- Added compound assignment `+= -= *= /=`
- Added `break` / `continue` with loop-context checking
- Added `examples/loops.vnt`
- Added lexer/parser/type-checker/codegen tests for the above

## v0.1.0 — 2024-XX-XX
- Initial working compiler
- Types: i32, u32, f32, f64, bool, void, ptr<T>
- Structs, components, systems (system = func)
- Arena allocator (non-copyable)
- Vec2, Vec3, Matrix4, Quat
- Examples: vector_math.vnt, physics.vnt
'@ | Set-Content CHANGELOG.md -Encoding utf8NoBOM