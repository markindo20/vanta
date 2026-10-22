# Vanta - a game-oriented systems language (v0.41.0)

Vanta is a small statically-typed language that compiles to C++17. It is
designed for high-performance game code: predictable memory, explicit
mutability, built-in vector types, and a stack-scoped arena allocator.

## Install

Vanta is a Python package with a native compile step, so it needs:

- Python 3.10+ (tested on 3.10.11 and 3.14)
- A C++17 compiler: `clang++`, `g++`, or MSVC's `cl`
- Optional: GDB 10+ and a GCC/Clang toolchain for native debugging

Install the `vanta` command with pipx (recommended) or pip:

```powershell
pipx install vanta-lang
# or
python -m pip install vanta-lang
```

Check the install and the toolchain:

```powershell
vanta --version
vanta doctor
```

`vanta doctor` reports the Python version, the C++ compiler it found, the
installed runtime header, and whether SDL2 is available for games. Non-game
programs only need the C++ compiler; the game kit additionally needs SDL2,
SDL2_ttf, and SDL2_image.

For compiler development, install an editable checkout instead:

```powershell
python -m pip install -e .
```

## Quick start

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
vanta check hello.vnt          # type-check only (fast, no C++)
vanta hello.vnt                # shorthand for `vanta run hello.vnt`
vanta build hello.vnt --release
vanta build hello.vnt --debug  # source-mapped build for GDB
```

Press **F5** in VS Code with a `.vnt` file open to debug it, or launch the
editor-agnostic debug adapter with `vanta dap`.

Diagnostics print the offending source line and a caret under the reported
column. Source files may start with a UTF-8 BOM.

Arguments after the source are passed through, so `vanta report.vnt 3` reaches
the program. In a checkout, the same commands work on the examples:

```powershell
vanta examples/vector_math.vnt
vanta examples/strike.vnt
```

### Modules

A file can begin with `module name` and export declarations with `pub`.
`import "lib.vnt"` brings a module's public names into the importing file;
`import "lib.vnt" as lib` uses qualified names such as `lib.func(...)` and
`lib.Type(...)`. Files without a `module` declaration keep the original flat,
all-public import behaviour. See the
[module example](examples/modules_demo/main.vnt) and the
[language reference](docs/LANGUAGE_REFERENCE.md#modules-and-imports-v040-modules-v0300).

### Option and Result

v0.31.0 adds generic enum declarations and a small standard library.
`import "std/option.vnt"` provides `Option<T>` (`None`/`Some(T)`) for values
that may be absent, and `import "std/result.vnt"` provides `Result<T, E>`
(`Ok(T)`/`Err(E)`) for success-or-error APIs. Both are ordinary enums, so
`match` destructures them exhaustively; constructors infer their type
arguments from the expected type or payload, with
`Option.None::<i32>()` and `Result.Err::<i32, str>("missing")` as the explicit
forms. See [examples/option_result.vnt](examples/option_result.vnt) and the
[reference](docs/LANGUAGE_REFERENCE.md#generic-enums-and-the-standard-library-v0310).

Start a new game with a playable paddle-and-ball starter:

```powershell
vanta new game.vnt
vanta game.vnt
```

The starter imports the game kit from the installed compiler, so `vanta new`
works the same from a checkout or a wheel install. Build a shareable Windows
bundle — the executable, its runtime DLLs, the example assets, and the kit font
go into one folder:

```powershell
vanta build examples/strike.vnt --release --bundle
.\build\strike\strike.exe
```

`run` compiles to a temporary executable and deletes it afterwards. `build`
writes to `build/<name>` (or `-o <path>`), and `--emit-cpp <path>` also writes
the generated C++. On C++ compilation failure the generated source is saved to
`build/vanta_failed.cpp` for inspection.

### Editor support

v0.41.0 ships a language server and a native debugger:

```powershell
vanta lsp
vanta dap
```

`vanta lsp` speaks LSP over stdin/stdout and provides diagnostics, completion,
hover, go-to-definition, and document symbols. `vanta dap` speaks the Debug
Adapter Protocol and drives GDB/MI2: line, function, conditional,
hit-count, log-point, data, and exception breakpoints, stack traces, locals and
arguments with structs that expand into their fields, watch expressions,
editing mutable locals, registers, disassembly and memory, run-to-cursor,
continue/step/pause, `stopOnEntry`, program output, attaching to a running
program, debugging a program on another machine, restart, and clean
termination. A debug build uses `#line` markers so GDB reports Vanta
files and lines directly. The VS Code client in
[`editors/vscode/`](editors/vscode/) adds both features on top of the existing
syntax highlighting; install the VSIX from the latest GitHub release or build
it from source. The server reads unsaved buffers, so diagnostics also work
before a file is saved.

The client finds `vanta` on `PATH`, in a workspace virtualenv, or through a
Python environment that can import the compiler. Set `vanta.server.path` to
override discovery and `vanta.debug.gdbPath` to choose GDB. See
[`docs/EDITOR.md`](docs/EDITOR.md) for setup and
[`docs/DEBUGGER.md`](docs/DEBUGGER.md) for debugging, settings, and
troubleshooting.

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
become `/I`, `/LIBPATH:`, and `<lib>.lib`. The SDL libraries the game kit uses
are detected from their extern block names — `extern "SDL2"`,
`"SDL2_ttf"`, and `"SDL2_image"` — and linked automatically. A self-contained
example ships with its C side in `examples/extern_demo_lib.c`:

```powershell
gcc -c examples/extern_demo_lib.c -o build/extern_demo_lib.o
ar rcs build/libdemo.a build/extern_demo_lib.o
python main.py run examples/extern_demo.vnt --lib-dir build --link demo
```

See `docs/LANGUAGE_REFERENCE.md` for the declaration rules.

SDL2 is the worked example of all this. `examples/sdl_window.vnt` opens a
window, `examples/sdl_text.vnt` draws text with SDL_ttf,
`examples/sdl_texture.vnt` loads image files as textures with SDL2_image,
`examples/sdl_audio.vnt` and `examples/sdl_audio_cb.vnt` make sound (a queued
tone, and a Vanta callback on SDL's audio thread), `examples/sdl_sound.vnt`
loads a WAV file, `examples/sdl_gamepad.vnt` polls a game controller, and
`examples/sdl_game.vnt` is the first playable Vanta game — catch the falling
coins with Left/Right (or A/D), Esc or the close button quits. The game kit
(`examples/gamekit/`) packages the SDL2 plumbing as ten importable modules,
and `examples/pong.vnt`, `examples/breakout.vnt`, and `examples/strike.vnt`
are the second, third, and fourth playable games built on it:
pong is W/S or Up/Down against a tracking AI, first to 5 wins, with the score
drawn as text and a beep on every hit and point; breakout is three walls of
tinted sprites, a spinning animated ball, a tracking paddle, WAV hits, a
persisted best score, and P/Space pause; with no key held the paddle plays its
own demo; strike is a one-screen wave shooter with an animated ship, three
waves of tinted saucers, WAV shots and hits, a gamepad fallback, and a
deterministic autopilot clear;
`examples/text_bench.vnt` is the kit's measured before/after for text
sprites.

```powershell
vanta examples/sdl_game.vnt
vanta examples/sdl_text.vnt
vanta examples/sdl_texture.vnt
vanta examples/sdl_audio.vnt
vanta examples/sdl_gamepad.vnt
vanta examples/pong.vnt
vanta examples/breakout.vnt
vanta examples/strike.vnt
```

All of them are pure `extern` declarations, so no SDL headers are needed to
compile. The windowed examples take an optional frame-limit argument for
headless smoke runs (`SDL_VIDEODRIVER=dummy`), and the audio examples run
under `SDL_AUDIODRIVER=dummy`, which plays to nowhere in real time. The kit
ships its own font (`examples/gamekit/fonts/tom-thumb.ttf`, a tiny 3x5 pixel
face), and the example images and WAVs in `examples/assets/` are generated
by a committed script (`gen_assets.py`) — nothing is vendored.

## Project layout

| Path | Contents |
|---|---|
| `main.py` | CLI entry point for a checkout |
| `pyproject.toml` | Package metadata; installing creates the `vanta` command |
| `setup.py` | Build hook that puts the runtime, game kit, assets, and standard library in the wheel |
| `compiler/` | Python frontend, language server, and debug adapter: lexer, parser, import loader and module resolver, type checker, C++ code generator, driver, `lsp.py`, `dap.py` |
| `runtime/vanta_runtime.hpp` | C++17 runtime: math types, `Arena`, IO, `rand` (shipped in the wheel) |
| `stdlib/` | Shipped Vanta library modules: `option.vnt` and `result.vnt` |
| `examples/` | Sample programs, one per feature area |
| `tests/` | `unittest` suite (762 tests) |
| `editors/vscode/` | VS Code language client, debugger contribution, syntax grammar, and VSIX build |
| `docs/` | Language reference, editor guide, debugger guide, and architecture notes |

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
| `modules_demo/main.vnt` | Declared modules: qualified and unqualified imports, `pub`, private helpers, module constants/enums |
| `grid.vnt` | 2D arrays: stack, struct-held, and `arena.alloc::<[T, W]>` grids |
| `dispatch.vnt` | First-class functions: function values, dispatch tables, callbacks |
| `bounds.vnt` | Bounds-checked access: `xs.at(i)` reads and writes |
| `ptr_at.vnt` | Checked pointer access: `p.at(i, size)` reads and writes through raw pointers |
| `lists.vnt` | Dynamic lists: `arena.list::<T>()`, `push`/`pop`/`insert`/`remove`, comparator sort |
| `callbacks.vnt` | C callbacks: Vanta functions called from C, with pointer user data (C side: `callbacks_lib.c`) |
| `narrow_ints.vnt` | Exact-width integers `i8`/`u8`/`i16`/`u16`: C ABI parameters and struct layout verified byte for byte (C side: `narrow_ints_lib.c`) |
| `foreach.vnt` | `for x in xs` over lists and arrays, with `break`/`continue` |
| `struct_eq.vnt` | `==`/`!=` on structs: `str` by content, arrays element-wise, nested structs |
| `ptr_cast.vnt` | `ptr_cast::<T>(p)` reinterpretation, including a `ptr<void>` round trip |
| `ptr_offset.vnt` | `ptr_offset(p, n)`: element-wise pointer arithmetic, cursor walking over arrays |
| `enums_extern.vnt` | Enum types in `extern` signatures, through `match` and back (C side: `enums_extern_lib.c`) |
| `str_builder.vnt` | String building: append into an arena-backed `StrBuilder` |
| `enums.vnt` | Named states: `enum State:`, members, `==`, `enum_to_i32` |
| `enums_advanced.vnt` | Explicit member values and payload enums, destructured by `match` |
| `option_result.vnt` | Generic enums and the standard library: `Option<T>`, `Result<T, E>`, constructor inference, explicit type arguments |
| `match.vnt` | Branching on enums: exhaustive `match`, multi-pattern arms, `else` |
| `sdl_window.vnt` | An SDL2 window: init, renderer, event loop, headless frame limit |
| `sdl_text.vnt` | Text with SDL_ttf: `SDL_Color` by value, `TTF_SizeUTF8`, render to texture |
| `sdl_texture.vnt` | Textures with SDL2_image: `IMG_LoadTexture`, tint, sheet regions, flip and rotate, pixel readback |
| `sdl_audio.vnt` | SDL2 audio, queue mode: a hand-built `SDL_AudioSpec`, `ptr_null::<T>()`, `SDL_QueueAudio` |
| `sdl_audio_cb.vnt` | SDL2 audio, callback mode: a Vanta function in `SDL_AudioSpec.callback`, state through `userdata` |
| `sdl_sound.vnt` | SDL2 audio, files: `SDL_LoadWAV_RW` over `SDL_RWFromFile`, queued and drained |
| `sdl_gamepad.vnt` | SDL2 controllers: `SDL_GameControllerOpen`, button/axis polling, the dead-handle path |
| `text_bench.vnt` | The measured before/after for `text_sprite`: one string drawn both ways; counts stable, milliseconds the machine's |
| `sdl_game.vnt` | The first playable game: paddle, falling coins, input, `ptr_is_null` |
| `gamekit/` | Ten reusable game modules: SDL2 window lifecycle, event access, controllers, rectangles, textures (SDL2_image), sprite animation, text (SDL_ttf), audio (tones and WAV files), random numbers, and pure collision tests |
| `pong.vnt` | The second playable game: paddles, tracking AI, text score, and beeps — built on the game kit |
| `breakout.vnt` | The third playable game: three tinted sprite walls, animated ball, auto-playing paddle, pause, persisted best score, WAV hits — built on the game kit |
| `strike.vnt` | The fourth playable game: animated ship, three waves of tinted saucers, text HUD, WAV hits, gamepad fallback, collision tests — built on the game kit |

## Tests

```powershell
python -m unittest discover -s tests
```

Integration tests compile and run real binaries, so they need a C++17 compiler
on `PATH`; they skip automatically if none is found. To force a specific
compiler, set the `CXX` environment variable. The GDB debugger integration test
also skips when no working GDB is available.

## Documentation

- [`docs/TUTORIAL.md`](docs/TUTORIAL.md) — hands-on introduction, ends with a small project
- [`docs/LANGUAGE_REFERENCE.md`](docs/LANGUAGE_REFERENCE.md) — syntax and semantics
- [`docs/EDITOR.md`](docs/EDITOR.md) — language server, debugger, and VS Code setup
- [`docs/DEBUGGER.md`](docs/DEBUGGER.md) — debugger guide, DAP setup, and troubleshooting
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — how the compiler is put together
- [`ROADMAP.md`](ROADMAP.md) — candidate next milestones and known gaps
- [`CHANGELOG.md`](CHANGELOG.md) — release history

New to Vanta? Start with the [tutorial](docs/TUTORIAL.md).

## Status

Vanta is a prototype, not a finished language. Programs can span multiple
files with optional module scopes, qualified imports, and `pub` visibility,
link against C libraries (callbacks and enum types included), read
command-line arguments, produce formatted output, read and write files, build
2D grids, pass functions around,
bounds-check array access with `xs.at(i)` and pointer access with
`p.at(i, size)`, grow, edit, and sort arena-backed
lists (`List<T>`) and walk lists and arrays with `for x in xs`, store
exact-width integers (`i8`/`u8`/`i16`/`u16`) whose memory layout matches C,
compare structs field by field with `==`, reinterpret pointers with
`ptr_cast::<T>(p)`, step them by elements with `ptr_offset(p, n)`, build
explicit nulls with `ptr_null::<T>()`,
build strings incrementally with `StrBuilder`, own runtime strings with
automatic reference counting, name states and modes with enums (including
explicit values, payloads, and generic instances), use the shipped
`Option`/`Result` library, branch on enum values exhaustively with `match`,
and build and run real SDL2 games
on the game kit, text rendering, sprite images, sprite-sheet animation, and
WAV sound files included
(nine SDL examples, four of them playable games) — but the remaining gaps
are real:

- strings are immutable and reference-counted, so runtime-built values are
  freed automatically and copies share storage; there is still no string
  indexing or slicing, and string refcounts are not atomic (Vanta is
  single-threaded)
- function values are plain pointers: no closures; they compare by address
  with `==`/`!=` (ordering is rejected), `ptr_is_null` tests them, and C
  callbacks work in both directions — `extern` parameters and return types
- array indexing is unchecked unless you opt in with `xs.at(i)`; pointer
  indexing is unchecked unless you pass the accessible element count with
  `p.at(i, size)` (the count is a runtime promise, and null is still
  `ptr_is_null`'s job), and there is no borrow checker for `ptr<T>` (only the
  `Arena` non-copyable rule is enforced)
- `List<T>` is arena-backed: elements must be copyable, growth and sorting
  allocate from the arena, and `sort` needs a comparator function value (there
  is no default ordering); `arena.reset()` invalidates the lists made from that
  arena
- enums name members with optional explicit `i32` values and payloads;
  enum declarations may take type parameters, and each concrete instance is
  monomorphized (`Option<i32>` and `Option<str>` are distinct types).
  `Option<T>` and `Result<T, E>` ship in `stdlib/` as ordinary generic enums,
  not compiler-special-cased types. `==`/`!=` compare the tag and active
  payload, and `match` destructures payloads with bindings. Payload enums
  have no C representation and cannot appear in `extern` signatures; plain
  enums still map to fixed-`int32_t` C++ enums
- windowing, images, and sound are shipped as SDL2 examples plus the game
  kit: the kit wraps controllers, sprite-sheet animation, textures, text,
  audio, and rectangle/circle collision; events are still read by hand (an
  `SDL_Event` is viewed as raw `i32`s), and `text_draw` uploads a texture
  per call — fine for HUDs, wasteful for walls of text
- pointers have no null safety beyond `ptr_is_null` / `ptr_null::<T>()`;
  `ptr<void>` widening
  is the only implicit pointer conversion, and `ptr_cast::<T>(p)` /
  `ptr_offset(p, n)` are the unchecked explicit escape hatches
- modules are one file each: imports are paths, with no nested modules,
  package manager, or general search path (only `std/` falls back to the
  shipped standard library); `pub` controls top-level declarations, not
  individual struct fields, and a public declaration cannot expose a private
  type, including through an inferred function or constant type

Editor support covers diagnostics, completion, hover, definition, and
document symbols through `vanta lsp` and the VS Code client. `vanta dap` adds
native debugging: line, function, conditional, hit-count, log-point, data, and
exception breakpoints, stack traces, locals and arguments with structs that
expand into their fields, watch expressions, editing mutable locals, registers,
disassembly and memory, run-to-cursor, continue/step/pause, `stopOnEntry`,
program output, attaching to a running program, debugging a program on another
machine, restart, and clean termination. Debug builds are unoptimized and
source-mapped back to Vanta lines; they need GDB plus a GCC or Clang
toolchain. Reverse debugging, LLDB, and MSVC/PDB are still future work.

These are tracked, prioritised, and sized in [ROADMAP.md](ROADMAP.md).
