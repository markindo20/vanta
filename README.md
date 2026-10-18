# Vanta - a game-oriented systems language (v0.12.0)

Vanta is a small statically-typed language that compiles to C++17. It is
designed for high-performance game code: predictable memory, explicit
mutability, built-in vector types, and a stack-scoped arena allocator.

## Quick start

Prerequisites:

- Python 3.10+ (tested on 3.10.11 and 3.14)
- A C++17 compiler: `clang++`, `g++`, or MSVC's `cl`

Write a program:

```vanta
func main() -> void:
    let arena = Arena(4096)
    let xs = arena.alloc::<i32>(4)
    for i in range(0, 4):
        xs[i] = i * i
    print_i32(xs[3])
```

Run it:

```powershell
python main.py check examples/vector_math.vnt   # type-check only (fast, no C++)
python main.py run   examples/vector_math.vnt   # compile and run
python main.py run   examples/report.vnt 3      # args after the source are passed through
python main.py build examples/vector_math.vnt --release
python main.py --version
```

`run` compiles to a temporary executable and deletes it afterwards. `build`
writes to `build/<name>` (or `-o <path>`), and `--emit-cpp <path>` also writes
the generated C++. On C++ compilation failure the generated source is saved to
`build/vanta_failed.cpp` for inspection.

## Linking C libraries

`extern` blocks declare functions implemented in C; the driver links the
library in:

```vanta
extern "SDL2" {
    func SDL_Init(flags: u32) -> i32
}
```

`--include-dir`, `--lib-dir`, and `--link` are repeatable flags on `build` and
`run`. On GCC-style toolchains they become `-I`, `-L`, and `-l`; on MSVC they
become `/I`, `/LIBPATH:`, and `<lib>.lib`. A self-contained example ships with
its C side in `examples/extern_demo_lib.c`:

```powershell
gcc -c examples/extern_demo_lib.c -o build/extern_demo_lib.o
ar rcs build/libdemo.a build/extern_demo_lib.o
python main.py run examples/extern_demo.vnt --lib-dir build --link demo
```

See `docs/LANGUAGE_REFERENCE.md` for the declaration rules.

SDL2 is the worked example of all this. `examples/sdl_window.vnt` opens a
window; `examples/sdl_game.vnt` is the first playable Vanta game — catch the
falling coins with Left/Right (or A/D), Esc or the close button quits:

```powershell
python main.py run examples/sdl_game.vnt --lib-dir C:/msys64/mingw64/lib --link SDL2
```

Both are pure `extern` declarations, so no SDL headers are needed to compile
them, and both take an optional frame-limit argument for headless smoke runs
(`SDL_VIDEODRIVER=dummy`).

## Project layout

| Path | Contents |
|---|---|
| `main.py` | CLI entry point |
| `compiler/` | Python frontend: lexer, parser, import loader, type checker, C++ code generator, driver |
| `runtime/vanta_runtime.hpp` | C++17 runtime: math types, `Arena`, IO, `rand` |
| `examples/` | Sample programs, one per feature area |
| `tests/` | `unittest` suite (403 tests) |
| `docs/` | Language reference and architecture notes |

## Examples

| File | Demonstrates |
|---|---|
| `vector_math.vnt` | `Vec3` arithmetic, `.dot()` |
| `physics.vnt` | `component` / `system`, arena arrays, compound assignment |
| `loops.vnt` | `break`, `continue`, compound assignment |
| `tier1_demo.vnt` | `const`, assertions, return inference, stepped ranges, vector equality |
| `arrays_and_math.vnt` | Fixed-size arrays, `len`, `Quat`, `Matrix4` products |
| `strings.vnt` | The `str` type, escapes, `print_str`, string equality |
| `boids.vnt` | A flocking simulation: `ptr<Vec2>`, nested loops, `elif` chains |
| `life.vnt` | Conway's Game of Life drawn as a character grid (`write_str`, `print_newline`) |
| `report.vnt` | Formatted output and string building, with a command-line argument |
| `extern_demo.vnt` | `extern` declarations linking a C library (C side: `extern_demo_lib.c`) |
| `file_io.vnt` | `file_exists` / `file_read` / `file_write`, with a path from the command line |
| `imports_demo.vnt` | A multi-file program: `import "imports_demo_lib.vnt"` |
| `grid.vnt` | 2D arrays: stack, struct-held, and `arena.alloc::<[T, W]>` grids |
| `dispatch.vnt` | First-class functions: function values, dispatch tables, callbacks |
| `bounds.vnt` | Bounds-checked access: `xs.at(i)` reads and writes |
| `lists.vnt` | Dynamic lists: `arena.list::<T>()`, `push`/`pop`, checked access |
| `str_builder.vnt` | String building: append into an arena-backed `StrBuilder` |
| `enums.vnt` | Named states: `enum State:`, members, `==`, `enum_to_i32` |
| `sdl_window.vnt` | An SDL2 window: init, renderer, event loop, headless frame limit |
| `sdl_game.vnt` | The first playable game: paddle, falling coins, input, `ptr_is_null` |

## Tests

```powershell
python -m unittest discover -s tests
```

Integration tests compile and run real binaries, so they need a C++17 compiler
on `PATH`; they skip automatically if none is found. To force a specific
compiler, set the `CXX` environment variable.

## Documentation

- [`docs/TUTORIAL.md`](docs/TUTORIAL.md) — hands-on introduction, ends with a small project
- [`docs/LANGUAGE_REFERENCE.md`](docs/LANGUAGE_REFERENCE.md) — syntax and semantics
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — how the compiler is put together
- [`CHANGELOG.md`](CHANGELOG.md) — release history

New to Vanta? Start with the [tutorial](docs/TUTORIAL.md).

## Status

Vanta is a prototype, not a finished language. Programs can span multiple
files, link against C libraries, read command-line arguments, produce formatted
output, read and write files, build 2D grids, pass functions around,
bounds-check array access with `xs.at(i)`, grow arena-backed lists
(`List<T>`), assemble strings with `StrBuilder`, name states and modes
with enums, and open real windows with SDL2 (two examples, one of them a
playable game) — but the remaining gaps are real:

- strings come from a fixed 64 KiB pool that is never freed; there is no
  per-value ownership, and `str_pool_reset()` invalidates everything built from
  it (`StrBuilder` builds without the pool, but a `str` is still a bare pointer)
- function values are plain pointers: no closures, no function-value equality,
  and C callbacks (function types in `extern`) are not supported yet
- array indexing is unchecked unless you opt in with `xs.at(i)`; pointers have
  no checked access, and there is no borrow checker for `ptr<T>` (only the
  `Arena` non-copyable rule is enforced)
- `List<T>` is arena-backed: there is no `insert`/`remove`/`sort`, and
  `arena.reset()` invalidates the lists made from that arena
- enums are plain named constants: no explicit member values, no associated
  data, and no `match`/`switch` — compare with `==`/`!=` and branch with
  `if`/`elif`
- windowing is shipped as SDL2 examples only: there is no audio/gamepad
  wrapper, no text rendering, and events are read by hand (an `SDL_Event`
  is viewed as raw `i32`s); nothing else ships in the box
- pointers have no null safety beyond `ptr_is_null`; `ptr<void>` widening
  is the only implicit pointer conversion
