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
4. `loader.py` — expands `import` declarations into one merged `Program`: the
   entry file plus everything it imports, recursively, with dependencies
   first. Paths resolve relative to the importing file, each file is loaded
   once (cycles and missing files are errors), and every AST position is
   stamped with its source file so diagnostics name the right file.
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
   direction), `ptr_is_null` is checked in `_check_ptr_is_null`, a
   `ptr<void>` cannot be indexed, and `alloc::<void>` is rejected with its
   own message.
7. `codegen_cpp.py` — emits C++17 inside `namespace vanta_user` and wraps
   `main` in `int main(int argc, char** argv)`, passing the arguments to the
   runtime. Builtin calls are mapped through lookup tables (`BUILTIN_FN`,
   `BUILTIN_MATH_CTOR`) to `vanta::` runtime functions. `extern` declarations
   are emitted as an `extern "C" {}` block before the namespace, and calls to
   them skip the `fn_` prefix user functions get. Each distinct function type
   is emitted as a `using FnPtrN = R(*)(P...)` alias at the top of the
   namespace, innermost first, with raw declarators never written inline.
   Enum declarations are emitted before the aliases, since signatures and
   fields may name them. A function that can fall through gets a
   type-appropriate default return: `""` for `str`, `nullptr` for pointers,
   value-initialization for everything else (`T{}` cannot be written for a
   raw `T*`, which is why pointers are special-cased). `match` lowers to an
   if/else chain over a single `const auto` binding of the matched value —
   deliberately not a C++ `switch`, so a `break`/`continue` written in an
   arm keeps its meaning for the enclosing loop.
8. `formats.py` — parses `print_fmt`/`write_fmt` format literals. Shared by the
   type checker (which counts placeholders and checks argument types) and the
   code generator (which turns them into printf conversions).
9. `driver.py` — orchestrates the frontend and native compilation, detects
   `clang++`/`g++`/`cl` (honouring `$CXX`), and implements `check`/`build`/`run`.
   `--include-dir`/`--lib-dir`/`--link` (repeatable, on `build` and `run`) pass
   `-I`/`-L`/`-l` — or the MSVC `/I`/`/LIBPATH:`/`<lib>.lib` equivalents —
   through to the C++ compiler.

Note that `component` and `system` are parsed as flags on the struct and
function declarations respectively (`parse_struct(is_component)`,
`parse_func(is_system)`). They are aliases that express ECS intent and have no
distinct semantics.

## Backend (C++17)

`runtime/vanta_runtime.hpp` is a single-header runtime providing:

- `Vec2`, `Vec3`, `Quat`, `Matrix4` (row-major) with their operators
- the `Arena` bump allocator
- `List<T>` with `list_new` / `list_push` / `list_pop` / `list_insert` /
  `list_remove` / `list_sort` (a stable merge sort driven by the caller's
  comparator function value) / `list_at_checked[_ref]` — the arena-backed
  growable lists behind `arena.list::<T>()`
- `StrBuilder` with `strb_append_*` / `strb_to_str` / `strb_clear` — arena-backed
  string building behind `arena.str_builder()`; `to_str()` copies, so results
  are stable
- `at_checked` / `at_checked_ref` (plus `index_fail`) — the bounds-checked
  access behind `xs.at(i)`; a bad index reports the array size and the
  access's source line
- IO, `sqrt` and trig (`sin`/`cos`/`tan`/`atan2`), `abs`/`min`/`max`/`floor`/`ceil`, and integer/float conversion helpers
- `write_*` variants of the `print_*` functions (no trailing newline)
- `print_fmt_impl` — the `printf`-backed target of `print_fmt`/`write_fmt`
- `str_eq` (`strcmp`-backed string equality), `str_len`, and `str_to_i32`/`str_to_f32`
- a 64 KiB process-lifetime string pool backing `str_concat`, `to_str_*`, and
  `file_read`
- `file_exists` / `file_read` / `file_write` — byte-exact file I/O; `file_read`
  allocates from the string pool and `file_write` returns the byte count or `-1`
- `rand_state` / `rand_seed` / `rand_f32` — xorshift32, fixed seed at startup
  so programs are reproducible unless explicitly seeded
- `g_argc` / `g_argv`, populated by the generated `main`, exposed as
  `arg_count` / `arg_str`

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
an error) and offers `ptr_is_null`. Broader ownership analysis is out of
scope.

## Tests

`tests/` holds 447 `unittest` cases across the lexer, parser, type checker,
code generator, and end-to-end integration. Integration tests compile and run
real binaries and skip automatically when no C++17 compiler is present. The
SDL2 tests build, link, and run the SDL examples headless
(`SDL_VIDEODRIVER=dummy` plus a frame-limit argument) and skip when SDL2 is
not installed; CI installs SDL2 on Linux, macOS, and Windows. The game kit's
`rng` module has no SDL dependency and is covered by its own test, so part
of the kit runs anywhere a C++ compiler does.

```powershell
python -m unittest discover -s tests
```
