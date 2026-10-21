# Debugging Vanta

Vanta v0.34.0 ships a native debugger. The compiler emits unoptimized C++ with
`#line` markers that point back to the original Vanta file, and `vanta dap`
speaks the Debug Adapter Protocol (DAP) to an editor while driving GDB's
machine interface. You set breakpoints in Vanta source, inspect Vanta locals,
and step through Vanta functions; the generated C++ stays an implementation
detail.

The debugger covers the core loop plus the breakpoint features that come with
it:

- line breakpoints, including breakpoints in imported Vanta files
- stack traces with Vanta file paths and line numbers
- **Locals** and **Arguments** scopes
- continue, pause, step over, step into, and step out
- `stopOnEntry`
- program stdout/stderr in the debug console
- conditional breakpoints and hit counts
- log points that print instead of stopping
- function breakpoints
- watch expressions in a **Watch** scope
- restart, which rebuilds the program and runs it again
- clean exit, terminate, and disconnect

## Requirements

- Vanta 0.34.0 or newer (`vanta --version`)
- A GCC or Clang C++17 toolchain that emits DWARF debug information
- GDB 10 or newer

MSVC's `cl` can still build normal Vanta programs, but the debugger currently
requires a GCC/Clang toolchain. MSVC emits PDB files, which GDB does not read.
On Windows, the WinLibs MinGW GCC toolchain is the most reliable combination;
an MSYS2 `mingw64` GDB works when its DLL dependencies are complete. A Windows
`clang++` may default to CodeView symbols, so prefer `g++` unless your Clang
is configured to emit DWARF.

Install GDB and put it on `PATH`, or point Vanta at it with the
`vanta.debug.gdbPath` setting (VS Code) or the `VANTA_GDB` environment variable
(any editor).

## VS Code

Install the compiler and the extension from the latest GitHub release:

```powershell
pipx install vanta-lang
code --install-extension vanta-language-0.5.0.vsix
```

Open a Vanta file, press **F5**, and choose **Vanta** if VS Code asks for an
environment. The extension creates a launch configuration like this:

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

`program` is the entry Vanta file. `args` is an array of command-line
arguments, and `stopOnEntry` pauses on the first statement of `main`.
The debugger builds the program automatically; there is no separate build step.

Set breakpoints by clicking the gutter, then start the session. The debug
console shows compiler errors, GDB startup output, and the program's own
output. If a breakpoint is hollow instead of solid, open the **Vanta** output
channel and the debug console for the reason.

### Settings

| Setting | Default | Description |
| --- | --- | --- |
| `vanta.server.path` | `""` | Executable or Python interpreter used for both the language server and the debug adapter. Empty means automatic discovery. |
| `vanta.debug.gdbPath` | `""` | Explicit GDB executable. Empty means `VANTA_GDB`, a GDB beside the C++ compiler, a WinLibs/MSYS2 installation, or `gdb` on `PATH`. |

The extension launches the debug adapter with the same discovery rules as the
language server. A configured `vanta.server.path` may be a `vanta` executable
or a Python interpreter; the adapter is started as `vanta dap` or
`python -m compiler dap` respectively. If you build the extension from source,
the generated VSIX is `editors/vscode/vanta-language-0.5.0.vsix`.

## Breakpoints

VS Code exposes the breakpoint kinds through the gutter context menu and the
**Breakpoints** view. The adapter supports:

- **Line breakpoints** - the default. The file and line are the Vanta ones,
  including files reached through `import`.
- **Function breakpoints** - pick a function name from the list. Names are
  Vanta names: `main`, `update`, or `geometry.area` for an imported module.
- **Conditional breakpoints** - a condition is evaluated on every hit. The
  breakpoint only stops when the condition is true. Conditions use Vanta
  names: `hp > 0`, `state == State.Running`, `len(items) == 3`.
- **Hit counts** - a hit condition such as `3` (stop on the third hit),
  `>= 3` (stop from the third hit on), or `% 2 == 0` (stop on every second
  hit).
- **Log points** - a message with `{expression}` holes. The message is printed
  in the debug console and the program keeps running, so the session never
  stops at that line.

Conditions, hit counts, and log points are evaluated by the adapter itself,
in the frame that was hit. GDB cannot evaluate a Vanta condition before the
program is running, and evaluating it in the adapter keeps the Vanta variable
names intact. The price is a short pause at every hit, which is invisible
unless the breakpoint actually stops.

A log point with a condition only logs when the condition is true. A
breakpoint with both a condition and a hit count stops only when both are
satisfied.

## Watch expressions

The **Watch** view keeps a list of expressions that are re-evaluated every
time the program stops. Expressions use Vanta names, so `total`, `hp`, and
`len(items)` all work. An expression that cannot be evaluated - because the
variable is not in scope yet, for example - shows `<not available>` instead of
failing the session.

## Restart

**Restart** (the restart button in the debug toolbar, or the
`workbench.action.debug.restart` command) rebuilds the program from the
current source, reloads the symbols, re-creates the breakpoints, and runs it
again. Edits to the Vanta source are picked up, so a restart is the quickest
way to try a change without ending the session.

## Other editors

Any DAP-capable editor can launch the adapter as a stdio process:

```powershell
vanta dap
# or, when only Python is easy to locate:
python -m compiler dap
```

The adapter speaks `Content-Length`-framed DAP on stdin/stdout. A launch
request takes the usual Vanta fields:

```json
{
  "type": "request",
  "command": "launch",
  "arguments": {
    "program": "C:/work/game.vnt",
    "cwd": "C:/work",
    "args": [],
    "stopOnEntry": false
  }
}
```

`gdbPath` (or `miDebuggerPath`) in the launch arguments overrides GDB
discovery for that session. `includeDirs`, `libDirs`, and `libs` are passed to
the C++ build, matching `vanta build --include-dir/--lib-dir/--link`.

## How it works

A normal Vanta build optimizes for release and does not emit source locations.
A debug build changes only the native compile step:

- `CodeGen(debug=True)` emits absolute `#line` directives around each Vanta
  function, statement, and match arm. GDB therefore reports the Vanta path and
  line directly in frames and breakpoint hits.
- The compiler uses `-O0 -g3 -fno-omit-frame-pointer`, so variables and stack
  frames remain inspectable.
- `vanta dap` starts GDB with `--interpreter=mi2`, sets breakpoints by Vanta
  source path and line, and translates MI records into DAP responses and
  events.
- User variables are emitted with a `v_` prefix. The adapter strips the prefix
  for display, so a Vanta local named `total` appears as `total`, not
  `v_total`. The same mapping is applied to conditions and watch expressions,
  so they can be written in Vanta terms.
- Generated wrapper code is attributed to the temporary generated `main.cpp`
  rather than to the last Vanta line. The main wrapper frame is therefore
  visible as generated code, while the Vanta `main` frame points at the Vanta
  source.

The build lives in a temporary directory and is removed when the session ends.
`vanta build --debug` exposes the same source-mapped build for manual
inspection:

```powershell
vanta build game.vnt --debug -o build/game-debug.exe
```

## Troubleshooting

- **"no working GDB found"**: install GDB, or set `vanta.debug.gdbPath` /
  `VANTA_GDB`. On Windows, a WinLibs GDB is the most reliable option. The
  adapter probes candidates and skips ones that cannot start.
- **GDB exits with `0xC0000139` on Windows**: the GDB installation cannot find
  a matching runtime DLL. Use the WinLibs package, or fix the MSYS2
  installation's DLL path. The adapter deliberately skips a GDB that fails its
  startup probe and tries the next candidate.
- **"the Vanta debugger currently needs a GCC or Clang toolchain"**: set `CXX`
  to `g++` or `clang++`, or install one and put it on `PATH`. MSVC is not
  supported for debugging yet.
- **Breakpoints are unverified**: the source path and line may not correspond
  to executable code, or the generated build may have failed. Check the debug
  console and the **Vanta** output channel.
- **A condition never becomes true**: conditions are evaluated in the frame
  that was hit, so a variable that is not in scope yet evaluates to an error
  and the breakpoint stops anyway. The debug console explains the failure.
- **The program cannot find SDL2 DLLs**: the debug build uses the same runtime
  environment as normal builds, but SDL2 DLLs still need to be on `PATH` or
  beside the executable. `vanta build --bundle` is the usual fix for a release
  build; for debugging, put the DLL directory on `PATH` before starting the
  session.
- **Stepping jumps into generated code**: the main wrapper and ABI adapters
  are generated C++. Step over them, or set a breakpoint on the next Vanta
  line. Vanta functions themselves step normally.

## Current limitations

- Breakpoint conditions, hit counts, and log points are evaluated by the
  adapter, not by GDB, so the program pauses briefly at every hit.
- No editable variables yet. The **Evaluate** request accepts simple
  expressions and maps plain Vanta names to their `v_` C++ names, but it is
  intentionally minimal, and it does not assign.
- No data breakpoints, exception breakpoints, attach, or remote debugging.
- No reverse debugging and no `goto`.
- No LLDB or MSVC/PDB backend. GDB/MI2 is the only transport.
- Multi-threaded programs expose GDB threads, but the first milestone focuses
  on the main thread and all-thread stops.
- Optimized debug builds are not offered. A debug session always uses `-O0`.
