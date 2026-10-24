# ADR-05: State-preserving hot reload phase II.C (supervisor body)

## Status
Phase II.C delivered: the host loads the rebuilt shared unit in-process and
hands the Arena pointer from the previous unit through `vanta_migrate(prev)`.
Memory for stored state continues to be obtained from a named shared Arena.

## Context
Phase II.A (v0.94.0) shipped `vanta::SharedArena`. Phase II.B (v0.94.2)
shipped a shared artifact ABI (`vanta_run_main`, `vanta_migrate(void*)`).
Phase II.B.1 (v0.95.0) proved the host can load that ABI in-process via
ctypes. This release finishes the loop: the previous unit's Arena pointer is
passed to `vanta_migrate` so it can reattach/reuse state.

## Design
- The host retains the previous library's `_migrate_from` return value but
  v0.94's ABI uses `vanta_migrate(prev)` with a pointer to the previous
  `Arena`. Application code owns that pointer and calls into the (still
  shallow) migrate body; the byte-for-byte default is provided only when
  a `prev` pointer is nonzero and the segment is mapped.

## Deliberate limits (0.97 Phase)
- `vanta_migrate` is still a no-op at the compiler default; games opt in by
  writing a `func __reload(prev: ptr<void>)` in their source.
- No capture of locals; state lives exclusively in the named Shared Arena.
