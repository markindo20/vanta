# Vanta for VS Code

Full language support for Vanta `.vnt` files, powered by the `vanta lsp`
language server.

## Features

- **Diagnostics** from the real lexer, parser, loader, and type checker,
  including unsaved buffers and imported files.
- **Completion** for keywords, builtins, declarations, locals, module aliases,
  enum members, struct fields, and builtin methods on `List`, `Arena`,
  `StrBuilder`, `Vec2`, `Vec3`, and `Quat`.
- **Hover** signatures and types for functions, declarations, locals, and
  members.
- **Go to definition** for functions, constants, types, parameters, locals,
  imported declarations, enum members, and struct fields.
- **Document symbols** / outline view for functions, structs, enums, fields,
  and enum members.
- Syntax highlighting and language configuration, including `#` comments.

## Requirements

- VS Code 1.82 or newer.
- A Vanta compiler reachable as one of:
  1. `vanta.server.path` (an executable, a Python interpreter, or a command
     name),
  2. `vanta` or `vanta.exe` inside a workspace `.venv`, `venv`, or `env`,
  3. `vanta` on `PATH`,
  4. a Python interpreter that can `import compiler` (the extension then runs
     `python -m compiler lsp`).

Install the compiler with:

```powershell
pip install vanta-lang
```

or work from a checkout of the repository. The Python fallback launches the
server as `python -m compiler lsp`.

## Install the extension

### From a VSIX

Download `vanta-language-0.3.0.vsix` from the latest Vanta GitHub release, then:

```powershell
code --install-extension vanta-language-0.3.0.vsix
```

### Build it yourself

Building requires Node 22 or newer.

```powershell
cd editors/vscode
npm install
npm run package
code --install-extension vanta-language-0.3.0.vsix
```

### Run from source

Open this folder in VS Code and press **F5** (Run Extension). In the extension
development window, open any `.vnt` file.

## Settings

| Setting | Default | Description |
| --- | --- | --- |
| `vanta.server.path` | `""` | Path to the `vanta` executable or a Python interpreter. Empty means automatic discovery. |

Use **Vanta: Restart Language Server** from the command palette after changing
the setting.

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
`<path> lsp`. When it names a Python interpreter, it runs
`<path> -m compiler lsp`. When it names a command (for example `vanta`), it
relies on `PATH`.

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
