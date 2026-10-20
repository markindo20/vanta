"""Generate the sprite and sound assets the examples ship.

Run from the repo root:

    python examples/assets/gen_assets.py

Writes next to this file (the outputs are committed, so nobody needs to
run this to build or test the examples; the script is here so the assets
are reproducible and reviewable — no opaque binaries, nothing licensed):

    ball.png   10x10 white ball, transparent corners   (PNG, alpha)
    ball_spin.png 40x10 sheet: four 10x10 ball frames   (PNG, animation demo)
    paddle.bmp 44x10 pale blue paddle                  (BMP, no alpha)
    brick.png  32x14 white brick, gray edge            (PNG, tinted per row by the game)
    tiles.png  32x16 sheet: two 16x16 tiles            (PNG, sprite-sheet demo)
    ship_anim.png 96x24 sheet: four 24x24 ships        (strike: player + flame)
    enemy.png  20x20 white saucer, tinted per wave     (strike: enemy)
    laser.png  4x12 cyan bolt                          (strike: bullet)
    blip.wav   60 ms 880 Hz sine                       (breakout: paddle hit)
    brick.wav  50 ms 660 Hz sine                       (breakout: brick break)
    lose.wav   200 ms 220 Hz sine, decaying            (breakout: ball lost)
    laser.wav  40 ms 1200 Hz sine                      (strike: shot)
    hit.wav    35 ms 520 Hz sine                       (strike: enemy destroyed)
    boom.wav   220 ms 140 Hz sine, decaying            (strike: player hit)

The PNGs are written by hand (zlib over filtered scanlines), the BMP by
hand, and the WAVs by hand — no Pillow, no numpy, only the standard
library.
"""

import math
import os
import struct
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
RATE = 44100


def write_png(path, w, h, pixel):
    """pixel(x, y) -> (r, g, b, a); 8-bit RGBA, one filter-0 scanline per row."""
    raw = bytearray()
    for y in range(h):
        raw.append(0)
        for x in range(w):
            raw.extend(pixel(x, y))

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff))

    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
           + chunk(b"IEND", b""))
    with open(os.path.join(HERE, path), "wb") as f:
        f.write(png)


def write_bmp(path, w, h, pixel):
    """pixel(x, y) -> (r, g, b); 24-bit BMP, bottom-up, rows padded to 4."""
    row_size = (w * 3 + 3) & ~3
    data = bytearray()
    for y in range(h - 1, -1, -1):
        row = bytearray()
        for x in range(w):
            r, g, b = pixel(x, y)
            row.extend((b, g, r))
        row.extend(b"\x00" * (row_size - len(row)))
        data.extend(row)
    header = (b"BM" + struct.pack("<IHHI", 14 + 40 + len(data), 0, 0, 54)
              + struct.pack("<IiiHHIIiiII", 40, w, h, 1, 24, 0, len(data),
                            2835, 2835, 0, 0))
    with open(os.path.join(HERE, path), "wb") as f:
        f.write(header + bytes(data))


def write_wav(path, samples):
    """samples: [int16]; 16-bit PCM, mono, 44100 Hz."""
    data = struct.pack("<%dh" % len(samples), *samples)
    wav = (b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE"
           + b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, RATE, RATE * 2, 2, 16)
           + b"data" + struct.pack("<I", len(data)) + data)
    with open(os.path.join(HERE, path), "wb") as f:
        f.write(wav)


def tone(freq, ms, vol=0.5, decay=False):
    """A sine with a 10 ms fade in/out (a linear decay instead, if asked)."""
    n = RATE * ms // 1000
    fade = RATE // 100
    out = []
    for i in range(n):
        env = min(1.0, i / fade, (n - i) / fade)
        if decay:
            env *= 1.0 - i / n
        out.append(int(math.sin(2.0 * math.pi * freq * i / RATE) * 32767 * vol * env))
    return out


def ball_pixel(x, y):
    dx, dy = x - 4.5, y - 4.5
    if dx * dx + dy * dy <= 20.25:
        return (255, 255, 255, 255)
    return (0, 0, 0, 0)


def ball_spin_pixel(x, y):
    # ball_spin.png: four 10x10 frames side by side; a pale-blue highlight
    # orbits the ball a quarter turn per frame, so playing them in order
    # reads as a spin. Frame 0 has it top-right.
    frame_x = x % 10
    dx, dy = frame_x - 4.5, y - 4.5
    if dx * dx + dy * dy > 20.25:
        return (0, 0, 0, 0)
    angle = (x // 10) * (math.pi / 2.0) - math.pi / 4.0
    hx = 4.5 + 1.8 * math.cos(angle)
    hy = 4.5 + 1.8 * math.sin(angle)
    if (frame_x - hx) * (frame_x - hx) + (y - hy) * (y - hy) <= 1.44:
        return (150, 205, 255, 255)
    return (255, 255, 255, 255)


def brick_pixel(x, y):
    if x < 2 or y < 2 or x >= 30 or y >= 12:
        return (150, 150, 150, 255)
    return (255, 255, 255, 255)


def tile_pixel(tile, body):
    def pixel(x, y):
        if x < 2 or y < 2 or x >= 14 or y >= 14:
            return (40, 40, 40, 255)
        if 6 <= x < 10 and 6 <= y < 10:
            return (255, 255, 255, 255)
        return (body[0], body[1], body[2], 255)
    return pixel


def ship_pixel(x, y):
    # ship_anim.png: four 24x24 frames; the hull is fixed and the exhaust
    # flame changes length, so animating the strip reads as a live engine.
    frame = x // 24
    fx = x % 24
    flame = (3, 1, 4, 2)[frame]
    if 9 <= fx <= 14 and 19 <= y <= 18 + flame:
        if 10 <= fx <= 13 and y < 18 + flame:
            return (255, 242, 150, 255)
        return (255, 170, 60, 255)

    half = (y - 2) * 0.55
    if 2 <= y <= 19 and abs(fx - 12) <= half:
        # Cockpit first: it sits on top of the hull.
        dx, dy = fx - 12, y - 10
        if dx * dx / 9.0 + dy * dy / 16.0 <= 1.0:
            return (90, 210, 255, 255)
        if y >= 15 and 4 <= fx <= 20:
            return (190, 212, 240, 255)
        if abs(fx - 12) >= half - 1.0:
            return (135, 165, 215, 255)
        return (235, 244, 255, 255)
    return (0, 0, 0, 0)


def enemy_pixel(x, y):
    # enemy.png: one white saucer, tinted per wave by the game. The dark
    # cockpit takes the same tint, so it stays readable in every colour.
    dx, dy = x - 10, y - 10
    if dx * dx / 81.0 + dy * dy / 36.0 <= 1.0:
        cx, cy = x - 10, y - 7
        if cx * cx + cy * cy <= 16.0:
            return (205, 214, 235, 255)
        if x - 10 >= -3 and x - 10 <= 3 and y >= 7 and y <= 13:
            return (65, 68, 88, 255)
        if y >= 14 and (x <= 4 or x >= 15) and y <= 18:
            return (180, 190, 215, 255)
        return (238, 240, 248, 255)
    return (0, 0, 0, 0)


def laser_pixel(x, y):
    # laser.png: a four-pixel-wide bolt, brighter down the middle.
    if x == 1 or x == 2:
        return (225, 250, 255, 255)
    return (70, 180, 255, 255)


def main():
    write_png("ball.png", 10, 10, ball_pixel)
    write_png("ball_spin.png", 40, 10, ball_spin_pixel)
    write_bmp("paddle.bmp", 44, 10, lambda x, y: (200, 220, 255))
    write_png("brick.png", 32, 14, brick_pixel)

    tile_a = tile_pixel(0, (220, 60, 60))
    tile_b = tile_pixel(1, (60, 180, 90))

    def sheet_pixel(x, y):
        # tiles.png: tile_a in the left 16 columns, tile_b in the right.
        return (tile_a if x < 16 else tile_b)(x % 16, y)

    write_png("tiles.png", 32, 16, sheet_pixel)
    write_png("ship_anim.png", 96, 24, ship_pixel)
    write_png("enemy.png", 20, 20, enemy_pixel)
    write_png("laser.png", 4, 12, laser_pixel)

    write_wav("blip.wav", tone(880, 60))
    write_wav("brick.wav", tone(660, 50))
    write_wav("lose.wav", tone(220, 200, decay=True))
    write_wav("laser.wav", tone(1200, 40, vol=0.35))
    write_wav("hit.wav", tone(520, 35, vol=0.45))
    write_wav("boom.wav", tone(140, 220, vol=0.6, decay=True))


if __name__ == "__main__":
    main()
    for name in ("ball.png", "ball_spin.png", "paddle.bmp", "brick.png",
                 "tiles.png", "ship_anim.png", "enemy.png", "laser.png",
                 "blip.wav", "brick.wav", "lose.wav", "laser.wav",
                 "hit.wav", "boom.wav"):
        path = os.path.join(HERE, name)
        print(f"{name}: {os.path.getsize(path)} bytes")
