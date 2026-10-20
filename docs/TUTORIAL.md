# Vanta in 30 minutes

A hands-on introduction that builds from `print_str` to a small project — an
ASCII terrain generator — and then leaves the terminal behind: the closing
sections open a real window with SDL2, draw text, load sprite images and
sound files, poll a game controller, and end with a playable game. Every code
block below is a complete program that was run to produce the output shown —
copy it into a file with a `.vnt` extension and run it.

**Prerequisites:** Python 3.10+ and a C++17 compiler (`g++`, `clang++`, or
MSVC `cl`). See the Quick start in the [README](../README.md). The SDL2
sections at the end additionally need the SDL2, SDL_ttf, and SDL2_image
libraries, but everything before them does not.

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

## Narrow integers

`i8`, `u8`, `i16`, `u16` store their exact width — this is your bridge to C
byte layouts, and how a `u8` field stays one byte in memory. Two rules make
them pleasant:

```vanta
func main() -> void:
    mut health: u8 = 250
    health = health + 10        # 260 does not fit: keeps the low bits
    print_i32(health)

    let damage: i16 = -40
    let shield: u16 = 100
    print_i32(shield + damage)  # reads promote to i32
```

```
4
60
```

Reading a narrow value yields `i32`, so arithmetic, comparisons, and printing
just work — `shield + damage` is a plain `i32`. Storing is C-style
truncation, as in `health` above, but a *literal* that does not fit its
narrow type is a compile error (`let x: u8 = 300`), so typos never silently
wrap.

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

## Comparing structs

`==` and `!=` work on structs when every field has equality: numbers by
value, `str` by content, arrays element by element, nested structs
recursively.

```vanta
struct Card:
    suit: str
    rank: i32

func main() -> void:
    let a = Card(suit: "spades", rank: 7)
    let b = Card(suit: "spades", rank: 7)
    let c = Card(suit: "hearts", rank: 7)
    print_bool(a == b)
    print_bool(a == c)
```

```
true
false
```

A field with no equality — a pointer, a function value, a `List` — makes the
comparison a compile error that names the field, so `==` never compares the
wrong thing quietly.

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

## Pointer casts

`ptr_cast::<T>(p)` reinterprets a pointer as pointing at a different type —
the escape hatch when raw bytes need a second viewing, and the way a
`ptr<void>` handed back by C becomes usable again:

```vanta
func main() -> void:
    let arena = Arena(256)
    let cell = arena.alloc::<i32>(1)
    cell[0] = 1078530011          # f32 pi, as bits
    let as_f32 = ptr_cast::<f32>(cell)
    print_f32(as_f32[0])
```

```
3.141593
```

It is unchecked by design — the bytes must really be a `T`. Function-type
targets are rejected.

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

A list is a handle: `len(xs)`, `xs.at(i)`, `xs[i]`, `push`, `pop`, `insert`,
`remove`, and `sort` all work through a plain `let`, and passing `xs` to a
function lets that function append to your list — `fill(xs)` above does
exactly that. `xs.at(i)` is checked and stops the program on a bad index;
`xs[i]` is the raw, unchecked form.

Lists also support insertion, removal, and comparator-driven sorting:

```vanta
struct Coin:
    value: i32

func by_value(a: Coin, b: Coin) -> i32:
    return a.value - b.value

func main() -> void:
    let arena = Arena(4096)
    let coins = arena.list::<Coin>()
    coins.push(Coin(value: 5))
    coins.push(Coin(value: 1))
    coins.push(Coin(value: 5))
    coins.insert(0, Coin(value: 3))   # 3 5 1 5
    let first = coins.remove(3)       # the 5 that was pushed first
    coins.sort(by_value)              # stable: 1 3 5
    print_i32(first.value)            # 5
    print_i32(len(coins))             # 3
    print_i32(coins.at(0).value)      # 1
    print_i32(coins.at(2).value)      # 5
```

```
5
3
1
5
```

`insert(i, v)` shifts the rest right — `i` may be `len(xs)`, same as `push`;
`remove(i)` shifts the rest left and returns the element; both stop the
program on an out-of-range index, exactly like `at`. `sort(cmp)` takes a
comparator `func(T, T) -> i32` returning negative, zero, or positive for
less-than, equal, greater-than, and is stable: elements the comparator calls
equal keep their order.

## Iterating a collection

`for x in xs` walks a `List<T>` or an array directly — no index needed. The
loop variable is a fresh read-only copy of the element; to write back, use
an index or `xs.at(i)`.

```vanta
func main() -> void:
    let arena = Arena(4096)
    let names = arena.list::<str>()
    names.push("ada")
    names.push("grace")
    for n in names:
        print_str(n)

    let dice = [1, 6, 3]
    mut best = 0
    for d in dice:
        if d > best:
            best = d
    print_i32(best)
```

```
ada
grace
6
```

`break` and `continue` work as in range loops. The iterable can be any
array/List expression — a variable, a parameter, even an array literal
(`for v in [1, 2, 3]:`). Don't push to a list while iterating it: the
length is re-read on every pass.

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

## C callbacks

C libraries often want to call back into *your* code — timers, event
handlers, hooks. An `extern` parameter typed `func(...)` is a C function
pointer, so passing a function value hands C the address to call. `atexit`
from the C standard library is the smallest way to watch this happen; it
runs its callbacks when the program exits, most recently registered first:

```vanta
extern "C" {
    func atexit(cb: func()) -> i32
}

func first():
    print_str("first registered, runs last")

func second():
    print_str("second registered, runs first")

func main() -> void:
    atexit(first)
    atexit(second)
    print_str("main")
```

```
main
second registered, runs first
first registered, runs last
```

Callbacks are plain function pointers — no closures — so state travels
through parameters, like the `ptr<i32>` user-data pointer in
`examples/callbacks.vnt`: a buildable example (with
`examples/callbacks_lib.c`) where C calls a Vanta function twice and walks a
visitor over a count. The C side must declare the matching
function-pointer type. An `extern` can return a function pointer too
(`examples/extern_return.vnt` with `examples/extern_return_lib.c`): the
result is an ordinary function value — call it, compare it with `==`/`!=`,
or test it with `ptr_is_null`. The Sound section's `examples/sdl_audio_cb.vnt`
is the same idea against a
real library — SDL calls the function on its audio thread, and the user-data
pointer carries the state. The full rules are under [Extern
declarations](#extern-declarations-v030) in the reference.

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

## The game kit

The SDL2 program above talks to C directly, and that never stops working —
but wiring the window, the input events, and the rectangles by hand in every
game gets old. The game kit (`examples/gamekit/`) does it once, as ten
ordinary `.vnt` modules you import when you need them: `sdl.vnt` (the SDL2
declarations, the key constants, and the `Screen` lifecycle), `input.vnt`
(reading events), `gamepad.vnt` (controllers, polled), `gfx.vnt` (rectangle
drawing), `image.vnt` (textures, over SDL2_image), `anim.vnt` (sprite-sheet
animation), `text.vnt` (text, over SDL_ttf), `audio.vnt` (tones and WAV
files, over SDL2's audio), `rng.vnt` (bounded random numbers over the
deterministic stream), and `collide.vnt` (pure overlap tests, with no SDL
dependency). A tiny demo — a square bouncing between the walls for 60
frames:

```vanta
import "gamekit/sdl.vnt"
import "gamekit/gfx.vnt"

func main() -> void:
    let screen = screen_open("bounce", 320, 200)
    if not screen_ok(screen):
        print_str("could not open a window and renderer")
        return
    let arena = Arena(256)
    let rect = arena.alloc::<i32>(4)     # one shared SDL_Rect scratch
    mut x = 0.0
    mut vx = 6.5
    mut frames = 0
    while frames < 60:
        x += vx
        if x < 0.0:
            x = 0.0
            vx = -vx
        if x > 296.0:                    # 320 - 24 (the square is 24 wide)
            x = 296.0
            vx = -vx
        gfx_clear(screen, 22, 24, 34)
        gfx_fill_rect(screen, rect, f32_to_i32(x), 88, 24, 24, 240, 200, 60)
        gfx_present(screen)
        frames += 1
    screen_close(screen)
    print_fmt("ended at {} ({} frames)", f32_to_i32(x), frames)
```

```
ended at 205 (60 frames)
```

Two details carry over from the raw SDL2 style. `Screen` fails the way C
does: `screen_open` hands back null handles when a call fails (there is no
nil literal), so `screen_ok` is the check. And the `gfx_*` calls share one
four-`i32` scratch rectangle — that is the `SDL_Rect` SDL asks for.

That is the whole kit: imports, prefixes, and C's own failure values.
`examples/pong.vnt` puts it to work with two paddles, a tracking AI,
`match` for the serve direction, a text score, and beeps;
`examples/breakout.vnt` adds sprite images, an animated ball, and sound
files; `examples/strike.vnt` is the fourth game and the full-kit example —
an animated ship, three waves of tinted saucers, a text HUD, WAV shots and
hits, a gamepad fallback, and collision tests; and
`examples/sdl_gamepad.vnt` shows the raw controller calls behind
`gamepad.vnt`; the [reference](LANGUAGE_REFERENCE.md#the-game-kit-v0140)
lists every function.

## Collision without SDL

`collide.vnt` is the one kit module with no SDL in it: pure Vanta functions,
no externs, no library to link, and a plain headless test on every machine.
Rectangles are `(x, y, w, h)` — the top-left corner and a positive size.
Edges that only touch are not overlaps, and point-in-rectangle is half-open,
so the left and top edges are inside while the right and bottom edges are
out. Circles take centre coordinates and radii; the distance tests compare
squares, so there is no `sqrt` in any of them:

```vanta
import "gamekit/collide.vnt"

func main() -> void:
    print_bool(collide_rects(0.0, 0.0, 10.0, 10.0, 5.0, 5.0, 10.0, 10.0))   # true
    print_bool(collide_rects(0.0, 0.0, 10.0, 10.0, 10.0, 0.0, 10.0, 10.0))  # false: edges touch
    print_bool(collide_point(0.0, 0.0, 0.0, 0.0, 10.0, 10.0))                # true: left/top edge
    print_bool(collide_point(10.0, 5.0, 0.0, 0.0, 10.0, 10.0))               # false: right edge is out
    print_bool(collide_circles(0.0, 0.0, 5.0, 7.0, 0.0, 3.0))                # true
    print_bool(collide_circle_rect(12.0, 5.0, 3.0, 0.0, 0.0, 10.0, 10.0))    # true: 2 px from the edge
```

```
true
false
true
false
true
true
```

## Text on screen

SDL2 paints rectangles and textures; words come from SDL_ttf, the companion
library. The kit's `text.vnt` wraps it the same way the other modules wrap
SDL: a `Font` handle, C-style failure (`font_ok`), and one call to draw a
string. A little title card:

```vanta
import "gamekit/sdl.vnt"
import "gamekit/gfx.vnt"
import "gamekit/text.vnt"

func main() -> void:
    let screen = screen_open("text", 320, 240)
    if not screen_ok(screen):
        print_str("could not open a window and renderer")
        return
    let font = font_open("examples/gamekit/fonts/tom-thumb.ttf", 32)
    if not font_ok(font):
        print_str("could not open a font")
        return
    let arena = Arena(512)
    let rect = arena.alloc::<i32>(4)         # the gfx scratch rect
    let scratch = arena.alloc::<i32>(10)     # the text scratch block
    mut frames = 0
    while frames < 3:
        gfx_clear(screen, 22, 24, 34)
        gfx_stroke_rect(screen, rect, 24, 24, 272, 192, 2, 58, 62, 78)
        text_draw(screen, font, 48, 100, "Vanta speaks!", scratch, 240, 220, 120)
        gfx_present(screen)
        frames += 1
    font_close(font)
    text_quit()
    screen_close(screen)
    print_fmt("frames {}", frames)
```

```
frames 3
```

Three things to know. **The kit ships the font**:
`examples/gamekit/fonts/tom-thumb.ttf` is a tiny 3x5 pixel face released
under CC0, so this program runs on any machine — point `font_open` at any
TrueType file you like instead. **The text scratch is ten `i32` slots**:
width, height, a source rectangle, a destination rectangle, filled in by
`text_measure` and `text_draw` themselves. `text_measure` writes the width
and height, which is how you right-align a score or centre a title: measure
first, then compute the x. **Rendering happens per call**: each `text_draw`
renders the string into a texture and frees it immediately — just right for
scores and timers that change.

Programs that import `text.vnt` link SDL_ttf as well as SDL2;
`examples/pong.vnt` now draws its score this way:

```powershell
python main.py run examples/pong.vnt --lib-dir C:/msys64/mingw64/lib --link SDL2_ttf --link SDL2
```

Text that stays the same but redraws every frame — a label, a wall of
instructions — takes the render-once path instead: `text_sprite` renders it
into a `TextSprite` (a texture plus its size), `text_sprite_ok` is the test,
`text_sprite_draw` blits it with no font call at all, and
`text_sprite_free` releases the texture. The cost difference is real:
`examples/text_bench.vnt` draws one string both ways and prints the two
numbers (headless `SDL_VIDEODRIVER=dummy` works), and the kit freezes the
counts, never the milliseconds.

```vanta
import "gamekit/sdl.vnt"
import "gamekit/text.vnt"

func main() -> void:
    let screen = screen_open("sprites", 320, 240)
    let font = font_open("examples/gamekit/fonts/tom-thumb.ttf", 32)
    print_bool(screen_ok(screen) and font_ok(font))   # true on any working driver
    let label = text_sprite(screen, font, "PAUSED", 240, 220, 120)
    print_bool(text_sprite_ok(label))
    for i in range(0, 3):
        text_sprite_draw(screen, label, 24, 24)       # no font call per frame
    text_sprite_free(label)
    font_close(font)
    text_quit()
    screen_close(screen)
```

```
true
true
```

## Sprites

Rectangles get you far, but games want images. `image.vnt` adds textures: a
`Tex` is a decoded image on the renderer — a handle, a width, and a height —
and the decoding comes from SDL_image, which is why programs that import the
module link `SDL2_image` as well as SDL2:

```vanta
import "gamekit/sdl.vnt"
import "gamekit/gfx.vnt"
import "gamekit/image.vnt"

func main() -> void:
    let screen = screen_open("sprites", 320, 240)
    let ball = tex_load(screen, "examples/assets/ball.png")
    print_bool(screen_ok(screen) and tex_ok(ball))   # true on any working driver
    print_fmt("{}x{}", ball.w, ball.h)               # the decoded size
    gfx_clear(screen, 22, 24, 34)
    tex_draw(screen, ball, 40, 40)                   # whole texture, natural size
    tex_tint(ball, 240, 96, 96)                      # draws from here on are red
    tex_draw(screen, ball, 80, 40)
    tex_draw_src(screen, ball, 0, 0, 5, 10, 120, 40) # half of it — a sheet region
    tex_draw_ex(screen, ball, 40, 100, 45.0, SDL_FLIP_NONE)   # rotated 45 degrees
    gfx_present(screen)
    print_str("drawn")
    tex_free(ball)
    screen_close(screen)
```

```
true
10x10
drawn
```

Four things to know. **Failure is quiet, again**: a missing or unreadable
file comes back as a dead `Tex` (`tex_ok` is the test), and every `tex_*`
call on one does nothing. **The kit ships no image files either** — the
files under `examples/assets/` are generated by a committed script
(`examples/assets/gen_assets.py`), so the repository vendors nothing.
**Tinting is multiplication**: `tex_tint` sets a colour multiplied into
every following draw of that texture (255 leaves a channel alone) and
`tex_alpha` sets an overall opacity — breakout's four brick rows are one
white texture and four tints. **Drawing comes in three shapes**: `tex_draw`
(whole texture at natural size), `tex_draw_src` (one rectangle of it — a
sprite-sheet frame), and `tex_draw_ex` (rotated by an `f64` angle in degrees
and/or flipped with `SDL_FLIP_HORIZONTAL` / `SDL_FLIP_VERTICAL`, both about
the texture's own centre). Unlike the `gfx_*` helpers, the `tex_draw*`
family needs no caller scratch — it builds its rects on a tiny transient
arena, because SDL copies them during the call.

`examples/breakout.vnt` is the worked example — a tinted sprite wall, a ball,
and a paddle:

```powershell
python main.py run examples/breakout.vnt --lib-dir C:/msys64/mingw64/lib --link SDL2_image --link SDL2_ttf --link SDL2
```

## Animated sprites

A sprite sheet plays back as a strip of equal frames. `anim.vnt` is the
frame clock over `tex_draw_src` that the sprites section left by hand:

```vanta
import "gamekit/sdl.vnt"
import "gamekit/image.vnt"
import "gamekit/anim.vnt"

func main() -> void:
    let screen = screen_open("animation", 96, 32)
    let spin = tex_load(screen, "examples/assets/ball_spin.png")   # 4 frames
    print_bool(screen_ok(screen) and tex_ok(spin))   # true on any working driver
    mut anim = anim_new(4, 10, 10, 8.0)              # 4 frames, 10x10, 8 fps
    for i in range(0, 6):
        anim = anim_tick(anim, 0.125)                # advance by 1/8 second
        anim_draw(screen, spin, anim, 4 + i * 14, 4)
        print_i32(anim_frame(anim))
    tex_free(spin)
    screen_close(screen)
```

```
true
1
2
3
0
1
2
```

`anim_tick` returns the updated clock — `anim = anim_tick(anim, dt)` is the
idiom, because structs are values — and the frame wraps, so the animation
loops. The step is the game's to choose: pass the frame time from your own
loop, as breakout does with a fixed 1/60 s so its headless run cannot
drift, or any exact amount when you want repeatable numbers like the ones
above. `anim_new` describes the strip (frame count, frame size, frames per
second); `anim_draw` blits the current frame under whatever tint the
texture carries. Nothing reads a wall clock, and a dead texture or an empty
strip (zero frames) draws nothing.

`examples/breakout.vnt` now spins its ball from `ball_spin.png`, the sheet
the assets script generates beside the static ball:

```powershell
python main.py run examples/breakout.vnt --lib-dir C:/msys64/mingw64/lib --link SDL2_image --link SDL2_ttf --link SDL2
```

## Sound

SDL2 makes noise without any companion library: audio is part of the core,
and the kit's `audio.vnt` wraps it the way `gfx.vnt` wraps drawing. Tones are
generated with no file involved — `audio_play_tone` takes a frequency, a
duration, and a caller-owned sample buffer, so the kit never allocates per
beep. A two-note chirp:

```vanta
import "gamekit/audio.vnt"

func main() -> void:
    let audio = audio_open()
    if not audio_ok(audio):
        print_str("could not open an audio device")
        return
    let arena = Arena(32768)
    let buf = arena.alloc::<i16>(11025)    # up to 250 ms of samples
    print_fmt("queued {} samples", audio_play_tone(audio, 880, 100, buf, 11025))
    audio_play_tone(audio, 660, 100, buf, 11025)
    audio_wait(audio)                      # play the chirp out
    print_fmt("still queued {}", audio_pending(audio))
    audio_close(audio)
```

```
queued 4410 samples
still queued 0
```

Things to know. **Audio is in SDL2 itself**: only `text.vnt` and `image.vnt`
ask for companion libraries (SDL_ttf, SDL2_image); audio programs link just
SDL2. **Playback happens in the background**: queueing returns immediately,
SDL's audio thread plays the tones on, and the game loop keeps running —
`audio_pending` asks how many bytes are still queued, and `audio_wait`
blocks until the queue drains (handy in scripts; games rarely wait).
**Failure is quiet by design**: `audio_open` returns an `Audio` whose
`audio_ok` is false when no device works, and every other audio call then
does nothing — pong, for instance, plays its beeps unconditionally and stays
silent on machines without sound.

**Sounds from files.** `sound_load` reads a WAV — 16-bit PCM at 44.1 kHz,
mono or stereo — into a buffer SDL allocates; `sound_play` queues it, and
`sound_free` gives the buffer back. A stereo file is folded to mono in place
at load (its byte count halves), and any other rate, sample format, or
channel count loads as a dead `Sound` whose `sound_ok` is false — playing or
freeing one is a no-op, so nothing changes on a machine where the files (or
the device) are missing. This one is a 60 ms blip:

```vanta
import "gamekit/audio.vnt"

func main() -> void:
    let audio = audio_open()
    let snd = sound_load(audio, "examples/assets/blip.wav")
    print_bool(audio_ok(audio) and sound_ok(snd))   # true on any working driver
    print_fmt("{} bytes", snd.len)                  # 5292 = 60 ms at 44.1 kHz
    sound_play(audio, snd)
    audio_wait(audio)
    sound_free(snd)
    audio_close(audio)
```

```
true
5292 bytes
```

The chirp above runs exactly like the game kit's other programs, but SDL
audio is also a good look at the raw C side: `examples/sdl_audio.vnt` opens
the device with the queue API (a `ptr_null::<func(...)>()` callback slot),
and `examples/sdl_audio_cb.vnt` does the opposite — it puts a Vanta function
in the spec's `callback` field and SDL runs it on its audio thread, which is
the same pattern as the [C callbacks](#c-callbacks) section above.
`examples/sdl_sound.vnt` is the raw file version — `SDL_LoadWAV_RW` over
`SDL_RWFromFile`. `examples/pong.vnt` beeps on every paddle hit and point,
and `examples/breakout.vnt` fires WAV files for its hits, bricks, and lost
balls:

```powershell
python main.py run examples/pong.vnt --lib-dir C:/msys64/mingw64/lib --link SDL2_ttf --link SDL2
python main.py run examples/breakout.vnt --lib-dir C:/msys64/mingw64/lib --link SDL2_image --link SDL2_ttf --link SDL2
```

## Gamepads

Controllers are another kit import — `gamepad.vnt`, over SDL2's core library,
so no companion library is needed. `pad_open` takes SDL's joystick index (0
is the first controller) and returns a `Pad`; with no controller at that
index the handle is dead, `pad_ok` is false, and every other call is a
guarded no-op. That is the trick that keeps a game playable on a
keyboard-only machine: poll the pad each frame and fall back to keys.

```vanta
import "gamekit/sdl.vnt"
import "gamekit/gamepad.vnt"

func main() -> void:
    let screen = screen_open("gamepads", 320, 240)
    let pad = pad_open(9999)                  # out of range: the dead path
    print_bool(pad_ok(pad))                   # false
    print_bool(pad_attached(pad))             # false, guarded
    print_bool(pad_button(pad, PAD_BUTTON_A)) # false, guarded
    print_i32(pad_axis(pad, PAD_AXIS_LEFT_X)) # 0, guarded
    pad_close(pad)                            # safe on a dead pad
    screen_close(screen)
```

```
false
false
false
0
```

Three things to know. **The index is SDL's, not a count**: `pad_open(0)` is
the first controller and 1 the second, so the snippet asks for 9999 to make
its frozen output the dead path on every machine — change it to 0 to play
with real hardware. **Axes are raw**: `pad_axis` returns SDL's `Sint16` —
sticks span -32768..32767 with 0 at rest, triggers 0..32767 — so divide and
apply your own deadzone. **Polling, not events**: `pad_button` reports the
current state each frame; the event loop stays keyboard-focused, and
`pad_attached` turns false when the pad is unplugged while the handle stays
open.

`examples/sdl_gamepad.vnt` is the raw version of the same calls — open by
index, poll A, d-pad-left, the left stick, and the left trigger, close. With
no controller it prints the dead path too:

```powershell
python main.py run examples/sdl_gamepad.vnt --lib-dir C:/msys64/mingw64/lib --link SDL2
```

## Where to go next

- [`LANGUAGE_REFERENCE.md`](LANGUAGE_REFERENCE.md) — the full language,
  including imports, `extern` C linking, the SDL2 walkthrough and the game
  kit, file I/O, and the builtin list.
- [`../examples/`](../examples) — one sample per feature area, from
  `physics.vnt` to `boids.vnt`, `grid.vnt`, and the playable `sdl_game.vnt`,
  `pong.vnt`, `breakout.vnt`, and `strike.vnt`, with the reusable `gamekit/`
  modules alongside.
- [`ARCHITECTURE.md`](ARCHITECTURE.md) — how the compiler is put together,
  if you want to contribute.
- `python -m unittest discover -s tests` — run the test suite (556 tests).
