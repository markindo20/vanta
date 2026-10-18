# Vanta for VS Code

Syntax highlighting for `.vnt` files: comments, strings, keywords, built-in
types, the builtin function families (`print_*`, `sin_*`, `str_*`, ...), and
function / struct names. `.vnt` files also show the Vanta mark in the
Explorer (light and dark variants) — this needs a file icon theme with
specific icons, like the default Seti; the generic-only Minimal theme does
not show language icons.

## Install (unpacked)

1. Copy this folder into your extensions directory:
   - Windows: `%USERPROFILE%\.vscode\extensions\vanta-language`
   - macOS / Linux: `~/.vscode/extensions/vanta-language`
2. Restart VS Code. Any `.vnt` file is highlighted automatically.

## Package it (optional)

```powershell
npx @vscode/vsce package
code --install-extension vanta-language-0.2.0.vsix
```

This is highlighting only — no diagnostics or completion yet. An LSP server
is the next step if the language picks up users.
