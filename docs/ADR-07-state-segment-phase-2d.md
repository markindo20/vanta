# ADR-07: Host-owned state segment for hot reload (phase II.D)

## Status
Delivered as v1.2.0.

## Context
Phase II.C (v1.0.x) proved the host can load a rebuilt shared unit
in-process and hand the previous Arena pointer to `vanta_migrate(prev)`.
However, state stored in a private per-generation arena was lost on every
swap, and named shared arenas were per-allocation and fragile on Windows
because closing the last handle destroyed the mapping. Vanta needed one
stable, host-owned byte buffer that outlives every generation and is rebound
into each unit before `vanta_run_main`.

## Decision
The host (`cmd_hot`) owns one flat `ctypes.create_string_buffer` per
`vanta hot` session and calls the generated `vanta_bind_state(base, bytes)`
before each generation. The runtime exposes `g_state_header` / `g_state_base`
and `state_arena()` allocates from that segment via a new `Arena(char*,
int32_t)` view constructor. On Windows the named mapping's `CreateFileMappingA`
handle is kept open for the segment's lifetime (a view alone does not keep a
named mapping alive); on POSIX `shm_open`/`mmap` is used.

Segments carry a 64-byte `StateHeader` (magic, version, bytes, used,
alloc_count, layout_count, flags) followed by up to 256 layout entries of
`(size, align, type_tag)` (stride 12), so user data starts at
`kStateDataOffset = 3136`. `raw_alloc` bumps a shared offset, records each
allocation's `(size, align, type_tag)`, and on replay verifies the sequence
matches; on a layout/type mismatch it keeps earlier bytes and appends new
values after `used`, printing a warning.

`hot_mode()` is driven by an explicit `vanta_set_hot(1)` call (Python's
`SetEnvironmentVariable` is not seen by MinGW/UCRT `getenv` after DLL
startup); `VANTA_HOT` remains a fallback. `request_host_reload()` sets a
`kStateFlagReload` bit the unit polls via `hot_should_reload()`. Units run on
the main thread; a watchdog thread polls source changes and calls
`vanta_request_reload()`.

`vanta_migrate(prev)` now calls the user-declared `__reload(prev)` when
present, otherwise is a no-op.

## Consequences
- State survives `vanta hot` rebuilds for programs using `state_arena()`.
- Outside `vanta hot`, `state_arena()` falls back to a private 1 MiB arena,
  so the same source runs under `vanta run`.
- Layout changes are detected conservatively (struct field changes with
  identical total size and type name are not detected).
- Cooperative reload requires user code to poll `hot_should_reload()`;
  otherwise the unit runs to completion.

## Related
ADR-03 (phase I supervisor), ADR-04 (shared arena), ADR-05 (phase II.C
migrate), ADR-06 (phase II.B in-process swap).
