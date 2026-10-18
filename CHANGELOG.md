# Changelog

Notable changes to Vanta, newest first. Versions correspond to git tags.

## v0.3.1 — 2026-10-18

- Added `file_exists(path)`, `file_write(path, data)`, and `file_read(path)`.
  `file_read` allocates from the string pool (valid until `str_pool_reset()`)
  and returns `""` on any failure; a file too large for the pool fails loudly
  with a specific message instead of truncating. `file_write` returns the byte
  count or `-1` on failure.
- Added `examples/file_io.vnt`: reads a file named on the command line and
  writes a copy to `<path>.copy`, reporting both byte counts.

## v0.3.0 — 2026-10-18

- Added `extern "lib" { ... }` declarations. Extern functions are declared
  without bodies, type-checked like any other function, and called under their
  original names; the generated C++ puts them in an `extern "C" {}` block
  outside `namespace vanta_user`, so the linker sees unmangled symbols.
- Added `--include-dir`, `--lib-dir`, and `--link` (all repeatable) to `build`
  and `run`: `-I`/`-L`/`-l` on GCC-style toolchains, `/I`/`/LIBPATH:`/`<lib>.lib`
  on MSVC.
- Added `examples/extern_demo.vnt` with its C side in
  `examples/extern_demo_lib.c`, plus an end-to-end integration test that
  compiles the C library, links it, and checks the output.
- Repository history: the tags v0.1.1 through v0.2.5 were re-cut so that each
  tagged commit reports its own version from `--version`; the stored version
  string had lagged the tags before v0.2.2's sync and again until v0.2.6.

## v0.2.6 — 2026-10-18

- Added `print_fmt(fmt, args...)` and `write_fmt(fmt, args...)`. Placeholders are
  `{}` and are resolved at compile time: the type checker counts them and checks
  each argument's type, and the code generator turns each one into the matching
  printf conversion. A literal/integer mismatched format is a compile error, not
  a runtime surprise.
- Format literals support `{{` and `}}` for literal braces, and `%` is escaped
  automatically so a stray percent cannot corrupt the output.
- Added a process-lifetime string pool with `str_concat`, `str_len`,
  `to_str_i32`, `to_str_f32`, `to_str_bool`, and `str_pool_reset`. Exhaustion
  fails loudly rather than corrupting memory.
- Added `str_to_i32` and `str_to_f32`, without which command-line arguments
  could not be used as numbers.
- Added `examples/report.vnt`.
- New `compiler/formats.py` holds the format parser shared by the checker and
  the code generator.

## v0.2.5 — 2026-10-18

- Added `arg_count()` and `arg_str(i)`; the generated `main` now receives
  `argc`/`argv` and hands them to the runtime
- `python main.py run prog.vnt a b` now passes `a b` through to the program

## v0.2.4 — 2026-10-18

- Added `examples/life.vnt` — Conway's Game of Life on a 40x20 torus, drawn as a
  character grid

## v0.2.3 — 2026-10-18

- Added `write_i32`, `write_u32`, `write_f32`, `write_f64`, `write_bool`, and
  `write_str` — like their `print_*` counterparts but with no trailing newline
- Registered `print_newline()`, which had been sitting unreachable in the runtime
- Added `abs_i32`, `abs_f32`, `min_i32`, `max_i32`, `min_f32`, `max_f32`,
  `floor_f32`, `ceil_f32`

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
