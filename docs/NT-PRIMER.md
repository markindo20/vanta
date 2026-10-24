# Vanta primer for Python/NT minds
- Vanta is compiled via C++; `let` immutable, `mut` only when writing mutables.
- Structs are value objects, use credentials types; `ptr<T>` allows manual deref, `Arena` typed allocation.
- Exceptions are not normal (use `Result<T,E>`), no garbage collector; cleanup via scope + explicit reset.
- `extern` lets you call C, boundaries require both types.
- Keep borrow/lifetime awareness: stack pointers, arena lifetimes, `ptr_null` handles.
- `signal` and `signal_emit` are explicit.
- Types explicit: enum generics by type argument.

Language constructs:
- `class`, `func`, `struct`, `enum`.
- `Self`, `mut`, `let`.
- Match exhaustive; guards allowed.
- Generics `T<T2>`.
- Fn values and no-capture lambdas.

Mapping:
- Python `dict` → combined types or Lists.
- exceptions → `Result<T,E>` or explicit returns.
If you touched C++ before, you'll feel at home.