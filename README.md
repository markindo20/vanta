# Vanta — a game-oriented systems language (v0.5.0)

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

## Project layout

| Path | Contents |
|---|---|
| `main.py` | CLI entry point |
| `compiler/` | Python frontend: lexer, parser, import loader, type checker, C++ code generator, driver |
| `runtime/vanta_runtime.hpp` | C++17 runtime: math types, `Arena`, IO, `rand` |
| `examples/` | Sample programs, one per feature area |
| `tests/` | `unittest` suite (187 tests) |
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

## Tests

```powershell
python -m unittest discover -s tests
```

Integration tests compile and run real binaries, so they need a C++17 compiler
on `PATH`; they skip automatically if none is found. To force a specific
compiler, set the `CXX` environment variable.

## Documentation

- [`docs/LANGUAGE_REFERENCE.md`](docs/LANGUAGE_REFERENCE.md) — syntax and semantics
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — how the compiler is put together
- [`CHANGELOG.md`](CHANGELOG.md) — release history

## Status

Vanta is a prototype, not a finished language. Programs can span multiple
files, link against C libraries, read command-line arguments, produce formatted
output, read and write files, and build 2D grids, but the remaining gaps are
real:

- strings come from a fixed 64 KiB pool that is never freed; there is no
  per-value ownership, and `str_pool_reset()` invalidates everything built from it
- no first-class functions, so no callbacks or ECS dispatch
- no bounds-checked indexing, and no borrow checker for `ptr<T>` (only the
  `Arena` non-copyable rule is enforced)
- windowing and audio are now reachable through `extern` (SDL2 and friends),
  but nothing ships in the box
