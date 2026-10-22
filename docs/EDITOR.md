# Editor support

Vanta v0.54.0 ships a language server, a native debugger, and a VS Code client.
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

Download `vanta-language-0.25.0.vsix` from the latest Vanta GitHub release and
install it:

```powershell
code --install-extension vanta-language-0.25.0.vsix
```

### Build from source

```powershell
cd editors/vscode
npm install
npm run package
code --install-extension vanta-language-0.25.0.vsix
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
and document symbols. It does not require a workspace root to start.

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
