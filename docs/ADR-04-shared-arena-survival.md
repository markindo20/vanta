# ADR-04: State-preserving hot reload, phase II (shared Arena and migrate hook)

## Status
Phase II.A substrate delivered as v0.94.0. Phase II.B (in-process lib reload)
delivered as v1.0.1. Phase II.C (migrate handoff) and Phase II.D (host-owned
state segment) delivered as v1.2.0: `vanta hot` binds one flat byte segment
into every generation and `state_arena()` replays the allocation layout
deterministically.

## Context
Phase I (ADR-03, v0.93.0) relaunches a child process on every source change,
discarding state. To beat interpreted scripting languages we must keep process
and Arena alive while refreshing user code. This ADR pins the design going
forward.

## Design

1. The Arena gains an optional **backing name**. `Arena(size, name)` attaches
   to (and creates if absent) a named shared-memory segment; no name means a
   private, process-local Arena (backwards compatible).

2. The supervisor owns the Arena and opens it before loading user code. State
   (a single game world in typical usage) lives there and survives across
   reloads when both sides agree on the segment name.

3. A newly compiled unit calls an exported `vanta_migrate(prev)` keyed by the
   schema hash before `main`. Phase II.A only ships the hook *signature* and a
   default byte-for-byte copy; deeper schema migration remains open.

4. Shared memory is OS-specific:
   - Windows: `CreateFileMapping` / `MapViewOfFile`
   - POSIX: `shm_open` / `mmap`
   Controlled by `#ifdef` in the runtime header.

## Decision
Ship phase II.A as `vanta::SharedArena` plus the documented `vanta_migrate`
entry-point stub in codegen. The supervisor pieces (II.B) follow later: a host
process, `dlopen`/`LoadLibrary`, and the symbol-rewrite loop that swaps entry
points in place.

## Explicit non-goals of II.A
- No ABI change to ordinary generated C++ (non-shared programs untouched).
- No `dlopen` host in this version.
- No migration beyond byte-for-byte memcpy fallback.

## Consequences
- Older binaries remain compatible (`Arena(n)` defaults private).
- Games may opt into persistent Arena with `Arena(262144, "game-world")`.
- Full sub-second reload-with-state waits on II.B, recorded as separate sprint.
