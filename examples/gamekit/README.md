# Vanta game kit

Four importable modules that package the SDL2 plumbing every game needs.
They are ordinary `.vnt` files — the kit is a convention, not a language
feature.

| Module | Provides |
|---|---|
| `sdl.vnt` | SDL2 `extern` declarations, the `EV_*` / `KEY_*` constants, and the `Screen` lifecycle: `screen_open`, `screen_ok`, `screen_close` |
| `input.vnt` | Event accessors: `ev_is_quit`, `ev_is_keydown`, `ev_is_keyup`, `ev_key` |
| `gfx.vnt` | Drawing: `gfx_clear`, `gfx_fill_rect`, `gfx_stroke_rect`, `gfx_present` |
| `rng.vnt` | `rand_int`, `rand_range_f32`, `rand_sign` — bounded helpers over the deterministic stream |

A minimal program — a window with a border and one square, for 3 frames:

```vanta
import "gamekit/sdl.vnt"
import "gamekit/gfx.vnt"

func main() -> void:
    let screen = screen_open("gamekit", 320, 240)
    if not screen_ok(screen):
        print_str("could not open a window and renderer")
        return
    let arena = Arena(256)
    let rect = arena.alloc::<i32>(4)
    mut frames = 0
    while frames < 3:
        gfx_clear(screen, 18, 20, 30)
        gfx_stroke_rect(screen, rect, 20, 20, 280, 200, 2, 70, 80, 100)
        gfx_fill_rect(screen, rect, 140, 100, 40, 40, 240, 200, 60)
        gfx_present(screen)
        frames += 1
    screen_close(screen)
    print_fmt("frames {}", frames)
```

```
frames 3
```

Build it like any SDL2 program:

```powershell
python main.py run game.vnt --lib-dir C:/msys64/mingw64/lib --link SDL2
```

Notes:

- **Prefixes, not namespaces.** Vanta has one flat namespace, so every kit
  name starts with its module's prefix (`screen_*`, `ev_*`, `gfx_*`,
  `rand_*`). Several modules — and the game's own names — coexist.
- **`Screen` carries whatever C returned.** There is no nil literal;
  `screen_open` hands back null handles when anything fails, and
  `screen_ok` is the test — check it once after opening.
- **One scratch rect.** SDL wants a four-`i32` `SDL_Rect*`; allocate it
  once with `arena.alloc::<i32>(4)` and pass it to every `gfx_*` call.
- **Headless runs are first-class.** With `SDL_VIDEODRIVER=dummy` plus a
  frame limit, kit programs run in CI, and the fixed RNG stream makes the
  results reproducible.

[`../pong.vnt`](../pong.vnt) is the full worked example — it imports all
four modules.
