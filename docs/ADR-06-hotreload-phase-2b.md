# ADR-06: Hot-reload Phase II.B finished (in-process swap + migrate bridging)

## Status
Phase II.B delivered as v1.0.1.

## Overview
Phase II.B wires the host supervisor over the Phase II shared-unit ABI:
- `vanta hot <file>` drives rebuilds through `_build_cache_key` + OS shared segment.
- on each unit change, the host terminates the previous child (if any), then
  builds through the cache and loads the new shared library directly via
  `ctypes.CDLL`, invoking the unit's `vanta_migrate(prev)` hook before
  running `vanta_run_main()`.

## Remaining
- Full migrate body / state arena pointer handoff (elided) -> scheduled Phase II.C.
- Process-state retention on `__reload` default implementation.