# Vanta Architecture

Vanta is a small compiler: a Python frontend that emits C++17, which is then
compiled to a native binary by an off-the-shelf C++ compiler. There is no
custom backend, no IR, and no optimizer — the C++ compiler does that work.

## Frontend (Python)

1. `tokens.py` — token types and the keyword table.
2. `lexer.py` — hand-written tokenizer producing `INDENT`/`DEDENT`/`NEWLINE`.
   Newlines are suppressed inside `(...)` and `[...]`, so array literals and
   argument lists can span lines. Tabs are rejected.
3. `parser.py` — recursive descent for declarations, Pratt for expressions.
   Produces `ast_nodes.py` nodes.
4. `loader.py` — builds the file graph and resolves module boundaries. It
   reads each file once, resolves imports relative to the importing file,
   detects cycles, and stamps every AST position with its source file so
   diagnostics name the right file. A file may start with `module name`;
   module-scoped declarations are private unless marked `pub`. An unqualified
   import brings public names into the importing file, an aliased import
   creates qualified names, and module-less files keep the original flat,
   all-public behaviour. The resolver rewrites declarations and references to
   unique internal names (`vanta_m_<module>__<name>`) and validates
   visibility, ambiguous imports, duplicate module names, and private-type
   leaks in public signatures. The resulting `Program` is still flat for the
   type checker and backend; a `display_names` map turns internal names back
   into source names in diagnostics. Entry `main` and extern C names stay
   unchanged.
5. `typesys.py` — the type model (`PrimType`, `PtrType`, `ArrayType`,
   `StructType`, `EnumType`, `FuncType`, ...).
6. `type_checker.py` — two passes: register structs, enums, builtins, and
   function signatures; then check bodies with scoped symbol tables. Annotates every
   expression node with `expr.type`. This is where the builtins are declared
   (`_register_builtins`), where `extern` functions are registered
   (`is_extern=True`), and where the `Arena` non-copyable rule is enforced.
   Assignment targets are validated by walking the storage chain (fields,
   indexes, and checked `at()` calls) to its root: an index on a pointer is
   writable regardless of the binding, otherwise the root binding must be
   `mut`. Function values are
   resolved here too: `func(...)` types are registered under the `FnPtrN`
   alias names codegen will use, and a local binding shadows a function of the
   same name in call position. The pointer rules live here as well: `_coerce_value`
   performs the C-style `ptr<T>` → `ptr<void>` widening (and only that
   direction), `ptr_is_null` is checked in `_check_ptr_is_null`,
   `ptr_null::<T>()` (v0.19.0) in `_check_ptr_null` (a function-type `T`
   yields a null callback), a
   `ptr<void>` cannot be indexed, and `alloc::<void>` is rejected with its
   own message. The integer-width rules live here too (v0.17.0): narrow
   values promote to `i32` in arithmetic, any integer truncates into a narrow
   slot, out-of-range literals are rejected, and `eq_blocker` (in
   `typesys.py`) walks struct fields to decide whether a struct may be
   compared with `==`.
7. `codegen_cpp.py` — emits C++17 inside `namespace vanta_user` and wraps
   `main` in `int main(int argc, char** argv)`, passing the arguments to the
   runtime. Module-scoped declarations have already been given unique
   internal identifiers by the loader, so the backend can stay flat and two
   modules may use the same source name. Builtin calls are mapped through
   lookup tables (`BUILTIN_FN`, `BUILTIN_MATH_CTOR`) to `vanta::` runtime
   functions. `extern` declarations
   are emitted as an `extern "C" {}` block before the namespace, and calls to
   them skip the `fn_` prefix user functions get. Extern signatures predate
   the namespace, so they are spelled in plain C: callback parameters expand
   inline as declarators (`int32_t(*v_f)(int32_t)` — the name folds inside
   the stars), and user structs are namespace-qualified with their tags
   forward-declared ahead of the block. Each distinct function type is
   emitted as a `using FnPtrN = R(*)(P...)` alias at the top of the
   namespace, innermost first, and drives the in-namespace spellings.
   Struct and enum definitions are emitted in source order; forward tags and
   aliases come first. Payload types must be declared before the enum that
   carries them, so source order is a valid dependency order. A plain enum is
   `enum class E : int32_t`; a payload enum is a struct with a nested
   `VantaTag` and one field per payload value, plus a `make_E_Member`
   constructor for each member. A function that can fall through gets a
   type-appropriate default return: `""` for `str`, `nullptr` for pointers,
   the first member for enums, value-initialization for everything else
   (`T{}` cannot be written for a raw `T*`, which is why pointers are
   special-cased). `match` lowers to an if/else chain over a single
   `const auto` binding of the matched value — deliberately not a C++
   `switch`, so a `break`/`continue` written in an arm keeps its meaning for
   the enclosing loop. Payload patterns compare `v_tag` and bind the active
   fields with `const auto&` locals. `for x in xs` lowers to an index loop
   over a bound handle (Lists) or a const reference (arrays), re-reading a
   list's length each pass. Comparable structs and payload enums get
   non-member `operator==`/`!=` (`str` through `str_eq`, arrays element-wise,
   payload enums by tag and active payload), every declaration ahead of every
   definition so nesting order does not matter, and narrow fields or elements
   get `static_cast<T>` where C++ braced initialization would refuse the
   narrowing. Plain enum tags are forward-declared with their fixed `int32_t`
   underlying type next to the struct tags ahead of the `extern "C"` block;
   payload enums are forward-declared as structs and rejected in extern
   signatures.
8. `formats.py` — parses `print_fmt`/`write_fmt` format literals. Shared by the
   type checker (which counts placeholders and checks argument types) and the
   code generator (which turns them into printf conversions).
9. `driver.py` — orchestrates the frontend and native compilation, detects
   `clang++`/`g++`/`cl` (honouring `$CXX`), and implements `check`/`build`/`run`.
   A bare source path is the same as `run`, and known extern block names
   (`SDL2`, `SDL2_ttf`, `SDL2_image`) add their link flags automatically.
   `new` writes a playable starter, and `build --bundle` walks the Windows
   executable's PE imports with `objdump` to copy non-system DLLs beside it.
   `--include-dir`/`--lib-dir`/`--link` (repeatable, on `build` and `run`) pass
   `-I`/`-L`/`-l` - or the MSVC `/I`/`/LIBPATH:`/`<lib>.lib` equivalents -
   through to the C++ compiler. Generated code is built with FP contraction
   off (`-ffp-contract=off`, or `/fp:strict` for MSVC), so deterministic
   float-based runs do not diverge between x86-64 and arm64.

Note that `component` and `system` are parsed as flags on the struct and
function declarations respectively (`parse_struct(is_component)`,
`parse_func(is_system)`). They are aliases that express ECS intent and have no
distinct semantics.

## Backend (C++17)

`runtime/vanta_runtime.hpp` is a single-header runtime providing:

- `Vec2`, `Vec3`, `Quat`, `Matrix4` (row-major) with their operators
- `Str` — immutable, reference-counted strings; literals are zero-copy static
  views, and owned buffers are freed by the last copy
- the `Arena` bump allocator; it constructs and destroys non-trivial element
  types, so `alloc::<str>` and structs containing `Str` are well-defined
- `List<T>` with `list_new` / `list_push` / `list_pop` / `list_insert` /
  `list_remove` / `list_sort` (a stable merge sort driven by the caller's
  comparator function value) / `list_at_checked[_ref]` — the arena-backed
  growable lists behind `arena.list::<T>()`
- `StrBuilder` with `strb_append_*` / `strb_to_str` / `strb_clear` — arena-backed
  string building behind `arena.str_builder()`; `to_str()` returns an owned
  `Str`, so results survive the builder and arena
- `at_checked` / `at_checked_ref` (plus `index_fail`) — the bounds-checked
  access behind `xs.at(i)`; a bad index reports the array size and the
  access's source line
- `ptr_at_checked` / `ptr_at_checked_ref` (plus `ptr_index_fail`) — the
  bounds-checked access behind `p.at(i, size)`; the caller supplies the
  accessible count because a raw pointer carries no length
- IO, `sqrt` and trig (`sin`/`cos`/`tan`/`atan2`), `abs`/`min`/`max`/`floor`/`ceil`, and integer/float conversion helpers
- `write_*` variants of the `print_*` functions (no trailing newline)
- `print_fmt_impl` — the `printf`-backed target of `print_fmt`/`write_fmt`
- `str_eq` (`memcmp`-backed byte equality), `str_len`, and
  `str_to_i32`/`str_to_f32`
- `str_concat` and `to_str_*` — return owned `Str` values; `str_pool_reset` is
  a compatibility no-op
- `file_exists` / `file_read` / `file_write` — byte-exact file I/O; `file_read`
  returns an owned `Str` and `file_write` returns the byte count or `-1`
- `rand_state` / `rand_seed` / `rand_f32` — xorshift32, fixed seed at startup
  so programs are reproducible unless explicitly seeded
- `g_argc` / `g_argv`, populated by the generated `main`, exposed as
  `arg_count` / `arg_str`

## Packaging (v0.28.0)

A checkout keeps the runtime at `runtime/` and the kit at `examples/gamekit/`,
so the examples and tests use the canonical copies. A wheel has no checkout
around it, so `setup.py` overrides `build_py` to copy those directories into
the build tree as `compiler/runtime/`, `compiler/templates/gamekit/`, and
`compiler/templates/assets/`; setuptools then packs them into the wheel.
`MANIFEST.in` includes the same files in the sdist, so building a wheel from
the sdist works too.

The driver resolves each directory through `_first_existing_dir`: it looks
beside `compiler/` first (the installed layout) and falls back to the repo root
(the checkout layout). `vanta doctor` reports which paths won, compiles a
one-line probe against the runtime header, and makes a best-effort SDL2 check.
The CI `package` job builds the wheel, installs it into a fresh venv, and runs
only the installed `vanta` command; `.github/workflows/release.yml` repeats the
smoke test on tags, attaches the wheel and sdist to the GitHub release, and can
publish to PyPI through Trusted Publishing (enabled with the
`PUBLISH_PYPI=true` repository variable).

## Versioning

`compiler/__init__.py` holds the single `VERSION` string. The driver reports it
for `--version`, and `codegen_cpp.py` writes it into the generated file's
header. There is no second copy to keep in sync.

## Diagnostics

All source-level errors carry `file:line:col`. The driver saves generated C++ on
compilation failure to `build/vanta_failed.cpp`.

## Ownership (v0.2.6)

The only rule enforced is that **`Arena` is non-copyable**: `let a2 = a1` (where
`a1: Arena`), `return a1`, and passing an `Arena` as an argument are all
rejected. `ptr<T>` has no borrow checking, lifetime tracking, or aliasing
analysis, so dangling and aliased pointers are not detected; the checker only
guards the conversions (widening to `ptr<void>` is implicit, the reverse is
an error) and offers `ptr_is_null`. `p.at(i, size)` (v0.25.0) is an opt-in
bounds check; `p[i]` and the cast/offset escape hatches stay unchecked.
`ptr_cast::<T>(p)` (v0.17.0) is the
explicit, unchecked reinterpretation, `ptr_offset(p, n)` (v0.18.0) the
explicit, unchecked element step, and `ptr_null::<T>()` (v0.19.0) the
explicit null — a function-type `T` makes it a null callback — so the
escape hatches stay opt-in.
Broader ownership analysis is out of scope.

## Tests

`tests/` holds 613 `unittest` cases across the lexer, parser, type checker,
code generator, and end-to-end integration. Integration tests compile and run
real binaries and skip automatically when no C++17 compiler is present. The
SDL2 tests build, link, and run the SDL examples headless
(`SDL_VIDEODRIVER=dummy` plus a frame-limit argument; the audio tests use
`SDL_AUDIODRIVER=dummy`, whose device paces playback in real time) and skip
when SDL2 is not installed; the SDL_ttf tests (the raw text example, pong's
text score, the `text` kit module) and the SDL2_image tests (the raw texture
example, the `image` kit module, breakout) do the same and skip when their
library is missing; audio needs no library beyond SDL2 core, and the WAV
format tests write their own sample files. CI installs SDL2, SDL_ttf, and
SDL2_image on Linux, macOS, and Windows. The game kit's `rng` module has no
SDL dependency and is covered by its own test, so part of the kit runs
anywhere a C++ compiler does.

```powershell
python -m unittest discover -s tests
```
