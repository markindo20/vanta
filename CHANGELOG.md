# Changelog

Notable changes to Vanta, newest first. Versions correspond to git tags.

## v0.15.0 — 2026-10-18

- `List<T>` can be edited in place: `xs.insert(i, v)` inserts at index `i`,
  shifting the rest right (`i` may be `len(xs)`, the same as `push`), and
  `xs.remove(i)` removes and returns the element at `i`, shifting the rest
  left. Out-of-range indexes stop the program with
  `vanta: insert index I out of bounds (size N) at line L` /
  `vanta: remove index I out of bounds (size N) at line L`.
- `xs.sort(cmp)` sorts a list in place with a comparator — a function value
  `func(T, T) -> i32` returning negative, zero, or positive for less-than,
  equal, greater-than. It is a stable, `O(n log n)` merge sort: elements the
  comparator calls equal keep their order.
- The comparator is fully checked: a missing, wrongly-typed, or wrong-arity
  comparator is a compile error naming the expected signature, e.g.
  `'sort' expects a comparator func(i32, i32) -> i32, got func(i32, i32) -> bool`.
- Codegen fix: function-pointer aliases may now mention structs by value —
  struct forward declarations are emitted before the aliases — so comparators
  over `List<Struct>` work.
- `examples/lists.vnt` now demonstrates insert, remove, and a comparator
  sort (stable ties included); 17 new tests (447 total).

## v0.14.0 — 2026-10-18

- Added the game kit: `examples/gamekit/` packages the SDL2 plumbing as four
  importable modules — `sdl.vnt` (`extern` declarations, `EV_*`/`KEY_*`
  constants, the `Screen` lifecycle), `input.vnt` (event accessors),
  `gfx.vnt` (clear, filled rect, outline, present), and `rng.vnt` (bounded
  integers and floats, random signs).
- `examples/pong.vnt`, the second playable game, is built on the kit: W/S
  or Up/Down against a tracking AI, wall bounces, contact-point steering,
  first to 5 wins. `match` picks the serve direction.
- Pong runs headless like the other SDL examples: a frame-limit argument
  plus `SDL_VIDEODRIVER=dummy`. The frozen headless run: the AI wins 5-0 in
  frame 576. `gamekit/rng.vnt` has no SDL dependency, so it gets its own
  test that runs on every machine with a C++ compiler.
- No compiler changes: the kit is plain Vanta, and the language needed
  nothing new — struct fields typed `ptr<void>` (the `Screen` handle), a
  failure value carried by C's own NULLs instead of a nil literal, and
  ordinary imports all already worked.
- 2 new tests (430 total).

## v0.13.0 — 2026-10-18

- Added `match`: branch on an enum value with `Enum.Member:` arms (several
  members per arm, commas between them) and an optional `else:` fallback.
  Arms run top to bottom; the first match wins. `examples/match.vnt` walks
  a little state machine:

  ```vanta
  match g.state:
      State.Menu:
          print_str("fresh start")
      State.Playing, State.Paused:
          print_str("in game")
      else:
          print_str("somewhere else")
  ```

- The checker proves coverage: when every member has an arm, no `else` is
  needed, and a missing member is a compile error that names the members
  it needs — add a member to an enum later and every match that must
  handle it says so. A member used by two arms, a member of a different
  enum, and a misspelled member are errors too.
- `match` arms have their own scope, and `break`/`continue` inside an arm
  still control the enclosing loop: `match` is not a loop, and codegen
  keeps it that way (an if/else chain rather than a C++ `switch`). The
  matched value is evaluated exactly once.
- `match` on numbers, strings, or structs is a compile error; it is a
  statement, not an expression. `match` joins the reserved keywords.
- 25 new tests (428 total).

## v0.12.0 — 2026-10-18

- SDL2 support, shown end to end. `examples/sdl_window.vnt` opens a window
  and clears it to a colour; `examples/sdl_game.vnt` is the first playable
  Vanta game — move the paddle with Left/Right (or A/D) to catch falling
  coins, Esc or the close button quits. Both are pure `extern`
  declarations, so no SDL headers are involved at compile time:

  ```powershell
  python main.py run examples/sdl_game.vnt --lib-dir C:/msys64/mingw64/lib --link SDL2
  ```

- Pointers widen to `ptr<void>` implicitly, matching C's conversion to
  `void*`: any `ptr<T>` is accepted where `ptr<void>` is expected, which
  is how opaque C handles (`SDL_Window`, `SDL_Renderer`, ...) are typed.
  The narrowing direction stays an error, and a `ptr<void>` cannot be
  indexed — it has no element type.
- New builtin `ptr_is_null(p) -> bool`: compares any pointer (including
  `ptr<void>`) against null so failed calls can be handled. Pointer
  bindings can be reassigned with `mut`, and user functions may take and
  return pointers.
- Fixed: functions returning pointers never compiled — the implicit
  default return was invalid C++ (`T*{}`); a fallthrough now yields
  `nullptr`. Same bug class as the v0.11.0 `str` fix.
- Both SDL examples take an optional frame-limit argument and run headless
  under `SDL_VIDEODRIVER=dummy`, so the test suite builds, links, and runs
  them for real; CI installs SDL2 on Linux, macOS, and Windows. 20 new
  tests (403 total).

## v0.11.0 — 2026-10-18

- Added enums: `enum Name:` declares a fixed set of named members, numbered
  from 0 in declaration order and written `Name.Member` (e.g.
  `State.Playing`). An enum is a first-class type — variables, struct
  fields, function parameters and returns, arrays, `List<T>`, function
  values, and imported modules all accept enum values unchanged.
- Values compare with `==` and `!=`. Ordering comparisons on enums, and
  compares between different enums or against numbers, are compile errors.
  `enum_to_i32(v)` returns a member's number for printing, arithmetic, or
  passing to an `extern` function (extern signatures cannot take enum types
  directly yet). Enum values cannot be constructed (`State(1)` is an error),
  and enum types have no fields — `s.Menu` suggests `State.Menu`.
- Fixed: functions returning `str` never compiled — the implicit default
  return that codegen appends was invalid C++ (`return const char*{};`).
  A function that falls through now yields the empty string.
- Fixed: a type declared after a function of the same name (`func P()` then
  `struct P:`) is now reported as a collision instead of silently shadowing
  the function.
- New example `examples/enums.vnt`: a tiny state machine switching on a
  `State` enum, plus `enum_to_i32` and iteration over an array of members;
  plus 42 tests (383 total).

## v0.10.0 — 2026-10-18

- Added `StrBuilder`, an arena-backed string builder: `arena.str_builder()`
  creates one growing buffer, `append_str` / `append_i32` / `append_u32` /
  `append_f32` / `append_f64` / `append_bool` append (formatted exactly like
  the matching `print_*`), `len(b)` reads the byte count, `clear()` resets it
  for reuse, and `to_str()` returns the current contents as a `str` — copied
  into a fresh arena block, so the result stays stable across later appends,
  growth, and `clear()`. Growth doubles from 32 bytes, and the fixed string
  pool is never touched.
- Like `List<T>`, a builder is a handle: copies alias the same buffer, appends
  work through a plain `let`, and helpers can take a `StrBuilder` parameter
  and append to the caller's builder. `arena.reset()` invalidates the builder
  and the strings taken from it.
- New example `examples/str_builder.vnt`: building a line once, reusing the
  buffer with `clear()`, and a helper that appends through its parameter;
  plus 28 tests (341 total).

## v0.9.0 — 2026-10-18

- Added dynamic lists: `List<T>`, a growable array backed by an `Arena`.
  `arena.list::<T>()` creates an empty list, `xs.push(v)` appends (growing by
  doubling from a capacity of 4), `xs.pop()` removes the last element, and
  `len(xs)` reads the size. Element access reuses the v0.7.0 checked
  `xs.at(i)` — reads and writes, with out-of-bounds errors naming the list
  size and source line — plus the unchecked `xs[i]` form.
- A list is a handle: copies alias the same storage, and passing one to a
  function lets the function append to the caller's list. Since a list is an
  indirection like `ptr<T>`, element writes and `push`/`pop` work through a
  plain `let`; `mut` only controls rebinding. `List<void>` and `List<Arena>`
  are compile errors, and `arena.reset()` invalidates the arena's lists.
- New example `examples/lists.vnt`: particles in a list, integrated through a
  function call, with checked reads and writes and a pop; plus 39 tests
  (313 total).

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
