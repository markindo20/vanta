# ADR-03: State-preserving hot reload (phase I delivery)

## Status
Phase I delivered as v0.93.0 (supervisor + incremental cache). State
survival remains open.

## Context
GDScript iteration latency is dominated by *editor play*, measured in
milliseconds; Vanta's rebuild currently measures seconds. v0.89.0 shipped a
content-addressed **build cache**; v0.81.0 shipped a **watch rebuild
loop**. Together these give fast-as-cache compile, but the supervisor
still relaunches the process, so global state (heap, arena, singletons,
the program entrypoint's context) is lost on every change. This is the
single usability gap that limits Vanta vs interpreted scripting languages.

## Goal (phase I scope delivered)
Provide a one-command `vanta run --hot` that:
  1. builds and launches the program through the existing cache;
  2. watches source + all sibling `.vnt` files;
  3. on change: rebuilds through the cache and relaunches a new child
     process, forwarding arguments/environment; and
  4. does not poll compiler failures forever (1 s back-off).

## Phase I limitation (documented)
State is **not retained**. The child process is terminated and a new one
started. Persistence of an `Arena`'s contents across a reload is explicitly
deferred to phase II.

## Deferred phases
### II.A - Shared-memory Arena
Move the `Arena`'s backing storage into a `vanta::SharedArena` opened via
OS shared memory (named mapping). On reload the new library reattaches to
the same name and reuses the allocation; gen `__reload(prev)` hook walks
through the old layout and rewrites references. Tricky because Vanta
struct layouts change across schema edits.

### II.B - Reload as shared library (`.dll`/`.so`/`.dylib`)
Compile the user unit as a shared library with exported `vanta_init_{ver}`.
The supervisor keeps the process alive, `dlopen`s the new library, swaps
the entry point pointer, and calls `vanta_migrate(prev_arena)`. State
survives because the host owns the arena.

### II.C - Source compatibility for `extern` reload
Extern libraries (SDL2, gamekit) are not hot-reloadable; the cache key
already pins their abs paths, so changing them forces a clean rebuild.

## Consequences of phase I
- No ABI changes to generated C++; runtime header unchanged for now.
- `--hot` reuses the cache, so second-and-beyond edits usually hit warm
  binaries in <100 ms (build cache hit) instead of seconds.
- State retention (goals II.A/II.B) is open; schedule as its own sprint
  before declaring Vanta "faster feedback than GDScript".
