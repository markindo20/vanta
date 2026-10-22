# Vanta for VS Code

Language support and native debugging for Vanta `.vnt` files, powered by the
`vanta lsp` language server and the `vanta dap` debug adapter.

## Features

- **Diagnostics** from the real lexer, parser, loader, and type checker,
  including unsaved buffers and imported files.
- **Completion** for keywords, builtins, declarations, locals, module aliases,
  enum members, struct fields, and builtin methods on `List`, `Arena`,
  `StrBuilder`, `Vec2`, `Vec3`, and `Quat`.
- **Signature help** in an open call for functions, builtin methods, struct
  constructors, and enum payloads.
- **Hover** signatures and types for functions, declarations, locals, and
  members.
- **Go to definition** for functions, constants, types, parameters, locals,
  imported declarations, enum members, and struct fields.
- **Find All References** and **Rename Symbol**, scope-aware and across the
  files the language server can load. Rename brings constructor labels, match
  patterns, module aliases, and type annotations along.
- **Quick fixes** under the light bulb: unknown names suggest the closest
  visible name, missing struct fields and enum members suggest the nearest
  member of that type, and an assignment to an immutable local offers
  `let` to `mut`.
- **Go to Symbol in Workspace** with `Ctrl+T`: functions, structs, enums,
  constants, struct fields, and enum members from every Vanta file in the
  project.
- **Semantic highlighting**: names are coloured by what they are - a
  function, a struct, an enum, a constant, a parameter, a local, a struct
  field, an enum member, or a module alias.
- **Format Document** rewrites the file with the canonical indentation.
- **Inlay hints** show the inferred type of a local without an annotation.
- **A code lens** above every used function, showing how many places call it.
- **Document symbols** / outline view for functions, structs, enums, fields,
  and enum members.
- **Debugging** with the `vanta` debugger type: line, function, conditional,
  hit-count, log-point, data, and exception breakpoints, stack traces, locals
  and arguments with structs that expand into their fields, watch
  expressions, editing mutable locals, registers and
  memory, run-to-cursor, continue/pause/step, `stopOnEntry`, program output,
  attaching to a running program, remote debugging, editing a struct field,
  restart, and clean termination. Requires GDB and a GCC/Clang toolchain.
- Syntax highlighting and language configuration, including `#` comments.

## Requirements

- VS Code 1.82 or newer.
- A Vanta compiler reachable as one of:
  1. `vanta.server.path` (an executable, a Python interpreter, or a command
     name),
  2. `vanta` or `vanta.exe` inside a workspace `.venv`, `venv`, or `env`,
  3. `vanta` on `PATH`,
  4. a Python interpreter that can `import compiler` (the extension then runs
     `python -m compiler lsp` or `python -m compiler dap`).
- For debugging: GDB 10+ and a GCC/Clang C++17 toolchain. MSVC/PDB is not
  supported by the debugger.

Install the compiler with:

```powershell
pip install vanta-lang
```

or work from a checkout of the repository. The Python fallback launches the
server as `python -m compiler lsp`.

## Install the extension

### From a VSIX

Download `vanta-language-0.28.0.vsix` from the latest Vanta GitHub release, then:

```powershell
code --install-extension vanta-language-0.28.0.vsix
```

### Build it yourself

Building requires Node 22 or newer.

```powershell
cd editors/vscode
npm install
npm run package
code --install-extension vanta-language-0.28.0.vsix
```

### Run from source

Open this folder in VS Code and press **F5** (Run Extension). In the extension
development window, open any `.vnt` file.

## Settings

| Setting | Default | Description |
| --- | --- | --- |
| `vanta.server.path` | `""` | Path to the `vanta` executable or a Python interpreter. Empty means automatic discovery. Used for both LSP and DAP. |
| `vanta.debug.gdbPath` | `""` | Path to GDB. Empty means `VANTA_GDB`, a GDB beside the compiler, WinLibs/MSYS2, or `gdb` on `PATH`. |

Use **Vanta: Restart Language Server** from the command palette after changing
`vanta.server.path`. `vanta.debug.gdbPath` is read when a debug session starts.

### Explicit executable on Windows

```json
{
  "vanta.server.path": "C:\\Users\\you\\projects\\vanta\\.venv\\Scripts\\vanta.exe"
}
```

### Python module fallback

If you do not have a `vanta` executable, point the extension at a Python
interpreter that can import the compiler:

```json
{
  "vanta.server.path": "C:\\Users\\you\\projects\\vanta\\.venv\\Scripts\\python.exe"
}
```

When `vanta.server.path` names a Vanta executable, the extension runs
`<path> lsp` for the language server and `<path> dap` for the debugger. When it
names a Python interpreter, it runs `<path> -m compiler lsp` or
`<path> -m compiler dap`. When it names a command (for example `vanta`), it
relies on `PATH`.

## Debugging

Open a `.vnt` file and press **F5**, or add a launch configuration:

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

The extension builds an unoptimized executable with Vanta source locations and
starts the debug adapter. Breakpoints, stack frames, locals, arguments,
stepping, and program output work in the Debug view. Function breakpoints,
conditional breakpoints, hit counts, log points, data breakpoints, watch
expressions, editing mutable locals, registers, memory reads, run-to-cursor,
disassembly, attaching to a running program, and restart are supported as
well; conditions and watch expressions are
written in Vanta terms (`hp > 0`, `len(items) == 3`), and only a binding
declared with `mut` can be edited. Set `vanta.debug.gdbPath` when GDB is not on `PATH`. See
[`docs/DEBUGGER.md`](https://github.com/markindo20/vanta/blob/master/docs/DEBUGGER.md)
for the full guide and troubleshooting.

## Troubleshooting

- **No diagnostics or completion:** run `vanta --version` in the VS Code
  terminal. If that fails, install `vanta-lang` into the active environment or
  set `vanta.server.path`.
- **Server failed to start:** open the **Vanta** output channel. It logs the
  resolved command and the server's error message.
- **Wrong Python environment:** set `vanta.server.path` to the exact `vanta`
  executable or Python interpreter. The extension does not guess between
  multiple global Python installations.
- **Diagnostics show only the first error:** the Vanta frontend stops at the
  first lex/parse/type error, so the server publishes that error. Fix it and
  the next one appears.

## Development

```powershell
npm install
npm run compile
npm run watch
```

The TypeScript source lives in `src/extension.ts`; compiled output goes to
`out/`. `npm run package` builds a VSIX.

The language server is implemented in `compiler/lsp.py` at the repository
root. It speaks JSON-RPC over stdin/stdout and uses full-document text sync.
The debug adapter is `compiler/dap.py`; it speaks DAP over stdin/stdout and
drives GDB/MI2 using source-mapped debug builds from `compiler/driver.py`.
