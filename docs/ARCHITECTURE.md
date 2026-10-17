# Vanta Architecture

## Frontend (Python)

1. `lexer.py` — hand-written tokenizer producing `INDENT`/`DEDENT`/`NEWLINE`.
2. `parser.py` — recursive descent for declarations, Pratt for expressions.
3. `type_checker.py` — two-pass: register structs/functions, then check bodies with scoped symbol tables. Annotates every expression node with `expr.type`.
4. `codegen_cpp.py` — emits C++17 inside `namespace vanta_user`, wraps `main` in `int main()`.
5. `driver.py` — orchestrates frontend + native compilation. Detects clang++/g++/cl.

## Backend (C++17)

`runtime/vanta_runtime.hpp` provides math types, the `Arena` allocator, and IO.

## Diagnostics

All source-level errors carry file:line:col. The driver saves generated C++ on compilation failure to `build/vanta_failed.cpp`.

## Ownership (v0.1)

Only rule enforced: **Arena is non-copyable**. `let a2 = a1` (where `a1: Arena`), `return a1`, and passing an Arena as an argument are all rejected. Broader ownership analysis is out of scope for v0.1.