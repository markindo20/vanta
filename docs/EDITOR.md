# Editor support

Vanta v0.32.0 ships a language server and a VS Code client. The server is part
of the compiler package, so an installed `vanta` command and a source checkout
provide the same editor features.

## What you get

- **Diagnostics** for lexer, parser, import, and type errors. The server
  validates unsaved buffers with the same frontend used by `vanta check`, and
  diagnostics from imported files are published to the file that contains the
  error.
- **Completion** for keywords, builtins, declarations, parameters, local
  variables, module aliases, enum members, struct fields, and the common
  builtin methods on `List`, `Arena`, `StrBuilder`, `Vec2`, `Vec3`, and `Quat`.
- **Hover** signatures and types for functions, constants, types, parameters,
  locals, enum members, struct fields, and imported declarations.
- **Go to definition** for functions, constants, types, parameters, locals,
  imported declarations, enum members, and struct fields.
- **Document symbols** for the outline view, including struct fields and enum
  members under their containing declaration.
- Syntax highlighting and language configuration for `.vnt` files.

The server uses full-document text sync. That keeps the first version small and
makes diagnostics reason about exactly the buffer the editor is showing.
Completion and navigation use a tolerant source index, so they keep working
while a line is only half typed.

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

Download `vanta-language-0.3.0.vsix` from the latest Vanta GitHub release and
install it:

```powershell
code --install-extension vanta-language-0.3.0.vsix
```

### Build from source

```powershell
cd editors/vscode
npm install
npm run package
code --install-extension vanta-language-0.3.0.vsix
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
| `vanta.server.path` | `""` | Path to the `vanta` executable or a Python interpreter. Empty means automatic discovery. |

Run **Vanta: Restart Language Server** after changing the setting.

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

## Other editors

Any LSP client can launch the server as a stdio process:

```powershell
vanta lsp
```

The server advertises UTF-16 positions, open/close document sync, full
document changes, completion, hover, definition, and document symbols. It does
not require a workspace root to start.

## Limitations

- The frontend stops at the first lex, parse, load, or type error, so the
  server publishes one diagnostic per validation. Fix it and the next one
  appears.
- Completion inside an incomplete declaration is recovered from source text
  and is deliberately best-effort. Once the file parses, the AST gives exact
  declaration and local-variable information.
- There is no rename, code action, formatting, workspace symbol, or semantic
  tokens support yet.
- There is no debugger or DAP adapter. Vanta compiles to C++ without mapping
  generated lines back to Vanta source, so stepping through Vanta code is a
  later milestone.

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
