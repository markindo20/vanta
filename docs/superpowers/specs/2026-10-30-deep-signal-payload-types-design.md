# Deep signal payloads and generic dispatch — design

**Status:** draft, awaiting approval
**Date:** 2026-10-30
**Size:** project (medium/large — touches type checker, codegen, runtime, tests, docs)

## Intent

Vanta classes can already declare signals such as `signal clicked(value: i32):` and emit them with `emit clicked(value)`. However, the payload system is artificially narrow: it only supports empty payloads, a single `i32`, a single `str`, and (added in v1.6.0) 2–4 `i32` values. The error text mentions `bool`, but `bool` is rejected. Pointer/struct payloads are wholly unsupported. This milestone is chosen (Option B) so that **any combination of Vanta payload types** may be used in any arity up to 4: `i32`, `u32`, `f32`, `f64`, `bool`, `str`, and `ptr<T>` (including class and struct pointers). This keeps Vanta viable for real game state (hit points, entity pointers, flags).

## Goals

- A class signal may declare 0–4 parameters of any supported type.
- `emit name(args...)` works for all combinations without new per-shape infrastructure.
- Listener registration `signal_on_instance(instance, name, handler)` accepts any handler whose signature matches the signal.
- `@export`/plain signal helpers stay on top of the new machinery.
- No per-payload-kind runtime files/spaghetti; dispatch is compile-time codegen using the signal's declared parameter types.
- Lifetime rules: handlers execute immediately in the emitting call stack on the same thread; no queued events. Pointer payloads retain caller responsibility for referent lifetime.

## Non-goals

- GC/event queues, async delivery, or marshalling across machines.
- `struct` value payloads (besides pointers) — ownership of captured struct by value during emit is deferred.
- Multi-site unsubscribe; `signal_off_instance` remains instance/name based.
- Pointer payload ownership tracking (the address is borrowed, as with `ptr<T>` generally).

## Constraints

- Signals are **instance-scoped**: instance = self signal handle.
- Existing public v1.6.0 shapes remain source-compatible.
- Runtime dispatch must use the declared C++ cast type per signal so that `ptr` arguments do not overflow.
- No invalid free-running pointer writes; pointer parameters are treated immutable references to caller-held data.
- String signals use `signal_on_str_instance` backward-compatible helper.
- Docs claim only what actually works.

## Runtime redesign (Option B, generic dispatch)

- **Simplify `InstanceSignalEntry`** to `instance`, `name`, `once`, `hptr` runtime-pointer only (old `kind`, `arity`, `mh1–mh4`, `i32h`, `strh` become unused).
- **Registration helper**: one generic variadic-ish binding: `signal_on_instance(int32_t instance, Str name, H handler)` (template deduced) that stores `e.hptr = reinterpret_cast<void*>(handler)`.
- **`signal_off_instance`**: instance/name based erase, no kind filter.
- **Emission codegen**: in `_gen_emit`, for a known class signal, emit a compile-run loop:
  - iterate registry
  - if instance+name match, treat `e.hptr` as `void(*)(payload types...)`, invoke with evaluated arguments (typed), and handle `once`.
  - No runtime dispatch helper needed; supporting bool/poise is automatic due to compile typing.
- **Void payload** uses `void(*)()` dispatch signature (falling back).
- Built-in `signal_on_instance` type becomes a declaratively polymorphic hook: if the supplied callback is any `FuncType` returning void, the checker accepts it without fixed payload mismatch.

## Artifact areas of code

- `runtime/vanta_runtime.hpp`: registry simplification.
- `compiler/type_checker.py`: allow any supported payload types and `_register_class_signals` allowlist broadening, plus `signal_on_*` special-case argument checking for callable matching.
- `compiler/codegen_cpp.py`: `_gen_emit` dispatch code generation; registration via template.
- `compiler/typesys.py`: no new structs.
- Tests: `tests/test_classes.py` and `tests/test_type_checker.py` new pointer/bool/void regression coverage.
- Docs: `LANGUAGE_REFERENCE.md`, `README.md`? (remove overstatement), `CHANGELOG.md`, `ROADMAP.md`.

## Anti-goals

- No new memory model for signal callbacks.
- No promises of `str` payload multi-tracking beyond 2–4 `str` types (allowed only where dispatch cast inference works).
- No dynamic partial-argument shifting.

## Approaches considered

1. **Generic codegen dispatch** (recommended): store opaque `void*` handler and typed-cast invocation at emit sites. Gives broad payload coverage with minimal runtime churn; semi-prototype shipped during the first signal iteration as a generic handler path for I32 payload.
2. **Typed runtime helpers per type** (current): works for i32, but cannot scale to pointer/bool without combinatorial overloads.
3. **Generic runtime helpers via `va_list`**: type-unsafe; rejected.

## Decision override point

Please confirm **(A) single new primitive payloads only** vs **(B) generic codegen dispatch**. Approach B is chosen by current name but assumes you want pointer payloads even when they coexist with other types.

## Next Implementation Behavior

1. Update allowlist: single + multi 2–4 of any i32/str/bool/ptr (no value copies).
2. Add runtime `signal_on_instance` template and `signal_off_instance` generic loop.
3. Add codegen dispatch to the `_gen_emit` runtime registry loop.
4. Add tests (void, ptr, bool plus multi combinations) and cleanup allowlist docs.
5. Document safety boundaries and pointer ownership expectations.

If you approve this design, invoke `writing-plans`, write the concrete plan, and then execute it TDD-style.

Do you approve this design?