# Vanta Architecture

Vanta is a small compiler: a Python frontend that emits C++17, which is then
compiled to a native binary by an off-the-shelf C++ compiler. There is no
custom backend, no IR, and no optimizer — the C++ compiler does that work.

## Frontend (Python)

1. `tokens.py` — token types and the keyword table.
2. `lexer.py` — hand-written tokenizer producing `INDENT`/`DEDENT`/`NEWLINE`.
   Tabs are rejected.
3. `parser.py` — recursive descent for declarations, Pratt for expressions.
   Produces `ast_nodes.py` nodes.
4. `typesys.py` — the type model (`PrimType`, `PtrType`, `ArrayType`,
   `StructType`, ...).
5. `type_checker.py` — two passes: register structs, builtins, and function
   signatures; then check bodies with scoped symbol tables. Annotates every
   expression node with `expr.type`. This is where the builtins are declared
   (`_register_builtins`) and where the `Arena` non-copyable rule is enforced.
6. `codegen_cpp.py` — emits C++17 inside `namespace vanta_user` and wraps
   `main` in `int main()`. Builtin calls are mapped through lookup tables
   (`BUILTIN_PRINT`, `BUILTIN_MATH_CTOR`) to `vanta::` runtime functions.
7. `driver.py` — orchestrates the frontend and native compilation, detects
   `clang++`/`g++`/`cl` (honouring `$CXX`), and implements `check`/`build`/`run`.

Note that `component` and `system` are parsed as flags on the struct and
function declarations respectively (`parse_struct(is_component)`,
`parse_func(is_system)`). They are aliases that express ECS intent and have no
distinct semantics.

## Backend (C++17)

`runtime/vanta_runtime.hpp` is a single-header runtime providing:

- `Vec2`, `Vec3`, `Quat`, `Matrix4` (row-major) with their operators
- the `Arena` bump allocator
- IO, `sqrt`, and integer/float conversion helpers
- `str_eq` (`strcmp`-backed string equality)
- `rand_state` / `rand_seed` / `rand_f32` — xorshift32, fixed seed at startup
  so programs are reproducible unless explicitly seeded

## Versioning

`compiler/__init__.py` holds the single `VERSION` string. The driver reports it
for `--version`, and `codegen_cpp.py` writes it into the generated file's
header. There is no second copy to keep in sync.

## Diagnostics

All source-level errors carry `file:line:col`. The driver saves generated C++ on
compilation failure to `build/vanta_failed.cpp`.

## Ownership (v0.2.2)

The only rule enforced is that **`Arena` is non-copyable**: `let a2 = a1` (where
`a1: Arena`), `return a1`, and passing an `Arena` as an argument are all
rejected. `ptr<T>` has no borrow checking, lifetime tracking, or aliasing
analysis, so dangling and aliased pointers are not detected. Broader ownership
analysis is out of scope.

## Tests

`tests/` holds 115 `unittest` cases across the lexer, parser, type checker,
code generator, and end-to-end integration. Integration tests compile and run
real binaries and skip automatically when no C++17 compiler is present:

```powershell
python -m unittest discover -s tests
```
