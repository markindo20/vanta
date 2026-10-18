# Changelog

Notable changes to Vanta, newest first. Versions correspond to git tags.

## v0.2.2 — 2026-10-18

- Added `rand_f32()` — xorshift32, returns `f32` in `[0, 1)`
- Added `rand_seed(seed: i32)` to select a random stream
- Random state is fixed at startup, so programs are reproducible until seeded
- Added 7 tests (type checker, codegen, and an end-to-end determinism test)
- Fixed: `compiler.VERSION` still reported `0.1.0` and the generated C++ header
  hardcoded `0.2.0`. Both now report `0.2.2`, and the header reads the shared
  `VERSION` constant instead of a literal, so it cannot drift again.

## v0.2.1 — 2026-10-17

- Added `examples/boids.vnt` — 30 boids on a 100x100 torus, deterministic init
- Added an end-to-end integration test asserting the four quadrant counts sum
  to 30, so the simulation cannot silently stop placing every boid

## v0.2.0 — 2026-10-17

- Added the `str` type, with escape sequences `\t`, `\n`, `\"`, `\\`
- Added `print_str`
- `==` and `!=` on `str` compare contents via `strcmp`, not pointers
- Added `Vec2.normalized` and `Quat.dot`
- Added `translation`, `scale`, and `from_quat` builtins returning `Matrix4`

## v0.1.3 — 2026-10-17

- Added fixed-size arrays: `[T, N]` types, array literals, indexing, and `len(xs)`
- Added Quat math: `Quat * Quat`, `Quat * Vec3`
- Added Matrix4 extras: `Matrix4 * Matrix4`, `Matrix4 * Vec3`
- Documented `examples/arrays_and_math.vnt`

## v0.1.2 — 2026-10-17

- Added `const` declarations (compile-time values, emitted as C++ `constexpr`)
- Added `assert(cond)`
- Added return-type inference when `-> T` is omitted
- Added 3-argument `range(start, end, step)`
- Added element-wise `Vec2` / `Vec3` equality and inequality
- Fixed mixed-literal return-type inference

## v0.1.1 — 2026-10-17

- Added compound assignment `+=`, `-=`, `*=`, `/=`
- Added `break` and `continue`, with loop-context checking
- Added `examples/loops.vnt`

## v0.1.0 — 2026-10-17

- Initial working compiler:
  source → lex → parse → type-check → C++17 → native binary
- Types: `i32`, `u32`, `f32`, `f64`, `bool`, `void`, `ptr<T>`
- Structs, `component`, and `system` declarations
- Non-copyable stack-scoped `Arena` allocator
- Built-in `Vec2`, `Vec3`, `Matrix4`, `Quat`
- Examples: `examples/vector_math.vnt`, `examples/physics.vnt`
