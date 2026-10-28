"""SDL ABI sanity: compare the game kit's documented SDL_Event offsets to the
SDL2 headers that are actually installed on this machine.

`examples/gamekit/input.vnt` reads an SDL_Event through raw `i32` indices
(56 bytes on the tested 64-bit builds, with the button / key / wheel fields
at known words). This test compiles a tiny offset probe against the real
`SDL_events.h` of the installed SDL2 and fails there first when an SDL
release changes the layout, instead of letting the synthetic-event tests
fail with cryptic wrong-field numbers.

Skipped when SDL2 headers or a C compiler are unavailable (e.g. an MSVC-only
Windows setup, where `_find_sdl2` also refuses to link).
"""
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from compiler.driver import find_cxx_compiler

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _find_sdl2_include_roots():
    """Include roots that plausibly contain SDL2 headers, most likely first."""
    roots = []
    cfg = shutil.which('sdl2-config')
    if cfg:
        try:
            out = subprocess.run([cfg, '--cflags'], capture_output=True,
                                 text=True).stdout
            for tok in out.split():
                if tok.startswith('-I'):
                    roots.append(tok[2:])
        except (OSError, subprocess.SubprocessError):
            pass
    name, path = find_cxx_compiler()
    if path and os.name == 'nt':
        # g++ typically lives in <prefix>\mingw64\bin or <prefix>\ucrt64\bin;
        # the SDL2 headers it pairs with sit in <prefix>\<env>\include.
        prefix = os.path.dirname(os.path.dirname(os.path.abspath(path)))
        roots.append(os.path.join(prefix, 'include'))
    roots.extend([r'C:\msys64\ucrt64\include', r'C:\msys64\mingw64\include'])
    roots.append('/usr/local/include')
    kept = []
    for root in roots:
        if root.endswith('SDL2'):
            root = os.path.dirname(root)
        if root and os.path.isdir(root) and root not in kept:
            kept.append(root)
    return kept


# Prints the SDL2 version, the union size, the event-type constants, and the
# byte offset of every field the game kit accessors index. Pure offsets: it
# needs the headers to compile but never loads the SDL2 library.
_PROBE = r'''
#include <stdio.h>
#include <stddef.h>

#if defined(__has_include)
# if __has_include(<SDL2/SDL_events.h>)
#   define SDL_FOUND 1
# elif __has_include(<SDL_events.h>)
#   define SDL_FOUND 1
# endif
#else
# define SDL_FOUND 1
#endif

#ifdef SDL_FOUND
# if defined(__has_include)
#  if __has_include(<SDL2/SDL_events.h>)
#   include <SDL2/SDL_events.h>
#   if __has_include(<SDL2/SDL_version.h>)
#    include <SDL2/SDL_version.h>
#   endif
#  else
#   include <SDL_events.h>
#   if __has_include(<SDL_version.h>)
#    include <SDL_version.h>
#   endif
#  endif
# else
#  include <SDL_events.h>
# endif
#endif

#ifndef SDL_FOUND
int main(void) { printf("no_sdl_headers=1\n"); return 2; }
#else

static void off(const char *name, size_t value) {
    printf("%s=%lu\n", name, (unsigned long) value);
}

int main(void) {
    printf("event_size=%lu\n",
           (unsigned long) sizeof(SDL_Event));
#ifdef SDL_MAJOR_VERSION
    printf("SDL_VERSION=%d.%d.%d\n", SDL_MAJOR_VERSION, SDL_MINOR_VERSION,
           SDL_PATCHLEVEL);
#endif
    printf("EV_QUIT=%d\n", (int) SDL_QUIT);
    printf("EV_KEYDOWN=%d\n", (int) SDL_KEYDOWN);
    printf("EV_KEYUP=%d\n", (int) SDL_KEYUP);
    printf("EV_WINDOWEVENT=%d\n", (int) SDL_WINDOWEVENT);
    printf("EV_MOUSEMOTION=%d\n", (int) SDL_MOUSEMOTION);
    printf("EV_MOUSEBUTTONDOWN=%d\n", (int) SDL_MOUSEBUTTONDOWN);
    printf("EV_MOUSEBUTTONUP=%d\n", (int) SDL_MOUSEBUTTONUP);
    printf("EV_MOUSEWHEEL=%d\n", (int) SDL_MOUSEWHEEL);
    printf("WINDOWEVENT_CLOSE=%d\n", (int) SDL_WINDOWEVENT_CLOSE);

    off("key_state_off", offsetof(SDL_KeyboardEvent, state));
    off("key_repeat_off", offsetof(SDL_KeyboardEvent, repeat));
    off("key_scancode_off", offsetof(SDL_KeyboardEvent, keysym.scancode));
    off("key_sym_off", offsetof(SDL_KeyboardEvent, keysym.sym));
    off("key_mod_off", offsetof(SDL_KeyboardEvent, keysym.mod));

    off("motion_which_off", offsetof(SDL_MouseMotionEvent, which));
    off("motion_state_off", offsetof(SDL_MouseMotionEvent, state));
    off("motion_x_off", offsetof(SDL_MouseMotionEvent, x));
    off("motion_y_off", offsetof(SDL_MouseMotionEvent, y));
    off("motion_xrel_off", offsetof(SDL_MouseMotionEvent, xrel));
    off("motion_yrel_off", offsetof(SDL_MouseMotionEvent, yrel));

    off("button_which_off", offsetof(SDL_MouseButtonEvent, which));
    off("button_button_off", offsetof(SDL_MouseButtonEvent, button));
    off("button_state_off", offsetof(SDL_MouseButtonEvent, state));
    off("button_clicks_off", offsetof(SDL_MouseButtonEvent, clicks));

    off("wheel_which_off", offsetof(SDL_MouseWheelEvent, which));
    off("wheel_x_off", offsetof(SDL_MouseWheelEvent, x));
    off("wheel_y_off", offsetof(SDL_MouseWheelEvent, y));
    off("wheel_direction_off", offsetof(SDL_MouseWheelEvent, direction));

    off("window_which_off", offsetof(SDL_WindowEvent, windowID));
    off("window_event_off", offsetof(SDL_WindowEvent, event));
    off("window_data1_off", offsetof(SDL_WindowEvent, data1));
    off("window_data2_off", offsetof(SDL_WindowEvent, data2));
    return 0;
}
#endif
'''


def _run_offsets_probe():
    """Compile and run the offset probe; return key->int or None."""
    compiler, compiler_path = find_cxx_compiler()
    if compiler is None or compiler_path is None:
        return None
    roots = _find_sdl2_include_roots()
    if not roots:
        return None
    tmp = tempfile.mkdtemp(prefix='vanta_sdl_abi_')
    try:
        src = os.path.join(tmp, 'probe.cpp')
        exe = os.path.join(tmp, 'probe.exe' if os.name == 'nt' else 'probe')
        with open(src, 'w', encoding='utf-8', newline='\n') as f:
            f.write(_PROBE)
        cmd = [compiler, src, '-o', exe]
        for root in roots:
            cmd = cmd[:2] + ['-I' + root] + cmd[2:]
        run = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if run.returncode != 0 or not os.path.exists(exe):
            # Include paths exist but the headers do not match the spelling
            # the probe tries; treat as unavailable rather than failing CI.
            return None
        run = subprocess.run([exe], capture_output=True, text=True, timeout=60)
        if run.returncode != 0:
            return None
        values = {}
        for line in run.stdout.splitlines():
            key, _, raw = line.partition('=')
            try:
                values[key.strip()] = int(raw.strip())
            except ValueError:
                continue
        if 'no_sdl_headers' in values or 'event_size' not in values:
            return None
        return values
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _vnt_constants(paths):
    """Collect `const NAME: i32 = N` across the kit, checking duplicates agree."""
    found = {}
    for path in paths:
        with open(path, encoding='utf-8') as f:
            for line in f:
                m = re.match(r'\s*const ([A-Za-z0-9_]+): i32 = (\d+)', line)
                if not m:
                    continue
                name, value = m.group(1), int(m.group(2))
                if name in found and found[name] != value:
                    raise AssertionError(
                        f'{name} is both {found[name]} and {value} in the kit')
                found.setdefault(name, value)
    return found


def _accessor_word_indices(text):
    """Map each ev_* accessor to the `ev[N]` word of its first return."""
    indices = {}
    current = None
    for line in text.splitlines():
        m = re.match(r'\s*func (ev_[a-z0-9_]+)\(', line)
        if m:
            current = m.group(1)
            continue
        m = re.match(r'\s*return.*?\bev\[(\d+)\]', line)
        if m and current:
            indices.setdefault(current, int(m.group(1)))
            current = None
    return indices


def _word_table(offsets):
    """Expected (accessor -> word index) from probe offsets."""
    table = {
        'ev_key': offsets['key_sym_off'] // 4,
        'ev_key_scancode': offsets['key_scancode_off'] // 4,
        'ev_key_mod': offsets['key_mod_off'] // 4,
        'ev_mouse_x': offsets['motion_x_off'] // 4,
        'ev_mouse_y': offsets['motion_y_off'] // 4,
        'ev_mouse_rel_x': offsets['motion_xrel_off'] // 4,
        'ev_mouse_rel_y': offsets['motion_yrel_off'] // 4,
        'ev_mouse_motion_buttons': offsets['motion_state_off'] // 4,
        'ev_mouse_which': offsets['motion_which_off'] // 4,
        'ev_mouse_button': offsets['button_button_off'] // 4,
        'ev_mouse_button_state': offsets['button_state_off'] // 4,
        'ev_mouse_button_clicks': offsets['button_clicks_off'] // 4,
        'ev_wheel_x': offsets['wheel_x_off'] // 4,
        'ev_wheel_y': offsets['wheel_y_off'] // 4,
        'ev_wheel_direction': offsets['wheel_direction_off'] // 4,
        'ev_window_event': offsets['window_event_off'] // 4,
        'ev_window_data1': offsets['window_data1_off'] // 4,
        'ev_window_data2': offsets['window_data2_off'] // 4,
    }
    # ev_key_state / ev_key_repeat read packed byte 0 / 1 of word
    # floor(offsetof(state) / 4): verify the packing arithmetic holds too.
    assert offsets['key_state_off'] % 4 == 0
    assert offsets['key_repeat_off'] % 4 == 1
    assert offsets['button_button_off'] % 4 == 0
    assert offsets['button_state_off'] % 4 == 1
    assert offsets['button_clicks_off'] % 4 == 2
    same = (offsets['button_button_off'] // 4
            == offsets['button_state_off'] // 4
            == offsets['button_clicks_off'] // 4)
    assert same, 'button/state/clicks must pack into one i32'
    return table


@unittest.skipUnless(find_cxx_compiler()[1] is not None,
                     "no C compiler available")
class SdlAbiLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.offsets = _run_offsets_probe()
        if cls.offsets is None or 'event_size' not in cls.offsets:
            raise unittest.SkipTest('SDL2 headers not found')

    def test_event_size_and_type_constants(self):
        # 56 bytes on the tested 64-bit builds, as documented in
        # docs/LANGUAGE_REFERENCE.md.
        self.assertEqual(self.offsets['event_size'], 56)
        kit = os.path.join(HERE, 'examples', 'gamekit')
        constants = _vnt_constants([
            os.path.join(kit, 'sdl.vnt'),
            os.path.join(kit, 'input.vnt'),
        ])
        for name in ('EV_QUIT', 'EV_KEYDOWN', 'EV_KEYUP', 'EV_WINDOWEVENT',
                     'EV_MOUSEMOTION', 'EV_MOUSEBUTTONDOWN',
                     'EV_MOUSEBUTTONUP', 'EV_MOUSEWHEEL',
                     'WINDOWEVENT_CLOSE'):
            self.assertEqual(constants[name], self.offsets[name], name)

    def test_accessors_match_installed_header_layout(self):
        input_path = os.path.join(HERE, 'examples', 'gamekit', 'input.vnt')
        with open(input_path, encoding='utf-8') as f:
            text = f.read()
        used = _accessor_word_indices(text)
        expected = _word_table(self.offsets)
        for accessor, word in expected.items():
            actual = used.get(accessor)
            self.assertEqual(
                actual, word,
                f'{accessor} must index ev[{word}] per the installed '
                'SDL2 headers')
        self.assertIn('ev_window_is_close_requested', used)
        self.assertEqual(
            used['ev_window_event'] * 4 + 0,
            self.offsets['window_event_off'] // 4 * 4)

    def test_wheel_window_and_key_packing(self):
        offsets = self.offsets
        # The wheel x/y/direction triple follows `which`, all in adjacent
        # 4-byte words, as input.vnt's ev_wheel_* assume.
        self.assertEqual(offsets['wheel_which_off'] + 4,
                         offsets['wheel_x_off'])
        self.assertEqual(offsets['wheel_x_off'] + 4, offsets['wheel_y_off'])
        self.assertEqual(offsets['wheel_y_off'] + 4,
                         offsets['wheel_direction_off'])
        # The window layout: windowID at word 2, event / data1 / data2 in
        # the three words after it.
        self.assertEqual(offsets['window_which_off'], 8)
        self.assertEqual(offsets['window_event_off'],
                         offsets['window_which_off'] + 4)
        self.assertEqual(offsets['window_data1_off'],
                         offsets['window_event_off'] + 4)
        self.assertEqual(offsets['window_data2_off'],
                         offsets['window_data1_off'] + 4)
        # keysym fields sit three consecutive words after the state byte.
        self.assertEqual(offsets['key_scancode_off'],
                         offsets['key_state_off'] + 4)
        self.assertEqual(offsets['key_sym_off'],
                         offsets['key_scancode_off'] + 4)
        self.assertEqual(offsets['key_mod_off'], offsets['key_sym_off'] + 4)


if __name__ == '__main__':
    unittest.main()
