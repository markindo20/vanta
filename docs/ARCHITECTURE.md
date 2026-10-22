# Vanta Architecture

Vanta is a small compiler: a Python frontend that emits C++17, which is then
compiled to a native binary by an off-the-shelf C++ compiler. There is no
custom backend, no IR, and no optimizer — the C++ compiler does that work.

## Frontend (Python)

1. `tokens.py` — token types and the keyword table.
2. `lexer.py` — hand-written tokenizer producing `INDENT`/`DEDENT`/`NEWLINE`.
   Newlines are suppressed inside `(...)` and `[...]`, so array literals and
   argument lists can span lines. Tabs are rejected.
3. `parser.py` — recursive descent for declarations, Pratt for expressions.
   Produces `ast_nodes.py` nodes.
4. `loader.py` — builds the file graph and resolves module boundaries. It
   reads each file once, resolves imports relative to the importing file,
   detects cycles, and stamps every AST position with its source file so
   diagnostics name the right file. `load_program(path, sources=...)` accepts
   an in-memory overlay map; the loader's read and existence checks consult it
   before the filesystem, which is how the language server validates unsaved
   editor buffers and unsaved imports. A file may start with `module name`;
   module-scoped declarations are private unless marked `pub`. An unqualified
   import brings public names into the importing file, an aliased import
   creates qualified names, and module-less files keep the original flat,
   all-public behaviour. Imports whose path starts with `std/` fall back to
   `stdlib/` in a checkout or `compiler/templates/stdlib/` in a wheel, but a
   sibling file with the same path wins. The resolver rewrites declarations and references to
   unique internal names (`vanta_m_<module>__<name>`) and validates
   visibility, ambiguous imports, duplicate module names, and private-type
   leaks in public signatures. The resulting `Program` is still flat for the
   type checker and backend; a `display_names` map turns internal names back
   into source names in diagnostics. Entry `main` and extern C names stay
   unchanged.
5. `typesys.py` — the type model (`PrimType`, `PtrType`, `ArrayType`,
   `StructType`, `EnumType`, `FuncType`, ...).
6. `type_checker.py` — two passes: register structs, enums, builtins, and
   function signatures; then check bodies with scoped symbol tables. Annotates every
   expression node with `expr.type`. This is where the builtins are declared
   (`_register_builtins`), where `extern` functions are registered
   (`is_extern=True`), and where the `Arena` non-copyable rule is enforced.
   Generic enum families are registered from their declarations and
   instantiated on demand in `_instantiate_enum`; the cache key is the family
   plus concrete type arguments, and each instance gets an internal name such
   as `Option__g0` while diagnostics keep `Option<i32>`. Constructor
   parameters come from explicit `::<...>` arguments, an expected type, or
   payload inference, in that order. Instantiation substitutes payload type
   expressions, checks copyability and recursive by-value use, and records
   every concrete enum for code generation.
   Assignment targets are validated by walking the storage chain (fields,
   indexes, and checked `at()` calls) to its root: an index on a pointer is
   writable regardless of the binding, otherwise the root binding must be
   `mut`. Function values are
   resolved here too: `func(...)` types are registered under the `FnPtrN`
   alias names codegen will use, and a local binding shadows a function of the
   same name in call position. The pointer rules live here as well: `_coerce_value`
   performs the C-style `ptr<T>` → `ptr<void>` widening (and only that
   direction), `ptr_is_null` is checked in `_check_ptr_is_null`,
   `ptr_null::<T>()` (v0.19.0) in `_check_ptr_null` (a function-type `T`
   yields a null callback), a
   `ptr<void>` cannot be indexed, and `alloc::<void>` is rejected with its
   own message. The integer-width rules live here too (v0.17.0): narrow
   values promote to `i32` in arithmetic, any integer truncates into a narrow
   slot, out-of-range literals are rejected, and `eq_blocker` (in
   `typesys.py`) walks struct fields to decide whether a struct may be
   compared with `==`.
7. `codegen_cpp.py` — emits C++17 inside `namespace vanta_user` and wraps
   `main` in `int main(int argc, char** argv)`, passing the arguments to the
   runtime. Module-scoped declarations have already been given unique
   internal identifiers by the loader, so the backend can stay flat and two
   modules may use the same source name. Builtin calls are mapped through
   lookup tables (`BUILTIN_FN`, `BUILTIN_MATH_CTOR`) to `vanta::` runtime
   functions. `extern` declarations
   are emitted as an `extern "C" {}` block before the namespace, and calls to
   them skip the `fn_` prefix user functions get. Extern signatures predate
   the namespace, so they are spelled in plain C: callback parameters expand
   inline as declarators (`int32_t(*v_f)(int32_t)` — the name folds inside
   the stars), and user structs are namespace-qualified with their tags
   forward-declared ahead of the block. In debug builds, `CodeGen` also emits
   absolute `#line` directives around functions, statements, and match arms,
   so native debug information points at the Vanta source instead of the
   generated `main.cpp`. Each distinct function type is
   emitted as a `using FnPtrN = R(*)(P...)` alias at the top of the
   namespace, innermost first, and drives the in-namespace spellings.
   Struct and enum definitions are emitted in dependency order; forward tags
   and aliases come first. Generic instances can be created while a field or
   signature is resolved, so `_ordered_user_types` walks direct by-value
   fields, payloads, and arrays and emits dependencies first; pointers and
   `List<T>` are handles and do not force completion. A plain enum is
   `enum class E : int32_t`; a payload enum is a struct with a nested
   `VantaTag` and one field per payload value, plus a `make_E_Member`
   constructor for each member. A function that can fall through gets a
   type-appropriate default return: `""` for `str`, `nullptr` for pointers,
   the first member for enums, value-initialization for everything else
   (`T{}` cannot be written for a raw `T*`, which is why pointers are
   special-cased). `match` lowers to an if/else chain over a single
   `const auto` binding of the matched value — deliberately not a C++
   `switch`, so a `break`/`continue` written in an arm keeps its meaning for
   the enclosing loop. Payload patterns compare `v_tag` and bind the active
   fields with `const auto&` locals. `for x in xs` lowers to an index loop
   over a bound handle (Lists) or a const reference (arrays), re-reading a
   list's length each pass. Comparable structs and payload enums get
   non-member `operator==`/`!=` (`str` through `str_eq`, arrays element-wise,
   payload enums by tag and active payload), every declaration ahead of every
   definition so nesting order does not matter, and narrow fields or elements
   get `static_cast<T>` where C++ braced initialization would refuse the
   narrowing. Plain enum tags are forward-declared with their fixed `int32_t`
   underlying type next to the struct tags ahead of the `extern "C"` block;
   payload enums are forward-declared as structs and rejected in extern
   signatures.
8. `formats.py` — parses `print_fmt`/`write_fmt` format literals. Shared by the
   type checker (which counts placeholders and checks argument types) and the
   code generator (which turns them into printf conversions).
9. `driver.py` — orchestrates the frontend and native compilation, detects
   `clang++`/`g++`/`cl` (honouring `$CXX`), and implements `check`/`build`/`run`.
   A bare source path is the same as `run`, and known extern block names
   (`SDL2`, `SDL2_ttf`, `SDL2_image`) add their link flags automatically.
   `new` writes a playable starter, and `build --bundle` walks the Windows
   executable's PE imports with `objdump` to copy non-system DLLs beside it.
   `--include-dir`/`--lib-dir`/`--link` (repeatable, on `build` and `run`) pass
   `-I`/`-L`/`-l` - or the MSVC `/I`/`/LIBPATH:`/`<lib>.lib` equivalents -
   through to the C++ compiler. Generated code is built with FP contraction
   off (`-ffp-contract=off`, or `/fp:strict` for MSVC), so deterministic
   float-based runs do not diverge between x86-64 and arm64. `build --debug`
   and the debug adapter's `build_debug()` path enable source markers; with
   GCC/Clang they force `-O0 -g3 -fno-omit-frame-pointer`. The debug adapter
   rejects MSVC because GDB cannot read PDB debug information.
10. `lsp.py` - the Language Server Protocol frontend. It implements JSON-RPC
   framing over stdin/stdout, full-document sync, UTF-16 position conversion,
   diagnostics, completion, signature help, hover, definition, references,
   rename (prepare and edit), and document symbols. The
   `lsp` subcommand in `driver.py` imports and runs it, and `compiler/__main__.py`
   provides the `python -m compiler lsp` fallback.
11. `dap.py` - the Debug Adapter Protocol frontend and GDB/MI2 bridge. The
   `dap` subcommand runs it on stdin/stdout; it builds the program with Vanta
   source markers, drives GDB, translates breakpoints/frames/scopes/step
   requests, and forwards target output as DAP output events.

Note that `component` and `system` are parsed as flags on the struct and
function declarations respectively (`parse_struct(is_component)`,
`parse_func(is_system)`). They are aliases that express ECS intent and have no
distinct semantics.

## Editor support (v0.33.0)

`vanta lsp` runs `lsp.py` as a stdio language server. Each open document is
stored by URI; a didChange notification replaces the whole buffer, matching
the full-sync capability the server advertises. Requests are handled
sequentially, and publishDiagnostics runs the frontend with every open buffer
in the loader overlay map before sending the first error to the file named by
its stamped `Pos.file`.

Completion and navigation do not use the loader's rewritten module names.
`_ProjectIndex` parses the current file and its imports directly, resolves
relative imports with the same `std/` fallback, and records declarations and
their source positions by their written names. It keeps a tolerant line
scanner for buffers that do not parse yet, so a cursor after `Color.` or
`value.` can still offer enum members and struct fields while the line is
incomplete. Locals come from the function body AST when possible and from a
line scan otherwise; the scan also infers common constructor and
`arena.list::<T>()` types. Builtin completions are generated from the type
checker's registered function and builtin-struct tables, with a small explicit
method table for runtime-backed types.

Signature help (v0.50.0) scans the buffer forward to the cursor, tracking `#`
comments and `"..."` strings, and keeps a stack of open parentheses so the
innermost call wins. The callee's dotted path is resolved through the same
project index as completion. Parameter labels are parsed from the declaration
detail the index already stores (`func f(a: i32) -> i32`), so user functions,
imported functions, builtins, function values, and the explicit method table
share one format; struct constructors use their fields and enum payload
members their types. The active parameter is the count of top-level commas
between the opening parenthesis and the cursor.

References and rename (v0.51.0) share one scope-aware walker over the parsed
program (`_ReferenceWalker`). Every identifier occurrence resolves to a stable
symbol tuple - a top-level declaration, a local binding, a struct field, an enum
member, or an import alias - so two occurrences in different files compare
equal only when they name the same declaration. The walker tracks lexical
scopes for parameters, locals, `for` variables, and match-arm bindings;
argument annotations, constructor calls, loop elements, index expressions, and
function return types (parsed from the index's declaration detail) feed a small
type inference used to resolve field and member receivers. `Member.pos` is the
dot token and `TypeExpr.pos` the type name, so edits land on the exact
identifier; a qualified type such as `math.Point` contributes a separate
reference for the alias and for `Point`, a struct constructor contributes its
`field:` labels, and a match pattern contributes its enum type, its member, and
its bindings. Rename walks every module in the project index, dedupes by
(uri, line, column), and returns a `changes` workspace edit with UTF-16 ranges.
The declaration is recovered from the tolerant line scanner when the buffer
does not parse, so rename still works mid-edit for the declaration itself.

The VS Code client in `editors/vscode/` is TypeScript compiled with `tsc`. It
uses `vscode-languageclient` over stdio and resolves the server command from
`vanta.server.path`, a workspace virtualenv, `PATH`, or a Python interpreter
that can import `compiler`. It passes the workspace as the server's working
directory so relative imports and Python module discovery behave like the
editor's project.

## Debugger (v0.33.0, depth in v0.34.0, editing in v0.35.0,
navigation in v0.36.0, sessions in v0.37.0, data in v0.38.0,
speed in v0.39.0, reach in v0.40.0, editing in v0.41.0,
terminal in v0.42.0, scope in v0.43.0,
polish in v0.44.0, readiness in v0.45.0, logging in v0.46.0, instructions in v0.47.0, hex values in v0.48.0, structured values in v0.49.0)

`vanta dap` runs `dap.py` as a stdio Debug Adapter Protocol server. A launch
request names a Vanta source file; the adapter calls `build_debug()` in
`driver.py`, which runs the normal frontend, emits C++ with debug source
markers, and compiles it with an unoptimized GCC/Clang command. The build lives
in a temporary directory owned by the session.

The bridge is a small synchronous GDB/MI2 client. `GdbMi` starts GDB with
`--interpreter=mi2 --quiet --nx`, multiplexes result records (`^done`,
`^running`, `^error`, `^exit`), async records (`*stopped`, `*running`), and
notifications (`=thread-created`, `=library-loaded`), and exposes a command
method that waits for the matching token. GDB writes the inferior's stdout and
stderr to two different pipes in practice: target stdout may arrive as plain
lines on GDB's stdout, while target stderr arrives on GDB's stderr. `dap.py`
forwards target stdout as DAP `stdout`, target stderr as DAP `stderr`, and
GDB's own notices as `console`, filtering the `(gdb)` prompt. This detail is
why the adapter does not merge GDB's stderr into the MI stream.

Breakpoints are sent to GDB as `path:line`, using the same absolute,
forward-slash path that `CodeGen` writes into `#line`. GDB therefore resolves
breakpoints and reports frames in Vanta terms without a post-processing source
map. User variables are emitted with a `v_` prefix; the adapter strips it for
the **Locals** and **Arguments** scopes and hides compiler temporaries.
Generated wrapper frames are attributed to the temporary generated `main.cpp`
so they are visibly distinct from Vanta frames. The native entry point is
attributed to the Vanta file as well. GDB's current source - the file a bare
`break 3` and `list` use - follows the entry point in some versions and the
compilation unit's name (the generated C++) in others, so `vanta debug` also
selects the Vanta file explicitly before the prompt appears
(`_source_prelude`, run through GDB's Python API so it prints nothing). A line
number typed at the prompt therefore always means the line a Vanta programmer
wrote.

Conditional breakpoints, hit counts, and log points are evaluated by the
adapter, not by GDB. GDB cannot evaluate a condition before the program is
running, and it only knows the generated names, so `hp > 0` would be
meaningless to it. The adapter instead keeps the DAP request next to the GDB
breakpoint number, translates the expression to the generated names
(`_translate_vanta_expression` rewrites bare identifiers to `v_<name>` and
rewrites `len(x)` to the field the code generator inlines), and evaluates it
in the stopped frame with `-data-evaluate-expression`. A hit that should not
stop is answered with `-exec-continue` and no `stopped` event, which is how a
log point behaves. Function breakpoints are resolved to the generated symbol
(`vanta_user::fn_<name>`, or `fn_vanta_m_<module>__<name>` for an imported
module) and inserted as ordinary GDB breakpoints, so they report the Vanta
file and line of the function's first statement. Watch expressions are kept
in a list and re-evaluated for the **Watch** scope on every stop. Restart
rebuilds the program, reloads it with `-file-exec-and-symbols`, re-creates the
breakpoints, and runs it again.

Editing a variable follows Vanta's own rule: only a binding declared with
`mut` may be written. The debug build keeps the set of mutable locals per
function (`mutable_locals()` in `driver.py` walks the function bodies), and
the adapter refuses an edit to an immutable binding - GDB would allow it,
because the generated C++ variable is not `const`. A value that cannot fit
the variable's type is refused as well. A field of a struct follows the
binding that holds the struct, so a field of a `mut` struct can be edited
and a field of a `let` struct cannot.

Data breakpoints are GDB watchpoints on the address of a local. The address
is only handed out to clients that advertise `supportsDataBreakpoints`,
because computing it costs one GDB round trip per variable. The registers
view reads `-data-list-register-names` and `-data-list-register-values`, and
raw memory reads use `-data-read-memory-bytes`.

The debug build also carries the source map of the program: which lines
hold a statement, and which function they belong to (`source_lines()` in
`driver.py` walks the function bodies). That map answers the
`breakpointLocations` request, so an editor knows which lines can hold a
breakpoint, and it limits the jump targets to the function that is
running. A jump moves the program counter with GDB's `jump` command and
lets the program continue. Exception breakpoints are GDB catchpoints; GDB's
machine interface has no catchpoint command, so they are set through the
console and their numbers are picked up from the notification GDB sends.

A session can also attach to a program that is already running. The attach
request names the executable that is running, because the breakpoints and
the stack are resolved from its debug information; GDB is started with it
and `-target-attach` takes over the process. An attached session never
starts the program, and the frontend alone is enough to know the source
map. Stepping selects the thread the editor asked for, so a step acts on
that thread, and the disassembly request reads the machine code with
`-data-disassemble`.

The Variables view speaks Vanta. The debug build carries the layout of every
struct and enum (`program_layouts()` in `driver.py` reads it from the type
checker), so the adapter can offer a struct as an expandable node, read its
fields one at a time, and show the member an enum holds instead of a
number. The generated C++ prefixes every field with `v_`, so a field is read
as `v_player.v_hp`. A `str` is shown as its text and a `List` as the number
of items it holds.

DAP stdio lifecycle is intentionally blunt: after `serve()` cleans up GDB and
the temporary build, `run_stdio()` flushes and exits with `os._exit(0)`. A
daemon stdin-reader thread can otherwise fight interpreter shutdown over the
buffered stdin lock and produce a fatal Python error when the client closes the
pipe.

## Backend (C++17)

`runtime/vanta_runtime.hpp` is a single-header runtime providing:

- `Vec2`, `Vec3`, `Quat`, `Matrix4` (row-major) with their operators
- `Str` — immutable, reference-counted strings; literals are zero-copy static
  views, and owned buffers are freed by the last copy
- the `Arena` bump allocator; it constructs and destroys non-trivial element
  types, so `alloc::<str>` and structs containing `Str` are well-defined
- `List<T>` with `list_new` / `list_push` / `list_pop` / `list_insert` /
  `list_remove` / `list_sort` (a stable merge sort driven by the caller's
  comparator function value) / `list_at_checked[_ref]` — the arena-backed
  growable lists behind `arena.list::<T>()`
- `StrBuilder` with `strb_append_*` / `strb_to_str` / `strb_clear` — arena-backed
  string building behind `arena.str_builder()`; `to_str()` returns an owned
  `Str`, so results survive the builder and arena
- `at_checked` / `at_checked_ref` (plus `index_fail`) — the bounds-checked
  access behind `xs.at(i)`; a bad index reports the array size and the
  access's source line
- `ptr_at_checked` / `ptr_at_checked_ref` (plus `ptr_index_fail`) — the
  bounds-checked access behind `p.at(i, size)`; the caller supplies the
  accessible count because a raw pointer carries no length
- IO, `sqrt` and trig (`sin`/`cos`/`tan`/`atan2`), `abs`/`min`/`max`/`floor`/`ceil`, and integer/float conversion helpers
- `write_*` variants of the `print_*` functions (no trailing newline)
- `print_fmt_impl` — the `printf`-backed target of `print_fmt`/`write_fmt`
- `str_eq` (`memcmp`-backed byte equality), `str_len`, and
  `str_to_i32`/`str_to_f32`
- `str_concat` and `to_str_*` — return owned `Str` values; `str_pool_reset` is
  a compatibility no-op
- `file_exists` / `file_read` / `file_write` — byte-exact file I/O; `file_read`
  returns an owned `Str` and `file_write` returns the byte count or `-1`
- `rand_state` / `rand_seed` / `rand_f32` — xorshift32, fixed seed at startup
  so programs are reproducible unless explicitly seeded
- `g_argc` / `g_argv`, populated by the generated `main`, exposed as
  `arg_count` / `arg_str`

## Packaging (v0.28.0, VSIX in v0.32.0, debugger in v0.33.0)

A checkout keeps the runtime at `runtime/`, the kit at `examples/gamekit/`,
the assets at `examples/assets/`, and the standard library at `stdlib/`, so
the examples and tests use the canonical copies. A wheel has no checkout
around it, so `setup.py` overrides `build_py` to copy those directories into
the build tree as `compiler/runtime/`, `compiler/templates/gamekit/`,
`compiler/templates/assets/`, and `compiler/templates/stdlib/`; setuptools
then packs them into the wheel. `MANIFEST.in` includes the same files in the
sdist, so building a wheel from the sdist works too.

The driver resolves each directory through `_first_existing_dir`: it looks
beside `compiler/` first (the installed layout) and falls back to the repo root
(the checkout layout). `vanta doctor` reports which paths won, compiles a
one-line probe against the runtime header, and makes a best-effort SDL2 check.
The CI `package` job builds the wheel, installs it into a fresh venv, and runs
only the installed `vanta` command; a separate `vscode` job runs `npm ci`,
compiles the TypeScript client, and packages the VSIX.
`.github/workflows/release.yml` repeats the smoke test on tags, builds the
VSIX, attaches the wheel, sdist, and VSIX to the GitHub release, and can
publish the Python distributions to PyPI through Trusted Publishing (enabled
with the `PUBLISH_PYPI=true` repository variable). The VSIX includes its
production `vscode-languageclient` dependencies, so it installs without a
separate `npm install`. The same VSIX carries the `vanta` debugger
contribution; the adapter itself lives in the Python package, so an installed
wheel and a checkout provide the same debugger.

## Versioning

`compiler/__init__.py` holds the single `VERSION` string. The driver reports it
for `--version`, and `codegen_cpp.py` writes it into the generated file's
header. There is no second copy to keep in sync.

## Diagnostics

All source-level errors carry `file:line:col`. The driver saves generated C++ on
compilation failure to `build/vanta_failed.cpp`.

## Ownership (v0.2.6)

The only rule enforced is that **`Arena` is non-copyable**: `let a2 = a1` (where
`a1: Arena`), `return a1`, and passing an `Arena` as an argument are all
rejected. `ptr<T>` has no borrow checking, lifetime tracking, or aliasing
analysis, so dangling and aliased pointers are not detected; the checker only
guards the conversions (widening to `ptr<void>` is implicit, the reverse is
an error) and offers `ptr_is_null`. `p.at(i, size)` (v0.25.0) is an opt-in
bounds check; `p[i]` and the cast/offset escape hatches stay unchecked.
`ptr_cast::<T>(p)` (v0.17.0) is the
explicit, unchecked reinterpretation, `ptr_offset(p, n)` (v0.18.0) the
explicit, unchecked element step, and `ptr_null::<T>()` (v0.19.0) the
explicit null — a function-type `T` makes it a null callback — so the
escape hatches stay opt-in.
Broader ownership analysis is out of scope.

## Tests

`tests/` holds 817 `unittest` cases across the lexer, parser, loader, type
checker, code generator, language server, debug adapter, and end-to-end
integration. The GDB tests skip when no working GDB is found; one verifies
source-mapped breakpoints directly, another runs a complete stdio DAP session
through launch, stop, locals, continue, and disconnect, and two more groups
cover the breakpoint kinds, watch expressions, restart, editing, data
breakpoints, registers, memory reads, breakpoint locations, jump targets,
exception breakpoints, attaching to a running program, expanding a struct,
watching a struct field, and a condition that only becomes true later.
Integration tests compile and run
real binaries and skip automatically when no C++17 compiler is present. The
SDL2 tests build, link, and run the SDL examples headless
(`SDL_VIDEODRIVER=dummy` plus a frame-limit argument; the audio tests use
`SDL_AUDIODRIVER=dummy`, whose device paces playback in real time) and skip
when SDL2 is not installed; the SDL_ttf tests (the raw text example, pong's
text score, the `text` kit module) and the SDL2_image tests (the raw texture
example, the `image` kit module, breakout) do the same and skip when their
library is missing; audio needs no library beyond SDL2 core, and the WAV
format tests write their own sample files. CI installs SDL2, SDL_ttf, and
SDL2_image on Linux, macOS, and Windows. The game kit's `rng` module has no
SDL dependency and is covered by its own test, so part of the kit runs
anywhere a C++ compiler does.

```powershell
python -m unittest discover -s tests
```
