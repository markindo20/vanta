# Vanta Language Reference (v0.71.0)

This is the reference for the language as implemented at tag `v0.33.0`. Every
claim here was checked against the compiler; where behaviour surprised us, the
surprise is called out explicitly.

## Installing and running

```powershell
pipx install vanta-lang       # or: python -m pip install vanta-lang
vanta --version
vanta doctor                  # compiler, runtime header, and SDL2 check
vanta check hello.vnt         # type-check only (fast, no C++)
vanta hello.vnt               # shorthand for `vanta run hello.vnt`
vanta build hello.vnt --release
```

A wheel install carries the C++ runtime header and the game kit, so only a
C++17 compiler is needed for non-game programs; the SDL2 examples and games
also need SDL2, SDL_ttf, and SDL2_image. From a checkout, `python main.py`
takes the same commands, and `python -m pip install -e .` installs an editable
`vanta`.

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
| `str` | immutable, reference-counted string (see [Strings](#strings)) |
| `ptr<T>` | raw pointer: locals, parameters, and returns; `p.at(i, size)` is checked, `p[i]` is not; `ptr<void>` is the untyped C-style handle (see [Pointers and the Arena](#pointers-and-the-arena)) |
| `[T, N]` | fixed-size array of `N` elements; `T` may itself be an array; checked access with `xs.at(i)` (see [Checked indexing](#checked-indexing-at-v070)) |
| `List<T>` | growable list whose storage lives in an `Arena`; `push`/`pop`/`len`/`at`/`xs[i]` (see [Dynamic lists](#dynamic-lists-listt-v090)) |
| `func(T1, ...) -> R` | function value; arrow omitted means `-> void` (see [Function values](#function-values-v060)) |
| `Vec2`, `Vec3`, `Quat`, `Matrix4` | built-in math types |
| `Arena` | stack-scoped allocator (see [Arena](#pointers-and-the-arena)) |
| `StrBuilder` | arena-backed string builder; append pieces, then `to_str()` (see [String building](#string-building-strbuilder-v0100)) |
| `Name` (enum) | named members with optional explicit values and payloads; `Name.Member`, `Name.Member(...)`, `==`/`!=`, `enum_to_i32` (see [Enums](#enums-v0110)) |

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

A field whose type has no equality — `ptr<T>`, `List<T>`, or
`Quat`/`Matrix4` — makes comparing the whole struct a compile error that
names the field path:

```
error: cannot compare struct 'Sprite' with '==': field 'pos.p' (ptr<i32>) has no equality
```

The check is recursive, so array fields (`cells[N]`) and nested structs are
inspected down to the leaf. A function-valued field compares by address, like
any function value.

## Enums (v0.11.0)

`enum` declares a fixed set of named members, numbered from `0` in
declaration order (explicit values and payloads arrived in v0.29.0). A member
is written `Name.Member`, and the enum is an ordinary type — variables, struct
fields, parameters, returns, arrays, `List<T>`, function values, and imported
modules all accept it:

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

Members can also name an explicit value and carry associated data:

```vanta
enum Level:
    Low = 1
    Medium
    High = 10

struct Point:
    x: i32
    y: i32

enum Shape:
    Empty
    Circle(Point, f32)

func radius(shape: Shape) -> f32:
    match shape:
        Shape.Empty:
            return 0.0
        Shape.Circle(center, r):
            return r + i32_to_f32(center.x)

func main() -> void:
    print_i32(enum_to_i32(Level.High))      # 10
    let p = Point(x: 2, y: 3)
    let s = Shape.Circle(p, 4.0)
    print_f32(radius(s))                    # 6.000000
    print_bool(s == Shape.Circle(p, 4.0))   # true
```

```
10
6.000000
true
```

- Members are numbered `0`, `1`, `2`, ... in declaration order. `Member = n`
  sets an explicit value; following members without a value continue from
  `n + 1`. Values are integer literals (optionally negative), must fit
  `i32`, and must be unique within the enum.
- `enum_to_i32(v)` returns a member's value — the bridge to printing and
  arithmetic. For a payload enum it returns the tag value.
- `==` and `!=` compare values of the same enum. For a payload enum they
  compare the tag and the active payload, so every payload type must support
  `==` under the same rules as a struct field (`ptr<T>` and `List<T>` do not).
  Ordering comparisons (`<`, `<=`, `>`, `>=`) are compile errors, as are
  compares between two different enums or between an enum and a number.
- A member written `Name.Member` with no payload is a value. A member with a
  payload is constructed as `Name.Member(value, ...)`; `Name.Member()` is
  also accepted for a member with no payload. Using a payload member without
  its values is an error.
- Payload types must be declared before the enum, and each must be copyable
  and non-void. Payloads can be primitives, `str`, arrays, structs, enums,
  pointers, function values, and `List<T>`. A payload cannot contain
  `Arena`, directly or inside a struct or array; recursive payloads are not
  supported because the type must be declared first.
- Payload enums have no C representation: `extern` signatures cannot take or
  return them, even behind a pointer. Plain enums remain fixed-`int32_t`
  C++ `enum class` values and may cross the C boundary (v0.17.0); explicit
  values are preserved.
- An enum cannot be constructed as `State(1)`. Enum values have no fields
  either — `s.Menu` is rejected with a hint to write `State.Menu`. Payload
  values are reachable only through `match`.
- Type names share one namespace: an enum cannot reuse the name of a struct,
  function, or constant. `List` and `FnPtrN` are reserved.
- `match` (v0.13.0, below) switches on enum values; when every member has
  an arm the checker proves it and no `else` is needed.
- `enum` is a reserved keyword.

## Generic enums, structs, and functions (v0.31.0, v0.80.0, v0.84.0)

A generic declaration takes type parameters after its name. The parameters
are in scope in that declaration's payload, field, parameter, or return
types and are replaced by concrete types when the declaration is used.
Enums have been generic since v0.31.0, structs since v0.80.0, and
functions since v0.84.0.

```vanta
enum Option<T>:
    None
    Some(T)

enum Result<T, E>:
    Ok(T)
    Err(E)

struct ParseError:
    code: i32

func parse(n: i32) -> Result<i32, ParseError>:
    if n < 0:
        return Result.Err(ParseError(code: 400))
    return Result.Ok(n)

func main() -> void:
    let absent: Option<i32> = Option.None
    let present = Option.Some(7)
    match present:
        Option.None:
            print_i32(0)
        Option.Some(value):
            print_i32(value)
    match parse(-1):
        Result.Ok(value):
            print_i32(value)
        Result.Err(error):
            print_i32(error.code)
```

```
7
400
```

- Type arguments are written in angle brackets: `Option<i32>`,
  `Result<i32, str>`, and nested forms such as `Option<Option<i32>>`.
  Every argument must be a complete, non-void type. `Option<i32>` and
  `Option<str>` are different types and cannot be assigned to each other.
- Constructors infer type parameters from the expected type first, then from
  their values: `let value: Option<i32> = Option.None`,
  `return Result.Ok(n)` in a function returning `Result<i32, ParseError>`, a
  struct field, a function argument, a list element, an array element, an
  assignment, and either side of `==`/`!=` all supply an expected type.
  `Option.Some(5)` with no annotation infers `Option<i32>`.
- A bare `Option.None` needs an expected type. If none is available, use an
  annotation or the explicit constructor form `Option.None::<i32>()`.
  `Result.Ok` and `Result.Err` similarly need both parameters from context or
  explicit arguments such as `Result.Err::<i32, str>("missing")`. The error
  for a missing parameter names it and shows the explicit form.
- Generic enum instances are monomorphized in generated C++. Each distinct
  set of type arguments gets its own concrete enum layout and constructor
  functions. Diagnostics and matches continue to use the source spelling,
  `Option<i32>`; generated internal names are not part of the source language.
- `match` still checks exhaustiveness over the enum's members. Patterns name
  the source family, `Option.Some(value)`, not a concrete internal instance.
  Payload bindings receive the instantiated payload types.
- Type arguments obey visibility: a public declaration cannot expose a
  private type through `Option<Hidden>`, whether written explicitly or inferred.
  Generic payloads must still be copyable and non-void after substitution, so
  `Option<Arena>` is rejected when a member stores `T`. A recursive
  instantiation such as `enum Seq<T>: Cons(T, Seq<T>)` is rejected with a
  hint to store the nested value behind a pointer.
- `import "std/option.vnt"` and `import "std/result.vnt"` load the shipped
  library definitions. They are ordinary module files: import them
  unqualified to use `Option`/`Result`, or with an alias
  (`import "std/option.vnt" as opt`) to use `opt.Option`. A sibling
  `std/option.vnt` next to the importing file wins over the installed copy.
  The library is library-shaped: Option and Result are generic enum
  declarations, not compiler-special-cased types.

### Generic structs (v0.80.0)

A struct declaration takes type parameters the same way an enum does:

```vanta
struct Pair<T, U>:
    left: T
    right: U

struct Node<T>:
    value: T
    next: ptr<Node<T>>

func main() -> void:
    let p: Pair<i32, str> = Pair(left: 7, right: "hi")
    let q = Pair::<i32, i32>(left: 1, right: 2)
    let n: Node<i32> = Node(value: 9, next: ptr_null::<Node<i32>>())
    print_i32(p.left)
    print_i32(q.left + q.right)
    print_i32(n.value)
```

```
7
3
9
```

- Fields use the parameters as ordinary types, including nested
  applications such as `List<T>`, `[T, 4]`, `ptr<T>`, and `Option<T>`.
- Construction keeps the usual named-argument form. The expected type
  supplies the parameters when it is a concrete `Pair<...>`; otherwise the
  field values are inferred, with integer and float literals defaulting to
  `i32`/`f32`. `Pair::<i32, str>(...)` always works explicitly.
- Each distinct set of arguments is a distinct type, monomorphized in the
  generated C++. `Pair<i32, str>` cannot be assigned to `Pair<str, i32>`.
- A struct may refer to itself behind a pointer, `next: ptr<Node<T>>`,
  because the instance is registered before its fields are resolved. A
  by-value self reference is left to the C++ compiler to reject.
- Type parameter names may not shadow primitives, `List`, or `ptr`, and a
  generic struct name may not be used without arguments.
- Generic functions are not part of this slice; they are the next step on
  the language track.

### Generic functions (v0.84.0)

A function declaration takes type parameters between its name and the
parameter list. The parameters are in scope in its parameter and return
types and may be referenced in the body.

```vanta
func identity<T>(x: T) -> T:
    return x

func swap<T, U>(a: T, b: U) -> U:
    return b

func main() -> void:
    let a = identity::<i32>(5)
    let b = identity(2.5)
    print_i32(a)
    print_f32(b)
    print_i32(swap::<str, i32>("hi", 42))
```

```
5
2.500000
42
```

- Type arguments follow the same rules as generic enums and structs:
  expected type first, explicit `::<...>` always works, inference from
  the arguments otherwise, with integer and float literals defaulting to
  `i32` / `f32`.
- Each distinct set of arguments monomorphizes one C++ function under an
  internal name such as `identity__g0`; diagnostics keep the source
  spelling `identity<i32>`.
- Generic function values (passing `identity` as a parameter, taking its
  address, returning it) are not yet supported and stay on the backlog.

## Match (v0.13.0)

`match` chooses a branch by comparing an enum value against member
patterns. Arms are written `Enum.Member:` or, for a payload member,
`Enum.Member(binding, ...):` — several patterns per arm are separated by
commas — and run top to bottom; the first match wins. `else:` is the
fallback branch:

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
- A payload member binds its values by position: `Shape.Circle(center, r):`.
  The number of bindings must match the payload exactly; `_` discards a
  value. A member with no payload may be written `State.Menu` or
  `State.Menu()`. Binding a payload member without parentheses is an error.
- An arm with several comma-separated patterns cannot bind names; use one
  pattern per arm when a payload value is needed.
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
- Pointers carry no length, so their checked form takes the accessible
  element count: `p.at(i, size)`. See
  [Checked pointer access](#checked-pointer-access-pati-size-v0250).
- `p[i]` remains the unchecked escape hatch for pointers.
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

`Arena(bytes, "name")` maps a **named** segment instead: the OS keeps the
bytes alive while any process holds the mapping, so a second process that
asks for the same name sees the same memory. The name form is how state
survives a rebuilt program; see
[state-preserving hot reload](#state-preserving-hot-reload-v120). Outside a
host session, `state_arena()` (v1.2.0) returns a private arena, so a program
written for `vanta hot` also runs under plain `vanta run`.

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

### State-preserving hot reload (v1.2.0)

`vanta hot <file>` keeps one flat byte segment alive for the whole session and
binds it into every rebuilt generation. A program whose working set comes from
`state_arena()` finds the same bytes at the same offsets after a swap, so state
that survives a source change is an ordinary program:

```vanta
let world = state_arena()
let ticks = world.alloc::<i32>(1)
ticks[0] = ticks[0] + 1
print_i32(ticks[0])   # 1, then 2, then 3 … across rebuilds
```

Without a host session (plain `vanta run`) `state_arena()` falls back to a
private arena, so the same source runs unchanged either way. `__reload(prev)`,
when declared, runs once per generation before `main`; use it for one-time
replay that `state_arena()` does not cover.

A program with an event loop cooperates by polling `hot_should_reload()` and
returning; the host then rebuilds and starts the next generation:

```vanta
while running:
    if hot_should_reload():
        running = false
    # … normal frame work …
```

Outside `vanta hot`, `hot_should_reload()` always returns `false`, so a loop
runs to completion under a normal run.

Reloads are deterministic: `--reloads N` rebuilds/swaps N extra times without
editing a file, and `file_write`/`file_read` can capture per-generation
checkpoints. See `examples/stateful_hot.vnt`.


`p.at(i, size)` is the pointer counterpart of `xs.at(i)`. The pointer does not
carry its length, so the caller supplies the accessible element count and the
index is checked against it before memory is touched:

```vanta
func main() -> void:
    let arena = Arena(256)
    let xs = arena.alloc::<i32>(4)
    xs.at(0, 4) = 10
    xs.at(1, 4) = 20
    xs.at(1, 4) += 2
    print_i32(xs.at(0, 4))
    print_i32(xs.at(1, 4))
```

```
10
22
```

Reads, writes, and compound assignment all work, including nested access such
as `rows.at(row, row_count).at(column)` when the element type is an array.
Pointer memory is writable through a plain `let` binding, exactly like
`p[i]`.

An out-of-bounds index stops the program with the pointer's element count:

```vanta
func main() -> void:
    let arena = Arena(64)
    let xs = arena.alloc::<i32>(4)
    print_i32(xs.at(4, 4))
```

```
vanta: pointer index 4 out of bounds (size 4) at line 4
```

- `size` is a promise made by the programmer. The runtime does not know the
  allocation size; passing a count larger than the real block is still
  unchecked memory access.
- `ptr<void>` cannot use `at`: it has no element type. Cast it to a typed
  pointer first.
- `p[i]`, `ptr_cast::<T>(p)`, and `ptr_offset(p, n)` stay unchecked escape
  hatches. Use them when the program is deliberately working below the
  checked layer.
- Null is still separate: `p.at(...)` checks the index, not the pointer value;
  use `ptr_is_null(p)` when a C function may return NULL.

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
null, and `ptr_is_null` stays the test; it accepts function values as well
as pointers. Like the other pointer builtins it takes no arguments:

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

`str_concat` is fine for one-off values, but building a string piece by piece
in a loop allocates an intermediate result on every iteration. A `StrBuilder`
is the arena-backed answer: one growing buffer, many appends, and only the
final `to_str()` allocation.

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
- `to_str()` returns the current contents as an owned, reference-counted
  `str`, so the result is stable: later appends, growth, `clear()`, and even
  `arena.reset()` do not change it.
- `clear()` resets the builder to empty; the buffer is reused.

Like `List<T>`, a `StrBuilder` is a handle: copies alias the same buffer, and
appends work through a plain `let` — `mut` only controls rebinding. A helper
function can take a `StrBuilder` parameter and append to the caller's builder.
The buffer grows by doubling from 32 bytes, allocating from the arena;
`arena.reset()` invalidates the builder and the buffer it points at, but not
strings already produced by `to_str()`.

**When to use which:** `str_concat` / `to_str_*` for isolated values;
`StrBuilder` for assembling lines, logs, and HUD text, especially per-frame —
build with `clear()`, print with `to_str()`.

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

- Values may be function pointers or closures: a `func` value points at a
named function or at a capturing lambda. A lambda may capture variables from
its enclosing scope by value, and `mut` bindings by durable reference.
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
- Function values compare by address with `==` and `!=`; ordering is
  rejected. `ptr_is_null(f)` is the explicit null test, and a null built with
  `ptr_null::<func(...)>()` compares equal to any null of the same type:

```vanta
func square(x: i32) -> i32:
    return x * x

func cube(x: i32) -> i32:
    return x * x * x

func main() -> void:
    let f = square
    let same = square
    let other = cube
    print_bool(f == same)                  # true: the same function
    print_bool(f == other)                 # false
    print_bool(ptr_is_null(f))             # false
    let missing = ptr_null::<func(i32) -> i32>()
    print_bool(ptr_is_null(missing))       # true
    print_bool(f != missing)               # true
```

```
true
false
false
true
true
```

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
- `==` and `!=` between function values of different types:
  `cannot compare func(i32) -> i32 and func(i32) -> bool with '=='`.
  Ordering (`<`, `<=`, `>`, `>=`) is rejected for every function value.
- Function values in `const` initializers.
- Using a function whose return type is still being inferred (no `-> T`) as a
  value **before** its declaration is checked; add `-> T` or move the
  declaration earlier.

Under the hood each distinct function type becomes a `using FnPtrN = R(*)(...)`
alias in the generated C++, so the C++ spelling of a function type never
appears in Vanta code. Equality compares those pointers, so two values are
equal only when they name the same function (or are both null).

## Strings

```vanta
let greeting = "Hello, Vanta!"
print_str(greeting)              # prints with a trailing newline
print_str("tab:\there")          # \t
print_str("quote: \"hi\"")       # \"
print_bool(greeting == "Hello, Vanta!")   # true — compares contents
```

Supported escapes: `\t`, `\n`, `\"`, `\\`. A `str` is **immutable**. Literals
are zero-copy static views; strings built at runtime by `str_concat`,
`to_str_*`, or `file_read` own a reference-counted heap buffer. Copying a
`str` is cheap and keeps the bytes alive; the last copy frees them.

`==` and `!=` compare the full byte contents, not pointers or refcounts.
Ordering comparisons (`<`) on `str` are rejected. `str` values may be `const`.

Indexing a `str` by byte yields a one-byte `str`:

```vanta
let s = "Vanta"
print_str(s[0])            # V
print_bool(s[1] == "a")    # true
```

`s[i]` is bounds-checked: a negative index, or an index at or past `str_len(s)`,
stops the program with `vanta: string index I out of bounds (length N) at line L`.
The result owns its byte, so it stays valid after the source string goes out of
scope. Indices count **bytes**, not UTF-8 characters; a multi-byte character
occupies several positions. There is no slicing; use `str_sub`. Concatenation
(`str_concat`), length (`str_len`), and conversions are covered under
[Strings and ownership](#strings-and-ownership-v0260); for building many pieces
into one string, see [String building](#string-building-strbuilder-v0100).

## Signals

A class may declare signals:

```vanta
class Button:
    signal clicked(value: i32):
    count: i32

    func press(self: Button, value: i32) -> void:
        self.count = value
        emit clicked(value)
```

`emit` triggers registered handlers for that instance (`signal_on_instance`), and `signal_off`/`signal_off_str_instance` remove listeners. Payloads can be void, a single `i32`, `str`, `bool`, `ptr<T>`, or multiple types (2–4 items). Pointer payloads are borrowed; the  `signal_on_instance` binding must match the handler signature at compile time.

See README/docs for richer examples.

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
| `str_len` | `(str) -> i32` | byte length |
| `str_concat` | `(str, str) -> str` | returns an owned string |
| `str_to_i32` | `(str) -> i32` | leading number; `0` if there is none |
| `str_to_f32` | `(str) -> f32` | leading number; `0.0` if there is none |
| `to_str_i32` | `(i32) -> str` | returns an owned string |
| `to_str_f32` | `(f32) -> str` | returns an owned string |
| `to_str_bool` | `(bool) -> str` | zero-copy literal (`"true"` / `"false"`) |
| `str_pool_reset` | `() -> void` | compatibility no-op (v0.26.0) |
| `file_exists` | `(str) -> bool` | `false` on any error |
| `file_write` | `(str, str) -> i32` | bytes written, or `-1` on failure |
| `file_read` | `(str) -> str` | returns an owned string; `""` on any failure |
| `assert` | `(bool) -> void` | see [Assertions](#assertions-v012) |
| `enum_to_i32` | `(E) -> i32` | a member's value (its tag for a payload enum); `E` is any enum type |
| `ptr_is_null` | `(ptr<T>) -> bool` | `true` when the pointer is null; `T` may be `void` |
| `ptr_cast` | `ptr_cast::<T>(p) -> ptr<T>` | reinterprets the element type; `T` may not be a function type; see [pointer casts](#pointer-casts-ptr_castt-v0170) |
| `ptr_offset` | `(ptr<T>, i32) -> ptr<T>` | moves `n` elements; `T` may not be `void`; see [pointer offsets](#pointer-offsets-ptr_offsetp-n-v0180) |
| `ptr_null` | `ptr_null::<T>() -> ptr<T>` | the null pointer; `T` may be a function type (then it is a null callback); see [null pointers](#null-pointers-ptr_nullt-v0190) |
| `state_arena` | `() -> Arena` | the reload-surviving arena under `vanta hot`; a private arena otherwise (v1.2.0) |
| `hot_should_reload` | `() -> bool` | `true` once the host has asked for a reload; always `false` outside `vanta hot` (v1.2.0) |

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

Pass arguments through the driver with `vanta run prog.vnt 3` (or
`python main.py run prog.vnt 3` from a checkout).

There is no integer-argument builtin: read the string and convert with
`str_to_i32` / `str_to_f32`.

## Strings and ownership (v0.26.0)

`str` is an immutable value with automatic ownership. A literal is a
zero-copy static view; `str_concat`, `to_str_i32`/`to_str_f32`, `file_read`,
and `StrBuilder.to_str()` return an owned buffer with a reference count.
Copying a `str` shares that buffer and increments the count; the last owner
frees it. There is no global pool, no fixed limit, and no reset step that can
invalidate a value you still hold.

```vanta
func main() -> void:
    let label = str_concat("scale", to_str_i32(3))
    print_fmt("{} has {} chars", label, str_len(label))
    let copy = label
    str_pool_reset()          # compatibility no-op since v0.26.0
    print_str(copy)
```

```
scale3 has 6 chars
scale3
```

- `str_pool_reset()` remains available so old programs keep compiling, but it
  does nothing and invalidates nothing.
- `to_str_bool` returns a zero-copy literal and allocates nothing.
- `file_read` is no longer capped by a string pool: it reads the whole file.
  A file larger than `i32` can address is a hard error, not a silent
  truncation.
- Building incrementally? `str_concat` in a loop allocates an intermediate
  string per iteration, but each discarded result is freed. The arena-backed
  [`StrBuilder`](#string-building-strbuilder-v0100) appends into one growing
  buffer and produces one owned result.

Indexing is byte-based and checked; see [Strings](#strings). There is no slicing.

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
- The string names the library. `SDL2`, `SDL2_ttf`, and `SDL2_image` are
  recognized and linked automatically; for any other library use `--lib-dir`
  to add a search path and `--link` to add the library (both repeatable, on
  `build` and `run`).
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
  C library cannot. A plain enum type is emitted as its `enum class` with a
  fixed `int32_t` underlying type, forward-declared ahead of the `extern "C"`
  block together with the struct tags, so the C side may declare the
  parameter/result as `int32_t` or a matching C enum. A payload enum has no
  C representation and is rejected in an `extern` signature, even behind a
  pointer.
- `str` crosses the boundary as `const char*`. The pointer is valid for the
  duration of the call; a C function declared to return `str` returns a
  NUL-terminated `const char*`, which Vanta copies into an owned `str`
  immediately. Extern functions with `str` parameters still work as function
  values: codegen emits a small adapter so the Vanta side keeps `Str`
  semantics while the C side sees `const char*`.
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
first. An `extern` can also *return* a function value (v0.23.0): declare the
return type as `func(...)`, and the generated C++ folds the declarator into
the signature (`void(*signal(int32_t, void(*)(int32_t)))(int32_t)`). The
result is an ordinary function value — call it, store it, compare it by
address, or test it with `ptr_is_null`. Taking `signal` from the C runtime:

```vanta
extern "C" {
    func signal(sig: i32, handler: func(i32) -> void) -> func(i32) -> void
}

func on_term(sig: i32) -> void:
    print_str("caught")

func main() -> void:
    let old = signal(15, on_term)
    print_bool(ptr_is_null(old))       # true: SIG_DFL is the null handler
    let back = signal(15, old)         # restore the old handler
    print_bool(back == on_term)        # true
```

```
true
true
```

The handler is never called here — installing and restoring it just proves
the return value round-trips. A `ptr<func(...)>` return works too and spells
as a double pointer (`int32_t(**get())(int32_t)`); an array or list of
function values is still rejected as an `extern` return, since C cannot
return those by value.

```powershell
python main.py run examples/extern_demo.vnt --lib-dir build --link demo
```

`examples/extern_demo.vnt` and `examples/extern_demo_lib.c` are a complete,
buildable example. `examples/callbacks.vnt` and `examples/callbacks_lib.c`
are a second one: a callback that C calls twice, and a visitor receiving a
`ptr<i32>` user-data pointer. `examples/extern_return.vnt` with
`examples/extern_return_lib.c` is the reverse direction: C returns a chosen
callback, and Vanta calls it, compares it, and tests it for null.
`examples/enums_extern.vnt` with `examples/enums_extern_lib.c` is an enum
crossing into C and back, and `examples/narrow_ints.vnt` with
`examples/narrow_ints_lib.c` shows exact-width parameters plus a C mirror
struct reading a Vanta struct's bytes.

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
`extern` declarations: no SDL headers are involved at compile time, and the
SDL libraries link automatically from the block names:

```powershell
vanta examples/sdl_game.vnt
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

- **SDL events are accessed through typed run-time guards.** The game
  kit's `input.vnt` module checks the SDL event kind before returning
  each field; a mismatch reports `vanta: assertion failed` and exits
  with status 1. The constants target the SDL2 `SDL_Event` ABI used in
  Vanta's examples and tests (56 bytes on the tested 64-bit build).

The windowed programs take an optional frame-limit argument, so a smoke run
needs no display at all — this is how the test suite exercises them (CI
installs SDL2 on Linux, macOS, and Windows and runs the same smoke tests):

```powershell
$env:SDL_VIDEODRIVER = "dummy"
vanta examples/sdl_window.vnt 120
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
nothing but SDL2. `examples/pong.vnt`, `examples/breakout.vnt`, and
`examples/strike.vnt`, the other three playable games, are built on the
[game kit](#the-game-kit-v0140) documented below.

## The game kit (v0.14.0)

`examples/gamekit/` is ten reusable modules over the SDL2, SDL_ttf, and
SDL2_image calls above — ordinary `.vnt` files, imported like anything else.
`collide.vnt` is the exception: pure Vanta, with no SDL and no externs.

| Module | Provides |
|---|---|
| `sdl.vnt` | SDL2 `extern` declarations, the `EV_*` / `KEY_*` / `SDL_FLIP_*` constants, `Screen`, `screen_open` / `screen_ok` / `screen_close` |
| `input.vnt` | Event accessors over a `ptr<i32>` SDL event buffer: `ev_is_quit`, `ev_is_keydown`, `ev_is_keyup`, `ev_key`, scancode, modifiers, mouse, button, wheel, window-event, and button-state/click accessors. Mismatched accessors fail at runtime with `vanta: assertion failed` rather than returning another event's field. Layout constants target the SDL2 `SDL_Event` ABI used by Vanta's tests and examples; other SDL header versions may need updated constants. |
| `gamepad.vnt` | SDL2 controllers: `Pad`, `pad_open` / `pad_ok` / `pad_close`, `pad_attached`, `pad_button`, `pad_axis`, the `PAD_BUTTON_*` / `PAD_AXIS_*` constants |
| `gfx.vnt` | `gfx_clear`, `gfx_fill_rect`, `gfx_stroke_rect`, `gfx_present` |
| `image.vnt` | SDL2_image: `Tex`, `tex_load` / `tex_ok` / `tex_free`, `tex_tint`, `tex_alpha`, `tex_draw` / `tex_draw_src` / `tex_draw_ex` |
| `anim.vnt` | Sprite-sheet animation: `Anim`, `anim_new` / `anim_tick` / `anim_frame` / `anim_draw` |
| `text.vnt` | SDL_ttf: `Font`, `font_open` / `font_ok` / `font_close`, `text_measure`, `text_draw`; `TextSprite`, `text_sprite` / `text_sprite_ok` / `text_sprite_draw` / `text_sprite_free`; `text_quit` |
| `audio.vnt` | SDL2 audio: `Audio`, `audio_open` / `audio_ok` / `audio_close`, `audio_play_tone`, `audio_pending`, `audio_wait`; `Sound`, `sound_load` / `sound_load_gain` / `sound_ok` / `sound_play` / `sound_free` |
| `rng.vnt` | `rand_int`, `rand_range_f32`, `rand_sign` |
| `collide.vnt` | Pure overlap tests (no SDL): `collide_rects`, `collide_point`, `collide_circles`, `collide_circle_rect` |

Three idioms fall out of the language rules:

- **Prefixes for clarity, not because Vanta requires them.** The kit is a set
  of legacy `module`-less files, so every kit name is prefixed by its module
  (`screen_*`, `ev_*`, `pad_*`, `gfx_*`, `tex_*`, `anim_*`, `font_*`,
  `text_*`, `audio_*`, `sound_*`, `rand_*`, `collide_*`) and several modules —
  and the game's own names — coexist. Declared modules (v0.30.0) get real
  scopes; the kit keeps its prefixes for readable call sites.
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
(WAV files load through `sound_load` or `sound_load_gain`, below). The queue API wants a *null*
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
`sound_play` queues it after whatever is already playing. `sound_load_gain`
loads the same way and then scales every sample in place; its `f32` gain is
clamped to 0..1, so it attenuates without clipping, and `sound_load` is the
full-volume shortcut. A stereo file is folded to mono in place at load, so its
byte count halves; any other rate, sample format, or channel count loads as a
dead `Sound` — `sound_ok` false, and every `sound_*` call on it is a no-op,
exactly like a dead `Audio`. Paths are opened by C, relative to the process
working directory:

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

`collide.vnt` next: the one kit module with no SDL in it. It is pure Vanta,
so it adds no library and can be tested in a plain headless program.
Rectangles are `(x, y, w, h)` with the top-left corner and a positive size;
edges that only touch are not overlaps, and `collide_point` is half-open —
the left and top edges are inside, the right and bottom edges are out.
Circles take centre coordinates and radii. The distance tests compare
squares, so none of them calls `sqrt`:

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

Kit programs run like any other Vanta program; `text.vnt` brings in SDL_ttf,
`image.vnt` brings in SDL2_image, and the kit's extern block names give the
driver everything it needs to link them (`audio.vnt`, `gamepad.vnt`, and
`collide.vnt` need nothing extra — the first two use SDL2's core library,
and `collide.vnt` uses no library at all):

```powershell
vanta examples/pong.vnt
vanta examples/breakout.vnt
vanta examples/strike.vnt
vanta new game.vnt
```

`vanta new` writes a playable starter without assets, and on Windows
`vanta build game.vnt --release --bundle` copies the executable's non-system
DLL dependencies and the example assets beside it.

`examples/pong.vnt` is the worked example for the first game: it imports six
of the modules (all but `image.vnt` and `gamepad.vnt`), serves with `match`,
draws its score with `text_draw`, beeps with `audio_play_tone`, and stays
testable headless — a frame-limit argument plus `SDL_VIDEODRIVER=dummy` and
`SDL_AUDIODRIVER=dummy` is how the test suite runs it in CI.
`examples/breakout.vnt` adds the satellite modules on top: three tinted
brick walls out of one white texture, WAV hits, P/Space pause, a best score
persisted in `breakout.score`, and a deterministic full-clear run the suite
freezes the same way.
`examples/strike.vnt` is the fourth game and the full-kit example: it uses
nine of the ten modules (all but `rng.vnt`), draws an animated ship and
three waves of tinted saucers, keeps the HUD with `text_draw`, fires WAV
shots and hits, falls back to the keyboard when no gamepad is attached, and
uses `collide.vnt` for every overlap test. With no input its autopilot
clears all eighteen saucers at frame 1020, which the suite freezes.

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
- `file_read(path) -> str` — reads the whole file into an owned string; returns
  `""` on any failure. There is no fixed pool limit; a file larger than `i32`
  can address is a hard error (`vanta: file '<path>' is too large for str`,
  exit code 1), so nothing is truncated silently.

An empty file and a missing file both read as `""`; use `file_exists` when the
difference matters. Reads and writes are byte-exact (`"rb"`/`"wb"`), and
`str_len` and `file_write` preserve embedded NUL bytes. Passing such a string
to a C function or `print_str` still stops at the first NUL because those use a
`const char*`.

`examples/file_io.vnt` reads a file named on the command line and writes a copy
to `<path>.copy`.

## Modules and imports (v0.4.0; modules v0.30.0)

`import` still loads another file by path. A file may begin with
`module <name>` to give its declarations a scope. Save this as
`geometry.vnt`:

```vanta
module geometry

pub const ORIGIN_X: i32 = 3

# Private: only code inside geometry.vnt can call square.
func square(n: i32) -> i32:
    return n * n

pub struct Point:
    x: i32
    y: i32

pub enum Shape:
    Dot
    Square(i32)

pub func length_squared(p: Point) -> i32:
    return square(p.x) + square(p.y)

pub func area(shape: Shape) -> i32:
    match shape:
        Shape.Dot:
            return 0
        Shape.Square(side):
            return square(side)
```

A second file imports it with an alias and uses qualified names. Save this as
`main.vnt`:

```vanta
module demo

import "geometry.vnt" as geo
import "units.vnt"

func local_double(n: i32) -> i32:
    return n * 2

func main() -> void:
    let p = geo.Point(x: 3, y: 4)
    print_i32(geo.length_squared(p))
    print_i32(geo.area(geo.Shape.Square(5)))
    print_i32(geo.ORIGIN_X)
    print_i32(meters_to_centimeters(2))
    print_i32(local_double(geo.ORIGIN_X))
```

The second import is unqualified, so `units.vnt` contributes its public names
to the bare namespace:

```vanta
module units

pub func meters_to_centimeters(m: i32) -> i32:
    return m * 100
```

Run `main.vnt` and it prints:

```text
25
25
3
200
6
```

- A `module` declaration must be the first declaration in its file. Module
  names are identifiers and must be unique across the program.
- A module's declarations are private by default. `pub` exports functions
  (including `system`/`component`), structs, enums, constants, and
  `extern` blocks. Inside a struct, a field is private by default and `pub`
  exports it. A private name cannot be imported or reached through an alias.
- A public declaration cannot expose a private type in an explicit parameter,
  return, field, payload, or constant type, or through an inferred function or
  constant type. Give the type `pub` as well, or keep the public surface in
  terms of public types.
- An unqualified import brings the target's public names into the importing
  file, used by their bare names. A local top-level declaration with the same
  name is an error; use an alias to keep both. If two unqualified imports
  provide the same name, using it is an error — import one or both with an
  alias and qualify the call.
- `import "geometry.vnt" as geo` gives qualified access: `geo.Point`,
  `geo.length_squared(...)`, `geo.Shape.Square(5)`, and `geo.ORIGIN_X` all
  work. An alias must not collide with a top-level declaration in the
  importing file.
- Import paths are resolved relative to the importing file first. For declared
  modules, dotted names (`math.vector`) also resolve from `VANTA_PATH`
  directories; missing imports remain a compile error. Additional search
  directories can be supplied with `VANTA_PATH`.
  transitively, and each file is loaded once no matter how many times it is
  imported. A declared module does not re-export its imports: importing `a.vnt`
  gives `a.vnt`'s public declarations, not the public names `a.vnt` imported.
  Legacy module-less files keep the old flat, transitive visibility.
- Import cycles are a compile error, reported with the chain:
  `a.vnt: import cycle: a.vnt -> b.vnt -> a.vnt`. A missing import is a
  compile error at the import statement:
  `main.vnt:1:1: cannot open import 'lib/nope.vnt'`.
- Files without a `module` declaration keep the original flat, all-public
  behaviour. Their declarations are imported by bare name exactly as before,
  and an alias can still be used to qualify them. This is why the game kit
  and all existing examples continue to work unchanged.
- `main` in the entry file is still the program entry point when that file
  declares a module; its other declarations are module-scoped. A `main` in an
  imported declared module is an ordinary scoped function; an unqualified
  import does not add it to the bare namespace, so use the alias.
- `extern` functions keep their C names. They live in the global C ABI even
  when declared inside a module; `pub extern` allows other modules to call
  them.
- Errors inside an imported file name that file, not the entry file.
  Diagnostics show source names, not the compiler's internal unique names.
- Imports may appear anywhere among top-level declarations after the optional
  `module` line; the convention is at the top of the file.

`examples/imports_demo.vnt` and `examples/imports_demo_lib.vnt` are the
original flat-import example. `examples/modules_demo/` is the complete
module example above, including the legacy flat compatibility path.

Nested modules are written with dots (`module math.vector`); dots become `__` in the
generated C++ prefix (`vanta_m_math__vector__`). Duplicate dotted names are rejected.
The compile-time search path (`VANTA_PATH`) may resolve imports through multiple
directories, and module-less files still keep the flat, transitive behavior
for compatibility.

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

## Virtual dispatch

When a subclass redeclares a method with the same parameter and return
types, that method becomes virtual. A Base-typed object or a `ptr<Base>`
pointing to a derived instance will call the method from the actual
runtime type:

```vanta
func tick(e: ptr<Entity>) -> i32:
    return e.update()
```

Methods that are not redeclared in a subclass remain ordinary static
methods with no extra call overhead.

Use only one level of method signatures for overriding: an override
with a different signature is rejected with `invalid override`.

Additional rules that implementations rely on:

- **Vanta has single inheritance only.** A class may extend one base;
  there is no multiple-inheritance dispatch matrix.
- **Virtual dispatch is signature based, not declaration based.** A
  method is virtual when its parameter types and return type match a
  base method; merely overriding the signature shape by return type,
  arity, or parameter type is a compile-time `invalid override`.
- **Each instance carries a fixed runtime type id.** Constructor
  values include `v__vanta_runtime_type`, initialized to
  `VANTA_TYPE_ID_<ClassName>`. Hand-built or serialised instances
  must keep that identifier matched with the C++ class shape; otherwise
  dispatch falls through to the base implementation. Generated
  identifiers follow the sorted class-name assignment of the current
  program.
- **Dispatch is `switch` plus guarded `reinterpret_cast`.** The base
  runtime type first tries the matching derived case and only
  reinterprets the base pointer after a successful type-id match.
- **`ptr<Base>` dispatch requires a heap/arena instance** created with
  the generated constructor. Stack-shaped pointers or copies bypass
  these runtime ids.

All source-level errors carry `file:line:col`:

```
examples/boids.vnt:3:5: argument: cannot assign i32 to u32
```

Use `vanta check <file>` (or `python main.py check <file>` from a checkout) to
type-check without invoking a C++ compiler.
When independent errors are present, the type checker reports them together
where their source spans are independent. Some invalid constructions still
prevent meaningful analysis and stop at the first error. Independent
diagnostics are stable in source order.
When C++ compilation fails during `build`, the generated source is saved to
`build/vanta_failed.cpp`.

## Build cache

`vanta run` caches compiled programs beside the source. The cache key uses `vanta_run` source files, imported dependencies, compiler and runtime files, build options, and `VANTA_PATH`. Cache entries are promoted atomically. Their size and age can be limited with `VANTA_CACHE_MAX_MB` (default 512) and `VANTA_CACHE_MAX_AGE_DAYS` (default 30; use 0 to disable age pruning); at least one valid active entry is retained even if the size limit is exceeded. Use `--no-cache` to disable caching and `--fresh` to rebuild.
