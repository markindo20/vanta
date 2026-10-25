"""Hot-reload state segment: ABI, replay, and host orchestration.

These tests build real shared units with the available C++ toolchain and load
them in-process with ctypes, which is exactly what `vanta hot` does.
"""

import contextlib
import ctypes
import io
import os
import shutil
import struct
import tempfile
import unittest
from types import SimpleNamespace

from compiler.driver import (
    cmd_build, cmd_hot, find_cxx_compiler, _windows_dll_search_dirs,
)

# Must match runtime/vanta_runtime.hpp: header plus the layout table.
STATE_DATA_OFFSET = 64 + 256 * 12


def _have_compiler():
    return find_cxx_compiler()[1] is not None


def _expose_toolchain_dlls():
    if os.name != 'nt':
        return
    _name, path = find_cxx_compiler()
    if path is None:
        return
    for directory in _windows_dll_search_dirs(path):
        try:
            os.add_dll_directory(directory)
        except OSError:
            pass


class HotStateTests(unittest.TestCase):
    def setUp(self):
        if not _have_compiler():
            self.skipTest('no C++ compiler on PATH')
        _expose_toolchain_dlls()
        self.tmp = tempfile.mkdtemp(prefix='vanta_hot_test_')

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _build(self, name, source):
        vnt = os.path.join(self.tmp, name + '.vnt')
        with open(vnt, 'w', encoding='utf-8') as f:
            f.write(source)
        ext = '.dll' if os.name == 'nt' else '.so'
        out = os.path.join(self.tmp, name + ext)
        args = SimpleNamespace(
            source=vnt, output=out, release=True, debug=False,
            bundle=False, emit_cpp=None, include_dir=[], lib_dir=[],
            link=[], shared=True, checked=False)
        with contextlib.redirect_stdout(io.StringIO()):
            rc = cmd_build(args)
        self.assertEqual(rc, 0, 'shared build failed for ' + name)
        return out

    def _load(self, path, base, size):
        lib = ctypes.CDLL(path)
        lib.vanta_bind_state.argtypes = [ctypes.c_void_p, ctypes.c_int32]
        lib.vanta_bind_state(ctypes.c_void_p(base), size)
        return lib

    def test_state_survives_a_second_load(self):
        lib_path = self._build('counter', (
            "func main() -> void:\n"
            "    let w = state_arena()\n"
            "    let n = w.alloc::<i32>(1)\n"
            "    n[0] = n[0] + 1\n"))
        buf = ctypes.create_string_buffer(4096)
        base = ctypes.addressof(buf)
        first = self._load(lib_path, base, 4096)
        first.vanta_run_main()
        self.assertEqual(struct.unpack_from('<i', buf, STATE_DATA_OFFSET)[0], 1)
        second = self._load(lib_path, base, 4096)
        second.vanta_run_main()
        self.assertEqual(struct.unpack_from('<i', buf, STATE_DATA_OFFSET)[0], 2)

    def test_layout_change_keeps_old_bytes_and_appends(self):
        first = self._build('layout_a', (
            "func main() -> void:\n"
            "    let w = state_arena()\n"
            "    let a = w.alloc::<i32>(1)\n"
            "    let b = w.alloc::<f32>(1)\n"
            "    a[0] = 11\n"
            "    b[0] = 2.5\n"))
        second = self._build('layout_b', (
            "func main() -> void:\n"
            "    let w = state_arena()\n"
            "    let b = w.alloc::<f32>(1)\n"
            "    let a = w.alloc::<i32>(1)\n"
            "    b[0] = 9.0\n"
            "    a[0] = 4\n"))
        buf = ctypes.create_string_buffer(4096)
        base = ctypes.addressof(buf)
        self._load(first, base, 4096).vanta_run_main()
        self.assertEqual(
            struct.unpack_from('<if', buf, STATE_DATA_OFFSET), (11, 2.5))
        self._load(second, base, 4096).vanta_run_main()
        # The old slot is untouched; the changed allocation starts after it.
        self.assertEqual(
            struct.unpack_from('<if', buf, STATE_DATA_OFFSET), (11, 2.5))
        self.assertEqual(
            struct.unpack_from('<fi', buf, STATE_DATA_OFFSET + 8), (9.0, 4))

    def test_reload_request_is_visible_to_the_unit(self):
        lib_path = self._build('request', (
            "func main() -> void:\n"
            "    let w = state_arena()\n"
            "    let flag = w.alloc::<i32>(1)\n"
            "    if hot_should_reload():\n"
            "        flag[0] = 7\n"))
        buf = ctypes.create_string_buffer(4096)
        base = ctypes.addressof(buf)
        lib = self._load(lib_path, base, 4096)
        lib.vanta_request_reload()
        lib.vanta_run_main()
        self.assertEqual(struct.unpack_from('<i', buf, STATE_DATA_OFFSET)[0], 7)

    def test_migrate_calls_the_user_reload_hook(self):
        marker = os.path.join(self.tmp, 'hook.txt').replace('\\', '/')
        lib_path = self._build('hook', (
            "func __reload(prev: ptr<void>) -> void:\n"
            "    file_write(\"%s\", \"hook\")\n"
            "\n"
            "func main() -> void:\n"
            "    let w = state_arena()\n"
            "    let n = w.alloc::<i32>(1)\n" % marker))
        buf = ctypes.create_string_buffer(4096)
        base = ctypes.addressof(buf)
        lib = self._load(lib_path, base, 4096)
        lib.vanta_migrate.argtypes = [ctypes.c_void_p]
        lib.vanta_migrate(ctypes.c_void_p(base))
        self.assertTrue(os.path.exists(marker))
        with open(marker, encoding='utf-8') as f:
            self.assertEqual(f.read(), 'hook')

    def test_cli_reloads_keep_state_across_generations(self):
        marker = os.path.join(self.tmp, 'count.txt').replace('\\', '/')
        source = os.path.join(self.tmp, 'cli.vnt')
        with open(source, 'w', encoding='utf-8') as f:
            f.write(
                "func main() -> void:\n"
                "    let w = state_arena()\n"
                "    let n = w.alloc::<i32>(1)\n"
                "    n[0] = n[0] + 1\n"
                "    file_write(\"%s\", to_str_i32(n[0]))\n" % marker)
        args = SimpleNamespace(
            source=source, release=True, checked=False, reloads=2,
            state_size=1 << 20, include_dir=[], lib_dir=[], link=[])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = cmd_hot(args)
        self.assertEqual(rc, 0)
        self.assertIn('build #3', out.getvalue())
        with open(marker, encoding='utf-8') as f:
            self.assertEqual(f.read(), '3')

    def test_named_arena_survives_generations(self):
        marker = os.path.join(self.tmp, 'named.txt').replace('\\', '/')
        name = 'vanta-test-' + os.path.basename(self.tmp).replace('.', '-')
        source = os.path.join(self.tmp, 'named.vnt')
        with open(source, 'w', encoding='utf-8') as f:
            f.write(
                "func main() -> void:\n"
                "    let w = Arena(65536, \"%s\")\n"
                "    let n = w.alloc::<i32>(1)\n"
                "    n[0] = n[0] + 1\n"
                "    file_write(\"%s\", to_str_i32(n[0]))\n" % (name, marker))
        args = SimpleNamespace(
            source=source, release=True, checked=False, reloads=2,
            state_size=1 << 20, include_dir=[], lib_dir=[], link=[])
        with contextlib.redirect_stdout(io.StringIO()):
            rc = cmd_hot(args)
        self.assertEqual(rc, 0)
        with open(marker, encoding='utf-8') as f:
            self.assertEqual(f.read(), '3')


if __name__ == '__main__':
    unittest.main()
