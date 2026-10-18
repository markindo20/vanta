# Changelog

Notable changes to Vanta, newest first. Versions correspond to git tags.

## v0.8.0 — 2026-10-18

- Added trigonometry: `sin`, `cos`, and `tan` for `f32` and `f64`, plus
  `atan2_f32`/`atan2_f64` — the angle of the vector `(x, y)`, the usual
  "heading toward a point" operation. Angles are radians, and the f32/f64
  pairs follow the existing `sqrt_f32`/`sqrt_f64` naming. They are callable
  like any builtin and usable as function values.
- Extended `examples/arrays_and_math.vnt` with a 45-degree unit vector and
  its heading recovered through `atan2`, plus 7 tests (274 total).

## v0.7.0 — 2026-10-18

- Added bounds-checked array access: `xs.at(i)` checks the index against the
  fixed size of `xs` before touching memory. Reads return the element, and
  writes (`xs.at(i) = v`, including compound forms) obey the normal mutability
  rules. An out-of-range or negative index prints
  `vanta: index I out of bounds (size N) at line L` to stderr and exits 1.
  Plain `xs[i]` stays unchecked.
- `at` composes with nested arrays — `g.at(y).at(x)` reads and
  `g.at(y).at(x) = v` writes — and rejects `ptr<T>` receivers with "a pointer
  has no length", since pointers have no size to check against.
- Codegen emits `vanta::at_checked` for reads and `vanta::at_checked_ref` (a
  real reference, so writes land in the array) for writes, carrying the
  access's source line into the failure message.
- Added `examples/bounds.vnt`, plus 29 tests (267 total).

## v0.6.0 — 2026-10-18

- Functions are first-class values. A `func(P1, P2) -> R` type names any
  function with that signature (omit the arrow for `void`), and values can be
  stored in variables, passed as arguments, returned, kept in struct fields and
  arrays, or allocated from an arena. The same call syntax invokes them:
  `f(x)`, `handlers[0](x)`, `op.run(x)`, `pick()(x)`.
- Values are plain function pointers — there are no closures, so nothing is
  captured. Vanta functions (emitted with their `fn_` prefix), `extern`
  functions, and builtins like `print_str` all work as values.
- Rejected on purpose: `len`/`print_fmt`/`write_fmt`/`assert` and type names as
  values, `==`/`!=` on function values, function values in `const`
  initializers, and function types in `extern` signatures (C callbacks come
  later).
- Local bindings now shadow functions of the same name in call position, so
  the canonical `func apply(f: func(i32) -> i32, ...)` works even when a
  function named `f` exists.
- Codegen emits one `using FnPtrN = R(*)(...)` alias per distinct function
  type, innermost first; type names matching `FnPtr<digits>` are reserved.
- Added `examples/dispatch.vnt`, plus 51 tests (238 total).

## v0.5.0 — 2026-10-18

- 2D arrays work end to end. Nested array types and literals (`[[i32, 8], 4]`)
  already parsed, but writes through pointers and struct fields were rejected;
  assignment targets are now validated by walking the whole storage chain, so
  arena-backed grids (`arena.alloc::<[i32, 8]>(h)`) and `mut` struct grids are
  writable at any depth while `let` bindings and parameters stay immutable.
- Array literals and call argument lists may span lines: the lexer ignores
  newlines inside `[...]` and `(...)`.
- Added `examples/grid.vnt`: a stack checkerboard, a struct-held heightmap,
  and an arena-backed dynamic grid, plus 11 tests (187 total).

## v0.4.0 — 2026-10-18

- Added `import "path.vnt"`. An import merges another file's declarations
  into the program: paths resolve relative to the importing file, imports are
  transitive, and each file is loaded once, so diamonds are fine. Import
  cycles and missing files are compile errors. Declarations merge into the
  existing flat namespace — imported functions, structs, constants, and
  externs are used by their bare names. `import` is now a reserved word.
- Errors inside imported files now name the file that contains them: every
  AST position carries its source file, and `CheckError` prefers it.
- Added `examples/imports_demo.vnt` with its module
  `examples/imports_demo_lib.vnt`, plus 12 tests (176 total).
- New `compiler/loader.py` owns import expansion; `_frontend_only` now goes
  through it.

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
