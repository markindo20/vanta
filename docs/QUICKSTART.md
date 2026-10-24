# Quickstart — Vanta in 10 minutes

1. Install prerequisites:
   - Python 3.10+
   - `pip install vanta-lang`
   - a C++17 compiler: `g++`/`clang++` (Linux/macOS) or `cl` (Visual
     Studio Build Tools) on Windows.
2. Run: `vanta doctor`
3. Scaffold:
   - Console: `vanta new hello.vnt --template console`
   - Systems: `vanta new game.vnt --template systems`
   - Arena:    `vanta new arena.vnt --template arena`
4. Type-check: `vanta check hello.vnt`
5. Run it: `vanta hello.vnt` (compiles and runs)
6. Browse examples: `examples/README.md`
7. Debug: open `.vnt` in VS Code and press F5.

### Common tips
- `let`/`mut` unless changed
- Arrays `[i32, 4]`, matching named args `Foo(x: 1, y: 2)`
- `str_concat`, `str_sub`, `str_fmt` for formatting
- `vanta new foo.vnt --interactive` with numbered template choices
-path cleanup handled automatically

### Typical layout
```
mygame.vnt  # any main entrypoint
src/
  lib.vnt   # imports resolved relative
```
Run `vanta check src --jobs 8` on CI.

### Quick syntax
- Function `func main() -> void:`
- Control: `if`, `elif`, `else`, `while`, `for i in range(0,5):`, match with `else`
- Enums with payload `enum Option<T>: None; Some(T)`

### Troubleshooting
- `vanta doctor --fix` prints a concrete install hint for your OS.
- No C++ compiler: use MSYS2 or VS Build Tools; progress with `vanta check` until ready
- SDL2 linking for examples automatically via `--link SDL2`.
- Report issues with `--log-file` to repro.