# Vanta Language Reference (v0.21.0)

This is the reference for the language as implemented at tag `v0.16.0`. Every
claim here was checked against the compiler; where behaviour surprised us, the
surprise is called out explicitly.

## Comments and layout

- `#` starts a line comment.
- Blocks are delimited by indentation, not braces. The lexer emits `INDENT` and
  `DEDENT` tokens. **Tabs are rejected** — indent with spaces.
- One statement per line, except inside `(...)` and `[...]`: newlines there are
  ignored, so array literals and argument lists may span lines.
- Statement bodies use `:` blocks; only `extern` uses `{` `}`.

## Values and mutability

`let` declares an immutable binding; `mut` declares a mutable one.

```vanta
let name = "vanta"      # immutable
mut count: i32 = 0      # mutable, explicit type
```

Assigning to a `let` binding is a compile-time error.

## Types

| Type | Notes |
|---|---|
| `i8`, `u8`, `i16`, `u16` | narrow integers with exact width — `u8` is one byte (see [Narrow integers](#narrow-integers-v0170)) |
| `i32`, `u32` | 32-bit integers |
| `f32`, `f64` | 32/64-bit floats |
| `bool` | `true` / `false` |
| `void` | function return only |
| `str` | string literal type (see [Strings](#strings)) |
| `ptr<T>` | raw pointer: locals, parameters, and returns; `ptr<void>` is the untyped C-style handle (see [Pointers and the Arena](#pointers-and-the-arena)) |
| `[T, N]` | fixed-size array of `N` elements; `T` may itself be an array; checked access with `xs.at(i)` (see [Checked indexing](#checked-indexing-at-v070)) |
| `List<T>` | growable list whose storage lives in an `Arena`; `push`/`pop`/`len`/`at`/`xs[i]` (see [Dynamic lists](#dynamic-lists-listt-v090)) |
| `func(T1, ...) -> R` | function value; arrow omitted means `-> void` (see [Function values](#function-values-v060)) |
| `Vec2`, `Vec3`, `Quat`, `Matrix4` | built-in math types |
| `Arena` | stack-scoped allocator (see [Arena](#pointers-and-the-arena)) |
| `StrBuilder` | arena-backed string builder; append pieces, then `to_str()` (see [String building](#string-building-strbuilder-v0100)) |
| `Name` (enum) | named integer members; `Name.Member`, `==`/`!=`, `enum_to_i32` (see [Enums](#enums-v0110)) |

Integer literals default to `i32`; float literals default to `f32`.

Wider-into-narrower integer assignment is the one exception (v0.17.0): any
integer stores into a narrow slot by keeping its low bits, C-style — see
[Narrow integers](#narrow-integers-v0170). **Otherwise there is no implicit
numeric conversion**, including `i32` → `u32`. This will bite you when
calling a `u32` parameter with an `i32` variable:

```
error: cannot assign i32 to u32
```

Use `i32_to_f32` / `f32_to_i32` for float conversions.

## Narrow integers (v0.17.0)

`i8`, `u8`, `i16`, and `u16` store their exact width — a `u8` field or buffer
element is one byte — so Vanta structs and pointers can match a C layout
byte for byte (`uint8_t`, `int16_t`, ... in the generated C++). Two rules
make them ergonomic:

**Reads promote.** Reading a narrow value yields `i32`, exactly like C's
integer promotion, so arithmetic and comparisons need no casts:

```vanta
func main() -> void:
    mut px: u8 = 250
    px = px + 10                # 260 does not fit: keeps the low bits
    print_i32(px)
    let big: u16 = 60000
    let small: i16 = -300
    print_i32(big + small)
    print_fmt("u8={} i16={}", px, small)
```

```
4
59700
u8=4 i16=-300
```

**Stores truncate; literals must fit.** Assigning any integer expression into
a narrow slot keeps the low bits (`px = px + 10` above stores `4`), but a
*literal* that does not fit is a compile-time error instead of a silent
mistake:

```
error: initializer: value 300 out of range for u8
```

The same range check applies to literals appearing beside a narrow value
(`if px == 300:` errors identically). Narrow values convert
value-preservingly into `i32`/`u32`, so `print_u32(x)` and `let w: u32 = x`
work for a `u8`; `u8` → `f32` does not (go through `i32_to_f32`).

Narrow types may be written anywhere a type is written: locals, struct
fields, array elements (`[u8, 16]`), `ptr<u16>`, `List<u8>`, and `extern`
signatures.

## Constants (v0.1.2)

```vanta
const GRAVITY: f32 = 9.81
const HALF = 0.5          # type inferred: f32
```

Constants are compile-time values, emitted as C++ `constexpr`. The initializer
must be a literal, a previously declared constant, or arithmetic on those.
Constants cannot be assigned to, and duplicate names are rejected.

## Assertions (v0.1.2)

`assert(cond)` requires a `bool`. If it is false at runtime, Vanta prints
`vanta: assertion failed at line N` to standard error and exits with code 1.

## Return type inference (v0.1.2)

When `-> T` is omitted, the return type is inferred from the body's `return`
statements. All returns must agree on a type.

```vanta
func square(x: i32):      # inferred -> i32
    return x * x
```

A function with an inferred return type must be declared **before** it is
called; otherwise add `-> T` explicitly.

## Ranges

```vanta
for i in range(0, 10):        # 0..9, end exclusive
for i in range(0, 20, 5):     # 0, 5, 10, 15
for i in range(5, 0, -1):     # 5, 4, 3, 2, 1
```

The end is exclusive. A step of zero is rejected. Ranges are the numeric
loop; to walk a collection element by element, `for x in xs` iterates arrays
and `List<T>` (next section).

## For-each over arrays and lists (v0.17.0)

```vanta
for x in xs:            # xs is a List<T> or a [T, N]
    print_i32(x)
```

`for x in <expr>` walks a `List<T>` or a fixed-size array element by element.
The loop variable is bound once per iteration to a **read-only copy** of the
element — assigning to it is a compile error, and writing back means an index
or a checked `at(i)`:

```vanta
func main() -> void:
    let arena = Arena(4096)
    let xs = arena.list::<i32>()
    xs.push(3)
    xs.push(5)
    mut total = 0
    for x in xs:
        total = total + x
    for v in [1, 2, 3]:
        total = total + v
    print_i32(total)
```

```
14
```

The iterable can be any expression of an array or `List` type — a local, a
parameter, a function result, an array literal. `break` and `continue` mean
the same as in range loops. Iterating anything else is a compile error:

```
error: cannot iterate over ptr<i32>; for-each supports arrays and Lists
```

A List's length is re-read every iteration (the loop lowers to an index loop
over the list handle), so **do not grow a list while iterating it** — use a
`while` loop when the collection changes mid-walk.

## Control flow

```vanta
if score > 100:
    print_str("high")
elif score > 50:
    print_str("mid")
else:
    print_str("low")
```

Note `elif`, not `else if`.

```vanta
while i < 3:
    i += 1
```

`break` and `continue` are only valid inside a loop; using them at the top
level is a compile-time error.

Enum values branch with `match` (v0.13.0, below); `if`/`elif`/`else`
chains stay the way to branch on bools.

## Structs, components, and systems

`struct` declares a data type. `component` is an identical declaration that
signals ECS intent, and `system` is an identical declaration to `func`.

```vanta
component Position:
    x: i32
    y: i32

system move(ps: ptr<Position>, count: i32) -> void:
    for i in range(0, count):
        ps[i].x += 1
```

Fields are accessed with `.`. **User-defined structs must be constructed with
named arguments** — unlike the built-in math types:

```vanta
let p = Position(x: 0, y: 0)   # correct
let p = Position(0, 0)         # error: struct construction requires named arguments
```

The built-in types are the exception and take positional arguments:
`Vec2(x, y)`, `Vec3(x, y, z)`, `Quat(x, y, z, w)`, `Matrix4()` (identity).

### Struct equality (v0.17.0)

`==` and `!=` compare two values of the same struct type field by field:
numbers by value, `str` **by content** (`str_eq`), arrays element by element,
and nested structs recursively. `Vec2` and `Vec3` keep their built-in
equality.

```vanta
struct Point:
    x: i32
    y: i32

func main() -> void:
    let a = Point(x: 2, y: 5)
    let b = Point(x: 2, y: 5)
    print_bool(a == b)
```

```
true
```

A field whose type has no equality — `ptr<T>`, a function value, `List<T>`,
or `Quat`/`Matrix4` — makes comparing the whole struct a compile error that
names the field path:

```
error: cannot compare struct 'Sprite' with '==': field 'pos.p' (ptr<i32>) has no equality
```

The check is recursive, so array fields (`cells[N]`) and nested structs are
inspected down to the leaf.

## Enums (v0.11.0)

`enum` declares a fixed set of named members, numbered from `0` in
declaration order. A member is written `Name.Member`, and the enum is an
ordinary type — variables, struct fields, parameters, returns, arrays,
`List<T>`, function values, and imported modules all accept it:

```vanta
enum State:
    Menu
    Playing
    Paused
    GameOver

struct Game:
    state: State

func is_over(s: State) -> bool:
    return s == State.GameOver

func main() -> void:
    let g = Game(state: State.Menu)
    if g.state == State.Menu:
        print_str("menu")               # menu
    mut s = State.Playing
    s = State.Paused
    print_i32(enum_to_i32(s))           # 2
    print_bool(is_over(s))              # false
```

```
menu
2
false
```

- Members are numbered `0`, `1`, `2`, ... in declaration order; there are no
  explicit member values.
- `==` and `!=` compare values of the same enum. Ordering comparisons
  (`<`, `<=`, `>`, `>=`) are compile errors, as are compares between two
  different enums or between an enum and a number.
- `enum_to_i32(v)` returns a member's number — the bridge to printing and
  arithmetic. `extern` signatures may also take and return enum types
  directly (v0.17.0): the generated C++ uses the fixed-`int32_t` enum, so
  the C side declares `int32_t` or a matching C enum.
- An enum cannot be constructed: `State(1)` is an error. Enum types have no
  fields either — `s.Menu` is rejected with a hint to write `State.Menu`.
- Type names share one namespace: an enum cannot reuse the name of a struct,
  function, or constant. `List` and `FnPtrN` are reserved.
- `match` (v0.13.0, below) switches on enum values; when every member has
  an arm the checker proves it and no `else` is needed.
- `enum` is a reserved keyword.

## Match (v0.13.0)

`match` chooses a branch by comparing an enum value against member
patterns. Arms are written `Enum.Member:` — several patterns per arm are
separated by commas — and run top to bottom; the first match wins.
`else:` is the fallback branch:

```vanta
enum State:
    Menu
    Playing
    Paused
    GameOver

func label(s: State) -> str:
    match s:
        State.Menu:
            return "menu"
        State.Playing, State.Paused:
            return "in game"
        State.GameOver:
            return "game over"

func main() -> void:
    print_str(label(State.Paused))      # in game
    print_str(label(State.GameOver))    # game over
    print_str(label(State.Menu))        # menu
```

```
in game
game over
menu
```

- The matched value must be an enum; `match` on numbers, strings, or
  structs is a compile error.
- Patterns must name members of the matched enum: `Mode.On` against a
  `State` value is an error, as are a misspelled member and the same
  member used by two arms.
- When every member has an arm somewhere in the match, no `else` is
  needed — the checker proves it. With a member missing and no `else`,
  the error names the missing members, so adding a member to an enum
  later points at every match that must handle it.
- `else` must be the last arm. It is allowed even when it is unreachable
  (every member already covered).
- Each arm has its own scope, and any statement is allowed inside —
  including `break` and `continue`, which still control the enclosing
  loop: `match` is not a loop, so it never captures them.
- `match` is a statement, not an expression: it produces no value.
- `match` is a reserved keyword.

## Arrays

Fixed-size arrays have type `[T, N]` and a literal form:

```vanta
let xs: [i32, 4] = [10, 20, 30, 40]
print_i32(len(xs))          # 4
print_i32(xs[0])            # 10

mut counts = [1, 2, 3, 4]
counts[0] += 100            # element compound assignment
counts[3] = 7               # element assignment
```

- `len(xs)` returns the element count.
- The size is part of the type: the literal must have exactly `N` elements.
- Empty array literals are rejected.
- An `f32` array accepts integer literals, which are coerced.
- Sizes in type annotations are integer literals; `const` names cannot appear
  there.

### Nested arrays (v0.5.0)

`T` may itself be an array type — that is how 2D grids are written:

```vanta
# 4 rows of 8 i32, indexed rows first: g[y][x]
mut g: [[i32, 8], 4] = [[0, 0, 0, 0, 0, 0, 0, 0],
                        [0, 0, 0, 0, 0, 0, 0, 0],
                        [0, 0, 0, 0, 0, 0, 0, 0],
                        [0, 0, 0, 0, 0, 0, 0, 0]]
g[1][3] = 9
print_i32(g[1][3])          # 9
```

- Grid literals may span lines: newlines inside `[...]` are ignored.
- Writes follow the binding rules at any depth: a `mut` binding makes its
  grid cells writable, a `let` binding does not, and parameters are immutable
  — including fields of structs passed by value.
- Writing **through a pointer** ignores binding mutability: pointer memory is
  always writable. `arena.alloc::<[T, W]>(h)` allocates a dynamic grid of `h`
  rows, each `W` wide:

```vanta
let arena = Arena(4096)
let rows = arena.alloc::<[i32, 8]>(4)   # 4 rows of 8
rows[0][0] = 1
print_i32(rows[3][7])
```

  The row width is fixed by the type argument; the row count is yours to
  track.

### Checked indexing: `at()` (v0.7.0)

`xs[i]` is unchecked. When an index cannot be trusted — it comes from data,
user input, or arithmetic — `xs.at(i)` checks it against the array's size
before touching memory:

```vanta
mut xs: [i32, 4] = [10, 20, 30, 40]
print_i32(xs.at(1))         # 20
xs.at(2) = 99               # checked write
print_i32(xs.at(2))         # 99
xs.at(3) += 1               # compound assignment works too
print_i32(xs.at(3))         # 41

let j = len(xs) - 2         # the index may be any i32 expression
print_i32(xs.at(j))         # 99
```

An out-of-bounds access — including a negative index — is a loud failure, not
a silent memory error. This program:

```vanta
func main() -> void:
    let xs: [i32, 4] = [10, 20, 30, 40]
    print_i32(xs.at(4))
```

prints to stderr and exits with status 1:

```
vanta: index 4 out of bounds (size 4) at line 3
```

- `at` works on fixed-size arrays `[T, N]`, including nested ones:
  `g.at(y).at(x)` reads an element and `g.at(y).at(x) = v` writes one.
  A read returns the element, so a function result can be a receiver too:
  `make_grid().at(0)`.
- Writes obey the normal mutability rules: the storage chain must reach a
  `mut` binding, or index through a `ptr<T>` — pointer memory is always
  writable.
- `at` is **not** available on `ptr<T>`: a pointer has no length, so there is
  nothing to check against — use `p[i]`. There is no checked access for
  pointers yet.
- `at` is a call, not a value: `xs.at` alone is an error.

## Pointers and the Arena

`Arena` is a bump allocator backed by a single `malloc`, intended for
frame-scoped game data.

```vanta
let arena = Arena(65536)
let positions = arena.alloc::<Vec2>(30)
positions[0] = Vec2(1.0, 2.0)
arena.reset()               # rewinds the allocation offset to 0
```

- `Arena(bytes)` — bytes must be an `i32`.
- `arena.alloc::<T>(count)` returns a `ptr<T>` to `count` contiguous `T`.
- Indexing a `ptr<T>` uses `p[i]`.
- `arena.reset()` rewinds the allocation offset; it does not zero memory.

Pointer values can also come from `extern` calls and live in locals. A pointer
local can be reassigned with `mut`, user functions may take and return
pointers, and any `ptr<T>` is accepted where `ptr<void>` is expected — C's
license to pass `T*` as `void*`. The narrowing direction stays an error, and a
`ptr<void>` cannot be indexed: declare the pointer with its element type
(`ptr<i32>`, ...) if you need `p[i]`. `ptr<void>` is how opaque C handles such
as `SDL_Window` are typed.

Because there is no `nil` literal, `ptr_is_null(p)` is the null test, and
`ptr_null::<T>()` (v0.19.0, [below](#null-pointers-ptr_nullt-v0190)) is the
explicit way to build the null value a C function asks for (see
[SDL2](#sdl2-and-a-window-v0120) for `ptr_is_null` in real use).

**Arena is non-copyable.** `let b = a`, `return a`, and passing an `Arena` as a
function argument are all rejected at compile time:

```
error: cannot pass Arena to a function
```

This is the only ownership rule enforced. `ptr<T>` has **no** borrow checking,
so dangling or aliased pointers are not detected.

### Pointer casts: `ptr_cast::<T>` (v0.17.0)

`ptr_cast::<T>(p)` reinterprets a pointer's element type, keeping the
address — `reinterpret_cast` in the generated C++. It is unchecked: the
language trusts the bytes really are a `T`. Use it to view the same memory
as a different type, or to give a `ptr<void>` from C a useful element type
again:

```vanta
func main() -> void:
    let arena = Arena(256)
    let words = arena.alloc::<i32>(1)
    words[0] = 1078530011        # the f32 bit pattern of pi
    let f = ptr_cast::<f32>(words)
    print_f32(f[0])
```

```
3.141593
```

The argument must be a pointer, and the target may be any data type —
`i32`, a struct, an array, or `void` (erasing the element type, so the
result is a `ptr<void>` and cannot be indexed). Function types are the one
rejection:

```
error: ptr_cast cannot target a function type
```

### Pointer offsets: `ptr_offset(p, n)` (v0.18.0)

`ptr_offset(p, n)` moves a pointer `n` elements — the `p + n` of C, spelled
as a call. The element type is kept, the result indexes and passes exactly
like `p`, and the offset counts elements, not bytes:

```vanta
func main() -> void:
    let arena = Arena(256)
    let xs = arena.alloc::<i32>(4)
    xs[0] = 10
    xs[1] = 20
    xs[2] = 30
    xs[3] = 40
    let third = ptr_offset(xs, 2)
    print_i32(third[0])                  # 30
    third[0] = 33                        # writes through to xs[2]
    print_i32(xs[2])                     # 33
    print_i32(ptr_offset(third, -1)[0])  # 20 — offsets may be negative
    print_i32(ptr_offset(xs, 3)[0])      # 40
```

```
30
33
20
40
```

The offset is plain arithmetic — bounds are the programmer's business, as
with `p[i]` — but it must be an integer: `i32`, with narrow values
promoting. A non-integer offset gets the usual conversion message:

```
error: offset: cannot assign f32 to i32
```

`ptr<void>` has no element size to step by, so it is the one rejection:

```
error: cannot offset a ptr<void> (it has no element size); ptr_cast it to a typed pointer first
```

C out-parameters are the motivating case. Functions like SDL_ttf's
`TTF_SizeUTF8(font, text, &w, &h)` write through two pointers; with
`ptr_offset` one scratch block and one `arena.alloc` cover them:
`TTF_SizeUTF8(font, text, scratch, ptr_offset(scratch, 1))` stores the width
in `scratch[0]` and the height in `scratch[1]`. The game kit's
[`text.vnt`](#the-game-kit-v0140) builds on exactly that.

### Null pointers: `ptr_null::<T>()` (v0.19.0)

Null handles come *from* C when a call fails — that is what `screen_ok`
tests. Some C functions also want to *receive* NULL: SDL asks for a device
name (NULL means "the default device") and for an empty callback slot when a
device plays through the queue API instead of a callback. `ptr_null::<T>()`
is how a program writes that value; the type argument says what the pointer
points at:

```vanta
func main() -> void:
    let d = ptr_null::<void>()
    print_bool(ptr_is_null(d))       # true
    let p = ptr_null::<i32>()
    print_bool(ptr_is_null(p))       # true
```

```
true
true
```

`T` can be any data type — `void` gives the anonymous `ptr<void>` — or a
function type, which makes the value a null callback: the empty slot a
queue-mode `SDL_AudioSpec` carries. The result is typed `ptr<T>` (or that
function type), so it passes to any `extern` that declares the same thing.
There is still no `nil` literal — this is the one explicit way to build a
null, and `ptr_is_null` stays the test. Like the other pointer builtins it
takes no arguments:

```
error: ptr_null takes no arguments, got 1
```

The game kit's [`audio.vnt`](#the-game-kit-v0140) is the worked example: it
hands `SDL_OpenAudioDevice` a null device name and a null callback, and
`examples/sdl_audio.vnt` does the same with raw `extern` declarations.

## Dynamic lists: `List<T>` (v0.9.0)

`List<T>` is a growable array whose storage lives in an `Arena`. Create an
empty one with `arena.list::<T>()` and append to it with `push`:

```vanta
let arena = Arena(4096)
let xs = arena.list::<i32>()
xs.push(10)
xs.push(20)
print_i32(len(xs))     # 2
print_i32(xs.at(1))    # 20
xs.at(1) = 21          # checked write
print_i32(xs.pop())    # 21
print_i32(len(xs))     # 1
```

- `xs.push(v)` appends one value; growth doubles the capacity (starting at 4)
  and copies the old elements into a fresh arena block.
- `xs.pop()` removes and returns the last element; popping an empty list stops
  the program with `vanta: pop from empty list at line L`.
- `len(xs)` returns the element count as `i32`.
- `xs.at(i)` is the v0.7.0 checked access: reads copy the element, writes store
  through it, and an out-of-bounds index stops the program with
  `vanta: index I out of bounds (size N) at line L`.
- `xs[i]` is the unchecked form, exactly as for fixed-size arrays.
- `xs.insert(i, v)` inserts `v` at index `i`, shifting the rest right; `i` may
  be `len(xs)`, which is the same as `push`. An out-of-range index stops the
  program with `vanta: insert index I out of bounds (size N) at line L`.
- `xs.remove(i)` removes and returns the element at index `i`, shifting the
  rest left. An out-of-range index stops the program with
  `vanta: remove index I out of bounds (size N) at line L`.
- `xs.sort(cmp)` sorts in place with a comparator — a function value
  `func(T, T) -> i32` that returns a negative number, zero, or a positive
  number for less-than, equal, greater-than. The sort is **stable** (elements
  the comparator calls equal keep their order) and costs `O(n log n)`
  comparisons.

**A `List<T>` is a handle, not the storage.** Copying one (`let ys = xs`) copies
the handle, so both names see the same elements. Passing a list to a function
therefore lets the function append to the caller's list:

```vanta
func fill(xs: List<i32>):
    for i in range(0, 3):
        xs.push(i)

func main() -> void:
    let arena = Arena(1024)
    let xs = arena.list::<i32>()
    fill(xs)
    print_i32(len(xs))     # 3
```

Because a list is an indirection — like `ptr<T>` — `push`, `pop`, `insert`,
`remove`, `sort`, and element writes are allowed through a plain `let`; `mut`
is only needed to rebind the name (`xs = other`).

`insert` shifts the rest right, `remove` shifts the rest left and returns the
element, and `sort` takes a comparator — a function value `func(T, T) -> i32`
returning negative, zero, or positive for less-than, equal, greater-than:

```vanta
func by_score(a: i32, b: i32) -> i32:
    return b - a            # descending

func main() -> void:
    let arena = Arena(1024)
    let xs = arena.list::<i32>()
    xs.push(3)
    xs.push(1)
    xs.insert(0, 2)         # 2 3 1
    print_i32(xs.remove(2)) # 1
    xs.sort(by_score)       # 3 2
    print_i32(xs.at(0))     # 3
    print_i32(xs.at(1))     # 2
```

```
1
3
2
```

Limits: element types must be copyable, so `List<void>` and `List<Arena>` are
compile errors. `arena.reset()` invalidates every list made from that arena,
because the storage lives there. Sorting allocates its scratch block from the
same arena. Iterate with `for x in xs` (v0.17.0, above) or an index range
(`for i in range(0, len(xs))`).

## String building: `StrBuilder` (v0.10.0)

The string pool is fine for one-off values, but building a string piece by
piece with `str_concat` in a loop burns pool memory on every intermediate
result. A `StrBuilder` is the arena-backed answer: one growing buffer, many
appends, and no pool involvement.

```vanta
let arena = Arena(4096)
let b = arena.str_builder()
b.append_str("hp ")
b.append_i32(42)
b.append_str(" / ")
b.append_f32(1.5)
print_str(b.to_str())     # hp 42 / 1.500000
print_i32(len(b))         # 16
```

- `append_str(s)` appends a `str`; `append_i32` / `append_u32` / `append_f32`
  / `append_f64` / `append_bool` format a value exactly like the matching
  `print_*` function.
- `len(b)` returns the byte count appended so far as `i32`.
- `to_str()` returns the current contents as a `str` — **copied into a fresh
  arena block**, so the result is stable: later appends, growth, and `clear()`
  do not change it.
- `clear()` resets the builder to empty; the buffer is reused.

Like `List<T>`, a `StrBuilder` is a handle: copies alias the same buffer, and
appends work through a plain `let` — `mut` only controls rebinding. A helper
function can take a `StrBuilder` parameter and append to the caller's builder.
The buffer grows by doubling from 32 bytes, allocating from the arena;
`arena.reset()` invalidates the builder and every string taken from it.

**When to use which:** `str_concat` / `to_str_*` for isolated values
(pool-backed); `StrBuilder` for assembling lines, logs, and HUD text,
especially per-frame — build with `clear()`, print with `to_str()`.

## Function values (v0.6.0)

Functions are values. A function type is written `func(P1, P2) -> R`; omit the
arrow for a `void` return type: `func(str)`.

```vanta
func square(x: i32) -> i32:
    return x * x

func apply(f: func(i32) -> i32, x: i32) -> i32:
    return f(x)

func main() -> void:
    let f = square              # inferred: func(i32) -> i32
    print_i32(f(5))             # indirect call: 25
    print_i32(apply(square, 7)) # a function as an argument: 49
```

- Values are plain function pointers: a `func` value always points at a named
  function. **There are no closures** — nothing is captured, so a function
  value cannot remember surrounding variables.
- Any named function works as a value: Vanta functions, `extern` functions
  (used under their C name), and builtins such as `print_str` or `sqrt_f32`.
- Function values fit anywhere a value fits: variables, parameters, return
  types, struct fields, arrays, and arena allocations:

```vanta
func negate(x: i32) -> i32:
    return 0 - x

func main() -> void:
    let ops: [func(i32) -> i32, 2] = [square, negate]
    for i in range(0, len(ops)):
        print_i32(ops[i](5))
```

- Indirect calls use the same syntax as direct calls — `f(x)`,
  `handlers[0](x)`, `op.run(x)`, even `pick()(x)`. Arguments are checked
  against the type of the value, so a wrong count or type is a compile error.
- A function-typed binding obeys the normal mutability rules: `let f = square`
  cannot be reassigned; `mut f: func(i32) -> i32 = square` can.

```vanta
struct Op:
    run: func(i32) -> i32

func pick() -> func(i32) -> i32:
    return square

func main() -> void:
    let op = Op(run: pick())
    print_i32(op.run(4))   # 16
```

Rejected on purpose, with a compile-time error:

- `len`, `print_fmt`, `write_fmt`, and `assert` are call syntax, not values:
  `cannot use builtin 'len' as a value`. Type names are not values either.
- `==` and `!=` on function values: `function values cannot be compared`.
- Function values in `const` initializers.
- Function types in `extern` signatures — C callbacks are not supported yet.
- Using a function whose return type is still being inferred (no `-> T`) as a
  value **before** its declaration is checked; add `-> T` or move the
  declaration earlier.

Under the hood each distinct function type becomes a `using FnPtrN = R(*)(...)`
alias in the generated C++, so the C++ spelling of a function type never
appears in Vanta code.

## Strings

```vanta
let greeting = "Hello, Vanta!"
print_str(greeting)              # prints with a trailing newline
print_str("tab:\there")          # \t
print_str("quote: \"hi\"")       # \"
print_bool(greeting == "Hello, Vanta!")   # true — compares contents
```

Supported escapes: `\t`, `\n`, `\"`, `\\`. `==` and `!=` compare string
contents via `strcmp`, not pointers. Ordering comparisons (`<`) on `str` are
rejected. `str` values may be `const`.

There is no string indexing, and indexing a `str` is not supported. Concatenation
(`str_concat`), length (`str_len`), and conversions are covered under
[Strings and the string pool](#strings-and-the-string-pool-v026); for building
many pieces into one string, see
[String building](#string-building-strbuilder-v0100).

## Vector and matrix types

| Expression | Result |
|---|---|
| `Vec2 + Vec2`, `Vec2 - Vec2`, `Vec2 * Vec2` | component-wise |
| `Vec2 * f32`, `f32 * Vec2`, `Vec2 / f32` | scalar scaling |
| `Vec3 + Vec3`, `Vec3 - Vec3`, `Vec3 * Vec3` | component-wise |
| `Vec3 * f32`, `f32 * Vec3`, `Vec3 / f32` | scalar scaling |
| `Vec2 == Vec2`, `Vec3 == Vec3`, and `!=` | element-wise, yields `bool` |
| `Quat * Quat` | quaternion composition |
| `Quat * Vec3`, `Vec3 * Quat` | rotate a vector |
| `Matrix4 * Vec3` | transform, using homogeneous `w = 1` |
| `Matrix4 * Matrix4` | compose transforms |

Methods:

| Method | Available on |
|---|---|
| `.dot(other)` | `Vec2`, `Vec3`, `Quat` |
| `.length()` | `Vec2`, `Vec3`, `Quat` |
| `.cross(other)` | `Vec3` |
| `.normalized()` | `Vec2`, `Vec3`, `Quat` |

`normalize` returns a zero vector (or identity quaternion) when the length is
zero, rather than dividing by zero.

Matrix4 is row-major and `Matrix4()` is the identity. Transform builders:

```vanta
let m = translation(10.0, 0.0, 0.0)
let s = scale(2.0)
let q = Quat(0.0, 0.0, 0.0, 1.0)
let r = from_quat(q)
```

## Built-in functions

| Builtin | Signature | Notes |
|---|---|---|
| `print_i32` | `(i32) -> void` | |
| `print_u32` | `(u32) -> void` | |
| `print_f32` | `(f32) -> void` | prints 6 decimal places |
| `print_f64` | `(f64) -> void` | prints 6 decimal places |
| `print_bool` | `(bool) -> void` | prints `true` / `false` |
| `print_str` | `(str) -> void` | prints with trailing newline |
| `write_i32` | `(i32) -> void` | as `print_i32`, but no newline |
| `write_u32` | `(u32) -> void` | no newline |
| `write_f32` | `(f32) -> void` | no newline |
| `write_f64` | `(f64) -> void` | no newline |
| `write_bool` | `(bool) -> void` | no newline |
| `write_str` | `(str) -> void` | no newline |
| `print_newline` | `() -> void` | writes `\n` |
| `sqrt_f32` | `(f32) -> f32` | |
| `sqrt_f64` | `(f64) -> f64` | |
| `sin_f32`, `cos_f32`, `tan_f32` | `(f32) -> f32` | radians |
| `sin_f64`, `cos_f64`, `tan_f64` | `(f64) -> f64` | radians |
| `atan2_f32` | `(f32, f32) -> f32` | `atan2(y, x)`; angle of `(x, y)`, radians |
| `atan2_f64` | `(f64, f64) -> f64` | `atan2(y, x)`; radians |
| `abs_i32` | `(i32) -> i32` | |
| `abs_f32` | `(f32) -> f32` | |
| `min_i32`, `max_i32` | `(i32, i32) -> i32` | |
| `min_f32`, `max_f32` | `(f32, f32) -> f32` | |
| `floor_f32`, `ceil_f32` | `(f32) -> f32` | |
| `i32_to_f32` | `(i32) -> f32` | |
| `f32_to_i32` | `(f32) -> i32` | truncates toward zero; `nan`/`inf` are undefined |
| `rand_f32` | `() -> f32` | xorshift32, in `[0, 1)` |
| `rand_seed` | `(i32) -> void` | selects the random stream |
| `arg_count` | `() -> i32` | includes the program name |
| `arg_str` | `(i32) -> str` | `""` when out of range |
| `str_len` | `(str) -> i32` | |
| `str_concat` | `(str, str) -> str` | allocates from the string pool |
| `str_to_i32` | `(str) -> i32` | leading number; `0` if there is none |
| `str_to_f32` | `(str) -> f32` | leading number; `0.0` if there is none |
| `to_str_i32` | `(i32) -> str` | allocates from the string pool |
| `to_str_f32` | `(f32) -> str` | allocates from the string pool |
| `to_str_bool` | `(bool) -> str` | no allocation |
| `str_pool_reset` | `() -> void` | reclaims the string pool |
| `file_exists` | `(str) -> bool` | `false` on any error |
| `file_write` | `(str, str) -> i32` | bytes written, or `-1` on failure |
| `file_read` | `(str) -> str` | reads into the string pool; `""` on any failure |
| `assert` | `(bool) -> void` | see [Assertions](#assertions-v012) |
| `enum_to_i32` | `(E) -> i32` | a member's number; `E` is any enum type |
| `ptr_is_null` | `(ptr<T>) -> bool` | `true` when the pointer is null; `T` may be `void` |
| `ptr_cast` | `ptr_cast::<T>(p) -> ptr<T>` | reinterprets the element type; `T` may not be a function type; see [pointer casts](#pointer-casts-ptr_castt-v0170) |
| `ptr_offset` | `(ptr<T>, i32) -> ptr<T>` | moves `n` elements; `T` may not be `void`; see [pointer offsets](#pointer-offsets-ptr_offsetp-n-v0180) |
| `ptr_null` | `ptr_null::<T>() -> ptr<T>` | the null pointer; `T` may be a function type (then it is a null callback); see [null pointers](#null-pointers-ptr_nullt-v0190) |

The random state is fixed at startup, so a program that never calls `rand_seed`
is **reproducible across runs** — useful for tests. Seeding with a different
value selects a different stream.

Trigonometry comes in `f32`/`f64` pairs; all angles are radians:

```vanta
print_f32(sin_f32(0.0))          # 0.000000
print_f32(cos_f32(0.0))          # 1.000000
print_f32(cos_f32(3.1415927))    # -1.000000  (pi as f32)
print_f32(atan2_f32(1.0, 1.0))   # 0.785398   (pi/4)
```

`atan2_f32(y, x)` is the angle of the vector `(x, y)` — the "heading toward a
point" operation — so a 45-degree unit vector comes back with its heading
intact. The functions are values like any other builtin:
`let g: func(f32) -> f32 = sin_f32` is fine.

## Formatted output (v0.2.6)

`print_fmt` writes a formatted line; `write_fmt` is the same without the
trailing newline.

```vanta
print_fmt("frame {}: centroid ({}, {})", 7, 1.5, 2.25)
# frame 7: centroid (1.500000, 2.250000)

write_fmt("{}", 42)      # no newline
print_newline()
```

Rules:

- The format argument must be a **string literal**. Placeholders are resolved at
  compile time, so a runtime-built string cannot be used as a format.
- `{}` consumes one argument, left to right. A mismatch between the number of
  placeholders and arguments is a compile error.
- Formattable types are `i32`, `u32`, `f32`, `f64`, `bool`, and `str`.
  Formatting a `Vec2` or a struct is a compile error.
- `{{` and `}}` produce literal braces. A lone `{` or `}` is a compile error.
- `%` in the literal is escaped for you, so `print_fmt("100% done")` is safe.
- `f32`/`f64` use six decimal places, matching `print_f32`/`print_f64`.

Because each placeholder is compiled to a typed printf conversion, there is no
way to pass the wrong type to a specifier — that class of `printf` bug cannot
happen here.

## Command-line arguments (v0.2.5)

```vanta
func main() -> void:
    if arg_count() > 1:
        let n = str_to_i32(arg_str(1))
        print_fmt("n={}", n)
```

`arg_count()` includes the program name at index 0. `arg_str(i)` returns `""`
for an out-of-range index rather than failing, so bounds need no checking.

Pass arguments through the driver with `python main.py run prog.vnt 3`.

There is no integer-argument builtin: read the string and convert with
`str_to_i32` / `str_to_f32`.

## Strings and the string pool (v0.2.6)

`str` is a `const char*`. Literals need no allocation, but anything built at
runtime must live somewhere, so `str_concat`, `to_str_i32`/`to_str_f32`, and
`file_read` allocate from a fixed **process-lifetime string pool** of 64 KiB.

```vanta
let label = str_concat("scale", to_str_i32(3))
print_fmt("{} has {} chars", label, str_len(label))
# scale3 has 6 chars
```

- The pool is bump-allocated and **never freed**. `str_pool_reset()` reclaims
  all of it, but doing so invalidates every string previously built from it.
- Exhausting the pool is a hard error: the program prints
  `vanta: string pool exhausted (65536 bytes); call str_pool_reset()` and exits
  with code 1. It does not silently corrupt memory.
- `to_str_bool` returns a literal and allocates nothing.
- Building incrementally? `str_concat` in a loop allocates an intermediate
  string per iteration. The arena-backed
  [`StrBuilder`](#string-building-strbuilder-v0100) appends into one growing
  buffer instead and never touches the pool.

There is no string indexing and no per-value ownership.

## Extern declarations (v0.3.0)

`extern` declares functions implemented in C and linked into the program:

```vanta
extern "demo" {
    func demo_clamp(v: i32, lo: i32, hi: i32) -> i32
    func demo_cube(x: f32) -> f32
}
```

- The block lists signatures only — no bodies. A `func` without `-> type`
  returns `void`.
- The string names the library for the reader. Linking is decided on the
  command line, not by the string: `--lib-dir` adds a library search path and
  `--link` adds a library (both repeatable, on `build` and `run`).
- Extern functions are called like any other function and type-checked the
  same way. The generated C++ declares them in an `extern "C" {}` block outside
  `namespace vanta_user`, and calls keep the original (unmangled) name.
- Stick to C-compatible types: `i8`, `u8`, `i16`, `u16` (v0.17.0), `i32`,
  `u32`, `f32`, `f64`, `bool`, `str` (`const char*`), `ptr<T>`, enum types
  (v0.17.0), and `func(...)` parameters (callbacks, below). Narrow types map
  to `int8_t`/`uint8_t`/`int16_t`/`uint16_t` in the generated signature, so
  the C side must declare the matching width (`Uint8` channels, for
  instance); a wider value passed into one keeps its low byte, with
  out-of-range *literals* caught at compile time. Opaque C handles are
  `ptr<void>`; a typed `ptr<T>` (e.g. `ptr<i32>`) is for C pointers you
  intend to index, and it widens to `ptr<void>` implicitly where that is
  declared (type it again later with `ptr_cast::<T>` — see
  [Pointer casts](#pointer-casts-ptr_castt-v0170)). Vanta struct types can
  appear in a signature — the generated code namespace-qualifies and
  forward-declares them — if the C side understands the layout, but a plain
  C library cannot. An enum type is emitted as its `enum class` with a fixed
  `int32_t` underlying type, forward-declared ahead of the `extern "C"`
  block together with the struct tags, so the C side may declare the
  parameter/result as `int32_t` or a matching C enum.
- A name declared twice — in one block, across blocks, or colliding with a
  Vanta function, builtin, or type — is a compile error.

A parameter typed `func(...)` is a C function pointer, so C can call back
into Vanta code (v0.16.0). Pass any function value — a Vanta function or
another `extern` — where the callback is wanted. The generated C++ spells
the parameter inline (`void(*v_cb)()`), and the C side must declare the
matching function-pointer type. Taking `atexit` from the C standard library:

```vanta
extern "C" {
    func atexit(cb: func()) -> i32
}

func farewell():
    print_str("goodbye from the callback")

func main() -> void:
    atexit(farewell)
    print_str("main is done")
```

```
main is done
goodbye from the callback
```

`atexit` runs its callbacks as the program exits, most recently registered
first. An `extern` cannot *return* a function type yet; wrap such a C
function in a shim that calls the callback instead.

```powershell
python main.py run examples/extern_demo.vnt --lib-dir build --link demo
```

`examples/extern_demo.vnt` and `examples/extern_demo_lib.c` are a complete,
buildable example. `examples/callbacks.vnt` and `examples/callbacks_lib.c`
are a second one: a callback that C calls twice, and a visitor receiving a
`ptr<i32>` user-data pointer. `examples/enums_extern.vnt` with
`examples/enums_extern_lib.c` is a third: an enum crossing into C and back,
and `examples/narrow_ints.vnt` with `examples/narrow_ints_lib.c` shows
exact-width parameters plus a C mirror struct reading a Vanta struct's
bytes.

## SDL2 and a window (v0.12.0)

SDL2 is the worked example of `extern`. Eight programs ship:
`examples/sdl_window.vnt` opens a window and clears it to a colour;
`examples/sdl_text.vnt` draws text (SDL_ttf); `examples/sdl_texture.vnt`
loads image files as textures and proves its draws by reading the pixels
back (SDL2_image); `examples/sdl_audio.vnt` and `examples/sdl_audio_cb.vnt`
make sound (a queued tone, and a Vanta callback on SDL's audio thread);
`examples/sdl_sound.vnt` loads a WAV file; `examples/sdl_gamepad.vnt` polls
a game controller; and `examples/sdl_game.vnt` is the first playable Vanta
game — move the paddle with Left/Right (or A/D) to catch falling coins; Esc
or the close button quits. Every one of them talks to C only through
`extern` declarations: no SDL headers are involved at compile time, only the
library at link time:

```powershell
python main.py run examples/sdl_game.vnt --lib-dir C:/msys64/mingw64/lib --link SDL2
```

A complete window in one program — event loop, one drawn rectangle, cleanup:

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
    func SDL_RenderFillRect(renderer: ptr<void>, rect: ptr<i32>) -> i32
    func SDL_RenderPresent(renderer: ptr<void>) -> void
    func SDL_PollEvent(event: ptr<i32>) -> i32
}

const EV_QUIT: i32 = 256
const EV_KEYDOWN: i32 = 768
const KEY_ESCAPE: i32 = 27

func main() -> void:
    if SDL_Init(32) != 0:                 # SDL_INIT_VIDEO
        print_str("SDL_Init failed")
        return
    let window = SDL_CreateWindow("Vanta", 100, 100, 480, 320, 4)
    if ptr_is_null(window):
        print_str("SDL_CreateWindow failed")
        SDL_Quit()
        return
    mut renderer = SDL_CreateRenderer(window, -1, 6)   # accelerated + vsync
    if ptr_is_null(renderer):
        renderer = SDL_CreateRenderer(window, -1, 0)   # any renderer (headless)
    if ptr_is_null(renderer):
        print_str("SDL_CreateRenderer failed")
        SDL_DestroyWindow(window)
        SDL_Quit()
        return

    let arena = Arena(256)
    let ev = arena.alloc::<i32>(16)        # room for one SDL_Event
    let rect = arena.alloc::<i32>(4)       # an SDL_Rect: x, y, w, h
    mut running = true
    mut frames = 0
    while running:
        while SDL_PollEvent(ev) == 1:
            let t = ev[0]
            if t == EV_QUIT:
                running = false
            elif t == EV_KEYDOWN and ev[5] == KEY_ESCAPE:
                running = false
        SDL_SetRenderDrawColor(renderer, 30, 90, 160, 255)
        SDL_RenderClear(renderer)
        rect[0] = 140                       # x
        rect[1] = 148                       # y
        rect[2] = 200                       # w
        rect[3] = 24                        # h
        SDL_SetRenderDrawColor(renderer, 240, 200, 60, 255)
        SDL_RenderFillRect(renderer, rect)
        SDL_RenderPresent(renderer)
        frames += 1
        if frames >= 3:                     # short demo; the shipped examples
            running = false                 # take the limit from the command line

    SDL_DestroyRenderer(renderer)
    SDL_DestroyWindow(window)
    SDL_Quit()
    print_fmt("frames {}", frames)
```

```
frames 3
```

What the moving parts mean:

- **Flags are `u32` numbers.** `SDL_INIT_VIDEO` is 32; `SDL_WINDOW_SHOWN`
  is 4; `SDL_RENDERER_ACCELERATED | SDL_RENDERER_PRESENTVSYNC` is 6. When 6
  fails — and it does under SDL's "dummy" video driver — 0 asks for any
  renderer, which is the software one.
- **Narrow C parameters are declared `i32`.** `SDL_SetRenderDrawColor` takes
  `Uint8` channels in C; the callee reads the low byte, so 255 works.
- **`SDL_Rect*` is a `ptr<i32>`.** A rectangle is four `i32`s (x, y, w, h),
  so an `arena.alloc::<i32>(4)` doubles as one — the same trick applies to
  any simple C struct, as long as you get the layout right.
- **An `SDL_Event` is read as `i32`s.** It is 56 bytes on 64-bit builds and
  starts with the event type; a key event's key symbol sits at byte 20. The
  buffer here holds 64 bytes of `i32`s: `ev[0]` is the type (256 quit, 768
  key down, 769 key up) and `ev[5]` is the key symbol (Esc 27, Left
  1073741904, Right 1073741903). `SDL_PollEvent` returns 1 while events
  remain.
- **`ptr_is_null` before trusting a handle**, and the `mut` on `renderer` is
  what lets the second creation attempt overwrite the first.

The windowed programs take an optional frame-limit argument, so a smoke run
needs no display at all — this is how the test suite exercises them (CI
installs SDL2 on Linux, macOS, and Windows and runs the same smoke tests):

```powershell
$env:SDL_VIDEODRIVER = "dummy"
python main.py run examples/sdl_window.vnt 120 --lib-dir C:/msys64/mingw64/lib --link SDL2
```

Files follow the same recipe: `examples/sdl_texture.vnt` decodes PNG and BMP
files into textures with `IMG_LoadTexture`, draws them tinted, flipped, and
rotated, and checks each draw by reading pixels back from a forced software
renderer — the readbacks are exact on every machine — while
`examples/sdl_sound.vnt` loads `examples/assets/blip.wav` with
`SDL_LoadWAV_RW` (the `SDL_RWFromFile` that `SDL_LoadWAV` wraps), queues it,
and waits for the device to drain. Sound has the same pair of examples:
`examples/sdl_audio.vnt` queues a generated tone on the default device, and
`examples/sdl_audio_cb.vnt` puts a Vanta function in the
`SDL_AudioSpec.callback` field for SDL's audio thread to run. All of these
are pure `extern` programs; the texture one links SDL2_image, the rest
nothing but SDL2. `examples/pong.vnt` and `examples/breakout.vnt`, the other
two playable games, are built on the
[game kit](#the-game-kit-v0140) documented below.

## The game kit (v0.14.0)

`examples/gamekit/` is nine reusable modules over the SDL2, SDL_ttf, and
SDL2_image calls above — ordinary `.vnt` files, imported like anything else:

| Module | Provides |
|---|---|
| `sdl.vnt` | SDL2 `extern` declarations, the `EV_*` / `KEY_*` / `SDL_FLIP_*` constants, `Screen`, `screen_open` / `screen_ok` / `screen_close` |
| `input.vnt` | `ev_is_quit`, `ev_is_keydown`, `ev_is_keyup`, `ev_key` |
| `gamepad.vnt` | SDL2 controllers: `Pad`, `pad_open` / `pad_ok` / `pad_close`, `pad_attached`, `pad_button`, `pad_axis`, the `PAD_BUTTON_*` / `PAD_AXIS_*` constants |
| `gfx.vnt` | `gfx_clear`, `gfx_fill_rect`, `gfx_stroke_rect`, `gfx_present` |
| `image.vnt` | SDL2_image: `Tex`, `tex_load` / `tex_ok` / `tex_free`, `tex_tint`, `tex_alpha`, `tex_draw` / `tex_draw_src` / `tex_draw_ex` |
| `anim.vnt` | Sprite-sheet animation: `Anim`, `anim_new` / `anim_tick` / `anim_frame` / `anim_draw` |
| `text.vnt` | SDL_ttf: `Font`, `font_open` / `font_ok` / `font_close`, `text_measure`, `text_draw`; `TextSprite`, `text_sprite` / `text_sprite_ok` / `text_sprite_draw` / `text_sprite_free`; `text_quit` |
| `audio.vnt` | SDL2 audio: `Audio`, `audio_open` / `audio_ok` / `audio_close`, `audio_play_tone`, `audio_pending`, `audio_wait`; `Sound`, `sound_load` / `sound_ok` / `sound_play` / `sound_free` |
| `rng.vnt` | `rand_int`, `rand_range_f32`, `rand_sign` |

Three idioms fall out of the language rules:

- **Prefixes, not namespaces.** Vanta has one flat namespace, so every kit
  name is prefixed by its module (`screen_*`, `ev_*`, `pad_*`, `gfx_*`,
  `tex_*`, `anim_*`, `font_*`, `text_*`, `audio_*`, `sound_*`, `rand_*`);
  several modules — and the game's own names — coexist.
- **Failures come back the way C reports them.** There is still no nil
  literal — `ptr_null::<T>()` (v0.19.0) is the explicit way to build one —
  so `screen_open` returns a `Screen` carrying whatever the C calls
  returned: null handles when anything failed, and `screen_ok` is the test
  to run once before the game loop. `font_open` and `audio_open` return
  their handles the same way, with `font_ok` and `audio_ok`.
- **One shared scratch rect.** SDL wants a four-`i32` `SDL_Rect*`; allocate
  it once with `arena.alloc::<i32>(4)` and pass it to every `gfx_*` call.

```vanta
import "gamekit/sdl.vnt"
import "gamekit/rng.vnt"

func main() -> void:
    let screen = screen_open("Vanta", 320, 240)
    print_bool(screen_ok(screen))     # true on any working video driver
    print_i32(rand_int(1, 6))         # the RNG stream is fixed at startup,
    print_i32(rand_int(1, 6))         # so these values are reproducible
    screen_close(screen)
```

```
true
4
3
```

`text.vnt` follows the same shape: `text_draw(screen, font, x, y, text,
scratch, r, g, b)` renders one string with its top-left corner at `(x, y)`.
The scratch block is ten `i32` slots — width, height, a source rect, a
destination rect — so one `arena.alloc::<i32>(10)` covers `text_measure`
and `text_draw` alike; `text_measure` fills `scratch[0]` (width) and
`scratch[1]` (height), which is how text gets aligned. The kit ships a CC0
font for examples, docs, and tests (`fonts/tom-thumb.ttf`), and `text_quit`
is the shutdown call, after closing fonts. `text_sprite` is the render-once
path: it renders one string into a `TextSprite` — a texture plus the
rendered size, with `text_sprite_ok` as the test — `text_sprite_draw` blits
it with no TTF call, and `text_sprite_free` destroys the texture. Right for
text that redraws every frame; `text_draw` stays right for text that
changes, and `examples/text_bench.vnt` measures both:

```vanta
import "gamekit/sdl.vnt"
import "gamekit/text.vnt"

func main() -> void:
    let screen = screen_open("Vanta", 320, 240)
    let font = font_open("examples/gamekit/fonts/tom-thumb.ttf", 32)
    print_bool(screen_ok(screen) and font_ok(font))   # true on any working driver
    let label = text_sprite(screen, font, "PAUSED", 240, 220, 120)
    print_bool(text_sprite_ok(label))
    text_sprite_draw(screen, label, 24, 24)
    text_sprite_free(label)
    font_close(font)
    text_quit()
    screen_close(screen)
```

```
true
true
```

`image.vnt` next: `tex_load` hands a path to SDL_image and gets a `Tex`
back — a handle plus the decoded size — with `tex_ok` as the C-style test.
Drawing comes in three shapes: `tex_draw` (whole texture, natural size),
`tex_draw_src` (one rectangle of it — a sprite-sheet frame), and
`tex_draw_ex` (rotated by an `f64` angle in degrees and/or flipped with the
`SDL_FLIP_*` constants); `tex_tint` and `tex_alpha` multiply a colour and an
opacity into every later draw of that texture. Unlike the `gfx_*` helpers
none of them take a scratch rect — SDL only needs the rectangles during the
call, so the kit builds them on a transient arena. Importing the module
means linking SDL2_image:

```vanta
import "gamekit/sdl.vnt"
import "gamekit/image.vnt"

func main() -> void:
    let screen = screen_open("Vanta", 320, 240)
    let ball = tex_load(screen, "examples/assets/ball.png")
    print_bool(screen_ok(screen) and tex_ok(ball))   # true on any working driver
    print_fmt("{}x{}", ball.w, ball.h)               # the decoded size
    tex_tint(ball, 240, 96, 96)
    tex_draw(screen, ball, 100, 100)
    tex_free(ball)
    screen_close(screen)
```

```
true
10x10
```

`anim.vnt` next: a sprite sheet plays back as a strip of equal frames.
`anim_new(count, fw, fh, fps)` describes the strip, `anim_tick` advances the
clock by the time the game hands it and returns the updated clock — structs
are values, so `anim = anim_tick(anim, dt)` is the idiom — `anim_frame`
reads the current frame, and `anim_draw` blits it through `tex_draw_src`.
The frame wraps, so the animation loops; a dead `Tex` or an empty strip
(zero frames) draws nothing; and nothing here reads a wall clock:

```vanta
import "gamekit/sdl.vnt"
import "gamekit/image.vnt"
import "gamekit/anim.vnt"

func main() -> void:
    let screen = screen_open("Vanta", 320, 240)
    let spin = tex_load(screen, "examples/assets/ball_spin.png")
    print_bool(screen_ok(screen) and tex_ok(spin))   # true on any working driver
    print_fmt("{}x{}", spin.w, spin.h)
    mut anim = anim_new(4, 10, 10, 8.0)              # 4 frames, 10x10, 8 fps
    for i in range(0, 4):
        anim = anim_tick(anim, 0.125)                # 1/8 s: exactly one frame
        anim_draw(screen, spin, anim, 40 + i * 14, 40)
        print_i32(anim_frame(anim))
    tex_free(spin)
    screen_close(screen)
```

```
true
40x10
1
2
3
0
```

`audio.vnt` next: tones need no file — the caller owns the sample buffer and
`audio_play_tone` fills it with a square wave and queues it on the device
(WAV files load through `sound_load`, below). The queue API wants a *null*
callback, built with `ptr_null::<func(...)>()`, and `SDL_AudioSpec` itself is
a Vanta struct whose callback field keeps its C function-pointer type — the
same struct drives callback mode when a program puts a real function there
(`examples/sdl_audio_cb.vnt` runs a Vanta function on SDL's audio thread).
`audio_play_tone` returns the samples queued; `audio_pending` asks how much
is still playing, and `audio_wait` blocks until the queue drains:

```vanta
import "gamekit/sdl.vnt"
import "gamekit/audio.vnt"

func main() -> void:
    let audio = audio_open()
    print_bool(audio_ok(audio))       # true on any working audio driver
    let arena = Arena(32768)
    let buf = arena.alloc::<i16>(11025)                # 250 ms of samples
    print_i32(audio_play_tone(audio, 880, 100, buf, 11025))
    audio_wait(audio)
    audio_close(audio)
```

```
true
4410
```

Sound *files* next: `sound_load(a, path)` reads a WAV — 16-bit PCM at the
device's 44.1 kHz, mono or stereo — into a buffer SDL allocates; the game
holds the `Sound` and hands the buffer back with `sound_free`, and
`sound_play` queues it after whatever is already playing. A stereo file is
folded to mono in place at load, so its byte count halves; any other rate,
sample format, or channel count loads as a dead `Sound` — `sound_ok` false,
and every `sound_*` call on it is a no-op, exactly like a dead `Audio`.
Paths are opened by C, relative to the process working directory:

```vanta
import "gamekit/sdl.vnt"
import "gamekit/audio.vnt"

func main() -> void:
    let audio = audio_open()
    let snd = sound_load(audio, "examples/assets/blip.wav")
    print_bool(audio_ok(audio) and sound_ok(snd))    # true on any working driver
    print_fmt("{} bytes", snd.len)                   # 5292 = 60 ms at 44.1 kHz
    sound_play(audio, snd)
    audio_wait(audio)
    sound_free(snd)
    audio_close(audio)
```

```
true
5292 bytes
```

`gamepad.vnt` next: `pad_open` takes SDL's joystick index (0 is the first
controller) and starts SDL's gamecontroller subsystem; a missing or
out-of-range controller comes back dead, so `pad_ok` is the test and every
other call is a guarded no-op — the same shape as a dead `Screen`, `Tex`, or
`Sound`. `pad_button` polls the current button state and `pad_axis` returns
SDL's raw `Sint16` (sticks -32768..32767 with 0 at rest, triggers
0..32767); the `PAD_BUTTON_*` / `PAD_AXIS_*` constants name the standard
controls. `pad_close` closes the device and stops the subsystem, before
`screen_close`'s `SDL_Quit`:

```vanta
import "gamekit/sdl.vnt"
import "gamekit/gamepad.vnt"

func main() -> void:
    let pad = pad_open(9999)                       # an index no machine has
    print_bool(pad_ok(pad))                        # dead handle
    print_bool(pad_button(pad, PAD_BUTTON_A))      # guarded: false
    print_i32(pad_axis(pad, PAD_AXIS_LEFT_X))      # guarded: 0
    pad_close(pad)
```

```
false
false
0
```

Kit programs build like any other SDL2 program; `text.vnt` links SDL_ttf as
well, `image.vnt` links SDL2_image (`audio.vnt` and `gamepad.vnt` need
nothing extra — they use SDL2's core library):

```powershell
python main.py run examples/pong.vnt --lib-dir C:/msys64/mingw64/lib --link SDL2_ttf --link SDL2
python main.py run examples/breakout.vnt --lib-dir C:/msys64/mingw64/lib --link SDL2_image --link SDL2_ttf --link SDL2
```

`examples/pong.vnt` is the worked example for the first game: it imports six
of the modules (all but `image.vnt` and `gamepad.vnt`), serves with `match`,
draws its score with `text_draw`, beeps with `audio_play_tone`, and stays
testable headless — a frame-limit argument plus `SDL_VIDEODRIVER=dummy` and
`SDL_AUDIODRIVER=dummy` is how the test suite runs it in CI.
`examples/breakout.vnt` adds the satellite modules on top: a tinted sprite
wall out of one white brick texture, WAV hits, and a deterministic
full-clear run the suite freezes the same way.

## File I/O (v0.3.1)

Three builtins read and write files as raw bytes:

```vanta
let path = arg_str(1)
if file_exists(path):
    let contents = file_read(path)
    print_fmt("{} bytes", str_len(contents))
    file_write(str_concat(path, ".copy"), contents)
```

- `file_exists(path) -> bool` — `true` when the file can be opened for
  reading; `false` on any error, including permission problems.
- `file_write(path, data) -> i32` — creates or truncates `path` and writes the
  bytes of `data`; returns the byte count, or `-1` if the file cannot be
  created or written.
- `file_read(path) -> str` — reads the whole file into the string pool, so the
  result stays valid until `str_pool_reset()`; returns `""` on any failure. A
  file too large for the pool is a hard error:
  `vanta: file '<path>' (<n> bytes) does not fit the 65536-byte string pool`,
  exit code 1 — nothing is truncated silently.

An empty file and a missing file both read as `""`; use `file_exists` when the
difference matters. Reads and writes are byte-exact (`"rb"`/`"wb"`), but Vanta
strings are NUL-terminated, so a file containing NUL bytes is cut short at the
first NUL when its contents are passed to string operations.

`examples/file_io.vnt` reads a file named on the command line and writes a copy
to `<path>.copy`.

## Imports (v0.4.0)

`import` merges another file's declarations into the program:

```vanta
import "imports_demo_lib.vnt"

func main() -> void:
    let sp = sprite_at(3, 2)
    print_i32(sprite_pixel(sp))
```

- The path is a string literal resolved **relative to the file containing the
  import**. There is no search path, and no implicit extension — write
  `import "lib/math.vnt"` in full.
- Vanta has a single flat namespace. An import makes the other file's
  functions, structs, constants, and `extern` declarations available as if
  they were written in the importing file; they are used by their bare names.
  A name declared twice across any files is a compile error.
- Imports are transitive, and each file is loaded once no matter how many
  times it is imported — importing a file twice, or from two files, still
  adds its declarations exactly once.
- Import cycles are a compile error, reported with the chain:
  `a.vnt: import cycle: a.vnt -> b.vnt -> a.vnt`.
- A missing import is a compile error at the import statement:
  `main.vnt:1:1: cannot open import 'lib/nope.vnt'`.
- Errors inside an imported file name that file, not the entry file.
- Imports may appear anywhere among top-level declarations; the convention is
  at the top of the file.

`examples/imports_demo.vnt` and `examples/imports_demo_lib.vnt` are a complete
example.

There is no per-module namespacing, no visibility control (`pub`), and no
package manager: an import is a path on disk.

## Operators

Precedence, loosest to tightest (verified against the parser):

1. `or`
2. `and`
3. `not` (unary)
4. `==`, `!=`, `<`, `<=`, `>`, `>=`
5. `+`, `-` (left-associative)
6. `*`, `/`, `%` (left-associative)
7. unary `-`
8. `.` field access, `::` type arguments, `()` calls, `[]` indexing

Assignment: `=`, and compound `+=`, `-=`, `*=`, `/=`. Integer `/` truncates
toward zero; `%` is the remainder.

## Diagnostics

All source-level errors carry `file:line:col`:

```
examples/boids.vnt:3:5: argument: cannot assign i32 to u32
```

Use `python main.py check <file>` to type-check without invoking a C++ compiler.
When C++ compilation fails during `build`, the generated source is saved to
`build/vanta_failed.cpp`.
