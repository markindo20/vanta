# Changelog

Notable changes to Vanta, newest first. Versions correspond to git tags.

## Unreleased

- **Deep signal payload types**: class signals now support up to four parameters and mixed types (`i32`, `u32`, `f32`, `f64`, `bool`, `str`, `ptr<T>`); emits use generated, typed dispatch over the instance signal registry.

  - Immutable `let` captures by value; `mut` captures shared by durable arena cell.
  - Escaping mutable captures remain valid through function return.
  - Existing non-capturing function pointers remain supported.
  - `ptr<Closure__N>` invocation via `v_invoke`.
  - Higher-order `func(...)` parameters do not accept capturing closures (diagnostic).
  - Integration tests: `test_closure_*`.

## v1.6.0 - 2026-10-26

- **Instance-bound signals and `@export` metadata are now fully consumable.**
- **Class-level signals:** declare a signal inside a class (`signal clicked(value: i32):`),
  then `emit clicked(value)` from one of its methods. The compiler lowers
  `emit` onto the per-instance handle (`v_self->v__sig_handle`) and the
  instance-signal registry, so `connect` queries fired by `emit` are scoped
  to that instance. Distinct class instances mint distinct handles.
- **Signal kinds:** a signal payload may be empty (void), a single `i32`, or a
  single `str`. `signal_on_instance`, `signal_on_once_instance`, and the
  `signal_emit*_instance` helpers set up callers by handle.
- **`@export`:** functions and class methods marked `@export` now get a real
  consumer — a C-ABI export wrapper (`vanta_export_<name>`, `extern "C"`) in
  shared/hot builds, plus the runtime metadata plumbing a host can use to look
  them up by name.
- **`emit` syntax:** new `emit` keyword. `emit clicked(v)` inside a method,
  or `emit b.clicked(v)` from arbitrary code, lowers to `signal_emit_instance`
  (and the void/str variants).
- **Signal _self_ mutation (pointer receivers):** all class methods now take
  `self` as a pointer internally, so `self.field = value` mutations are
  visible through the original instance instead of a copied value.
- Tests: 1016.

## v1.5.0 - 2026-10-25

- **Landed in v1.5.0:** per-field visibility (`pub`) for structs and classes;
  nested/dotted modules; `VANTA_PATH` search-path resolution; generic
  type-parameter constraints (`T: Copyable`, `T: Eq`, chained with `+`);
  top-level `mut`/`let` globals backed by the state segment (validated
  by hot reload); capturing lambdas/closures; reverse debugging in the DAP
  adapter; and the v1.4.0 package manager is now paired with improved GDB
  reverse-recording handling and game-kit visibility fixes.
- Closures capture analysis rewrites, closure struct allocation from the
  state arena, and closure calls through `ptr->v_invoke`.
- Generic constraints are enforced at both registration and instantiation
  time, including transitive `Arena` copyability rejection.
- Module loading now falls back through relative, `std/`, and `VANTA_PATH`,
  resolving dotted names to dotted paths.
- Tests: 1004.

## v1.4.0 - 2026-10-25

- **vanta pm: client-side package manager**. New `vanta pm` subcommand with
  declarative manifest (`vanta.toml`) and lockfile (`vanta.lock`).
  Subcommands: `init`, `add <sources>`, `install`, `remove <names>`,
  `list`, `lock`, `check`. Dependency sources: local paths, git URLs, and
  registry (via `VANTA_REGISTRY` env var). Transitive dependency resolution
  by reading each dependency's `vanta.toml` and merging into the root
  manifest. Backward compatible with `vanta get`. Zero central registry
  requirement for v1.4.0 (registry support via env var only).
- Added `tests/test_packages.py` covering manifest/lockfile IO, local-path
  fetching, transitive resolution, add/list/lock/check/remove/install, and
  error cases.
- Tests: 968 (945 + 23 package-manager tests).

## v1.3.0 - 2026-10-25

- **Classes — full model + tests**: `class` declarations with fields and methods,
  single inheritance (`extends`), construction via named arguments (flattening
  inherited fields), field read/write, `ptr<Self>` self parameter, method calls
  with inheritance resolution (base methods invoked on subclass instances).
- Added `tests/test_classes.py` with 9 tests (basic field read/write, method
  read/mutation/params, inheritance of fields and methods, missing/unknown
  field rejection).
- Tests: 945 (936 + 9 class tests).

## v1.2.0 - 2026-10-25

- **Phase II.D: state-preserving hot reload**. `vanta hot` owns one flat byte
  segment per session and binds it into every rebuilt generation.
  `state_arena()` allocates from it, so values survive a source change across
  reloads; `hot_should_reload()` lets a loop end the current generation when
  the host asks for a rebuild, and `__reload(prev)` runs once per generation.
  `--reloads N` runs deterministic build/swap cycles; `--state-size`,
  `--include-dir`, `--lib-dir`, and `--link` control the session.
- `Arena(bytes, "name")` maps a real OS shared segment (Windows file mapping
  with the handle retained across generations; POSIX `shm_open`/`mmap` on
  Unix) with a `StateHeader` + 256-entry layout table, so replay is
  deterministic and layout changes keep earlier bytes and append new ones.
- Tests: 936 (930 + 6 hot-reload/state tests in tests/test_hot.py).

## v1.1.1 - 2026-10-24

- **Lexical string interpolation is operational**: `"Hello {expr}"` lexes to
  `str_fmt("Hello {}", expr)` and resolves at compile-time; `{{` and `}}`
  escapes remain literal (via str_fmt's placeholder count).
- Tests: 930 (unchanged).

## v1.1.0 - 2026-10-24

- Onboarding pack v1: templates, quickstart docs, `vanta new --template/--interactive`, `vanta doctor --fix`, examples guide, VS Code snippets.
- Tests: 930 (unchanged).


- New CLI command `vanta get <path<|message|>url>` fetches a dependency into a local
  vendor directory and maintains `.vanta.lock`. Local paths and git URLs
  supported (depth-1 clone). No central registry yet.
- Tests: 930 (unchanged).

## v1.0.5 - 2026-10-24

- New CLI command `vanta get <path or url>` fetches a dependency into a local
  vendor directory and maintains `.vanta.lock`. Local paths and git URLs
  supported (depth-1 clone). No central registry yet.
- Tests: 930 (unchanged).

## v1.0.3 - 2026-10-24

- String interpolation `'Hello {expr}'` expands at lex-time to `str_fmt("Hello {}", expr)`.
  Supports `{{` / `}}` escapes; empty holes fall back to the literal text.
- 930 tests.

## v1.0.2 - 2026-10-24

- Richer strings and lexical string interpolation now wired into the lexer (`str_fmt`). Internals: incremental cache safe; tests 930.
- Patch released to push forward to v1(.0?) class development.
## v1.0.1 - 2026-10-24

- **Phase II.B finished**: `vanta hot` loads the rebuilt shared unit in-process, invokes `vanta_migrate(prev)` before `vanta_run_main`, and keeps the host alive across iterations; ADR-06 documents the path.
- Tests: 930.
- Roadmap: ADR-05/ADR-06 remain the schema-state contract.

## v1.0.0 - 2026-10-24

- String interpolation: `"Hello {expr}"` transforms to `str_fmt("Hello {}", expr)`
  at lex-time. Supports `{{` / `}}` escapes; avoids an interpolation by
  using non-brace text. (Validated during examples.)
- 930 tests total.

## v0.99.2 - 2026-10-24

- Richer string builtins: `str_sub`, `str_repeat`, `str_to_upper`, `str_to_lower`,
  `str_trim`, `str_index_of`, completing the string manipulation surface.
- 930 tests (unchanged).

## v0.99.0 - 2026-10-24

- State-preserving hot reload Phase II.C: persistent counter via named shared
  Arena survives across `vanta hot` invocations, plus docs contract.
- 930 tests (unchanged).

## v0.98.0 - 2026-10-24

- Shared-state hot path: new `examples/stateful_hot.vnt` demonstrates an
  `Arena(262144, name)` that maps a shared segment whose pointer survives
  across `--reload` rotations, and a short ADR documenting the contract.
- Tests: 930 in total (unchanged).

## v0.97.0 - 2026-10-24

- Hot-reload phase II.C: host passes previous unit handle into `vanta_migrate(prev)`; ADR-05 documents state contract and limitations.
- Tests: 930 in total (unchanged).

## v0.96.0 - 2026-10-24

- New builtin `str_fmt(...)` returns a Str (snprintf-backed). Uses the same
  compile-time `{}` placeholders as `print_fmt`/`write_fmt`, but is a value
  expression, so:
  - `let s = str_fmt("hello {}", 42)` builds labeled text for UI.
- Runtime: `vanta::str_fmt_impl`, allocates an owned Str (cap handled via
  snprintf sizing + safe realloc).
- Tests: 930 in total (unchanged; runtime exercised via example).

## v0.95.0 - 2026-10-24

- **Phase II.B host supervisor (Phase 1)**: new `vanta hot <file>` command (and `--hot` on `run`)
  loads each rebuilt shared unit's `vanta_run_main` into the host Python process
  via `ctypes.CDLL` (Windows/Linux host), then migrates state with the stub
  `vanta_migrate`. On source change it rebuilds through the incremental cache
  and hot-swaps the unit, keeping the OS-level parent alive.
  Phase II.C (surviving process state/Arena) is the next step — see ADR-03.
- Tests: 930 in total (unchanged — hot-loader smoke against the shared
  artifacts).

## v0.94.2 - 2026-10-24

- `vanta build --shared` produces a shared library (`.dll`/`.so`/`.dylib`)
  exporting `vanta_run_main` and `vanta_migrate`, the entry points the II.B
  supervisor will load. Builder debug flag and `--bundle` restored.
- 930 tests.

## v0.94.1 - 2026-10-24

- Bugfix: runtime shared Arena no longer references a member function's
  instance data from a static helper, fixing `vanta doctor` smoke on Linux.
- 930 tests; behavior identical.

## v0.94.0 - 2026-10-24:

- Arena gains a second constructor `Arena(size, name)` that attaches to a
  named shared-memory segment on POSIX; plain `Arena(size)` remains private.
  On platforms without OS shared memory the constructor falls back to a
  per-process heap buffer. `docs/ADR-04-...md` documents the phase II
  survival plan (shared arena, `vanta_migrate`, lib reload).
- Tests: 930 in total (unchanged); runtime compile checked via example.

## v0.93.0 - 2026-10-24

- Hot-reload phase I: `vanta run --hot` supervises the program and, on any
  source or sibling `.vnt` change, rebuilds through the incremental cache
  and relaunches a new child. ADR-03 documents the state-preservation work
  deferred to phases II.A/II.B (shared-memory Arena, lib reload).
- Tests: 930 in total (unchanged).

## v0.92.0 - 2026-10-24

- Richer signals: string-payload channels (`signal_emit_str` /
  `signal_on_str`) and one-shot subscriptions (`signal_on_once`) that
  auto-unsubscribe after the first emit.
- Tests: 930 in total (unchanged; signals exercised via example).

## v0.91.0 - 2026-10-24

- Non-capturing lambda literals: `func (x: i32) -> i32: return ...` may
  appear in expression position. Each literal desugars to a fresh top-level
  function (`__lambda_0`, …) with no environment capture; the expression
  is a normal function value, so it can be passed to
  `func(...) -> ...` callbacks. Lambda capturing (closing over locals) is
  deliberately deferred to a later release.
- Tests: 930 in total (unchanged; lambda exercised via examples).

## v0.90.0 - 2026-10-24

- Match arms may carry a guard: `Enum.Member(...) if expr:`. The guard is
  type-checked as bool in the arm's scope and compiled into the arm
  condition (`tag == Tag && expr`). Repeats of the same member behind
  different guards are allowed, so e.g. `State.Busy if n > 5:` and an
  unguarded `State.Busy:` can both cover the same tag.
- Tests: +1.

## v0.89.0 - 2026-10-24

- Incremental build cache: `vanta run` and `vanta build` use a content-
  addressed cache under `.vanta/cache/<key>/` keyed by source + dependency
  `.vnt` files + flags + version. A second run reuses the cached executable
  instead of recompiling; `--no-cache` / `--fresh` force rebuilds.
- Tests: 929 in total (unchanged).

## v0.88.0 - 2026-10-24

- Minimal signal/event bus: `signal_on(name, handler)` registers a Vanta
  function of type `func(i32) -> void`, and `signal_emit(name, value)`
  invokes every registered handler for that signal name. Independent
  runtime-side registration so any place with a Str can emit.
- Tests: 929 in total (unchanged; signals exercised via example).

## v0.87.0 - 2026-10-24

- `vanta watch` now scans every `.vnt` beneath the source file's directory
  and treats any of them as a triggering change, so editing an imported
  module rebuilds the program. Prints the file count in each rebuild
  banner; unchanged mtime leaves the loop quiet.
- Tests: 929 in total (unchanged; watcher extended).

## v0.86.0 - 2026-10-24

- String predicates join `str_concat`/`str_len`: `str_contains(s, sub)`,
  `str_starts_with(s, prefix)`, and `str_ends_with(s, suffix)` return bool.
- Tests: 929 in total (unchanged; runtime coverage exercised via example).

## v0.85.0 - 2026-10-24

- Runtime overflow checks for integer arithmetic. The compiler now emits
  `VANTA_CK_*_ADD/SUB/MUL` helper calls for fixed-size integer types
  (+,-,*), and the runtime header maps them to bounds-checked inline
  helpers when compiled with `-DVANTA_CHECKED_ARITH`, aborting on
  overflow, or to the plain operator otherwise.
- `vanta build`/`vanta run` accept `--checked` (and checkers default to
  `not --release`, so debug builds are checked automatically).
- Tests: 929 in total (unchanged; runtime checks exercised via example).

## v0.84.0 - 2026-10-24

- Generic functions close the generics arc. A declaration such as
  `func identity<T>(x: T) -> T` takes type parameters in scope in its
  parameter and return types, and each concrete call monomorphizes one
  C++ function (for instance `identity__g0`). Explicit arguments use
  `identity::<i32>(5)`; inference then defaults integer and float
  literals to `i32` / `f32`.
- Codegen skips the un-instantiated generic declaration and emits one
  function per instantiated combination.
- Tests: 929 in total (prior 924 + 5 new tests).
- Docs: LANGUAGE_REFERENCE gains a Generic functions subsection. Build
  uses 0.84.0; extension stays 0.43.0.

## v0.83.0 - 2026-10-24

- Debugger polish:
  - `_remote_target` accepts IPv6 bracket forms, comma- and space-separated
    targets, and dict aliases (`hostname`/`targetPort`).
  - Hit-count parsing accepts `% N`, `every N`, `hitcount N`/`hitcount: N`,
    and `hits N` in addition to the canonical operator forms.
  - Attach cleanup and error reporting remain intact on failure.
- Tests: 924 in total (new unit coverage for both areas).

## v0.82.0 - 2026-10-24

- `vanta repl` starts an interactive read-compile-run loop. Each program is
  read until a blank line, then type-checked and run. A lone sequence of
  statements is wrapped into `func main()`, and a full program (with
  declarations) is taken verbatim and given a no-op main when it lacks one.
  EOF or Ctrl+C ends the session. This is a first interactive slice of the
  feedback-loop track.
- Tests: 918 in total (917 + 1 new test).

## v0.81.0 - 2026-10-24

- `vanta watch file.vnt` rebuilds and reruns on source change. `vanta run
  --watch file.vnt` does the same from a single command. Both poll for
  modification and rerun the build/run pipeline; Ctrl+C stops the loop. This
  is the first piece of the debugger/feedback-loop track: a hot-reload
  skeleton driven by rebuild-on-change rather than an in-process compiler.
- Tests: +1 new test in test_cli for the watch loop.
- Build uses 0.81.0. Extension stays 0.43.0.

## v0.80.0 - 2026-10-24

- Generic structs join generic enums. A declaration such as
  `struct Pair<T, U>: left: T, right: U` takes type parameters that
  substitute into field types, and construction monomorphizes one layout per
  set of arguments: `Pair<i32, str>`, `Pair<f32, bool>` and so on.
- Type arguments follow the same rules as generic enums: expected type
  first, explicit `::<...>` always works, inference from field values
  otherwise (int and float literals default to `i32`/`f32`). Recursive
  references are safe behind a pointer, `next: ptr<Node<T>>`.
- Codegen emits one `Pair__gN` C++ struct and constructor per concrete
  argument combination; diagnostics keep the source spelling.
- Tests: 916 in total. New type-checker and codegen coverage for generic
  structs, plus an integration test exercising inference, explicit args, a
  pointer-recursive node, a generic-enum field, and equality.
- Docs: LANGUAGE_REFERENCE, README, ARCHITECTURE, ROADMAP, and EDITOR notes
  describe the new capability. Build uses 0.80.0; the VS Code extension stays
  0.43.0 (no LSP change).

## v0.79.0 - 2026-10-24

- `vanta test` now runs test files concurrently (`--jobs N`, 0 = auto) and
  prints per-file timings plus a total wall-clock summary.
- Failed and errored cases print their captured output beneath the result
  instead of interleaving with other files.
- New `--junit FILE` writes a JUnit XML report (`testsuite`/`testcase`
  with `failure` and `error` elements) for CI dashboards.
- Tests: 906 in total. New coverage for discovery, JUnit output, and the
  parallel runner end to end. Build 0.79.0; extension stays 0.43.0.

## v0.78.0 - 2026-10-24

- `vanta fmt` accepts a directory and formats every `.vnt` file under it,
  reporting a per-file result and a non-zero exit when any file fails.
  `--check` works in directory mode too.
- Build 0.78.0; extension stays 0.43.0.

## v0.77.0 - 2026-10-24

- `vanta check` type-checks directory targets in parallel (`--jobs N`,
  0 = auto) and reports results in sorted order.
- Build 0.77.0; extension stays 0.43.0.

## v0.76.0 - 2026-10-23

- Compile-time integer overflow guard. Constant integer additions,
  subtractions, and multiplications that fall outside their type's range
  raise `integer overflow in '+'`. Division or modulo by a constant zero
  likewise raises `division by zero`.
- Tests: 903 in total. New tests cover integer overflow and division by
  zero in the type checker.
- Notes: this is one slice of track 3 (language safety). Build uses 0.76.0;
  the VS Code extension stays 0.43.0 (no LSP change).

## v0.72.0 - 2026-10-23

- Performance: a process-global parse cache keyed by `(path, sha256(text))`
  reuses parsed `ModuleInfo` across requests and documents, cutting repeated
  lexer/parser work in the LSP. `vanta check --timing` reports frontend
  milliseconds.
- Tests: 901 in total. New test ensures distinct cache keys for changed
  content.
- Docs: `docs/EDITOR.md`, `editors/vscode/README.md`, README, ROADMAP,
  `docs/ARCHITECTURE.md`, and this file describe the cache and timing flag.
  The VS Code extension is 0.43.0.

## v0.71.0 - 2026-10-23

- Go-to-implementation. `textDocument/implementation` jumps from a type
  declaration (`struct`/`enum`) to its concrete construction sites, or from
  a function declaration to its call sites.
- Tests: 900 in total. New tests cover construction and call sites.
- Docs: `docs/EDITOR.md`, `editors/vscode/README.md`, README, ROADMAP,
  `docs/ARCHITECTURE.md`, and this file describe the feature. The VS Code
  extension is 0.42.0.

## v0.70.0 - 2026-10-23

- Rename safety. Cross-module renames propagate across every open document and
  imported module. A rename is refused when the new name collides with an
  existing declaration visible from the current module.
- `prepareRename` already returns the exact symbol span, so editors select only
  the identifier.
- Tests: 898 in total. New tests cover cross-file propagation and collision
  refusal.
- Docs: `docs/EDITOR.md`, `editors/vscode/README.md`, README, ROADMAP,
  `docs/ARCHITECTURE.md`, and this file describe the change. The VS Code
  extension is 0.41.0.

## v0.69.0 - 2026-10-23

- Code actions beyond import fixes. Added a quick fix that changes a
  `let x: T = value` annotation when the initializer type does not match
  (e.g. `let x: i32 = "hi"` offers `change annotation to str`).
- Tests: 896 in total. New test covers the annotation-change action.
- Docs: `docs/EDITOR.md`, `editors/vscode/README.md`, README, ROADMAP,
  `docs/ARCHITECTURE.md`, and this file describe the new action. The VS
  Code extension is 0.40.0.

## v0.68.0 - 2026-10-23

- Incremental diagnostics on `didChange`. Range-based content changes are now
  applied precisely (LSP byte/character offsets) instead of dropping them,
  so live typing produces accurate diagnostics after every edit.
- Tests: 895 in total. New test covers an incremental range edit that turns
  a valid buffer into a type-mismatch diagnostic.
- Docs: `docs/EDITOR.md`, `editors/vscode/README.md`, README, ROADMAP,
  `docs/ARCHITECTURE.md`, and this file describe the change. The VS Code
  extension is 0.39.0.

## v0.67.0 - 2026-10-23

- Type definition. `textDocument/typeDefinition` jumps from a variable or
  field access to the declaration of the type it names (e.g. `let p: Point`
  or `v.energy` -> `struct Point`).
- Tests: 894 in total. New tests cover a type name, a variable, a field of
  a user type, and a builtin returning none.
- Docs: `docs/EDITOR.md`, `editors/vscode/README.md`, README, ROADMAP,
  `docs/ARCHITECTURE.md`, and this file describe type definition. The VS
  Code extension is 0.38.0.

## v0.66.0 - 2026-10-23

- Completion for import paths. Inside `import "..."` the editor offers
  sibling `.vnt` files plus everything under `std/` (filtered by prefix).
- Signature help now works for imported functions, both unqualified (`spawn(...)`)
  and through an alias (`g.spawn(...)`).
- Tests: 890 in total. New tests cover completion of sibling and std-module
  paths, the path-replacing text edit, and signature help on imported names.
- Docs: `docs/EDITOR.md`, `editors/vscode/README.md`, README, ROADMAP,
  `docs/ARCHITECTURE.md`, and this file describe the additions. The VS
  Code extension is 0.37.0.

## v0.65.0 - 2026-10-23

- Semantic tokens for import paths. The `import "path"` string literal is now
  classified as a string token, so the editor can style it distinctly.
- Workspace symbol filtering. The `workspace/symbol` request accepts a `kind`
  parameter (an array of LSP `SymbolKind` values) to restrict results to
  functions, structs, enums, fields, etc.
- Tests: 885 in total. New tests cover import path semantic tokens and
  workspace symbol kind filtering.
- Docs: `docs/EDITOR.md`, `editors/vscode/README.md`, README, ROADMAP,
  `docs/ARCHITECTURE.md`, and this file describe the new features. The VS
  Code extension is 0.36.0.

## v0.64.0 - 2026-10-23

- Import hover and go-to-definition. Hovering an `import` path shows the
  resolved file (or "unresolved"). `Go to Definition` on an import path
  jumps to the target file.
- Tests: 883 in total. New tests cover hover on a resolved import, hover on
  an unresolved import, definition jump to the imported file, and
  definition returning none for an unresolved import.
- Docs: `docs/EDITOR.md`, `editors/vscode/README.md`, README, ROADMAP,
  `docs/ARCHITECTURE.md`, and this file describe import hover/definition.
  The VS Code extension is 0.35.0.

## v0.63.0 - 2026-10-23

- Selection ranges. The server answers `textDocument/selectionRange`, so the
  editor can expand a selection from the word under the cursor to its line,
  the enclosing indentation blocks, and the whole file.
- Tests: 879 in total. New tests cover nested blocks, the `if` header, a
  blank line, and an empty document.
- Docs: `docs/EDITOR.md`, `editors/vscode/README.md`, README, ROADMAP,
  `docs/ARCHITECTURE.md`, and this file describe selection ranges. The VS
  Code extension is 0.34.0.

## v0.62.0 - 2026-10-23

- Folding ranges. The server answers `textDocument/foldingRange`, so the
  editor folds a function body, a struct or enum body, a nested block, and a
  `match` arm from the line that opens it.
- The ranges are computed from indentation, so they keep working while a line
  is half typed and a file that does not parse still folds. Blank lines at
  the end of a block are left out, so a fold ends on the last real line.
- Runs of comments fold as a `comment` region, and a run of consecutive
  `import` lines folds as an `imports` region.
- Tests: 875 in total. New tests cover the capability, a function body,
  nested blocks, a struct body, comment and import runs, and the blank-line
  trimming.
- Docs: `docs/EDITOR.md`, `editors/vscode/README.md`, README, ROADMAP,
  `docs/ARCHITECTURE.md`, and this file describe folding ranges. The VS Code
  extension is 0.33.0.

## v0.61.0 - 2026-10-22

- Document links. The server answers `textDocument/documentLink`, so an
  `import` path is a link: the editor can follow it to the file it names.
- The target is the file the loader resolved, so a relative import, an
  `import "std/..."` from the standard library, and an aliased import all
  point at the real file rather than at a guessed path.
- A path that does not resolve stays a link with no target and a tooltip
  that says so, so a typo is visible without opening the Problems panel.
- Tests: 870 in total. New tests cover the capability, a relative import,
  an aliased import, an unresolved import, and the highlighting of a struct
  field and of a function.
- Docs: `docs/EDITOR.md`, `editors/vscode/README.md`, README, ROADMAP,
  `docs/ARCHITECTURE.md`, and this file describe document links. The VS Code
  extension is 0.32.0.

## v0.60.0 - 2026-10-22

- Document highlighting. The server answers `textDocument/documentHighlight`,
  so the editor highlights every occurrence of the symbol under the cursor in
  the file that is open.
- The occurrences are scope-aware, from the same resolver that powers
  references and rename: a shadowing local with the same name is not
  highlighted, a field is highlighted only where the receiver has the
  declaring struct's type, and a declaration is distinguished from its uses.
- The declaration is reported as text and each use as a read, so the editor
  can colour them differently. A word that resolves to nothing falls back to
  every textual occurrence of that word, which keeps the feature useful while
  a line is still being typed.
- Tests: 865 in total. New tests cover the capability, a local with its
  declaration and uses, a shadowing local that is not mixed in, and the
  fallback for an unknown word.
- Docs: `docs/EDITOR.md`, `editors/vscode/README.md`, README, ROADMAP,
  `docs/ARCHITECTURE.md`, and this file describe document highlighting. The
  VS Code extension is 0.31.0.

## v0.59.0 - 2026-10-22

- A type hierarchy. The server answers `textDocument/prepareTypeHierarchy` and
  the two follow-up requests, so the editor can show which structs hold a
  type and which types a struct holds.
- Vanta has no inheritance, so the hierarchy is the one the language
  actually has: a struct that holds another by value. A `ptr<T>` field does
  not count, because a pointer does not embed the struct.
- The relation is resolved by name, across modules, so a struct in another
  file is found.
- Tests: 862 in total. New tests cover the capability, the structs that
  hold a type, the types a struct holds, and a pointer field that is not a
  holding.
- Docs: `docs/EDITOR.md`, `editors/vscode/README.md`, README, ROADMAP,
  `docs/ARCHITECTURE.md`, and this file describe the type hierarchy. The VS
  Code extension is 0.30.0.

## v0.58.0 - 2026-10-22

- A call hierarchy. The server answers `textDocument/prepareCallHierarchy` and
  the two follow-up requests, so VS Code can show who calls a function and
  what a function calls.
- The hierarchy is scope-aware, because it comes from the same resolver that
  powers references and rename: a call in another module is a caller, a
  local with the same name is not, and a function passed around as a value is
  not a call either.
- The caller's name and the line of the call are both reported, so the
  editor can show "main calls helper, at line 12" and jump to it.
- Tests: 860 in total. New tests cover the capability, the callers of a
  function, the functions it calls, and a function with neither.
- Docs: `docs/EDITOR.md`, `editors/vscode/README.md`, README, ROADMAP,
  `docs/ARCHITECTURE.md`, and this file describe the call hierarchy. The VS
  Code extension is 0.29.0.

## v0.57.0 - 2026-10-22

- A code lens above every function that is used somewhere. The editor shows
  how many places call it, and clicking the count opens the list of them.
- The count is the number of *uses*, not of occurrences, and it is
  scope-aware: a call in another module counts, a shadowing local with the
  same name does not, and the declaration itself does not count. The count
  therefore matches what **Find All References** would list.
- The lens appears on the function's name and carries the locations, so the
  editor can jump straight to a use.
- Tests: 858 in total. New tests cover the capability, the count and the
  locations, and a function nobody calls.
- Docs: `docs/EDITOR.md`, `editors/vscode/README.md`, README, ROADMAP,
  `docs/ARCHITECTURE.md`, and this file describe the code lens. The VS Code
  extension is 0.28.0.

## v0.56.0 - 2026-10-22

- Inlay hints. The server answers `textDocument/inlayHint`, so the editor
  shows the type of a local that has no type annotation right next to it.
- The type is inferred, not spelled out: `let x = add(1, 2)` shows `i32`,
  `let e = Enemy(hp: 1)` shows `Enemy`, `let h = e.hp` shows `i32`, and a
  literal shows `str`, `f32`, or `bool`. A local that already has an
  annotation gets no hint, because the type is already written down.
- The inference reuses the same scope-aware resolver that powers references
  and rename, so a local's type is the one the compiler will actually use,
  including a type that comes from another module.
- Tests: 856 in total. New tests cover the capability, the inferred types of
  a call, a constructor, a field, and a literal, and the fact that an
  annotated local gets no hint.
- Docs: `docs/EDITOR.md`, `editors/vscode/README.md`, README, ROADMAP,
  `docs/ARCHITECTURE.md`, and this file describe inlay hints. The VS Code
  extension is 0.27.0.

## v0.55.0 - 2026-10-22

- A source formatter. `vanta fmt <file>` rewrites a file in place, and
  `vanta fmt --check <file>` reports whether it is already formatted
  without touching it. The editor gets the same thing: the server answers
  `textDocument/formatting`, so **Format Document** and format-on-save work.
- The formatter normalizes the whitespace around a program and never the
  program itself: every logical line is indented with four spaces per block
  level, a line that continues an expression keeps its alignment relative to
  the line that opened it, comments keep their text and their place, trailing
  whitespace is removed, runs of blank lines collapse to one, and the file
  ends with exactly one newline.
- Only the indentation changes, so the block structure the parser sees is
  the same before and after. A file that does not parse is refused rather
  than reformatted, because the formatter cannot know what was meant, and
  formatting is idempotent: formatting a formatted file changes nothing.
- Tests: 855 in total. New tests cover the formatter's rules, its refusal to
  touch a file that does not parse, its idempotence, the CLI command, and
  the editor request.
- Docs: `docs/EDITOR.md`, `editors/vscode/README.md`, README, ROADMAP,
  `docs/ARCHITECTURE.md`, and this file describe the formatter. The VS Code
  extension is 0.26.0.

## v0.54.0 - 2026-10-22

- Semantic highlighting. The server answers `textDocument/semanticTokens/full`,
  so the editor colours Vanta code by what each name *is* rather than by how
  it is spelled.
- The classification is scope-aware, because it comes from the same resolver
  that powers references and rename: a function, a struct, an enum, a
  constant, a parameter, a local, a struct field, an enum member, and a module
  alias each get their own kind. A local named `hp` and a field named `hp`
  are no longer the same colour, and a shadowing inner local is told apart
  from the outer one.
- Builtins are marked as library code, so `print_i32` and `Vec2` read as
  built-in rather than as user code. Keywords, operators, strings, numbers,
  and comments keep their lexical colouring, and a declaration is marked as
  such.
- The tokens are computed from the buffer as it is on screen, so an unsaved
  file is highlighted the way it is written.
- Tests: 834 in total. New tests cover the capability, the classification of
  declarations and uses, builtins, and a buffer that does not parse.
- Docs: `docs/EDITOR.md`, `editors/vscode/README.md`, README, ROADMAP,
  `docs/ARCHITECTURE.md`, and this file describe semantic highlighting. The
  VS Code extension is 0.25.0.

## v0.53.0 - 2026-10-22

- Workspace symbols. The server answers `workspace/symbol`, so VS Code's
  **Go to Symbol in Workspace** (Ctrl+T) searches the whole project.
- The search covers every `.vnt` file under the workspace root, plus the
  imported modules of the open documents when the editor did not send a
  root. Functions, structs, enums, constants, struct fields, and enum members
  are all symbols, each with its kind and the module or declaration that
  contains it.
- Matching is forgiving: an exact name comes first, then a prefix, then a
  case-insensitive substring, then a loose subsequence so `dmg` still finds
  `damage`. Results are capped and ranked, so the closest match is on top.
- The file list is cached for a few seconds and each file is re-parsed only
  when it changes, so typing in the symbol picker stays fast. An unsaved
  buffer is searched as it is on screen, not as it is on disk.
- Tests: 831 in total. New tests cover the capability, declarations across
  two files, struct fields and enum members, prefix and substring matching,
  an unsaved buffer, and a workspace without a root.
- Docs: `docs/EDITOR.md`, `editors/vscode/README.md`, README, ROADMAP,
  `docs/ARCHITECTURE.md`, and this file describe workspace symbols. The VS
  Code extension is 0.24.0.

## v0.52.0 - 2026-10-22

- Quick fixes. The server answers `textDocument/codeAction` with `quickfix`
  actions for the diagnostics it already publishes, so VS Code's light bulb
  (and `Ctrl+.`) can repair the problem under the cursor.
- Unknown names suggest the closest visible name: locals, parameters,
  declarations, imported symbols, module aliases, builtins, and type names
  (`valeu` becomes `value`). A missing struct field or enum member suggests the
  nearest member of that type, both on a member access (`e.hpp`) and on a
  constructor label (`Enemy(hpp: 1)` becomes `Enemy(hp: 1)`, `Color.reed`
  becomes `Color.red`).
- An assignment to an immutable local offers `let` to `mut` at the declaration,
  including a write through a field (`e.hp = 5`), where the root binding is what
  must become mutable. Parameters and loop variables are left alone because
  there is no `let` to rewrite.
- Actions replace only the identifier (or the `let` keyword). The server
  computes the range from the buffer, because a missing member is reported on
  the dot and an unknown constructor label is reported on the callee. The best
  match is marked `isPreferred`, and up to three suggestions are offered.
- The server recomputes the diagnostics it needs from the buffer and also uses
  the ones the client sends in the request context, so a client that sends no
  context still works. A request that asks for another kind than `quickfix`
  gets nothing back.
- Tests: 827 in total. New tests cover the capability, each fix, a client that
  supplies its diagnostics, a stale client diagnostic, a module alias, the
  receiver type used for field suggestions, the requested action kind,
  parameter refusal, and an unrelated diagnostic that produces no action.
- Docs: `docs/EDITOR.md`, `editors/vscode/README.md`, README, ROADMAP,
  `docs/ARCHITECTURE.md`, and this file describe quick fixes. The VS Code
  extension is 0.23.0.

## v0.51.0 - 2026-10-22

- References and rename. The server answers `textDocument/references`,
  `textDocument/prepareRename`, and `textDocument/rename`; VS Code's **Find All
  References** and **Rename Symbol** now work on Vanta source.
- References are scope-aware rather than a text search. A symbol is identified
  by its declaration, so renaming an outer local leaves a shadowing inner local
  alone, and renaming a function does not touch a parameter or field that
  happens to share its name.
- Rename covers top-level functions, structs, enums, and constants, including
  imported ones; parameters, locals, `for` variables, and match-arm bindings;
  struct fields (declaration, reads, writes, and constructor labels such as
  `Enemy(hp: 1)`); enum members (declaration, `Color.red`, payload
  constructors, and `match` patterns); module aliases (the `as` name and every
  `alias.` use, including type annotations and match patterns); and type names
  in annotations, return types, fields, arrays, lists, pointers, extern
  declarations, constructor calls, `arena.alloc::<T>()`, and nested member
  access.
- Edits span files: renaming an imported function or field changes the
  declaration in its module and every use in the files the project index can
  load (open documents and their imports). Field and member references are
  only renamed when the receiver's type can be established from an annotation,
  a constructor, a parameter, a loop element, an index, or a function return
  type; unresolved receivers are left alone rather than guessed.
- The server refuses to rename builtins, unresolved names, invalid
  identifiers, and keywords, and `prepareRename` returns the exact word range
  and placeholder so the editor's rename box opens on the right text.
- Tests: 817 in total. New tests cover the capabilities, scope and shadowing,
  imported functions and module aliases, struct fields with writes and
  constructor labels, enum members with payloads and match patterns through an
  alias, type annotations, nested imported fields and list elements,
  `prepareRename`, refusals, and a buffer that does not parse yet.
- Docs: `docs/EDITOR.md`, `editors/vscode/README.md`, README, ROADMAP,
  `docs/ARCHITECTURE.md`, and this file describe references and rename. The VS
  Code extension is 0.22.0.

## v0.50.0 - 2026-10-22

- Signature help. An open call now lists its parameters and highlights the one
  being typed. The server answers `textDocument/signatureHelp` and asks the
  client to open it on `(` and again on every `,`.
- It covers local and imported functions (`add(`, `math.add(`), builtin
  functions, function values held in parameters or locals, builtin methods
  (`xs.push(`), user struct constructors (`Enemy(`), and enum payload members
  (`Shape.label(`). Nested calls show the innermost signature, calls that span
  lines work, and a comma inside a string, a `#` comment, or nested brackets
  does not move the highlight.
- The scan reads the buffer left to right with the lexer's rules for comments
  and strings, so it keeps working while a line is half typed. Callees are
  resolved through the existing project index, which means an unsaved imported
  file offers the same signatures completion already uses. A `func` declaration
  line does not offer its own signature.
- Tests: 807 in total. New tests cover the capability, a user function with the
  first and second parameter active, a call split across lines, nested calls,
  commas in strings and comments, struct construction, builtin functions and
  methods, imported functions, enum payloads, function-typed values, a
  declaration line, and a position outside any call.
- Docs: `docs/EDITOR.md`, `editors/vscode/README.md`, README, ROADMAP, and this
  file describe signature help. The VS Code extension is 0.21.0.

## v0.49.0 - 2026-10-22

- A distribution GDB is found. The probe looked for an upper-case `GDB` in
  `--version`, and a Linux build prints `GNU gdb (Ubuntu 15.0.50)` in lower
  case, so a perfectly good `/usr/bin/gdb` was reported as missing. The banner
  is now matched without regard to case.
- A bare breakpoint number means the Vanta line. GDB takes the generated C++
  file as its current source on Linux, so `break 3` typed at the `vanta debug`
  prompt landed in generated code there. The session now selects the Vanta file
  before the prompt appears, through GDB's Python API so nothing is printed; a
  debugger without Python keeps the old behaviour instead of failing to start.
- A list expands. A `List<T>` in the Variables view opens into its items -
  `[0]`, `[1]`, and so on - and an item that is a struct opens again into its
  fields. A list stops at its first hundred items and a final row counts the
  rest, so a long list cannot flood the view.
- A string reads as text. A `str` field of a struct showed the address of its
  characters, sometimes with a symbol annotation, instead of the text; it now
  shows `"abc"`, and a null string shows `""`.
- A handle shows braces. A type with no layout to expand, such as `Arena`,
  showed an empty cell; it now shows `{...}`.
- Tests: 796 in total. New tests cover string display with and without a symbol
  annotation, a null string, list expansion for integers, strings, and structs,
  an empty list, a handle, the helpers, the GDB probe, and the source prelude.
  The command-line test that drives `vanta debug` now skips when no GDB is
  installed instead of failing the suite, which is what made CI red on machines
  without one; the CI job also lifts Ubuntu's ptrace restriction so the attach
  test can run, and the SDL probe tolerates another platform's `sdl2-config`
  on `PATH`.
- Docs: `docs/DEBUGGER.md` documents how structs, lists, and strings read, and
  the limitation about lists is corrected. README, CHANGELOG, ROADMAP,
  docs/EDITOR.md, and docs/ARCHITECTURE.md are updated. The VS Code extension
  is 0.20.0. Reverse debugging and MSVC/PDB support remain future work.

## v0.48.0 - 2026-10-22

- Values in hex. The Variables view has a hex toggle: with it on, an integer
  shows as `0xff` instead of `255`, in locals, arguments, globals, the fields
  of a struct, and the result of an expression in the Debug Console. Floats,
  strings, and addresses keep their own form. The session advertises
  `supportsValueFormattingOptions`, so an editor offers the toggle.
- Tests: 782 in total. New tests cover the formatting helper, a variables
  request that asks for hex, a struct field in hex, an evaluate request in
  hex, and the decimal display when no format is asked for.
- Docs: `docs/DEBUGGER.md` documents the toggle; README, CHANGELOG, ROADMAP,
  docs/EDITOR.md, and docs/ARCHITECTURE.md are updated. The VS Code extension
  is 0.19.0. Reverse debugging and MSVC/PDB support remain future work.

## v0.47.0 - 2026-10-22

- Breakpoints on instructions. The disassembly view can put a breakpoint on
  a single address, and an address breakpoint takes a condition, a hit
  count, and a log message like a source breakpoint does. The program
  stops with the same reason and the same breakpoint id.
- Instruction stepping. Stepping in and over has an instruction
  granularity, so one instruction of the machine code is run instead of
  one Vanta statement.
- The session now advertises what it can actually do. It says it supports
  `setExpression` (editing a watch value worked but was not offered),
  stepping granularity, and instruction breakpoints.
- Docs and tests. `docs/DEBUGGER.md` documents the disassembly workflow and
  states the toolchain limit accurately. 776 tests total, including
  instruction stepping, an address breakpoint that stops where it was set,
  a reference that is not an address, and the advertised capabilities.

## v0.46.0 - 2026-10-22

- Recording a session. `vanta dap --log session.log` writes every DAP
  message and every line of GDB traffic to a file, one per line, so a
  session that misbehaves can be read afterwards instead of guessed at. In
  VS Code, `vanta.debug.logFile` turns the same recording on for the next
  session. Logging never changes what a session does: if the file cannot
  be written, the session carries on.
- Docs and tests. `docs/DEBUGGER.md` documents the recording, and
  `docs/EDITOR.md` documents the setting. 772 tests total, including a
  session that records itself and checks that the conversation is in the
  file. Reverse debugging and MSVC/PDB support remain future work.

## v0.45.0 - 2026-10-22

- Debugger readiness. `vanta doctor` now reports whether a debug session
  will work: it prints the debug toolchain and the debugger it found, so a
  machine that would fail a session fails at a command prompt instead:
  `debug build: ok (g++: /usr/bin/g++)` and `debugger: GDB 16.3
  (/usr/bin/gdb)`. When either is missing, the line says what is missing.
- Docs and tests. `docs/DEBUGGER.md` opens with the check. 771 tests total,
  including a session that runs `vanta doctor` and a test for the debugger
  description. Reverse debugging and MSVC/PDB support remain future work.

## v0.44.0 - 2026-10-22

- Program arguments reach the program. `vanta run game.vnt -- --level 2`
  passes `--level 2` to the program instead of failing, and `vanta debug`
  hands the same arguments to GDB, quoted the way GDB expects, so
  `show args` in a session shows them.
- Floats read like Vanta. A `f32` or `f64` in the Variables view is shown
  with the same six decimals `print_f32` and `print_f64` use, instead of the
  raw binary value.
- Docs and tests. 768 tests total, including tests for the argument
  handling and the float formatting. Reverse debugging and MSVC/PDB support
  remain future work.

## v0.43.0 - 2026-10-22

- A Globals scope. The program's constants are listed in their own scope,
  with the names and types the programmer wrote, so `const MAX_ENEMIES = 10`
  shows up as `MAX_ENEMIES: i32 = 10`. A constant is a value the program can
  read but not change, so the scope is read-only.
- Docs and tests. `docs/DEBUGGER.md` documents the Globals scope. 764 tests
  total, including a session that reads the constants. Reverse debugging and
  MSVC/PDB support remain future work.

## v0.42.0 - 2026-10-22

- Debugging from the terminal. `vanta debug game.vnt` builds the program with
  Vanta source locations and starts GDB on it. GDB opens on the Vanta
  program: `break 3` sets a breakpoint on the third line of the Vanta file,
  `list` shows the Vanta source, and the backtrace names the Vanta
  functions. The command takes `--exec` for GDB commands, `--gdb`,
  `--build-dir`, the usual include and link options, and passes the rest to
  the program.
- The entry point belongs to the Vanta file. GDB takes the program's current
  source file from its entry point, so the native entry point is now
  attributed to the Vanta file. A debugger prompt no longer starts in the
  generated C++, which is what made `break 3` and `list` point at the wrong
  file. The rest of the generated wrapper stays attributed to the generated
  file, so it is still visibly distinct from Vanta frames.
- Docs and tests. `docs/DEBUGGER.md` documents the terminal workflow. 763
  tests total, including a session that drives `vanta debug` and checks that
  a breakpoint lands on the Vanta file. Reverse debugging and MSVC/PDB
  support remain future work.

## v0.41.0 - 2026-10-22

- Editing a struct field. A field of a struct can be changed from the
  Variables view, and it follows the same rule as the source: a field of a
  `mut` struct can be edited, exactly like `p.hp = 99` in the program, and a
  field of a `let` struct is refused.
- Editor snippets. The VS Code extension offers a configuration snippet for
  each kind of session: a local launch, an attach to a running program, and
  a launch that debugs a program on another machine.
- Docs and tests. `docs/DEBUGGER.md` documents editing a field. 762 tests
  total, including stdio sessions that edit the field of a mutable struct and
  that refuse the field of an immutable one. Reverse debugging and MSVC/PDB
  support remain future work.

## v0.40.0 - 2026-10-21

- Remote debugging. A launch configuration may name the machine that runs the
  program, and the debugger drives it over the GDB remote protocol. The
  program is still built locally, because that is where the debug information
  comes from; the connection is made when the session starts, the
  breakpoints are set on the remote program, and the session continues it.
  This is how a build for a console or a board is debugged.
- Docs and tests. `docs/DEBUGGER.md` documents remote debugging. 760 tests
  total, including unit tests for the remote target and a stdio session that
  reports a remote machine that cannot be reached. Reverse debugging and
  MSVC/PDB support remain future work.

## v0.39.0 - 2026-10-21

- Faster conditions. A breakpoint condition is evaluated in the frame that
  was hit, which stopped the program briefly at every hit. As soon as the
  variables are in scope, the debugger hands the same expression to GDB, and
  GDB then evaluates it without stopping the program at all when the
  condition is false. A breakpoint that also carries a hit count keeps the
  adapter-side path, because the count needs to see every hit.
- Watching a struct field. A field of a struct can be watched the same way a
  local can, so a program can stop when a health value changes.
- An LLDB fallback. On macOS, where GDB is rarely installed, the debugger
  accepts `lldb-mi`, the machine-interface front end that ships with LLDB.
  It covers the core of the protocol; a few inspection requests are not part
  of it.
- Docs and tests. `docs/DEBUGGER.md` documents the faster conditions, the
  field watches, and the LLDB fallback. 756 tests total, including stdio
  sessions that watch a struct field and that stop on a condition which only
  becomes true later. Remote debugging, reverse debugging, and MSVC/PDB
  support remain future work.

## v0.38.0 - 2026-10-21

- The Variables view speaks Vanta. A struct is a node that expands into its
  fields, with the names the programmer wrote, and a struct field that is
  itself a struct expands again. An enum shows the member it holds instead of
  a number, a `str` shows its text instead of the reference-counted struct
  behind it, and a `List` shows how many items it holds.
- Docs and tests. `docs/DEBUGGER.md` documents how the data is shown. 754
  tests total, including unit tests for the struct and enum layouts and stdio
  sessions that expand a struct and read an enum member. Remote debugging,
  reverse debugging, LLDB, and MSVC/PDB remain future work.

## v0.37.0 - 2026-10-21

- Attach to a running program. A debug session can attach to a program that
  is already running, which is how a game is debugged: build it with
  `vanta build --debug`, start it, and attach to the process. The attach
  request names the executable that is running, because the breakpoints and
  the stack are resolved from its debug information. An attached session
  never starts the program, and stopping the session leaves it running. On
  Windows, a program that never waits can refuse the attach; one that sleeps
  between frames attaches fine.
- Per-thread stepping. A step now acts on the thread the editor asked for,
  instead of on whichever thread GDB happened to have selected.
- Disassembly. The adapter answers the disassembly request, so an editor can
  show the machine code of the current instruction.
- Hover values. The adapter now answers the evaluate request that editors
  send while hovering a variable.
- A failing adapter says so. An error that escapes the request handlers is
  printed on stderr instead of ending the session silently.
- Docs and tests. `docs/DEBUGGER.md` documents attaching, per-thread
  stepping, and the disassembly view. 751 tests total, including a stdio
  session that attaches to a running program, watches it, and detaches.
  Remote debugging, reverse debugging, LLDB, and MSVC/PDB remain future work.

## v0.36.0 - 2026-10-21

- Breakpoint lines. The adapter knows which lines of a Vanta file hold a
  statement and answers the breakpoint-locations request, so an editor greys
  out the lines that cannot hold a breakpoint instead of setting one that
  never hits.
- Run to cursor. The adapter answers the jump-targets request with the lines
  of the function that is running, and a jump moves the program counter
  there and lets the program continue.
- Exception breakpoints. The debugger offers filters for C++ exceptions
  thrown and caught, which are GDB catchpoints. Vanta has no exceptions of
  its own, but the runtime and any C library reached through `extern` can
  raise one.
- Docs and tests. `docs/DEBUGGER.md` documents the breakpoint lines, run to
  cursor, and exception breakpoints. 749 tests total, including unit tests
  for the source-line map and stdio sessions that list the valid breakpoint
  lines, offer jump targets, jump, and set an exception breakpoint. Attach
  and remote debugging, reverse debugging, LLDB, and MSVC/PDB remain future
  work.

## v0.35.0 - 2026-10-21

- Editable variables. A local can be changed from the Variables view, but
  only where Vanta allows it: only a binding declared with `mut` may be
  written, and an immutable binding is refused with a clear message. GDB
  itself would allow the write, because the generated C++ variable is not
  `const`; the adapter is what keeps Vanta's promise. A value that cannot
  fit the variable's type is refused too.
- Data breakpoints. A local can be watched, and the session stops when its
  value is written. The watch is a GDB watchpoint on the variable's address,
  and the address is only handed out to clients that ask for data
  breakpoints.
- Registers and memory. The adapter answers the registers request with the
  processor registers and their values, and it answers raw memory reads, so
  an editor that shows memory can read it.
- Thread events. A thread that starts or exits is reported to the editor,
  and a stop now says whether every thread is stopped.
- Docs and tests. `docs/DEBUGGER.md` documents editing, data breakpoints,
  registers, and memory. 742 tests total, including unit tests for the
  value/type rules and the mutable-local table, plus stdio sessions that
  edit a variable, refuse an immutable one, watch a value, list the
  registers, and read memory. Exception breakpoints, attach and remote
  debugging, reverse debugging, LLDB, and MSVC/PDB remain future work.

## v0.34.0 - 2026-10-21

- Breakpoint depth. The debug adapter now supports conditional breakpoints,
  hit counts, log points, and function breakpoints. Conditions and log
  messages are written in Vanta terms (`hp > 0`, `len(items) == 3`); the
  adapter maps them onto the generated names and evaluates them in the frame
  that was hit, because GDB cannot evaluate a Vanta condition before the
  program runs. A log point prints its message and lets the program continue,
  so a session never stops at that line.
- Watch expressions. The **Watch** scope lists the expressions the editor
  asked for and re-evaluates them every time the program stops. Expressions
  that are not in scope show `<not available>` instead of failing the
  session.
- Restart. The `restart` request rebuilds the program from the current
  source, reloads the symbols, re-creates the breakpoints, and runs it again,
  so an edit can be tried without ending the session.
- Better hit reporting. Stopped events carry `hitBreakpointIds`, and Vanta
  names are shown for module functions (`geometry.area`).
- Docs and tests. `docs/DEBUGGER.md` documents the new breakpoint kinds,
  watch expressions, and restart. 729 tests total, including unit tests for
  the expression translation, the hit-condition forms, and the log-message
  interpolation, plus stdio sessions that exercise log points, conditions,
  hit counts, function breakpoints, watch expressions, and restart against a
  real GDB. Editable variables, data and exception breakpoints, attach and
  remote debugging, reverse debugging, LLDB, and MSVC/PDB remain future work.

## v0.33.0 - 2026-10-21

- Native debugger. `vanta dap` is a Debug Adapter Protocol server backed by
  GDB/MI2. It builds the requested Vanta program as an unoptimized native
  executable, sets breakpoints by Vanta source path and line, and translates
  GDB stacks, scopes, variables, stepping, pauses, and process exit into DAP.
  `python -m compiler dap` provides the Python-only fallback.
- Source mapping. Debug builds emit absolute `#line` directives around
  functions, statements, and match arms, so GDB reports Vanta files and lines
  directly. The generated wrapper and entry point stay attributed to the
  generated `main.cpp`. Debug compiles use
  `-O0 -g3 -fno-omit-frame-pointer`; release builds are unchanged.
  `vanta build --debug` exposes the same source-mapped build.
- Debugger features. Line breakpoints work in the entry file and imported Vanta
  files. The adapter provides stack traces, **Locals** and **Arguments**
  scopes (using Vanta names without the generated `v_` prefix), continue,
  pause, step over, step into, step out, `stopOnEntry`, program stdout/stderr
  in the debug console, and clean terminate/disconnect. User output is
  forwarded from both GDB output channels; the `(gdb)` prompt is filtered.
- Toolchain handling. GDB discovery accepts `vanta.debug.gdbPath`,
  `VANTA_GDB`, a GDB beside the C++ compiler, WinLibs/MSYS2 installations, or
  `gdb` on `PATH`, and skips candidates that fail a startup probe. The
  debugger requires a GCC or Clang toolchain because MSVC emits PDB files,
  which GDB does not read. `vanta doctor` and normal builds are unchanged.
- VS Code client. The extension version is 0.4.0. It registers the `vanta`
  debugger type, a launch-configuration provider, and a debug-adapter factory
  that reuses the language server's executable/Python discovery. A new
  `vanta.debug.gdbPath` setting selects GDB; `vanta.server.path` works for both
  LSP and DAP.
- Docs and tests. New `docs/DEBUGGER.md` covers VS Code, editor-agnostic DAP,
  source mapping, GDB discovery, and troubleshooting. `docs/EDITOR.md`,
  `docs/ARCHITECTURE.md`, README, and roadmap are updated. 710 tests total,
  including DAP framing, GDB/MI parsing, debug source markers, a real GDB
  breakpoint/source-mapping test, and a stdio DAP session that launches,
  stops, inspects locals, continues, and disconnects. Conditional breakpoints,
  watch expressions, editable variables, attach/remote debugging, LLDB, and
  MSVC/PDB remain future work.

## v0.32.0 - 2026-10-21

- Language server. `vanta lsp` speaks the Language Server Protocol over
  stdin/stdout with full-document text sync. Diagnostics reuse the real lexer,
  parser, loader, and type checker, so editor errors match `vanta check`. The
  server also supports `python -m compiler lsp` for environments where only
  the Python interpreter is easy to locate.
- Editor features. Completion covers keywords, builtins, declarations,
  parameters, local variables, module aliases, enum members, struct fields,
  and common builtin methods on `List`, `Arena`, `StrBuilder`, `Vec2`, `Vec3`,
  and `Quat`. Hover reports signatures and types; go-to-definition resolves
  declarations, locals, imports, enum members, and struct fields; document
  symbols include struct fields and enum members nested under their type.
- Unsaved buffers. The loader accepts in-memory source overlays, so
  diagnostics, completion, and navigation use the editor's current buffer
  rather than the last saved file. This includes unsaved imported files and
  files that exist only as overlays.
- Tolerant editing. Completion and navigation build a source index directly
  from the AST, with a line-based fallback while a declaration is incomplete.
  Positions are converted between LSP's UTF-16 offsets and Vanta's 1-based
  Unicode positions.
- VS Code client. `editors/vscode/` is now a compiled language client. It
  discovers `vanta` from `vanta.server.path`, a workspace virtualenv, `PATH`,
  or a Python interpreter that can import the compiler; logs the resolved
  command to the **Vanta** output channel; and exposes **Vanta: Restart
  Language Server**. The extension version is 0.3.0.
- Packaging and CI. CI compiles the TypeScript client and packages the VSIX;
  the release workflow builds the extension and attaches the VSIX to the
  GitHub release with the wheel and sdist. `MANIFEST.in` includes the
  extension source in the sdist.
- Docs and tests. `docs/EDITOR.md` documents installation, discovery,
  settings, features, limitations, and troubleshooting. README, roadmap, and
  architecture notes are updated. 692 tests total, including protocol-level
  LSP tests, loader-overlay tests, unsaved-buffer diagnostics, and UTF-16
  position conversion. Debugger support was the next milestone.

## v0.31.0 - 2026-10-21

- Generic enum declarations. `enum Option<T>:` and `enum Result<T, E>:`
  declare type parameters, and payloads may use them anywhere a type is
  accepted: `Some(T)`, `Ok(T)`, `Err(E)`, `Cons(T, Seq<T>)`. Type arguments
  are written in angle brackets (`Option<i32>`, `Option<Option<i32>>`), and
  `Option<i32>` and `Option<str>` are distinct, nominally different types.
  v0.31.0 adds generics only to enum declarations; generic structs and
  functions remain out of scope.
- Constructor inference and explicit arguments. `Option.Some(5)` infers
  `Option<i32>` from its payload. `Option.None`, `Result.Ok`, and
  `Result.Err` take missing parameters from an expected type - an annotation,
  return type, struct field, function argument, list/array element,
  assignment, or either side of `==`/`!=`. When no context supplies a
  parameter, the diagnostic names it and shows the explicit form:
  `Option.None::<i32>()`, `Result.Err::<i32, str>("missing")`.
- Instantiation rules. Each concrete instance is monomorphized with its own
  layout, tags, and constructor helpers; generated names are internal and
  diagnostics keep the source spelling. Matches resolve against the concrete
  instance while still checking exhaustiveness by member. Type arguments obey
  module privacy, payloads must remain copyable and non-void after
  substitution, recursive by-value instantiation is rejected with a
  store-behind-a-pointer hint, and `VantaTag` remains reserved for payload
  enums.
- Standard library. `stdlib/option.vnt` ships `Option<T>` (`None`/`Some(T)`)
  and `stdlib/result.vnt` ships `Result<T, E>` (`Ok(T)`/`Err(E)`) as ordinary
  generic enums, not compiler-special-cased types. Imports starting with
  `std/` resolve from the checkout or the installed wheel after checking for
  a sibling file, so projects can vendor their own copy. The wheel and sdist
  include the library, and `vanta doctor` reports its location.
- Examples and docs. `examples/option_result.vnt` covers constructor
  inference, explicit type arguments, nested error payloads, and exhaustive
  matches; its output and the new tutorial/reference snippets are frozen in
  the integration suite. The reference, tutorial, README, roadmap, and
  changelog are updated. 674 tests total; the frozen pong, strike, and
  breakout runs are unchanged.

## v0.30.0 - 2026-10-21

- Modules, namespaces, and privacy. A file may start with `module name`;
  its declarations are private unless marked `pub`. `pub` works on functions
  (including `system`/`component`), structs, enums, constants, and `extern`
  blocks. Module names are unique, and the declaration must be the first
  declaration in its file. `module`, `pub`, and `as` are now reserved words.
- Qualified imports. `import "math.vnt" as math` exposes public names through
  the alias: `math.add(...)`, `math.Point(...)`, `math.Shape.Square(5)`, and
  `math.CONST`. A plain `import "math.vnt"` brings public names into the
  importing file's bare namespace. Aliases may not collide with a top-level
  declaration; a local declaration may not silently shadow an unqualified
  import; two unqualified imports with the same name are an error when used,
  and the fix is to qualify with an alias.
- Backward compatibility. Files without a `module` declaration keep the
  original flat, all-public import behaviour, including transitive visibility
  and the old duplicate-name errors. The game kit and every existing example
  compile unchanged.
- Privacy checks. Private symbols cannot be imported or reached through an
  alias. Public declarations cannot expose private types in explicit
  parameter, return, field, payload, or constant types, or through an inferred
  function or constant type. Extern C names and the entry `main` keep their
  ABI names; other module declarations are rewritten to unique internal names
  and diagnostics map them back to source names. Module-scoped declarations
  with the same source name in two modules coexist.
- Examples and docs. `examples/modules_demo/` covers qualified and unqualified
  imports, a private helper behind a public function, a module constant, and a
  payload enum crossing a boundary; its output is frozen in the integration
  suite. The reference, tutorial, README, roadmap, and architecture notes are
  updated, and the VS Code grammar highlights the new keywords. 641 tests
  total; the frozen pong, strike, and breakout runs are unchanged.

## v0.29.1 - 2026-10-20

- Accept a UTF-8 byte-order mark at the start of source files. Windows
  editors and PowerShell may write one; it is now ignored instead of producing
  `unexpected character '\ufeff'` at `1:1`.
- Diagnostics now print the offending source line and a caret at the reported
  column for lexer, parser, loader, and type-checker errors. 619 tests total.

## v0.29.0 — 2026-10-20

- Explicit enum values. `Member = n` sets an `i32` value and following
  members without a value continue from `n + 1`; duplicate and out-of-range
  values are compile errors. `enum_to_i32` returns the explicit value (or the
  tag for a payload enum).
- Payload enums. A member written `Member(Type, ...)` carries associated
  data; `Name.Member(value, ...)` constructs it, and `match` destructures it
  with positional bindings: `Shape.Circle(center, radius):`. `_` discards a
  value, binding counts are checked, and exhaustiveness covers payload
  members. An arm with several comma-separated patterns cannot bind names.
- Representation and equality. Plain enums remain fixed-`int32_t` C++
  `enum class` values and still cross `extern` boundaries. A payload enum is
  a tagged struct; `==`/`!=` compare the tag and active payload, so every
  payload type must support equality. Payload enums have no C representation
  and are rejected in `extern` signatures. Payload types must be declared
  before the enum and must be copyable and non-void; `Arena` payloads are
  rejected.
- Examples and docs. `examples/enums_advanced.vnt` exercises explicit values,
  struct/str payloads, wildcard bindings, equality, and `enum_to_i32`; the
  reference, README, and roadmap are updated. 613 tests total; the frozen
  pong, strike, and breakout runs are unchanged.

## v0.28.0 — 2026-10-20

- Installable Vanta. `pip install vanta-lang` (or `pipx install vanta-lang`)
  now installs the `vanta` command without a checkout. A `setup.py` build hook
  copies `runtime/vanta_runtime.hpp` and the game kit into the wheel as
  `compiler/runtime/` and `compiler/templates/`, and `MANIFEST.in` keeps the
  same files in the sdist. The driver resolves either layout, so a checkout and
  an installed wheel behave the same.
- `vanta doctor` reports the Python and C++ compiler versions, the resolved
  runtime header and game kit paths, compiles a one-line runtime probe, and
  makes a best-effort SDL2 / SDL2_ttf / SDL2_image check. Missing SDL only
  warns: non-game programs need nothing beyond the C++ compiler.
- `vanta new` keeps working from an installed wheel because the starter points
  at the game kit inside the installed compiler.
- Packaging checks. CI gains a `package` job that builds the wheel and sdist,
  runs `twine check`, installs the wheel into a fresh venv, and exercises
  `--version`, `doctor`, a hello program, `new`, `check`, and a headless game
  run on Linux and Windows. `.github/workflows/release.yml` repeats the smoke
  test on version tags, attaches the wheel and sdist to the GitHub release, and
  publishes to PyPI through Trusted Publishing when the `PUBLISH_PYPI`
  repository variable is set.
- Metadata is release-ready: SPDX `MIT`, license files, classifiers, project
  URLs, and `setuptools>=77`. 588 tests total.
- Docs: README and the tutorial lead with `pipx install vanta-lang`,
  `vanta doctor`, and the installed-command workflow; the reference gains an
  installing/running section and the architecture notes describe the build
  hook and layout resolution.

## v0.27.0 — 2026-10-20

- Breakout polish. `examples/breakout.vnt` now has three walls of 4, 5, and 6
  rows (125 bricks total), with diagonal gaps in the later walls. Clearing a
  wall serves the next one; clearing the third wins. The score carries across
  walls, and the HUD shows the current level and best score.
- Pause. P or Space freezes the paddle, ball, collisions, and ball animation
  while events and drawing keep running; a centered `PAUSED` label shows the
  state. Esc and the close button still quit. `gamekit/sdl.vnt` gains the
  `KEY_SPACE` and `KEY_P` symbols.
- Score persistence. The best score is read from `breakout.score` at startup
  and only rewritten when the run beats it. The optional second program
  argument changes the score path, so tests and headless runs stay out of the
  working tree; `breakout.score` is git-ignored.
- Per-sound gain. `gamekit/audio.vnt` gains
  `sound_load_gain(audio, path, gain)`: it loads a WAV like `sound_load` and
  scales every mono S16 sample in place. Gain is clamped to 0..1, so it
  attenuates without clipping; `sound_load` remains the full-volume shortcut.
- Floating-point determinism. The driver now passes `-ffp-contract=off` to
  GCC/Clang (and `/fp:strict` to MSVC), so `f32` expressions are not
  contracted into fused multiply-adds. The breakout autopilot therefore
  reaches the same frame 5969 on x86-64 and Apple arm64; without the flag the
  FMA-capable Mac took 7070 frames.
- The breakout headless probe now freezes the three-wall clear
  (`cleared 125 lives 3 level 3 best 125 frames 5969`) and then loads a higher
  score in a one-frame run to prove it is not overwritten. The sound probe
  loads a stereo file at half gain and checks the folded samples scale from
  6000 to 3000, then loads it at gain 2.0 and checks the clamp keeps the
  original 6000 peak. 586 tests total.
- Docs: README, tutorial, reference, roadmap, and the kit comments describe
  levels, pause, persistence, and gain. The frozen pong and strike runs are
  unchanged; breakout's frozen run deliberately records the new mode.

## v0.26.0 — 2026-10-20

- `str` now owns its storage automatically. It is an immutable,
  reference-counted value: literals and command-line arguments are zero-copy
  static views, while `str_concat`, `to_str_i32`, `to_str_f32`, `file_read`,
  and `StrBuilder.to_str()` return owned buffers. Copies share the buffer and
  the last copy frees it.
- The fixed 64 KiB process-lifetime string pool is gone. Long-running string
  loops no longer exhaust a global limit, `file_read` reads arbitrarily large
  files (up to the `i32` length limit), and `str_pool_reset()` remains only as
  a compatibility no-op that invalidates nothing.
- `file_read` and `file_write` stay byte-exact: embedded NUL bytes are kept in
  the returned `str`, counted by `str_len`, and written by `file_write`. C
  functions and `print_str` still see a `const char*` and stop at the first
  NUL.
- The C boundary is unchanged for existing code: extern declarations keep
  `str` as `const char*`, direct calls convert at the call site, and a C
  function returning `str` has its result copied into an owned value. Small
  generated adapters let extern functions with `str` signatures be used as
  `func(str)` values and let Vanta functions/builtins with `str` signatures be
  passed to C callbacks.
- `Arena` now constructs and destroys non-trivial element types, and
  `arena.reset()` runs those destructors. `alloc::<str>`, arrays of `str`, and
  structs containing `str` therefore work without leaking or double-freeing.
- 15 new tests (13 net, after replacing the two pool-exhaustion tests): large
  file reads, pool-free allocation loops, string reset compatibility,
  builder/arena lifetime, arena string destruction, owned `List<str>`, const
  strings, embedded NUL round-trips, extern `str` arguments, extern `str`
  function values, and C callbacks with `str` arguments and returns. 586
  total.
- Documentation: the reference, tutorial, architecture notes, README, roadmap,
  and file-I/O example all describe owned strings; every new snippet was
  executed with its output frozen.

## v0.25.0 — 2026-10-20

- Checked pointer access: `p.at(i, size)` reads, writes, and compound-assigns
  through a `ptr<T>` after checking `0 <= i < size`. The pointer has no length
  of its own, so the caller supplies the accessible count. `ptr<void>` is
  rejected, nested array elements work
  (`rows.at(row, row_count).at(column)`), and the new `examples/ptr_at.vnt`
  demonstrates the read/write paths.
- An out-of-bounds pointer index stops the program with
  `vanta: pointer index I out of bounds (size N) at line L`. The raw `p[i]`,
  `ptr_cast::<T>(p)`, and `ptr_offset(p, n)` escape hatches are unchanged, and
  `size` remains a programmer promise — null is still `ptr_is_null`'s job.
- 10 new tests: pointer `at` reads/writes/compound assignment, nested array
  access, `ptr<void>` rejection, size type checking, the `let`-pointer and
  temporary-pointer write rules, generated-code shape, the new example, and
  out-of-bounds read/write failures. 573 total.

## v0.24.1 — 2026-10-20

- `vanta game.vnt` is shorthand for `vanta run game.vnt`: a bare source path
  now compiles and runs. Installing the checkout once with
  `python -m pip install -e .` creates the `vanta` command, so games launch
  without repeating `python main.py` or spelling out link flags.
- `vanta new game.vnt` writes a playable starter — a paddle, a falling block,
  three lives, and a frame-limited mode for headless smoke tests. Its imports
  point at the checkout's game kit relative to the new file.
- The driver links SDL2, SDL2_ttf, and SDL2_image automatically when it sees
  their extern block names. Explicit `--link` values still work and are
  deduplicated; custom C libraries still use `--include-dir`, `--lib-dir`,
  and `--link`. On Windows the compiler's own `bin` directory is added to the
  child `PATH`, so the SDL DLLs are found without a manual environment setup.
- `vanta build --bundle` (Windows) writes `build/<name>/<name>.exe`, walks the
  executable's PE imports with `objdump`, and copies every non-system DLL it
  loads — SDL2, SDL2_ttf, SDL2_image, and their codec dependencies — beside
  the executable. It also copies `examples/assets` and the kit font, so the
  bundled example games run from a folder with only Windows on `PATH`.
- Compile failures now print a platform-specific install hint for missing SDL
  development libraries (MSYS2 package names on Windows, `brew` on macOS, and
  `apt-get` on Linux), and MSVC users are told why the MinGW import libraries
  cannot be used.
- 7 new tests: command normalization, auto-link detection and ordering, custom
  externs staying unlinked, explicit-link deduplication, starter generation,
  overwrite protection, and a Windows bundle that runs with a system-only
  `PATH`. 563 total.

## v0.24.0 — 2026-10-20

- The fourth playable game. `examples/strike.vnt` is a one-screen wave
  shooter: left/right arrows (or A/D, or a gamepad stick/D-pad) move the
  ship, the cannon fires on a fixed cadence, and three waves of six saucers
  descend, drift, and bounce off the walls. A bolt destroys a saucer; a
  saucer that touches the ship or slips past the bottom costs one of three
  lives. Clear all eighteen to win. The ship is an animated four-frame
  strip, the saucers are one white texture tinted per wave, the HUD is
  `text_draw`, and the shot/hit/boom sounds are WAV files. With no input the
  autopilot lines up under the lowest saucer and clears the game without
  losing a life at frame 1020 — the suite freezes those counts. The game
  imports nine of the ten kit modules (all but `rng.vnt`) and links SDL2,
  SDL2_ttf, and SDL2_image.
- `gamekit/collide.vnt`, the tenth module, is pure Vanta with no externs and
  no SDL dependency: `collide_rects`, `collide_point`, `collide_circles`,
  and `collide_circle_rect`. Rectangles are `(x, y, w, h)`; edges that only
  touch are not overlaps, `collide_point` is half-open, and the circle tests
  compare squared distances, so none of them calls `sqrt`. The pure module
  gets its own headless test on every machine with a C++ compiler.
- New generated assets: `ship_anim.png` (four 24x24 frames), `enemy.png`,
  `laser.png`, and `laser.wav` / `hit.wav` / `boom.wav`, all from
  `examples/assets/gen_assets.py`.
- No compiler changes: the kit and the game are plain Vanta. The new tests
  are the collision semantics and the frozen strike run, for 556 total.
- Documentation: the game-kit chapters in the tutorial and reference now
  cover ten modules and collision, the README lists the fourth game and the
  ten-module kit, and the game-kit README documents the new helpers. Every
  new snippet was executed with its output frozen.

## v0.23.0 — 2026-10-20

- `extern` functions can return function values. A signature like `func
  signal(sig: i32, handler: func(i32) -> void) -> func(i32) -> void` now
  compiles: the generated `extern "C"` declaration folds the declarator into
  the name (`void(*signal(int32_t, void(*)(int32_t)))(int32_t)`) instead of
  emitting a bare function type where C needs a name. Returned values are
  ordinary function values — call them, store them, or hand them back to C.
  Pointer-to-function returns (`ptr<func(...)>`) and nested function-typed
  returns (`func() -> func() -> i32`) spell correctly too; an array or list
  of function values is still rejected as an extern return, since C cannot
  return those by value. `examples/extern_return.vnt` with
  `examples/extern_return_lib.c` is the buildable demo: C picks a function,
  returns null for an unknown id, and the program calls, compares, and
  null-tests the result.
- Function-value equality. `==` and `!=` compare function values by address;
  values of the same type are accepted, different signatures are a compile
  error, and ordering is rejected with a message pointing at `==`/`!=`. A
  null built with `ptr_null::<func(...)>()` compares equal to any null of its
  type, and `ptr_is_null` now accepts function values as well as pointers, so
  the explicit null test needs no cast or sentinel. Struct equality follows:
  a function-valued field no longer blocks comparing the whole struct, because
  the field compares by address like any function value. Still no closures:
  equality compares plain function pointers.
- Tests: 11 new cases cover the checker, generated declarations (including
  nested and pointer-to-function returns), equality emission, struct equality
  with a function field, and a real C fixture that hands function pointers
  back across the boundary. 554 total.
- Docs: the reference's Function values section gains the equality rules and
  a frozen snippet, its Extern section gains a runnable `signal` example, and
  the tutorial, README, and version banners follow. Every new snippet is
  executed with its output frozen; the frozen pong and breakout runs are
  unchanged.

## v0.22.0 — 2026-10-19

- Sprite animation. `gamekit/anim.vnt` (a ninth module) is a frame clock over
  `tex_draw_src` for a horizontal strip of equal frames. `anim_new(count, fw,
  fh, fps)` describes the strip; `anim_tick(anim, dt)` advances the clock by
  the time the game hands it and *returns* the updated clock — structs are
  values, so `anim = anim_tick(anim, dt)` is the idiom — the frame wraps, and
  `anim_draw` blits the current frame through `tex_draw_src`. Nothing reads a
  wall clock, a dead texture draws nothing, and an empty strip (zero frames)
  stays on frame 0. The assets script grows `ball_spin.png` (four 10x10
  frames, a highlight orbiting the ball), and `examples/breakout.vnt` now
  spins its ball from it with a fixed 1/60 s step. The animation is purely
  visual: the physics is untouched, and the frozen headless run still prints
  exactly `cleared 40 lives 3 frames 2064`.
- Text sprites. `gamekit/text.vnt` gains `TextSprite` — the render-once path
  for text that redraws every frame. `text_sprite` renders one string into a
  texture (same colours as `text_draw`, with `text_sprite_ok` as the test and
  a dead sprite for a failed font or an empty string), `text_sprite_draw`
  blits it with no TTF call at all, and `text_sprite_free` destroys it;
  `text_draw` is unchanged. The alternative — a bounded cache keyed by
  (font, size, string, colour) — was weighed and rejected: the kit has no
  hidden state to put it in, pool strings can be invalidated under a cache,
  and an explicit handle is the kit's shape with the same measured win.
- The measured before/after ships as `examples/text_bench.vnt`: one 24 pt
  string, both paths, counts stable and milliseconds the machine's. On the
  development machine (headless dummy driver, software renderer) 40000 draws
  went from ~130 ms via `text_draw` to ~4 ms via one sprite — about 30x. A
  smoke test asserts the two output lines' shape and never the numbers, the
  rule being that timings are never frozen. 3 new tests (543 total).
- Docs: the tutorial gains an Animated sprites section and the render-once
  paragraph in Text on screen; the reference's kit chapter lists nine
  modules, and both READMEs follow. Every new snippet is executed with its
  output frozen, and the frozen runs of pong and breakout are re-verified
  unchanged.

## v0.21.0 — 2026-10-19

- Game controllers. `gamekit/gamepad.vnt` (an eighth module) wraps SDL2's
  `SDL_GameController` API: `pad_open(index)` returns a `Pad`, with `pad_ok`
  as the test, `pad_attached` for the unplug check, and `pad_button` /
  `pad_axis` polling the current state. A missing controller — none plugged
  in, or an index out of range — opens *dead*, the same shape as a dead
  `Screen`, `Tex`, or `Sound`: every other call is a guarded no-op, so a
  keyboard-only machine stays playable. `pad_open` starts SDL's refcounted
  gamecontroller subsystem and `pad_close` stops it, so pads close before
  `screen_close`'s `SDL_Quit`. Axes stay raw — sticks span -32768..32767
  with 0 at rest, triggers 0..32767 — and the `PAD_BUTTON_*` / `PAD_AXIS_*`
  constants name the standard controls, extended share/paddle/touchpad
  buttons included. This is polling, not events: the event loop stays
  keyboard-focused.
- `examples/sdl_gamepad.vnt` (raw C calls, SDL2 core only) opens a controller
  by index and polls A, d-pad-left, the left stick, and the left trigger;
  with no controller it reports the dead path and exits cleanly. The two new
  headless tests open index 9999 — out of range on every machine — so their
  frozen output is hardware-independent, and the existing games still build
  without the module. 2 new tests (540 total).
- The tutorial gains a Gamepads section (dead-handle semantics, raw axis
  ranges, polling vs events), the reference adds the module to the kit
  chapter, and both READMEs count eight modules. The new snippets join the
  frozen-output doc checks.

## v0.20.0 — 2026-10-19

- Sprites. `gamekit/image.vnt` (a seventh module) wraps SDL2_image:
  `tex_load` decodes a PNG or BMP file into a `Tex` — a handle plus the
  decoded size; a missing or unreadable file comes back dead, so `tex_ok`
  is the test. `tex_draw` blits at natural size, `tex_draw_src` blits one
  rectangle of the texture (sprite-sheet frames), and `tex_draw_ex` rotates
  by a `f64` angle in degrees and/or flips with the new `SDL_FLIP_*`
  constants, about the texture's own centre — and none of the three take a
  scratch rect: SDL copies the rectangles during the call, so the helpers
  build them on a tiny transient arena. `tex_tint` and `tex_alpha` set a
  colour and an opacity multiplied into every later draw of that texture.
  Importing the module means linking SDL2_image; `sdl.vnt` gains
  `SDL_QueryTexture`, `SDL_RenderCopyEx`, the colour/alpha mods, and
  `SDL_DestroyTexture` (moved there from `text.vnt`, where it would have
  collided in the flat namespace).
- Sound files. `gamekit/audio.vnt` gains `sound_load` / `sound_ok` /
  `sound_play` / `sound_free`: 16-bit PCM WAV at 44.1 kHz, mono or stereo,
  decoded by `SDL_LoadWAV_RW` into a buffer SDL allocates. Stereo is folded
  to mono in place at load, so the `Sound`'s byte count halves; any other
  rate, sample format, or channel count loads as a dead sound, and playing
  or freeing one is a no-op — games stay quiet on machines with no device.
  The game holds the `Sound` across plays and hands the buffer back with
  `sound_free`.
- `examples/sdl_texture.vnt` (raw C calls, SDL2_image): loads PNG and BMP
  files, draws tinted, draws a sheet region flipped, rotates 90 degrees,
  and checks every draw by reading pixels back from a forced software
  renderer — exact on every machine, headless included.
  `examples/sdl_sound.vnt` loads `examples/assets/blip.wav`, prints the
  file's spec, queues it, and drains the device. The seven assets (three
  PNGs, one BMP, three WAVs) are generated by the committed
  `examples/assets/gen_assets.py` — nothing is vendored.
- `examples/breakout.vnt` is the third playable game and the worked example
  for both additions: a four-row wall tinted over one white brick texture,
  a ball and paddle loaded from files, and WAV hits. With no key held the
  paddle auto-plays, so the headless run is one exact trajectory: it clears
  all 40 bricks with all three lives intact at frame 2064, and the test suite
  freezes `cleared 40 lives 3 frames 2064` (the frame cap is only a
  backstop).
- CI installs SDL2_image on all three platforms, so the new tests run
  everywhere; the sprite and sound-file snippets join the frozen-output doc
  checks. 5 new tests (538 total).

## v0.19.0 — 2026-10-19

- SDL2 audio. `examples/sdl_audio.vnt` plays a synthesized tone through the
  device's *queue* API — `SDL_OpenAudioDevice` with a hand-built
  `SDL_AudioSpec` (its `callback` field a true C function-pointer type),
  `SDL_QueueAudio`, `SDL_PauseAudioDevice`, `SDL_GetQueuedAudioSize` — and
  `examples/sdl_audio_cb.vnt` puts a Vanta function in the spec's `callback`
  field instead, so SDL runs it on its audio thread; callback state travels
  through the `userdata` pointer, as with any C callback. Under SDL's dummy
  driver both run headless in real time, which is how the tests cover them.
- `ptr_null::<T>()` builds the null pointer explicitly — the value C APIs ask
  *for*, where `ptr_is_null` only tests one C hands back. `T` may be a data
  type (`void` gives the anonymous `ptr<void>`) or a function type, which
  makes it a null callback: the empty slot a queue-mode `SDL_AudioSpec`
  carries (`SDL_OpenAudioDevice` also wants NULL, not `""`, for "the default
  device"). Like the other pointer builtins it takes no arguments; there is
  still no `nil` literal.
- The game kit gains `gamekit/audio.vnt` (six modules now): `audio_open` /
  `audio_ok` / `audio_close`, `audio_play_tone(aud, freq, ms, buf, capacity)`
  — fills a caller-owned `i16` buffer with a square wave, queues it, and
  returns the samples queued (0 for a dead device, nonsense values, or an
  SDL error; a tone longer than the buffer is cut short) — plus
  `audio_pending` (the bytes still queued) and `audio_wait`. Failure is
  quiet: with no working device every call does nothing, so games keep
  running silently. The kit ships no sound files; tones are generated.
- `examples/pong.vnt` beeps: 880 Hz on a player paddle hit, 660 Hz on an AI
  hit, and low/high tones on points. The beeps are fire-and-forget, so the
  headless run is unchanged (`player 0 ai 5 frames 576`).
- The audio tests need no library beyond SDL2 core, so CI gains no packages;
  they run under `SDL_AUDIODRIVER=dummy`, whose device paces consumption in
  real time, so queueing and draining stay deterministic. Examples:
  `sdl_audio.vnt`, `sdl_audio_cb.vnt`, `gamekit/audio.vnt`. 12 new tests
  (533 total).

## v0.18.0 — 2026-10-19

- `ptr_offset(p, n)` moves a pointer `n` elements with its element type kept
  (`p + n` in the generated C++). The offset must be an integer (`i32`;
  narrow values promote) and may be negative; `ptr<void>` is rejected —
  `cannot offset a ptr<void> (it has no element size); ptr_cast it to a
  typed pointer first`. C out-parameters are the motivating case:
  `TTF_SizeUTF8(font, text, &w, &h)` reaches its second slot with
  `ptr_offset(scratch, 1)` instead of a second allocation.
- Text rendering, through SDL_ttf. `examples/sdl_text.vnt` draws with the
  raw C API — `TTF_Init` / `TTF_OpenFont`, `TTF_SizeUTF8`,
  `TTF_RenderUTF8_Blended` into a texture, `SDL_RenderCopy` — with
  `SDL_Color` declared as a Vanta struct of four `u8` channels passed to C
  by value (the layout was verified against a C mirror).
- The game kit gains `gamekit/text.vnt`: `font_open` / `font_ok` /
  `font_close`, `text_measure` (writes width and height into a caller
  scratch block), `text_draw(screen, font, x, y, text, scratch, r, g, b)`,
  and `text_quit`. The scratch layout is 10 `i32` slots: `[0] w`, `[1] h`,
  `[2..5]` source rect, `[6..9]` destination rect — one `arena.alloc`
  covers measure and draw. A font that failed to open measures 0x0 and
  draws nothing instead of crashing.
- `examples/pong.vnt` now draws its score as text (the pip rectangles are
  gone) and links `SDL2_ttf`; the headless run is unchanged
  (`player 0 ai 5 frames 576`).
- The kit ships a font: `examples/gamekit/fonts/tom-thumb.ttf`, a 3x5
  pixel monospace face (CC0/CC-BY 3.0; credits in `fonts/LICENSE.md`), so
  examples, docs, and CI depend on no system fonts.
- CI installs SDL_ttf everywhere (`libsdl2-ttf-dev`, `sdl2_ttf`,
  `mingw-w64-x86_64-SDL2_ttf`); the SDL_ttf tests skip when it is missing,
  like the SDL2 tests. Examples: `ptr_offset.vnt`, `sdl_text.vnt`,
  `gamekit/text.vnt`. 14 new tests (521 total).

## v0.17.0 — 2026-10-18

- Narrow integers: `i8`, `u8`, `i16`, `u16`. They store their exact width —
  a `u8` field is one byte (`uint8_t` in the generated C++) — and read as
  `i32` in arithmetic, C's integer promotion. Assigning any integer into a
  narrow slot keeps the low bits, but a *literal* that does not fit is a
  compile-time error (`initializer: value 300 out of range for u8`), and the
  same check covers literals beside a narrow value (`x == 300`). Narrow types
  work everywhere a type is written: fields, arrays, `ptr<u16>`, `List<u8>`,
  and `extern` signatures. Pushing to a narrow `List` element type now emits
  an explicit template argument so wider values still convert.
- `ptr_cast::<T>(p)` reinterprets a pointer's element type
  (`reinterpret_cast` semantics, unchecked): view the same memory as another
  type, or give a `ptr<void>` from C a useful element type again. Any data
  type is a legal target, `void` included (erasing the type); function-type
  targets are rejected (`ptr_cast cannot target a function type`).
- `for x in xs` iterates a `List<T>` or an array element by element. The loop
  variable is a read-only copy, one per iteration; `break`/`continue` mean the
  same as in range loops; anything else is a compile error (`cannot iterate
  over ptr<i32>; for-each supports arrays and Lists`). A list's length is
  re-read every pass, so do not grow one mid-walk.
- Struct equality: `==`/`!=` on user structs compare field by field — numbers
  by value, `str` by content, arrays element-wise, nested structs
  recursively. A field with no equality (pointer, function value, `List`,
  `Quat`/`Matrix4`) is a compile error naming the path (`cannot compare struct
  'Outer' with '==': field 'inner.p' (ptr<i32>) has no equality`). Every
  comparable struct gets non-member `operator==`/`!=` emitted — all
  declarations before all definitions, so nesting order does not matter.
- Enum types may now appear in `extern` signatures (parameters, returns,
  `ptr<Enum>`, `List<Enum>`); the generated C++ names the fixed-`int32_t`
  enum and forward-declares it ahead of the `extern "C"` block, so the C side
  declares `int32_t` or a matching C enum. The old "pass `enum_to_i32(...)`
  instead" limitation is gone.
- Examples: `narrow_ints.vnt` plus a C fixture (exact-width parameters and a
  C mirror struct reading a Vanta struct's bytes for the layout check),
  `foreach.vnt`, `struct_eq.vnt`, `ptr_cast.vnt`, and `enums_extern.vnt` plus
  a C fixture. 52 new tests (507 total).

## v0.16.0 — 2026-10-18

- C callbacks: an `extern` parameter typed `func(...)` is now a C function
  pointer, so C libraries can call back into Vanta code. Pass any function
  value — a Vanta function or another `extern`. The generated C++ spells the
  callback inline where it appears (`int32_t(*v_f)(int32_t)` in a
  declaration, `int32_t(**v_slot)(int32_t)` through a `ptr<func(...)>`), so
  no aliases are needed before the namespace.
- An `extern` cannot return a function type yet: the error says so and
  suggests wrapping the C function in a shim (`extern function 'get' cannot
  return a function type yet; wrap it in a C shim that calls it`).
- Codegen fix: struct types in extern signatures are now namespace-qualified
  and forward-declared ahead of the `extern "C"` block, so
  `func f(p: ptr<State>)` in an `extern` compiles (previously the bare
  `State` name was emitted before any declaration).
- `examples/callbacks.vnt` + `examples/callbacks_lib.c`: a callback C calls
  twice (`f(f(x))`) and a visitor with a `ptr<i32>` user-data pointer.
  A libc `atexit` test exercises callbacks on every platform. 8 new tests
  (455 total).

## v0.15.0 — 2026-10-18

- `List<T>` can be edited in place: `xs.insert(i, v)` inserts at index `i`,
  shifting the rest right (`i` may be `len(xs)`, the same as `push`), and
  `xs.remove(i)` removes and returns the element at `i`, shifting the rest
  left. Out-of-range indexes stop the program with
  `vanta: insert index I out of bounds (size N) at line L` /
  `vanta: remove index I out of bounds (size N) at line L`.
- `xs.sort(cmp)` sorts a list in place with a comparator — a function value
  `func(T, T) -> i32` returning negative, zero, or positive for less-than,
  equal, greater-than. It is a stable, `O(n log n)` merge sort: elements the
  comparator calls equal keep their order.
- The comparator is fully checked: a missing, wrongly-typed, or wrong-arity
  comparator is a compile error naming the expected signature, e.g.
  `'sort' expects a comparator func(i32, i32) -> i32, got func(i32, i32) -> bool`.
- Codegen fix: function-pointer aliases may now mention structs by value —
  struct forward declarations are emitted before the aliases — so comparators
  over `List<Struct>` work.
- `examples/lists.vnt` now demonstrates insert, remove, and a comparator
  sort (stable ties included); 17 new tests (447 total).

## v0.14.0 — 2026-10-18

- Added the game kit: `examples/gamekit/` packages the SDL2 plumbing as four
  importable modules — `sdl.vnt` (`extern` declarations, `EV_*`/`KEY_*`
  constants, the `Screen` lifecycle), `input.vnt` (event accessors),
  `gfx.vnt` (clear, filled rect, outline, present), and `rng.vnt` (bounded
  integers and floats, random signs).
- `examples/pong.vnt`, the second playable game, is built on the kit: W/S
  or Up/Down against a tracking AI, wall bounces, contact-point steering,
  first to 5 wins. `match` picks the serve direction.
- Pong runs headless like the other SDL examples: a frame-limit argument
  plus `SDL_VIDEODRIVER=dummy`. The frozen headless run: the AI wins 5-0 in
  frame 576. `gamekit/rng.vnt` has no SDL dependency, so it gets its own
  test that runs on every machine with a C++ compiler.
- No compiler changes: the kit is plain Vanta, and the language needed
  nothing new — struct fields typed `ptr<void>` (the `Screen` handle), a
  failure value carried by C's own NULLs instead of a nil literal, and
  ordinary imports all already worked.
- 2 new tests (430 total).

## v0.13.0 — 2026-10-18

- Added `match`: branch on an enum value with `Enum.Member:` arms (several
  members per arm, commas between them) and an optional `else:` fallback.
  Arms run top to bottom; the first match wins. `examples/match.vnt` walks
  a little state machine:

  ```vanta
  match g.state:
      State.Menu:
          print_str("fresh start")
      State.Playing, State.Paused:
          print_str("in game")
      else:
          print_str("somewhere else")
  ```

- The checker proves coverage: when every member has an arm, no `else` is
  needed, and a missing member is a compile error that names the members
  it needs — add a member to an enum later and every match that must
  handle it says so. A member used by two arms, a member of a different
  enum, and a misspelled member are errors too.
- `match` arms have their own scope, and `break`/`continue` inside an arm
  still control the enclosing loop: `match` is not a loop, and codegen
  keeps it that way (an if/else chain rather than a C++ `switch`). The
  matched value is evaluated exactly once.
- `match` on numbers, strings, or structs is a compile error; it is a
  statement, not an expression. `match` joins the reserved keywords.
- 25 new tests (428 total).

## v0.12.0 — 2026-10-18

- SDL2 support, shown end to end. `examples/sdl_window.vnt` opens a window
  and clears it to a colour; `examples/sdl_game.vnt` is the first playable
  Vanta game — move the paddle with Left/Right (or A/D) to catch falling
  coins, Esc or the close button quits. Both are pure `extern`
  declarations, so no SDL headers are involved at compile time:

  ```powershell
  python main.py run examples/sdl_game.vnt --lib-dir C:/msys64/mingw64/lib --link SDL2
  ```

- Pointers widen to `ptr<void>` implicitly, matching C's conversion to
  `void*`: any `ptr<T>` is accepted where `ptr<void>` is expected, which
  is how opaque C handles (`SDL_Window`, `SDL_Renderer`, ...) are typed.
  The narrowing direction stays an error, and a `ptr<void>` cannot be
  indexed — it has no element type.
- New builtin `ptr_is_null(p) -> bool`: compares any pointer (including
  `ptr<void>`) against null so failed calls can be handled. Pointer
  bindings can be reassigned with `mut`, and user functions may take and
  return pointers.
- Fixed: functions returning pointers never compiled — the implicit
  default return was invalid C++ (`T*{}`); a fallthrough now yields
  `nullptr`. Same bug class as the v0.11.0 `str` fix.
- Both SDL examples take an optional frame-limit argument and run headless
  under `SDL_VIDEODRIVER=dummy`, so the test suite builds, links, and runs
  them for real; CI installs SDL2 on Linux, macOS, and Windows. 20 new
  tests (403 total).

## v0.11.0 — 2026-10-18

- Added enums: `enum Name:` declares a fixed set of named members, numbered
  from 0 in declaration order and written `Name.Member` (e.g.
  `State.Playing`). An enum is a first-class type — variables, struct
  fields, function parameters and returns, arrays, `List<T>`, function
  values, and imported modules all accept enum values unchanged.
- Values compare with `==` and `!=`. Ordering comparisons on enums, and
  compares between different enums or against numbers, are compile errors.
  `enum_to_i32(v)` returns a member's number for printing, arithmetic, or
  passing to an `extern` function (extern signatures cannot take enum types
  directly yet). Enum values cannot be constructed (`State(1)` is an error),
  and enum types have no fields — `s.Menu` suggests `State.Menu`.
- Fixed: functions returning `str` never compiled — the implicit default
  return that codegen appends was invalid C++ (`return const char*{};`).
  A function that falls through now yields the empty string.
- Fixed: a type declared after a function of the same name (`func P()` then
  `struct P:`) is now reported as a collision instead of silently shadowing
  the function.
- New example `examples/enums.vnt`: a tiny state machine switching on a
  `State` enum, plus `enum_to_i32` and iteration over an array of members;
  plus 42 tests (383 total).

## v0.10.0 — 2026-10-18

- Added `StrBuilder`, an arena-backed string builder: `arena.str_builder()`
  creates one growing buffer, `append_str` / `append_i32` / `append_u32` /
  `append_f32` / `append_f64` / `append_bool` append (formatted exactly like
  the matching `print_*`), `len(b)` reads the byte count, `clear()` resets it
  for reuse, and `to_str()` returns the current contents as a `str` — copied
  into a fresh arena block, so the result stays stable across later appends,
  growth, and `clear()`. Growth doubles from 32 bytes, and the fixed string
  pool is never touched.
- Like `List<T>`, a builder is a handle: copies alias the same buffer, appends
  work through a plain `let`, and helpers can take a `StrBuilder` parameter
  and append to the caller's builder. `arena.reset()` invalidates the builder
  and the strings taken from it.
- New example `examples/str_builder.vnt`: building a line once, reusing the
  buffer with `clear()`, and a helper that appends through its parameter;
  plus 28 tests (341 total).

## v0.9.0 — 2026-10-18

- Added dynamic lists: `List<T>`, a growable array backed by an `Arena`.
  `arena.list::<T>()` creates an empty list, `xs.push(v)` appends (growing by
  doubling from a capacity of 4), `xs.pop()` removes the last element, and
  `len(xs)` reads the size. Element access reuses the v0.7.0 checked
  `xs.at(i)` — reads and writes, with out-of-bounds errors naming the list
  size and source line — plus the unchecked `xs[i]` form.
- A list is a handle: copies alias the same storage, and passing one to a
  function lets the function append to the caller's list. Since a list is an
  indirection like `ptr<T>`, element writes and `push`/`pop` work through a
  plain `let`; `mut` only controls rebinding. `List<void>` and `List<Arena>`
  are compile errors, and `arena.reset()` invalidates the arena's lists.
- New example `examples/lists.vnt`: particles in a list, integrated through a
  function call, with checked reads and writes and a pop; plus 39 tests
  (313 total).

## v0.8.0 — 2026-10-18

- Added trigonometry: `sin`, `cos`, and `tan` for `f32` and `f64`, plus
  `atan2_f32`/`atan2_f64` — the angle of the vector `(x, y)`, the usual
  "heading toward a point" operation. Angles are radians, and the f32/f64
  pairs follow the existing `sqrt_f32`/`sqrt_f64` naming. They are callable
  like any builtin and usable as function values.
- Extended `examples/arrays_and_math.vnt` with a 45-degree unit vector and
  its heading recovered through `atan2`, plus 7 tests (274 total).

## v0.7.0 — 2026-10-18

- Added bounds-checked array access: `xs.at(i)` checks the index against the
  fixed size of `xs` before touching memory. Reads return the element, and
  writes (`xs.at(i) = v`, including compound forms) obey the normal mutability
  rules. An out-of-range or negative index prints
  `vanta: index I out of bounds (size N) at line L` to stderr and exits 1.
  Plain `xs[i]` stays unchecked.
- `at` composes with nested arrays — `g.at(y).at(x)` reads and
  `g.at(y).at(x) = v` writes — and rejects `ptr<T>` receivers with "a pointer
  has no length", since pointers have no size to check against.
- Codegen emits `vanta::at_checked` for reads and `vanta::at_checked_ref` (a
  real reference, so writes land in the array) for writes, carrying the
  access's source line into the failure message.
- Added `examples/bounds.vnt`, plus 29 tests (267 total).

## v0.6.0 — 2026-10-18

- Functions are first-class values. A `func(P1, P2) -> R` type names any
  function with that signature (omit the arrow for `void`), and values can be
  stored in variables, passed as arguments, returned, kept in struct fields and
  arrays, or allocated from an arena. The same call syntax invokes them:
  `f(x)`, `handlers[0](x)`, `op.run(x)`, `pick()(x)`.
- Values are plain function pointers — there are no closures, so nothing is
  captured. Vanta functions (emitted with their `fn_` prefix), `extern`
  functions, and builtins like `print_str` all work as values.
- Rejected on purpose: `len`/`print_fmt`/`write_fmt`/`assert` and type names as
  values, `==`/`!=` on function values, function values in `const`
  initializers, and function types in `extern` signatures (C callbacks come
  later).
- Local bindings now shadow functions of the same name in call position, so
  the canonical `func apply(f: func(i32) -> i32, ...)` works even when a
  function named `f` exists.
- Codegen emits one `using FnPtrN = R(*)(...)` alias per distinct function
  type, innermost first; type names matching `FnPtr<digits>` are reserved.
- Added `examples/dispatch.vnt`, plus 51 tests (238 total).

## v0.5.0 — 2026-10-18

- 2D arrays work end to end. Nested array types and literals (`[[i32, 8], 4]`)
  already parsed, but writes through pointers and struct fields were rejected;
  assignment targets are now validated by walking the whole storage chain, so
  arena-backed grids (`arena.alloc::<[i32, 8]>(h)`) and `mut` struct grids are
  writable at any depth while `let` bindings and parameters stay immutable.
- Array literals and call argument lists may span lines: the lexer ignores
  newlines inside `[...]` and `(...)`.
- Added `examples/grid.vnt`: a stack checkerboard, a struct-held heightmap,
  and an arena-backed dynamic grid, plus 11 tests (187 total).

## v0.4.0 — 2026-10-18

- Added `import "path.vnt"`. An import merges another file's declarations
  into the program: paths resolve relative to the importing file, imports are
  transitive, and each file is loaded once, so diamonds are fine. Import
  cycles and missing files are compile errors. Declarations merge into the
  existing flat namespace — imported functions, structs, constants, and
  externs are used by their bare names. `import` is now a reserved word.
- Errors inside imported files now name the file that contains them: every
  AST position carries its source file, and `CheckError` prefers it.
- Added `examples/imports_demo.vnt` with its module
  `examples/imports_demo_lib.vnt`, plus 12 tests (176 total).
- New `compiler/loader.py` owns import expansion; `_frontend_only` now goes
  through it.

## v0.3.1 — 2026-10-18

- Added `file_exists(path)`, `file_write(path, data)`, and `file_read(path)`.
  `file_read` allocates from the string pool (valid until `str_pool_reset()`)
  and returns `""` on any failure; a file too large for the pool fails loudly
  with a specific message instead of truncating. `file_write` returns the byte
  count or `-1` on failure.
- Added `examples/file_io.vnt`: reads a file named on the command line and
  writes a copy to `<path>.copy`, reporting both byte counts.

## v0.3.0 — 2026-10-18

- Added `extern "lib" { ... }` declarations. Extern functions are declared
  without bodies, type-checked like any other function, and called under their
  original names; the generated C++ puts them in an `extern "C" {}` block
  outside `namespace vanta_user`, so the linker sees unmangled symbols.
- Added `--include-dir`, `--lib-dir`, and `--link` (all repeatable) to `build`
  and `run`: `-I`/`-L`/`-l` on GCC-style toolchains, `/I`/`/LIBPATH:`/`<lib>.lib`
  on MSVC.
- Added `examples/extern_demo.vnt` with its C side in
  `examples/extern_demo_lib.c`, plus an end-to-end integration test that
  compiles the C library, links it, and checks the output.
- Repository history: the tags v0.1.1 through v0.2.5 were re-cut so that each
  tagged commit reports its own version from `--version`; the stored version
  string had lagged the tags before v0.2.2's sync and again until v0.2.6.

## v0.2.6 — 2026-10-18

- Added `print_fmt(fmt, args...)` and `write_fmt(fmt, args...)`. Placeholders are
  `{}` and are resolved at compile time: the type checker counts them and checks
  each argument's type, and the code generator turns each one into the matching
  printf conversion. A literal/integer mismatched format is a compile error, not
  a runtime surprise.
- Format literals support `{{` and `}}` for literal braces, and `%` is escaped
  automatically so a stray percent cannot corrupt the output.
- Added a process-lifetime string pool with `str_concat`, `str_len`,
  `to_str_i32`, `to_str_f32`, `to_str_bool`, and `str_pool_reset`. Exhaustion
  fails loudly rather than corrupting memory.
- Added `str_to_i32` and `str_to_f32`, without which command-line arguments
  could not be used as numbers.
- Added `examples/report.vnt`.
- New `compiler/formats.py` holds the format parser shared by the checker and
  the code generator.

## v0.2.5 — 2026-10-18

- Added `arg_count()` and `arg_str(i)`; the generated `main` now receives
  `argc`/`argv` and hands them to the runtime
- `python main.py run prog.vnt a b` now passes `a b` through to the program

## v0.2.4 — 2026-10-18

- Added `examples/life.vnt` — Conway's Game of Life on a 40x20 torus, drawn as a
  character grid

## v0.2.3 — 2026-10-18

- Added `write_i32`, `write_u32`, `write_f32`, `write_f64`, `write_bool`, and
  `write_str` — like their `print_*` counterparts but with no trailing newline
- Registered `print_newline()`, which had been sitting unreachable in the runtime
- Added `abs_i32`, `abs_f32`, `min_i32`, `max_i32`, `min_f32`, `max_f32`,
  `floor_f32`, `ceil_f32`

## v0.2.2 — 2026-10-18

- Added `rand_f32()` — xorshift32, returns `f32` in `[0, 1)`
- Added `rand_seed(seed: i32)` to select a random stream
- Random state is fixed at startup, so programs are reproducible until seeded
- Added 7 tests (type checker, codegen, and an end-to-end determinism test)
- Fixed: `compiler.VERSION` still reported `0.1.0` and the generated C++ header
  hardcoded `0.2.0`. Both now report `0.2.2`, and the header reads the shared
  `VERSION` constant instead of a literal, so it cannot drift again.

## v0.2.1 — 2026-10-17

- Added `examples/boids.vnt` — 30 boids on a 100x100 torus, deterministic init
- Added an end-to-end integration test asserting the four quadrant counts sum
  to 30, so the simulation cannot silently stop placing every boid

## v0.2.0 — 2026-10-17

- Added the `str` type, with escape sequences `\t`, `\n`, `\"`, `\\`
- Added `print_str`
- `==` and `!=` on `str` compare contents via `strcmp`, not pointers
- Added `Vec2.normalized` and `Quat.dot`
- Added `translation`, `scale`, and `from_quat` builtins returning `Matrix4`

## v0.1.3 — 2026-10-17

- Added fixed-size arrays: `[T, N]` types, array literals, indexing, and `len(xs)`
- Added Quat math: `Quat * Quat`, `Quat * Vec3`
- Added Matrix4 extras: `Matrix4 * Matrix4`, `Matrix4 * Vec3`
- Documented `examples/arrays_and_math.vnt`

## v0.1.2 — 2026-10-17

- Added `const` declarations (compile-time values, emitted as C++ `constexpr`)
- Added `assert(cond)`
- Added return-type inference when `-> T` is omitted
- Added 3-argument `range(start, end, step)`
- Added element-wise `Vec2` / `Vec3` equality and inequality
- Fixed mixed-literal return-type inference

## v0.1.1 — 2026-10-17

- Added compound assignment `+=`, `-=`, `*=`, `/=`
- Added `break` and `continue`, with loop-context checking
- Added `examples/loops.vnt`

## v0.1.0 — 2026-10-17

- Initial working compiler:
  source → lex → parse → type-check → C++17 → native binary
- Types: `i32`, `u32`, `f32`, `f64`, `bool`, `void`, `ptr<T>`
- Structs, `component`, and `system` declarations
- Non-copyable stack-scoped `Arena` allocator
- Built-in `Vec2`, `Vec3`, `Matrix4`, `Quat`
- Examples: `examples/vector_math.vnt`, `examples/physics.vnt`