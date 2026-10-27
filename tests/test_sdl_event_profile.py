import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from compiler.driver import find_cxx_compiler, _compiler_cmd
from compiler.driver import _emit_source, _frontend_only
from tests.test_integration import _find_sdl2


SDL2 = _find_sdl2()
EXAMPLES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'examples')


def source_lines(lines):
    return os.linesep.join(lines) + os.linesep


class SDLEventProfileTests(unittest.TestCase):
    def setUp(self):
        if not find_cxx_compiler()[1] or SDL2 is None:
            self.skipTest('no C++ compiler or SDL2 runtime available')
        self._tmp = tempfile.mkdtemp(prefix='vanta_sdl_profile_')

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _build(self, lines):
        source_root = os.path.join(self._tmp, 'main')
        os.makedirs(source_root, exist_ok=True)
        shutil.copytree(os.path.join(EXAMPLES, 'gamekit'),
                        os.path.join(source_root, 'gamekit'),
                        dirs_exist_ok=True)
        source_path = os.path.join(source_root, 'profile.vnt')
        with open(source_path, 'w', encoding='utf-8', newline='') as f:
            f.write(source_lines(lines))

        name, path = find_cxx_compiler()
        prog, tc = _frontend_only(source_path)
        cpp = os.path.join(self._tmp, 'profile.cpp')
        _emit_source(prog, tc, cpp)
        exe = os.path.join(self._tmp, 'profile.exe' if os.name == 'nt' else 'profile')
        command = _compiler_cmd(name, path, cpp, exe, release=True,
                                lib_dirs=SDL2['lib_dirs'], libs=SDL2['libs'])
        build = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(build.returncode, 0, msg=build.stderr)
        return exe

    def test_synthetic_mousemotion_profile_harness(self):
        lines = [
            'import "gamekit/sdl.vnt"',
            'import "gamekit/input.vnt"',
            '',
            'func main() -> void:',
            '    if SDL_Init(SDL_INIT_VIDEO) != 0:',
            '        return',
            '    let window = SDL_CreateWindow("Vantaprofile", 100, 100, 64, 64, SDL_WINDOW_SHOWN)',
            '    if ptr_is_null(window):',
            '        SDL_Quit()',
            '        return',
            '    let renderer = SDL_CreateRenderer(window, -1, 0)',
            '    if ptr_is_null(renderer):',
            '        SDL_DestroyWindow(window)',
            '        SDL_Quit()',
            '        return',
            '    let arena = Arena(256)',
            '    let ev = arena.alloc::<i32>(16)',
            '    let pushed = arena.alloc::<i32>(9)',
            '    pushed[0] = EV_MOUSEMOTION',
            '    pushed[1] = 0',
            '    pushed[2] = 0',
            '    pushed[3] = 0',
            '    pushed[4] = 0',
            '    pushed[5] = 0',
            '    pushed[6] = 0',
            '    pushed[7] = 0',
            '    pushed[8] = 0',
            '    mut pushed_count = 0',
            '    while pushed_count < 1024:',
            '        SDL_PushEvent(pushed)',
            '        pushed_count = pushed_count + 1',
            '    mut polled = 0',
            '    mut accesses = 0',
            '    while SDL_PollEvent(ev) == 1:',
            '        if ev_is_mousemotion(ev):',
            '            accesses = accesses + ev_mouse_x(ev) + ev_mouse_y(ev)',
            '            accesses = accesses + ev_mouse_rel_x(ev) + ev_mouse_rel_y(ev)',
            '            accesses = accesses + ev_mouse_which(ev)',
            '            accesses = accesses + ev_mouse_motion_buttons(ev)',
            '        polled = polled + 1',
            '    print_i32(polled)',
            '    print_i32(accesses)',
            '    SDL_DestroyRenderer(renderer)',
            '    SDL_DestroyWindow(window)',
            '    SDL_Quit()',
        ]
        env = dict(os.environ, SDL_VIDEODRIVER='dummy')
        started = time.perf_counter()
        exe = self._build(lines)
        elapsed_compile_and_run = time.perf_counter() - started
        run_started = time.perf_counter()
        run = subprocess.run([exe], capture_output=True, text=True, env=env)
        elapsed_run = time.perf_counter() - run_started
        self.assertEqual(run.returncode, 0, msg=run.stderr)
        output_lines = [line.strip() for line in run.stdout.splitlines()]
        self.assertEqual(len(output_lines), 2, msg=run.stdout + run.stderr)
        self.assertGreaterEqual(int(output_lines[0]), 1024)
        self.assertEqual(int(output_lines[1]), 0, msg=run.stdout)
        self.assertLessEqual(elapsed_run, 3.0,
                            msg='SDL synthetic profile harness exceeded 3 seconds')

        profile_output = (
            '\\nSDL event profile harness: %s run=%.4fs compile_run=%.4fs\\n'
            % (run.stdout.strip().replace(chr(10), ' / '), elapsed_run,
               elapsed_compile_and_run))
        sys.stdout.write(profile_output)
        sys.stdout.flush()
