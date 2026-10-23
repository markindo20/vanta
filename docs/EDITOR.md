# Editor support

Vanta v0.65.0 ships a language server, a native debugger, and a VS Code client.
The server and debug adapter are part of the compiler package, so an installed
`vanta` command and a source checkout provide the same editor features.

## What you get

- **Diagnostics** for lexer, parser, import, and type errors. The server
  validates unsaved buffers with the same frontend used by `vanta check`, and
  diagnostics from imported files are published to the file that contains the
  error.
- **Completion** for keywords, builtins, declarations, parameters, local
  variables, module aliases, enum members, struct fields, and the common
  builtin methods on `List`, `Arena`, `StrBuilder`, `Vec2`, `Vec3`, and `Quat`.
- **Signature help** in an open call: the parameters are listed and the one
  being typed is highlighted. It works for local and imported functions,
  builtin functions, function values, builtin methods, struct constructors,
  and enum payload members, including calls that span lines.
- **Hover** signatures and types for functions, constants, types, parameters,
  locals, enum members, struct fields, and imported declarations.
- **Go to definition** for functions, constants, types, parameters, locals,
  imported declarations, enum members, and struct fields.
- **Find All References** with `Shift+F12` and **Rename Symbol** with `F2`.
  References are scope-aware: a shadowing inner local is not part of the outer
  binding, and a field or enum member with the same name as a local is kept
  apart. Rename edits every file the project index can load, including the
  declaring module of an imported symbol.
- **Quick fixes** under the light bulb (or `Ctrl+.`): unknown names suggest the
  closest visible name, missing struct fields and enum members suggest the
  nearest member of that type on member access and constructor labels, and an
  assignment to an immutable local offers `let` to `mut`.
- **Go to Symbol in Workspace** with `Ctrl+T`: functions, structs, enums,
  constants, struct fields, and enum members from every Vanta file in the
  project.
- **Semantic highlighting**: names are coloured by what they are - a function,
  a struct, an enum, a constant, a parameter, a local, a struct field, an
  enum member, or a module alias - so a local and a field with the same name
  no longer look alike.
- **Format Document** rewrites the file with the canonical indentation:
  four spaces per block level, comments kept in place, and one blank line
  between blocks.
- **Inlay hints** show the inferred type of a local that has no type
  annotation, right where it is written.
- **A code lens** above every function that is used somewhere, showing how
  many places call it; clicking the count opens the list.
- **A call hierarchy**: who calls this function, and what does it call.
- **A type hierarchy**: which structs hold this type, and which types this
  struct holds.
- **Document highlighting**: every occurrence of the symbol under the cursor
  in the current file, scope-aware, so a name and its uses light up together.
- **Document links**: an `import` path opens the file it names; an unresolved
  path is marked.
- **Folding** for function and struct bodies, nested blocks, `match` arms,
  comment runs, and import runs.
- **Selection ranges** to grow a selection from the word under the cursor to
  its line, the enclosing blocks, and the whole file.
- **Import hover** to see the resolved target of an `import` (or that it is
  unresolved).
- **Go to definition** on an `import` path jumps to the imported file.
- **Semantic tokens** for import paths: the string literal in `import "path"`
  is classified as a string for distinct highlighting.
- **Workspace symbol filter**: the symbol search can be restricted by kind
  (function, struct, enum, field, enum member).
- **Document symbols** for the outline view, including struct fields and enum
  members under their containing declaration.
- **Native debugging** through a `vanta` debug configuration: line,
  function, conditional, hit-count, log-point, data, and exception
  breakpoints, instruction breakpoints from the disassembly view, stack
  traces, locals and arguments with structs and lists that expand
  into their fields, a scope for the program's constants, watch
  expressions, editing mutable locals, registers,
  disassembly and memory, run-to-cursor,
  continue/step/pause, `stopOnEntry`, program output, attaching to a running
  program, restart, and clean termination.
- Syntax highlighting and language configuration for `.vnt` files.

The server uses full-document text sync. That keeps the first version small and
makes diagnostics reason about exactly the buffer the editor is showing.
Completion and navigation use a tolerant source index, so they keep working
while a line is only half typed.

## References and rename

Put the cursor on a name and press `Shift+F12` to list its references, or `F2`
to rename it. The server resolves the word to a declaration instead of matching
text, so shadowing works:

```vanta
func main() -> i32:
    let x: i32 = 1
    if x > 0:
        let x: i32 = 2
        return x    # the inner x, not the outer one
    return x
```

Rename covers declarations and uses of functions, structs, enums, constants
and imported declarations; parameters, locals, `for` variables, and match-arm
bindings; struct fields (including constructor labels); enum members (including
payload constructors and `match` patterns); module aliases; and type names in
every annotation, field, return type, and constructor call. A rename returns a
workspace edit, so files other than the one you are editing change in place
when the editor applies it.

Builtins, keywords, and names that cannot be resolved are refused. A field or
member access is renamed only when the receiver's type can be established from
an annotation, parameter, constructor, loop element, or function return type;
an unknown receiver is left alone rather than guessed.

## Quick fixes

When a diagnostic is under the cursor, the light bulb (or `Ctrl+.`) offers a
repair. The server answers `textDocument/codeAction` with `quickfix` actions:

- An unknown name gets the closest visible name, considering locals,
  parameters, declarations, imported symbols, module aliases, builtins, and
  type names. Typing `valeu` where `value` exists offers `value`.
- A missing struct field or enum member gets the nearest member of that type.
  The action works on a member access (`e.hpp` offers `hp`) and on a
  constructor label (`Enemy(hpp: 1)` offers `Enemy(hp: 1)`). The member list
  comes from the receiver's type, so a field of an unrelated struct is never
  offered.
- `invalid assignment target` on a write to an immutable `let` local offers
  **Make 'x' mutable**, rewriting that declaration's `let` to `mut`. A write
  through a field (`e.hp = 5`) changes the root binding, because the type
  checker requires the root to be mutable.

The best match is marked as preferred, and up to three suggestions are offered.
Actions replace only the identifier, or the `let` keyword in the mutability
fix, so the surrounding code is untouched. Parameters and loop variables have
no declaration keyword to rewrite and are left alone, and a diagnostic outside
these families produces no action.

## Workspace symbols

`Ctrl+T` opens **Go to Symbol in Workspace**, which asks the server for
`workspace/symbol`. The server walks every `.vnt` file under the workspace
root and lists the declarations it finds: functions, structs, enums,
constants, struct fields, and enum members. Each result carries its kind and
the module or declaration that contains it.

```vanta
module game

pub struct Enemy:
    hp: i32
```

Searching `hp` lists the field with `Enemy` as its container; searching
`enem` finds `Enemy` itself.

Matching is forgiving. An exact name ranks first, then a prefix, then a
case-insensitive substring, and finally a loose subsequence, so `dmg` still
finds `damage`. The file list is cached for a few seconds and a file is
re-parsed only when it changes, so typing in the picker stays fast. An unsaved
buffer is searched as it is on screen, not as it is on disk.

Without a workspace root the server searches the open documents and the
modules they import.

## Semantic highlighting

The editor colours Vanta code by what each name *is*, not by how it is
spelled. The server answers `textDocument/semanticTokens/full` and uses the
same scope-aware resolver that powers references and rename, so the colouring
is exact:

| Kind | Examples |
| --- | --- |
| function | `damage`, `main` |
| struct | `Enemy` |
| enum | `Color` |
| constant | `LIMIT` (also marked read-only) |
| parameter | `e`, `amount` |
| local | `total` |
| struct field | `hp` |
| enum member | `red` |
| module alias | `g` in `g.Enemy` |

A local named `hp` and a field named `hp` therefore get different colours,
and a shadowing inner local is told apart from the outer one. Builtins such
as `print_i32` and `Vec2` are marked as library code, and a declaration is
marked as one. Keywords, operators, strings, numbers, and comments keep their
lexical colouring.

The tokens are computed from the buffer as it is on screen, so an unsaved
file is highlighted the way it is written, and a file that does not parse yet
is still highlighted as far as it goes.

## Formatting

**Format Document** in the editor rewrites the file with the canonical
indentation, and the same formatter is available on the command line:

```powershell
vanta fmt game.vnt            # rewrite the file in place
vanta fmt --check game.vnt     # report whether it is already formatted
```

The formatter normalizes the whitespace around a program and never the
program itself:

- every logical line is indented with four spaces per block level,
- a line that continues an expression keeps its alignment relative to the
  line that opened it,
- a comment keeps its text and its place in the file,
- trailing whitespace is removed, runs of blank lines collapse to one, and
  the file ends with exactly one newline.

Only the indentation of a line changes, so the block structure the parser
sees is the same before and after, and formatting a formatted file changes
nothing. A file that does not parse is refused rather than reformatted:
the formatter cannot know what the author meant.

## Inlay hints

The editor shows the type of a local that has no type annotation, right
next to the name:

```vanta
let x = add(1, 2)     # x: i32
let e = Enemy(hp: 1)  # e: Enemy
let h = e.hp          # h: i32
```

The type is inferred rather than spelled out, and it is the type the
compiler will actually use: a call returns what its function returns, a
constructor returns the struct it builds, and a field access returns the
field's type. A local that already has an annotation gets no hint, because
the type is already written down.

## Code lens

Above every function that is used somewhere, the editor shows how many places
call it:

```vanta
func helper() -> i32:    # 2 references
    return 1
```

Clicking the count opens the list of the uses, so you can jump straight to
one. The count is the number of *uses*, and it is scope-aware: a call in
another module counts, a local with the same name in another function does
not, and the declaration itself does not count. The count therefore matches
what **Find All References** would list.

A function nobody calls gets no lens, because "0 references" says nothing
worth reading.

## Call hierarchy

Put the cursor on a function and the editor can show who calls it and what
it calls:

```vanta
func helper() -> i32:     # called by main
    return 1

func main() -> i32:       # calls helper
    return helper()
```

The hierarchy is scope-aware, because it comes from the same resolver that
powers references and rename: a call in another module is a caller, a local
with the same name in another function is not, and a function passed around
as a value is not a call either. The line of each call is reported, so the
editor can jump straight to it.

## Type hierarchy

Put the cursor on a struct and the editor can show which structs hold it
and which structs it holds:

```vanta
struct Inner:
    hp: i32

struct Outer:
    inner: Inner        # Outer holds Inner
```

Vanta has no inheritance, so the hierarchy is the one the language actually
has: a struct that holds another **by value**. A `ptr<T>` field does not
count, because a pointer does not embed the struct - it only refers to it.
The relation is resolved by name across modules, so a struct in another
file is found.

## Document highlighting

Put the cursor on a name and the editor highlights every occurrence of the
same symbol in the current file:

```vanta
struct Enemy:
    hp: i32

func heal(target: Enemy, amount: i32) -> void:
    target.hp = target.hp + amount   # all three 'hp' names highlight
```

Highlighting is scope-aware, because it comes from the same resolver that
powers references and rename: a shadowing local with the same name is not
highlighted, and a field is highlighted only where the receiver has the
declaring struct's type. The declaration is reported as text and each use as
a read. A word that resolves to nothing still highlights every textual
occurrence of that word, so an unfinished line keeps the feature.

Unlike **Find All References**, the highlights stay in the current file and
need no second click; they follow the cursor. That is also the limit: a use
in another module is not highlighted, even when the file is imported.

## Document links

An `import` path is a link. Hover it to see the file it resolves to and
follow it to open that file:

```vanta
import "std/option.vnt"
import "enemy.vnt" as enemy
```

The target comes from the loader, not from a second guess at the path, so a
relative import, an aliased import, and a `std/` import all point at the file
the compiler actually reads. A path that does not resolve stays a link with
no target, and its tooltip says the import is unresolved.

## Folding

Every indented block folds from the line that opens it: a function body, a
struct or enum body, a nested `if` or loop, and a `match` arm. The fold ends
on the last non-blank line of the block, so trailing blank lines stay
outside it.

```vanta
func main() -> void:
    if true:
        print_str("nested")
    print_str("outer")
```

Ranges come from indentation rather than from the parse tree, so folding
keeps working while a line is only half typed. A run of two or more comment
lines folds as a comment region, and a run of consecutive `import` lines
folds as an imports region.

## Install the compiler

The server is launched through the `vanta` command:

```powershell
pipx install vanta-lang
# or
python -m pip install vanta-lang
```

Check it:

```powershell
vanta --version
```

A checkout works too. From the repository root:

```powershell
python main.py --version
python -m compiler lsp
```

## Install the VS Code client

The extension requires VS Code 1.82 or newer and Node 22 if you build it from
source.

### From a release

Download `vanta-language-0.36.0.vsix` from the latest Vanta GitHub release and
install it:

```powershell
code --install-extension vanta-language-0.36.0.vsix
```

### Build from source

```powershell
cd editors/vscode
npm install
npm run package
code --install-extension vanta-language-0.36.0.vsix
```

To work on the extension itself, open `editors/vscode` in VS Code and press
**F5**. The extension development window loads the compiled client from
`out/`.

## Server discovery

The client tries these locations in order:

1. The `vanta.server.path` setting. This may be an absolute path, a path
   relative to the workspace, `~`-expanded, or a command name on `PATH`.
2. `vanta` or `vanta.exe` inside a workspace `.venv`, `venv`, or `env`.
3. `vanta` on `PATH`.
4. A Python interpreter that can `import compiler`. The client runs that
   interpreter with `-m compiler lsp`. Workspace virtualenvs are preferred,
   then `python3` and `python` on `PATH` (`py` as well on Windows).

If `vanta.server.path` names a Vanta executable, the client runs it as
`<path> lsp`. If it names a Python interpreter, the client runs
`<path> -m compiler lsp`.

## Settings

| Setting | Default | Description |
| --- | --- | --- |
| `vanta.server.path` | `""` | Path to the `vanta` executable or a Python interpreter. Empty means automatic discovery. Used for both the language server and the debug adapter. |
| `vanta.debug.gdbPath` | `""` | Path to a GDB executable. Empty means `VANTA_GDB`, a GDB beside the C++ compiler, a WinLibs/MSYS2 installation, or `gdb` on `PATH`. |

Run **Vanta: Restart Language Server** after changing `vanta.server.path`. The
GDB setting is read when a new debug session starts.

Example for a Windows virtualenv:

```json
{
  "vanta.server.path": "C:\\Users\\you\\projects\\vanta\\.venv\\Scripts\\vanta.exe"
}
```

Example using the Python fallback:

```json
{
  "vanta.server.path": "C:\\Users\\you\\projects\\vanta\\.venv\\Scripts\\python.exe"
}
```

## Debugging

The extension registers the `vanta` debugger type. Press **F5** on a Vanta file
and choose **Vanta** if prompted, or add a configuration:

```json
{
  "type": "vanta",
  "request": "launch",
  "name": "Debug Vanta Program",
  "program": "${workspaceFolder}/game.vnt",
  "cwd": "${workspaceFolder}",
  "args": [],
  "stopOnEntry": false
}
```

The adapter builds an unoptimized native executable with Vanta source
locations, starts GDB in MI2 mode, and translates breakpoints, stack frames,
scopes, stepping, and output into DAP. The **Locals** and **Arguments** scopes
show Vanta names without the generated `v_` prefix. Breakpoints in imported
Vanta files work because every statement carries its original file and line.

Beyond plain line breakpoints the adapter supports function breakpoints,
conditional breakpoints, hit counts, log points, watch expressions, data
breakpoints, and restart. Conditions and watch expressions are written in
Vanta terms (`hp > 0`, `len(items) == 3`), and the adapter maps them onto the
generated names.

A session can be recorded: set `vanta.debug.logFile` to a path and every
message between the editor and the debugger, and every line of GDB
traffic, is written there.

A local can be edited from the **Variables** view, but only when Vanta allows
it: only a binding declared with `mut` may be written, and an immutable
binding is refused with a clear message. A field of a struct follows the
binding that holds it. The **Registers** view, the
disassembly view, and raw memory reads are available as well, and the
adapter tells the editor which lines can hold a breakpoint, so it can grey
out the ones that cannot.

A debug session needs GDB plus a GCC or Clang toolchain. MSVC builds normal
programs but emits PDB files, which this debugger does not read. Set
`vanta.debug.gdbPath` when GDB is not on `PATH`. On macOS, `lldb-mi` is used
instead of GDB. The debug adapter is launched
through the same discovery as the language server: a configured
`vanta.server.path` may be a `vanta` executable or a Python interpreter, and
the client runs `vanta dap` or `python -m compiler dap`.

See [`docs/DEBUGGER.md`](DEBUGGER.md) for the full guide, editor-agnostic DAP
setup, source-mapping details, and troubleshooting.

## Other editors

Any LSP client can launch the server as a stdio process:

```powershell
vanta lsp
```

The server advertises UTF-16 positions, open/close document sync, full
document changes, completion, signature help, hover, definition, references,
rename (with prepare support), quick fixes, workspace symbols, semantic tokens,
formatting, inlay hints, code lenses, call hierarchy, type hierarchy, and
document symbols. It does not require a workspace root to start.

For debugging, any DAP client can launch:

```powershell
vanta dap
```

The adapter uses `Content-Length`-framed DAP on stdin/stdout and accepts the
standard launch fields `program`, `cwd`, `args`, and `stopOnEntry`, plus an
optional `gdbPath`. See [`docs/DEBUGGER.md`](DEBUGGER.md).

## Limitations

- The frontend stops at the first lex, parse, load, or type error, so the
  server publishes one diagnostic per validation. Fix it and the next one
  appears.
- Completion inside an incomplete declaration is recovered from source text
  and is deliberately best-effort. Once the file parses, the AST gives exact
  declaration and local-variable information.
- References and rename cover the files the project index can load: the current
  file, other open documents, and their imports. A file that is neither open
  nor imported is not searched. A field or member use whose receiver type
  cannot be established is left untouched rather than risk a wrong edit, and
  builtins, keywords, and unresolved names are refused.
- Quick fixes cover the five diagnostic families described above (unknown name,
  missing field, missing enum member, unknown constructor label, and invalid
  assignment target). There is no formatting, semantic token, or refactor
  code action support yet.
- Workspace symbols cover the files under the workspace root and the imports
  of the open documents. A file that is neither in the root nor imported is
  not searched, and locals and parameters are not workspace symbols.
- Semantic highlighting marks the kinds of names it can resolve. A name that
  resolves to nothing is left to the lexical colouring, and a file that does
  not parse is highlighted as far as it goes.
- The formatter refuses a file that does not parse, and it does not rewrite
  the text inside a line: only the indentation, the blank lines, and the
  trailing whitespace change.
- Inlay hints cover a local without a type annotation. A type the resolver
  cannot establish is left out rather than guessed.
- The code lens counts the uses of a function the project index can reach.
  A function called only from a file the index cannot load shows no lens.
- The call hierarchy covers the files the project index can reach, and it
  reports a call, not a mention: a function used as a value is not a caller.
- The type hierarchy holds a struct only when the field is by value. A
  `ptr<T>` or `List<T>` field is a reference, not a holding.
- Document highlighting stays inside the current file. A use in another
  module is not highlighted, and every use is reported as a read: an
  assignment target is highlighted but not distinguished as a write. A name
  the resolver cannot place falls back to textual matches of the same word.
- Document links cover `import` paths only, and the target is resolved when
  the document is loaded. A path that does not resolve has no target until
  the file appears next to the importing one.
- Folding follows indentation, not the parse tree. A continuation line that
  is indented deeper than the statement that opened it becomes a fold of its
  own, and a file with inconsistent indentation folds where the indentation
  says, not where the parser would.
- Selection ranges grow from the word under the cursor through its line and
  each enclosing indentation block; an inconsistent indent file selects
  where the indentation says.
- Import hover and definition use the tolerant project index (the same
  resolver as document links). If the file parses, the AST gives exact
  positions; otherwise the line-scanner recovers the import and the loader
  resolves the path.
- Semantic tokens for import paths use the AST import nodes for exact
  positions. Workspace symbol filtering uses the same symbol kinds as
  document symbols.
- The debugger is intentionally a first milestone: no remote debugging; no
  reverse debugging; no LLDB or MSVC/PDB support. Breakpoint conditions, hit
  counts, and log points are evaluated by the adapter, so the program pauses
  briefly at every hit. Debug sessions always use an unoptimized build.

## Troubleshooting

- **No editor features:** run `vanta --version` in a VS Code terminal. If it
  fails, install `vanta-lang` into the active environment or set
  `vanta.server.path`.
- **The server fails to start:** open the **Vanta** output channel. It logs
  the resolved command and the server's error message.
- **Wrong Python environment:** point `vanta.server.path` at the exact
  executable or interpreter. The client does not try to choose between
  several global Python installations.
- **A diagnostic points at an imported file:** that is intentional. The
  loader stamps each AST position with its source file, so the error is shown
  where it belongs rather than at the importing entry file.

## Protocol tests

The transport is ordinary LSP framing: a `Content-Length` header, a blank
line, then a UTF-8 JSON body. Send `shutdown` and then `exit` to stop the
process. `tests/test_lsp.py` exercises the transport through both
`vanta lsp` and `python -m compiler lsp`, along with every editor request,
unsaved buffers, imported-file diagnostics, and UTF-16 position conversion.
`tests/test_dap.py` covers DAP framing, GDB/MI parsing, debug source markers,
expression translation, and optional GDB tests that verify a breakpoint lands
on the original Vanta file and line, that a real stdio adapter session can
inspect locals and finish cleanly, and that log points, conditions, hit
counts, function breakpoints, watch expressions, and restart behave as
documented.
