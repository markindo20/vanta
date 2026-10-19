# Vanta game kit

Seven importable modules that package the SDL2 (and SDL_ttf and SDL2_image)
plumbing every game needs. They are ordinary `.vnt` files — the kit is a
convention, not a language feature.

| Module | Provides |
|---|---|
| `sdl.vnt` | SDL2 `extern` declarations, the `EV_*` / `KEY_*` / `SDL_FLIP_*` constants, and the `Screen` lifecycle: `screen_open`, `screen_ok`, `screen_close` |
| `input.vnt` | Event accessors: `ev_is_quit`, `ev_is_keydown`, `ev_is_keyup`, `ev_key` |
| `gfx.vnt` | Rectangle drawing: `gfx_clear`, `gfx_fill_rect`, `gfx_stroke_rect`, `gfx_present` |
| `image.vnt` | SDL2_image textures: `tex_load`, `tex_ok`, `tex_free`, `tex_tint`, `tex_alpha`, `tex_draw`, `tex_draw_src`, `tex_draw_ex` |
| `text.vnt` | SDL_ttf text: `font_open`, `font_ok`, `font_close`, `text_measure`, `text_draw`, `text_quit` |
| `audio.vnt` | SDL2 audio: tones — `audio_open`, `audio_ok`, `audio_play_tone`, `audio_pending`, `audio_wait`, `audio_close` — and WAV files: `sound_load`, `sound_ok`, `sound_play`, `sound_free` |
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

Text is one more import — `text.vnt` over SDL_ttf, with a font the kit
ships. `text_measure` writes the rendered size into the scratch block;
`text_draw` renders and blits in one call:

```vanta
import "gamekit/sdl.vnt"
import "gamekit/text.vnt"

func main() -> void:
    let screen = screen_open("gamekit", 320, 240)
    let font = font_open("examples/gamekit/fonts/tom-thumb.ttf", 32)
    print_bool(screen_ok(screen) and font_ok(font))
    let arena = Arena(512)
    let scratch = arena.alloc::<i32>(10)     # w, h, src rect, dst rect
    text_draw(screen, font, 24, 24, "Vanta", scratch, 240, 220, 120)
    text_measure(font, "Vanta", scratch)
    print_bool(scratch[0] > 0)               # the measured width is real
    font_close(font)
    text_quit()
    screen_close(screen)
```

```
true
true
```

Sprites are one more import — `image.vnt` over SDL2_image, decoding PNG and
BMP files into `Tex` handles: draw whole textures or sheet regions, rotated
and flipped, with a tint multiplied into every draw. A missing file loads as
a dead `Tex` and draws nothing:

```vanta
import "gamekit/sdl.vnt"
import "gamekit/image.vnt"

func main() -> void:
    let screen = screen_open("gamekit", 320, 240)
    let brick = tex_load(screen, "examples/assets/brick.png")
    print_bool(screen_ok(screen) and tex_ok(brick))
    print_fmt("{}x{}", brick.w, brick.h)
    tex_tint(brick, 240, 96, 96)                      # draws from here on are red
    tex_draw(screen, brick, 40, 40)
    tex_draw_ex(screen, brick, 120, 40, 20.0, SDL_FLIP_NONE)
    tex_free(brick)
    screen_close(screen)
```

```
true
32x14
```

Sound is another import — `audio.vnt` over SDL2's own audio, with no extra
library to link. Tones are generated (`audio_play_tone` fills a caller-owned
`i16` buffer); WAV files load through `sound_load` (16-bit PCM at 44.1 kHz,
mono or stereo):

```vanta
import "gamekit/sdl.vnt"
import "gamekit/audio.vnt"

func main() -> void:
    let audio = audio_open()
    print_bool(audio_ok(audio))              # true on any working driver
    let arena = Arena(32768)
    let buf = arena.alloc::<i16>(11025)      # up to 250 ms of samples
    print_i32(audio_play_tone(audio, 880, 100, buf, 11025))
    audio_wait(audio)
    audio_close(audio)
```

```
true
4410
```

```vanta
import "gamekit/audio.vnt"

func main() -> void:
    let audio = audio_open()
    let snd = sound_load(audio, "examples/assets/blip.wav")
    print_bool(audio_ok(audio) and sound_ok(snd))    # true on any working driver
    print_fmt("{} bytes", snd.len)                   # 60 ms at 44.1 kHz
    sound_play(audio, snd)
    audio_wait(audio)
    sound_free(snd)
    audio_close(audio)
```

```
true
5292 bytes
```

Build it like any SDL2 program — `text.vnt` links SDL_ttf and `image.vnt`
links SDL2_image as well as SDL2, and `audio.vnt` needs nothing beyond the
core library:

```powershell
python main.py run game.vnt --lib-dir C:/msys64/mingw64/lib --link SDL2_image --link SDL2_ttf --link SDL2
```

Notes:

- **Prefixes, not namespaces.** Vanta has one flat namespace, so every kit
  name starts with its module's prefix (`screen_*`, `ev_*`, `gfx_*`,
  `tex_*`, `font_*`, `text_*`, `audio_*`, `sound_*`, `rand_*`). Several
  modules — and the game's own names — coexist.
- **`Screen` carries whatever C returned.** There is no nil literal —
  `ptr_null::<T>()` builds one explicitly where C asks for NULL —
  and `screen_open` hands back null handles when anything fails, with
  `screen_ok` as the test — check it once after opening. `Font` and
  `Audio` work the same way, with `font_ok` and `audio_ok`.
- **One scratch rect.** SDL wants a four-`i32` `SDL_Rect*`; allocate it
  once with `arena.alloc::<i32>(4)` and pass it to every `gfx_*` call. The
  `tex_draw*` helpers are the exception — they build their own rects on a
  transient arena, because SDL only needs them during the call.
- **One text scratch of ten.** `text_measure` / `text_draw` want ten
  `i32` slots — width, height, a source rect, a destination rect — so one
  `arena.alloc::<i32>(10)` covers both calls and every string.
- **One tone buffer.** `audio_play_tone` fills a caller-owned `i16`
  buffer — allocate it once with `arena.alloc::<i16>(...)` and reuse it
  for every beep; a tone longer than the buffer is cut short, and a
  device that failed to open makes every call a quiet no-op.
- **WAV files are SDL's buffers.** `sound_load` reads a 44.1 kHz 16-bit
  PCM WAV — mono or stereo, folded to mono in place at load — into a
  buffer SDL allocates; `sound_free` hands it back. Any other rate,
  sample format, or channel count loads as a dead `Sound`, and playing
  or freeing one is a no-op.
- **Headless runs are first-class.** With `SDL_VIDEODRIVER=dummy` and
  `SDL_AUDIODRIVER=dummy` plus a frame limit, kit programs run in CI (the
  fixed RNG stream keeps results reproducible, and the dummy audio driver
  plays to nowhere in real time).

[`../pong.vnt`](../pong.vnt) and [`../breakout.vnt`](../breakout.vnt) are the
worked examples: pong imports six of the seven modules, draws its score with
`text_draw`, and beeps with `audio_play_tone`; breakout loads the ball,
paddle, and bricks from image files with `image.vnt` and fires WAV hits with
`sound_load`.
