# Vanta roadmap

Vanta ships in milestones: every release lands compiler work, game-kit work,
tests, and documentation together, and nothing ships undocumented or
untested. This file is a candidate backlog, not a promise — priorities move
as the games show what actually hurts.

Current release: **v0.39.0** ([changelog](CHANGELOG.md)). The language's
present limits are listed at the end of the [README](README.md#status); this
file turns those limits into work. Within each section the small,
high-leverage items come first; relative size is noted.

## Landed in v0.39.0

Debugger speed landed. A breakpoint condition is now handed to GDB as soon
as the variables are in scope, so a hot loop no longer stops at every hit. A
field of a struct can be watched the same way a local can, and on macOS the
debugger accepts `lldb-mi` when GDB is not installed. 756 tests total,
including stdio sessions that watch a struct field and that stop on a
condition which only becomes true later.

The next debugger milestone is deliberately separate again: remote debugging,
reverse debugging, and MSVC/PDB support. A debug session always uses an
unoptimized build.

## Landed in v0.38.0

Debugger data landed. The Variables view speaks Vanta: a struct expands into
its fields, an enum shows the member it holds, a `str` shows its text, and a
`List` shows how many items it holds. The debug build carries the layout of
every struct and enum, so the adapter knows the field names without guessing
them from the generated C++. 754 tests total, including unit tests for the
layouts and stdio sessions that expand a struct and read an enum member.

The next debugger milestone is deliberately separate again: remote debugging,
reverse debugging, LLDB, and MSVC/PDB support. A debug session always uses an
unoptimized build.

## Landed in v0.37.0

Debugger sessions landed. A session can attach to a program that is already
running, which is how a game is debugged: build it with `vanta build --debug`,
start it, and attach to the process. Stepping acts on the thread the editor
asked for, the adapter can show the machine code of the current instruction,
and it answers the evaluate request that editors send while hovering a
variable. 751 tests total, including a stdio session that attaches to a
running program, watches it, and detaches.

The next debugger milestone is deliberately separate again: remote debugging,
reverse debugging, LLDB, and MSVC/PDB support. A debug session always uses an
unoptimized build.

## Landed in v0.36.0

Debugger navigation landed. The debug build carries a source map of the
program, so the adapter can tell an editor which lines hold a statement and
can hold a breakpoint, and it offers the lines of the running function as
jump targets. A jump moves the program counter and continues the program.
Exception breakpoints for C++ exceptions thrown or caught are available as
GDB catchpoints. 749 tests total, including unit tests for the source-line
map and stdio sessions that list the valid lines, jump, and set an exception
breakpoint.

The next debugger milestone is deliberately separate again: attach and remote
debugging, reverse debugging, LLDB, and MSVC/PDB support. A debug session
always uses an unoptimized build.

## Landed in v0.35.0

Debugger editing landed. A local can be edited from the Variables view, but
only where Vanta allows it: only a binding declared with `mut` may be
written, and an immutable binding is refused with a clear message. The
adapter also watches a value (a GDB watchpoint on the local's address),
lists the processor registers, answers raw memory reads, and reports threads
that start or exit. 742 tests total, including unit tests for the value and
type rules and stdio sessions that edit, refuse, watch, and read machine
state.

The next debugger milestone is deliberately separate again: exception
breakpoints, attach and remote debugging, reverse debugging, `goto`, LLDB,
and MSVC/PDB support. A debug session always uses an unoptimized build.

## Landed in v0.34.0

Debugger depth landed. The adapter now supports conditional breakpoints, hit
counts, log points, and function breakpoints, plus watch expressions in a
**Watch** scope and a `restart` request that rebuilds the program and runs it
again. Conditions, hit counts, and log messages are evaluated by the adapter
in the frame that was hit, so they can be written in Vanta terms
(`hp > 0`, `len(items) == 3`) instead of the generated `v_` names. 729 tests
total, including unit tests for the expression translation and the hit
condition forms, and stdio sessions that exercise the new breakpoint kinds
against a real GDB.

The next debugger milestone is deliberately separate again: editable
variables, data and exception breakpoints, attach and remote debugging,
reverse debugging, LLDB, and MSVC/PDB support. A debug session always uses an
unoptimized build.

## Landed in v0.33.0

Native debugging landed. `vanta dap` is a DAP server backed by GDB/MI2.
Debug builds emit absolute `#line` directives and compile with
`-O0 -g3 -fno-omit-frame-pointer`, so GDB reports Vanta files and lines
directly. The adapter supports line breakpoints in the entry file and imports,
stack traces, **Locals** and **Arguments**, continue/pause/step over/step
into/step out, `stopOnEntry`, program output, and clean termination. The VS
Code extension version 0.4.0 contributes the `vanta` debugger type and reuses
the language client's executable/Python discovery. `docs/DEBUGGER.md`
documents setup, source mapping, GDB discovery, and troubleshooting. 710 tests
total, including DAP/MI unit tests, a real GDB breakpoint/source-mapping test,
and a stdio DAP session that launches, stops, inspects locals, continues, and
disconnects.

Debugger follow-ups are intentionally separate from the first milestone:
conditional and function breakpoints, watch expressions, editable variables,
attach/remote debugging, LLDB, and MSVC/PDB support. A debug session always
uses an unoptimized build.

## Landed in v0.32.0

Editor support landed. `vanta lsp` is a stdio language server with diagnostics,
completion, hover, go-to-definition, and document symbols. Diagnostics run the
real lexer, parser, loader, and type checker; source overlays let the loader
read unsaved editor buffers, including unsaved imported files. Completion and
navigation build a tolerant source index from the AST and fall back to line
scanning while a declaration is half typed.

The VS Code client in `editors/vscode/` is now a compiled language client
rather than a grammar-only extension. It discovers `vanta` through a setting,
`PATH`, a workspace virtualenv, or a Python environment that can import the
compiler. CI compiles and packages the VSIX, and the release workflow attaches
it to the GitHub release alongside the wheel and sdist. `docs/EDITOR.md`
documents setup, discovery, features, limitations, and troubleshooting.

Editor support in v0.32.0 was intentionally scoped: no debugger, semantic
rename, formatting, or code actions. The debugger followed in v0.33.0; rename,
formatting, and code actions remain candidates. 692 tests at that release.

## Landed in v0.31.0

Generic enums and a library-shaped standard library landed. An enum
declaration may take type parameters (`enum Result<T, E>:`), payloads may use
them, and each concrete instance (`Result<i32, str>`) is monomorphized with
its own layout, tags, and constructors. Constructors infer missing parameters
from a payload or an expected type; explicit forms such as
`Option.None::<i32>()` cover contexts with no expected type. Matches remain
exhaustive over the source family, type arguments obey module privacy, and
non-copyable or recursive-by-value payloads are rejected.

The standard library is real Vanta code: `stdlib/option.vnt` defines
`Option<T>` and `stdlib/result.vnt` defines `Result<T, E>` as ordinary generic
enums. `import "std/option.vnt"` resolves from a checkout or an installed wheel,
with a sibling file taking precedence. `examples/option_result.vnt` is the
worked example. Generic structs and generic functions are deliberately not
part of this milestone.

## Landed in v0.30.0

Module boundaries landed. A file can start with `module name`; its
declarations are private unless marked `pub`. `import "file.vnt"` brings a
module's public names into the importing file, while
`import "file.vnt" as alias` uses qualified names such as `alias.func(...)`,
`alias.Type(...)`, and `alias.Enum.Member`. Module-less files keep the
original flat, all-public import behaviour, so the game kit and every existing
program compile unchanged. The resolver rejects private access, ambiguous
unqualified imports, duplicate module names, and private types exposed by
public declarations. `examples/modules_demo/` is the worked example.

## Next: language (candidate v0.40.0)

1. **Module follow-ups - medium.** Per-field visibility, nested modules, and
   a package/search-path story were deliberately out of v0.30.0. They become
   worth doing when a library wants to hide struct representation or when
   path-only imports become painful.
2. **Generic follow-ups - large.** Generic enum payloads now cover
   `Option`, `Result`, and reusable error containers. Generic structs,
   generic functions, and constraints each need their own design and are not
   assumed by this milestone.

## Kit and examples

- Breakout polish landed in v0.27.0: three walls, P/Space pause, a best score
  persisted in `breakout.score`, and `sound_load_gain` for per-sound volume.
  The pong and strike frozen runs stay untouched; breakout's frozen run now
  records the three-wall clear.
- `examples/enums_advanced.vnt` exercises explicit member values, payload
  enums, struct/str payloads, wildcard bindings, equality, and `enum_to_i32`;
  its output is frozen in the integration suite.
- `examples/modules_demo/` exercises declared modules, `pub`, a private
  helper, qualified and unqualified imports, module constants, and a payload
  enum crossing a module boundary; its output is frozen in the integration
  suite.
- `examples/option_result.vnt` exercises the shipped generic `Option<T>` and
  `Result<T, E>`, constructor inference, explicit type arguments, nested
  error payloads, and exhaustive matches; its output is frozen in the
  integration suite.
- Keep the asset pipeline honest: `examples/assets/gen_assets.py` generates
  every image and sound the examples use; new examples add generators, never
  binaries from elsewhere.

## Tooling and documentation

- Distribution is live: `vanta-lang` is on PyPI and the release workflow
  publishes each version tag through Trusted Publishing, attaching the wheel,
  sdist, and VS Code VSIX to the GitHub release. Homebrew, Scoop, and winget
  formulas are follow-ups.
- Editor support is shipped in v0.32.0: `vanta lsp` plus the VS Code client
  provide diagnostics, completion, hover, definition, and document symbols.
  Native debugging shipped in v0.33.0: source-mapped debug builds and a DAP
  adapter over GDB/MI2. Debugger depth shipped in v0.34.0: conditional and
  function breakpoints, hit counts, log points, watch expressions, and
  restart. Debugger editing shipped in v0.35.0: editing mutable locals, data
  breakpoints, registers, and memory reads. Debugger navigation shipped in
  v0.36.0: valid breakpoint lines, run to cursor, and exception breakpoints.
  Debugger sessions shipped in v0.37.0: attaching to a running program,
  per-thread stepping, and the disassembly view. Debugger data shipped in
  v0.38.0: structs expand into their fields, enums show their member.
  Debugger speed shipped in v0.39.0: faster conditions, field watches, and
  an LLDB fallback. The next debugger work is remote debugging, reverse
  debugging, and MSVC/PDB support.
- Watch the `ubuntu-latest` runner migration to Ubuntu 26 (GitHub announced
  the change for the 2026-10-19 window): if the Linux job's SDL package
  install or tests change behaviour, pin the label or adapt the setup,
  verified with the usual full-suite run.
- Documentation keeps its rule: every snippet in the tutorial and reference
  is executed with its output frozen, and CI runs the real programs that the
  docs describe.

## Not scheduled

Garbage collection, closures, and generic structs/functions are each a
language-design project, not a milestone. If one becomes necessary for a
game, it graduates to the sections above with a concrete motivating program.
