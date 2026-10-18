# Vanta in 30 minutes

A hands-on introduction that builds from `print_str` to a small project — an
ASCII terrain generator — and then leaves the terminal behind: the last
section opens a real window with SDL2. Every code block below is a complete
program that was run to produce the output shown — copy it into a file with a
`.vnt` extension and run it.

**Prerequisites:** Python 3.10+ and a C++17 compiler (`g++`, `clang++`, or
MSVC `cl`). See the Quick start in the [README](../README.md). The SDL2
section at the end additionally needs the SDL2 library, but everything
before it does not.

```powershell
python main.py run hello.vnt     # compile and run
python main.py check hello.vnt   # type-check only (fast, no C++)
python main.py build hello.vnt --release
```

`run` compiles to a temporary executable and deletes it afterwards; `build`
keeps the binary in `build/`.

## Hello

```vanta
func main() -> void:
    print_str("hello, vanta")
```

```
hello, vanta
```

Every program starts at `func main() -> void:`. Statements live in indented
blocks; functions, structs, and constants sit at the top level.

## Values and mutability

`let` binds once, `mut` can be reassigned. There is no implicit numeric
conversion between types.

```vanta
func main() -> void:
    let width = 8          # i32
    mut score = 0
    score += width * 2
    print_i32(score)       # 16
```

```
16
```

## Functions

Return types are written with `->`; omit it for `void`. `-> T` can be omitted
too — the checker infers it from the body, as long as the function is declared
before its first caller — but explicit types are easier to read.

```vanta
func clamp(v: i32, lo: i32, hi: i32) -> i32:
    if v < lo:
        return lo
    if v > hi:
        return hi
    return v

func main() -> void:
    print_i32(clamp(12, 0, 10))    # 10
```

```
10
```

## Control flow

`if` / `elif` / `else`, `while`, and `for ... in range(start, end)` — the
exclusive end matches the zero-based indexing you will see next. Conditions
combine with `and`, `or`, `not`.

```vanta
func main() -> void:
    mut total = 0
    for i in range(1, 6):
        total += i
    print_i32(total)       # 15

    mut n = 3
    while n > 0:
        total += n
        n -= 1
    print_i32(total)       # 21
```

```
15
21
```

## Structs

Structs are plain data; construction uses named fields. A `mut` binding is
required to change a field.

```vanta
struct Enemy:
    hp: i32
    damage: i32

func main() -> void:
    mut slime = Enemy(hp: 10, damage: 2)
    slime.hp -= 3
    print_i32(slime.hp)    # 7

    let boss = Enemy(hp: 100, damage: 25)
    print_i32(boss.damage) # 25
```

```
7
25
```

## Enums

An `enum` names a fixed set of states. Members are numbered from zero and
written `Type.Member`; compare with `==`/`!=` and branch with `if`/`elif`
(or `match` — next section). `enum_to_i32` turns a member into its number
when you need to print it.

```vanta
enum State:
    Menu
    Playing
    Paused

func label(s: State) -> str:
    if s == State.Menu:
        return "menu"
    elif s == State.Playing:
        return "playing"
    return "paused"

func main() -> void:
    mut s = State.Menu
    print_str(label(s))           # menu
    s = State.Playing
    print_str(label(s))           # playing
    print_i32(enum_to_i32(s))     # 1
```

```
menu
playing
1
```

## Match

`match` replaces the `if`/`elif` ladder when branching on an enum. Arms
are written `Type.Member:` and run top to bottom; `else:` catches the
rest. When every member has an arm, no `else` is needed — the compiler
proves the match is exhaustive, and adding a member later points at every
match that needs a new arm.

```vanta
enum State:
    Menu
    Playing
    Paused

func label(s: State) -> str:
    match s:
        State.Menu:
            return "menu"
        State.Playing:
            return "playing"
        State.Paused:
            return "paused"

func main() -> void:
    mut s = State.Menu
    print_str(label(s))             # menu
    s = State.Playing
    print_str(label(s))             # playing
    print_str(label(State.Paused))  # paused
```

```
menu
playing
paused
```

Several patterns can share one arm — `State.Menu, State.Paused:` — and
`break`/`continue` inside an arm still control the enclosing loop, so a
match inside a `for` never swallows them.

## Arrays and checked access

Fixed-size arrays carry their length in the type: `[i32, 4]`. `len(xs)`
returns it. `xs[i]` is unchecked; `xs.at(i)` checks the index at run time
and stops the program with a clear message if it is out of bounds. When an
index comes from data or arithmetic, use `at`.

```vanta
func main() -> void:
    mut xs: [i32, 4] = [1, 2, 3, 4]
    xs.at(0) = 10          # checked write
    print_i32(xs.at(0))    # 10
    print_i32(len(xs))     # 4
    print_i32(xs[3])       # 4 (unchecked, fine here)
```

```
10
4
4
```

Arrays nest: `[[i32, 8], 4]` is "4 rows of 8 i32", indexed `g[y][x]`. Writes
follow the binding rules at any depth — a `mut` binding is writable, a `let`
one is not, and memory behind a `ptr<T>` is always writable.

## Strings and formatted output

`str` values come from literals or helpers like `str_concat` (which
allocates from a fixed, resettable pool). `print_fmt` formats a literal
template with `{}` placeholders.

```vanta
func main() -> void:
    let name = "player"
    print_fmt("hello, {} (hp {})", name, 7)
    let label = str_concat("hi, ", name)
    print_str(label)
```

```
hello, player (hp 7)
hi, player
```

The pool is fine for a value or two, but assembling a line piece by piece
with `str_concat` in a loop allocates an intermediate string every time. For
that, build into an arena-backed `StrBuilder` and take the result once:

```vanta
func main() -> void:
    let arena = Arena(4096)
    let b = arena.str_builder()
    b.append_str("hp ")
    b.append_i32(42)
    b.append_str(" / 100")
    print_str(b.to_str())     # hp 42 / 100
    print_i32(len(b))         # 11
    b.clear()                 # reuse the buffer
    b.append_str("ready")
    print_str(b.to_str())     # ready
```

```
hp 42 / 100
11
ready
```

`to_str()` copies the current contents into a fresh arena block, so the
string it returns stays valid and unchanged when you keep appending or call
`clear()`.

## Function values

Functions are values with type `func(P1, P2) -> R`. They can be stored in
variables, passed, returned, kept in structs, and called with the same
syntax.

```vanta
func double(x: i32) -> i32:
    return x * 2

func main() -> void:
    let f: func(i32) -> i32 = double
    print_i32(f(21))       # 42
```

```
42
```

## The Arena

`Arena` is a bump allocator for frame-scoped data. `alloc::<T>(n)` returns a
`ptr<T>` to `n` values; indexing a pointer uses `p[i]`. There is no borrow
checking; the one ownership rule is that an `Arena` cannot be copied, returned,
or passed to a function.

```vanta
func main() -> void:
    let arena = Arena(256)
    let xs = arena.alloc::<i32>(3)
    xs[0] = 5
    xs[1] = xs[0] * 2
    print_i32(xs[1])       # 10
```

```
10
```

## Growable lists

Arrays are fixed-size; when the size is not known up front (entities, events,
anything you append to), use a `List<T>`. It allocates from the `Arena`, so
per-frame data comes back to life with `arena.reset()`. Create it with
`arena.list::<T>()` and grow it with `push`:

```vanta
func fill(xs: List<i32>):
    for i in range(0, 5):
        xs.push(i * i)

func main() -> void:
    let arena = Arena(4096)
    let xs = arena.list::<i32>()
    fill(xs)
    print_i32(len(xs))      # 5
    print_i32(xs.at(3))     # 9
    xs.at(3) = 100          # checked write
    print_i32(xs.at(3))     # 100
    print_i32(xs.pop())     # 16
```

```
5
9
100
16
```

A list is a handle: `len(xs)`, `xs.at(i)`, `xs[i]`, `push`, and `pop` all work
through a plain `let`, and passing `xs` to a function lets that function append
to your list — `fill(xs)` above does exactly that. `xs.at(i)` is checked and
stops the program on a bad index; `xs[i]` is the raw, unchecked form.

## Project: an ASCII terrain generator

Everything together: a seeded random number generator, a 2D grid, checked
indexing, and character output.

```vanta
const W: i32 = 8
const H: i32 = 4

func main() -> void:
    rand_seed(7)           # deterministic map
    mut map: [[i32, 8], 4] = [[0, 0, 0, 0, 0, 0, 0, 0],
                              [0, 0, 0, 0, 0, 0, 0, 0],
                              [0, 0, 0, 0, 0, 0, 0, 0],
                              [0, 0, 0, 0, 0, 0, 0, 0]]
    for y in range(0, H):
        for x in range(0, W):
            let r = rand_f32()
            if r < 0.33:
                map[y][x] = 0      # water
            elif r < 0.66:
                map[y][x] = 1      # plain
            else:
                map[y][x] = 2      # mountain
    for y in range(0, H):
        for x in range(0, W):
            let t = map.at(y).at(x)
            if t == 0:
                write_str("~")
            elif t == 1:
                write_str(".")
            else:
                write_str("#")
        print_newline()
```

```
~~.#~~..
~.....##
#~.~#..#
..#.#~.~
```

The map is reproducible because `rand_seed(7)` pins the stream; change the
seed to explore. Note `map.at(y).at(x)` in the drawing loop: even if a
coordinate slipped past the grid, the program would stop loudly with
`vanta: index ... out of bounds (size ...) at line ...` instead of printing
garbage.

## SDL2: a real window

Printing to the terminal is where Vanta starts, not where it stops. `extern`
blocks declare C functions and the driver links the library in; SDL2 — the
game windowing library — is the worked example. This program opens a window,
clears it to a blue, shows it for 600 ms, and quits:

```vanta
extern "sdl2" {
    func SDL_Init(flags: u32) -> i32
    func SDL_Quit() -> void
    func SDL_CreateWindow(title: str, x: i32, y: i32, w: i32, h: i32, flags: u32) -> ptr<void>
    func SDL_DestroyWindow(window: ptr<void>) -> void
    func SDL_CreateRenderer(window: ptr<void>, index: i32, flags: u32) -> ptr<void>
    func SDL_DestroyRenderer(renderer: ptr<void>) -> void
    func SDL_SetRenderDrawColor(renderer: ptr<void>, r: i32, g: i32, b: i32, a: i32) -> i32
    func SDL_RenderClear(renderer: ptr<void>) -> i32
    func SDL_RenderPresent(renderer: ptr<void>) -> void
    func SDL_Delay(ms: u32) -> void
}

func main() -> void:
    if SDL_Init(32) != 0:              # SDL_INIT_VIDEO
        print_str("SDL_Init failed")
        return
    let window = SDL_CreateWindow("Vanta", 100, 100, 480, 320, 4)
    if ptr_is_null(window):
        print_str("SDL_CreateWindow failed")
        SDL_Quit()
        return
    mut renderer = SDL_CreateRenderer(window, -1, 6)
    if ptr_is_null(renderer):
        renderer = SDL_CreateRenderer(window, -1, 0)
    SDL_SetRenderDrawColor(renderer, 30, 90, 160, 255)
    SDL_RenderClear(renderer)
    SDL_RenderPresent(renderer)
    SDL_Delay(600)                     # hold the window open for 600 ms
    SDL_DestroyRenderer(renderer)
    SDL_DestroyWindow(window)
    SDL_Quit()
    print_str("a blue window, then gone")
```

```
a blue window, then gone
```

Run it with the library on the command line (Windows / MSYS2 paths — on
Linux and macOS SDL2 lives in the default search path, so `--link SDL2`
alone is enough):

```powershell
python main.py run window.vnt --lib-dir C:/msys64/mingw64/lib --link SDL2
```

Things worth noticing:

- The block declares only the functions used, with C-compatible types;
  SDL's headers never enter the picture. `func` without `-> type` returns
  `void`.
- `SDL_CreateWindow` and friends return opaque handles typed `ptr<void>`.
  `ptr_is_null` tests one for failure, and any `ptr<T>` is accepted where
  `ptr<void>` is expected — never the other way around.
- Flags like `SDL_INIT_VIDEO` (32) and `SDL_WINDOW_SHOWN` (4) are plain
  numbers at the call site. The renderer fallback exists because flags 6
  (`SDL_RENDERER_ACCELERATED | SDL_RENDERER_PRESENTVSYNC`) fails on SDL's
  "dummy" video driver, which is how the examples run headless in CI:
  `SDL_VIDEODRIVER=dummy` plus a frame limit makes these programs testable
  without a display.

`examples/sdl_window.vnt` picks up from here with the event loop — quit on
Esc or the close button — and `examples/sdl_game.vnt` turns it into the
first playable Vanta game: move the paddle with Left/Right to catch the
falling coins. The event numbers (type at `ev[0]`, key symbol at `ev[5]`)
and the rest of the API are documented in the reference's
[SDL2 walkthrough](LANGUAGE_REFERENCE.md#sdl2-and-a-window-v0120).

## Where to go next

- [`LANGUAGE_REFERENCE.md`](LANGUAGE_REFERENCE.md) — the full language,
  including imports, `extern` C linking, the SDL2 walkthrough, file I/O,
  and the builtin list.
- [`../examples/`](../examples) — one sample per feature area, from
  `physics.vnt` to `boids.vnt`, `grid.vnt`, and the playable `sdl_game.vnt`.
- [`ARCHITECTURE.md`](ARCHITECTURE.md) — how the compiler is put together,
  if you want to contribute.
- `python -m unittest discover -s tests` — run the test suite (403 tests).
