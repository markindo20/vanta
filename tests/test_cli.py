import contextlib
import io
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from compiler.driver import (
    RUNTIME_DIR,
    _GAMEKIT_DIR,
    _auto_link_libs,
    _frontend_only,
    _merge_link_libs,
    _normalize_argv,
    _starter_source,
    cmd_check,
    cmd_doctor,
    cmd_fmt,
    cmd_new,
    find_cxx_compiler,
)


HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXAMPLES = os.path.join(HERE, 'examples')


class CliTests(unittest.TestCase):
    def test_bare_source_is_run_shorthand(self):
        self.assertEqual(_normalize_argv(['game.vnt']), ['run', 'game.vnt'])
        self.assertEqual(_normalize_argv(['examples/strike.vnt', '60']),
                         ['run', 'examples/strike.vnt', '60'])
        self.assertEqual(_normalize_argv(['new', 'game.vnt']),
                         ['new', 'game.vnt'])
        self.assertEqual(_normalize_argv(['run', 'game.vnt']),
                         ['run', 'game.vnt'])
        self.assertEqual(_normalize_argv(['doctor']), ['doctor'])
        self.assertEqual(_normalize_argv(['lsp']), ['lsp'])
        self.assertEqual(_normalize_argv(['--version']), ['--version'])
        self.assertEqual(_normalize_argv([]), [])

    def test_starter_game_typechecks(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, 'game.vnt')
            source = _starter_source(target)
            self.assertIn('gamekit/sdl.vnt', source.replace('\\', '/'))
            self.assertIn('func main()', source)
            with open(target, 'w', encoding='utf-8', newline='\n') as f:
                f.write(source)
            _frontend_only(target)

    def test_fmt_rewrites_the_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'game.vnt')
            with open(path, 'w', encoding='utf-8', newline='\n') as f:
                f.write('func main() -> void:\n  return\n')
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = cmd_fmt(SimpleNamespace(source=path, check=False))
            self.assertEqual(code, 0)
            with open(path, encoding='utf-8') as f:
                self.assertEqual(f.read(),
                                 'func main() -> void:\n    return\n')

    def test_fmt_check_reports_an_unformatted_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'game.vnt')
            with open(path, 'w', encoding='utf-8', newline='\n') as f:
                f.write('func main() -> void:\n  return\n')
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = cmd_fmt(SimpleNamespace(source=path, check=True))
            self.assertEqual(code, 1)
            self.assertIn('is not formatted', out.getvalue())

    def test_fmt_check_passes_on_a_formatted_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'game.vnt')
            with open(path, 'w', encoding='utf-8', newline='\n') as f:
                f.write('func main() -> void:\n    return\n')
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = cmd_fmt(SimpleNamespace(source=path, check=True))
            self.assertEqual(code, 0)
            self.assertIn('is formatted', out.getvalue())

    def test_fmt_refuses_a_file_that_does_not_parse(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'bad.vnt')
            with open(path, 'w', encoding='utf-8', newline='\n') as f:
                f.write('func main() -> void:\n    let x: i32 = \n')
            err = io.StringIO()
            with contextlib.redirect_stderr(err), \
                    contextlib.redirect_stdout(io.StringIO()):
                code = cmd_fmt(SimpleNamespace(source=path, check=False))
            self.assertEqual(code, 1)
            self.assertIn('bad.vnt', err.getvalue())

    def test_check_shows_source_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'bad.vnt')
            with open(path, 'w', encoding='utf-8', newline='\n') as f:
                f.write("func main() -> void:\n    let x: i32 = 1.5\n")
            err = io.StringIO()
            with contextlib.redirect_stderr(err), \
                    contextlib.redirect_stdout(io.StringIO()):
                code = cmd_check(SimpleNamespace(source=path))
            self.assertEqual(code, 1)
            text = err.getvalue()
            self.assertIn('let x: i32 = 1.5', text)
            self.assertTrue(any(line.strip() == '^'
                                for line in text.splitlines()))

    def test_check_shows_context_for_imported_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            lib = os.path.join(tmp, 'lib.vnt')
            with open(lib, 'w', encoding='utf-8', newline='\n') as f:
                f.write('func bad() -> i32:\n    return "oops"\n')
            main = os.path.join(tmp, 'main.vnt')
            with open(main, 'w', encoding='utf-8', newline='\n') as f:
                f.write('import "lib.vnt"\nfunc main() -> void:\n    return\n')
            err = io.StringIO()
            with contextlib.redirect_stderr(err), \
                    contextlib.redirect_stdout(io.StringIO()):
                code = cmd_check(SimpleNamespace(source=main))
            self.assertEqual(code, 1)
            text = err.getvalue()
            self.assertIn('return "oops"', text)
            self.assertTrue(any(line.strip() == '^'
                                for line in text.splitlines()))

    def test_check_shows_context_for_lex_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'bad.vnt')
            with open(path, 'w', encoding='utf-8', newline='\n') as f:
                f.write("func main() -> void:\n    let x = @\n")
            err = io.StringIO()
            with contextlib.redirect_stderr(err), \
                    contextlib.redirect_stdout(io.StringIO()):
                code = cmd_check(SimpleNamespace(source=path))
            self.assertEqual(code, 1)
            text = err.getvalue()
            self.assertIn('let x = @', text)
            self.assertTrue(any(line.strip() == '^'
                                for line in text.splitlines()))

    def test_new_refuses_to_overwrite_without_force(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, 'game.vnt')
            args = SimpleNamespace(path=target, force=False)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cmd_new(args), 0)
            self.assertTrue(os.path.exists(target))
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(cmd_new(args), 1)
            args.force = True
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cmd_new(args), 0)

    def test_shipped_data_dirs_exist(self):
        self.assertTrue(os.path.exists(
            os.path.join(RUNTIME_DIR, 'vanta_runtime.hpp')))
        self.assertTrue(os.path.exists(
            os.path.join(_GAMEKIT_DIR, 'sdl.vnt')))

    def test_doctor_reports_a_working_toolchain(self):
        if find_cxx_compiler()[1] is None:
            self.skipTest('no C++ compiler on PATH')
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cmd_doctor(SimpleNamespace())
        self.assertEqual(code, 0)
        text = out.getvalue()
        self.assertIn('vanta ', text)
        self.assertIn('compile test: ok', text)

    def test_sdl_extern_blocks_auto_link(self):
        program, _ = _frontend_only(os.path.join(EXAMPLES, 'strike.vnt'))
        self.assertEqual(_auto_link_libs(program),
                         ['SDL2_image', 'SDL2_ttf', 'SDL2'])

    def test_custom_extern_is_not_auto_linked(self):
        program, _ = _frontend_only(os.path.join(EXAMPLES, 'extern_demo.vnt'))
        self.assertEqual(_auto_link_libs(program), [])

    def test_manual_sdl_link_is_deduped_and_kept_last(self):
        program, _ = _frontend_only(os.path.join(EXAMPLES, 'strike.vnt'))
        self.assertEqual(_merge_link_libs(program, ['SDL2']),
                         ['SDL2_image', 'SDL2_ttf', 'SDL2'])


if __name__ == '__main__':
    unittest.main()
