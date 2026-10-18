# Vanta — a game-oriented systems language (v0.2.2)

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
python main.py build examples/vector_math.vnt --release
python main.py --version
```

`run` compiles to a temporary executable and deletes it afterwards. `build`
writes to `build/<name>` (or `-o <path>`), and `--emit-cpp <path>` also writes
the generated C++. On C++ compilation failure the generated source is saved to
`build/vanta_failed.cpp` for inspection.

## Project layout

| Path | Contents |
|---|---|
| `main.py` | CLI entry point |
| `compiler/` | Python frontend: lexer, parser, type checker, C++ code generator, driver |
| `runtime/vanta_runtime.hpp` | C++17 runtime: math types, `Arena`, IO, `rand` |
| `examples/` | Sample programs, one per feature area |
| `tests/` | `unittest` suite (115 tests) |
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

Vanta is a prototype, not a finished language. Notable gaps: no imports or
multi-file programs, no dynamic strings or string concatenation, no 2D arrays,
no first-class functions, no bounds-checked indexing, and no borrow checker for
`ptr<T>` (only the `Arena` non-copyable rule is enforced).
