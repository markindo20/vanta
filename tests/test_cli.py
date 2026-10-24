import contextlib
import io
import os
import sys
import time
import tempfile
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from compiler.driver import (
    RUNTIME_DIR,
    _GAMEKIT_DIR,
    _auto_link_libs,
    _discover_test_files,
    _frontend_only,
    _merge_link_libs,
    _normalize_argv,
    _starter_source,
    _write_junit,
    cmd_check,
    cmd_doctor,
    cmd_fmt,
    cmd_new,
    cmd_repl,
    cmd_test,
    cmd_watch,
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

    def test_discover_test_files_matches_naming(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ('a_test.vnt', 'test_b.vnt', 'notes.vnt'):
                with open(os.path.join(tmp, name), 'w', encoding='utf-8'):
                    pass
            sub = os.path.join(tmp, 'sub')
            os.mkdir(sub)
            with open(os.path.join(sub, 'c_test.vnt'), 'w',
                      encoding='utf-8'):
                pass
            found = _discover_test_files(tmp)
            self.assertEqual([os.path.basename(p) for p in found],
                             ['a_test.vnt', 'c_test.vnt', 'test_b.vnt'])

    def test_junit_report_records_failures_and_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, 'report.xml')
            results = [
                {'path': 'ok_test.vnt', 'ok': True, 'kind': 'pass',
                 'output': '', 'seconds': 0.1},
                {'path': 'bad_test.vnt', 'ok': False, 'kind': 'fail',
                 'output': 'boom <x>', 'seconds': 0.2},
                {'path': 'err_test.vnt', 'ok': False, 'kind': 'error',
                 'output': 'no main', 'seconds': 0.0},
            ]
            _write_junit(out, results, 0.3)
            with open(out, encoding='utf-8') as f:
                text = f.read()
            self.assertIn('tests="3"', text)
            self.assertIn('failures="1"', text)
            self.assertIn('errors="1"', text)
            self.assertIn('<failure', text)
            self.assertIn('boom &lt;x&gt;', text)
            self.assertIn('<error', text)

    def test_test_command_runs_files_in_parallel(self):
        if find_cxx_compiler()[1] is None:
            self.skipTest('no C++ compiler on PATH')
        with tempfile.TemporaryDirectory() as tmp:
            src = 'func main() -> void:\n    print_i32(1)\n'
            for name in ('one_test.vnt', 'two_test.vnt'):
                with open(os.path.join(tmp, name), 'w',
                          encoding='utf-8') as f:
                    f.write(src)
            junit = os.path.join(tmp, 'junit.xml')
            args = SimpleNamespace(source=tmp, jobs=2, junit=junit)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = cmd_test(args)
            self.assertEqual(rc, 0)
            self.assertIn('2/2 tests passed', out.getvalue())
            self.assertTrue(os.path.exists(junit))


    def test_watch_runs_one_build_then_stops(self):
        if find_cxx_compiler()[1] is None:
            self.skipTest('no C++ compiler on PATH')
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, 'w.vnt')
        with open(path, 'w', encoding='utf-8') as f:
            f.write('func main() -> void:\n    print_i32(1)\n')
        args = SimpleNamespace(source=path, release=True, prog_args=[],
                               include_dir=[], lib_dir=[], link=[])
        orig = time.sleep
        def fake_sleep(sec):
            raise KeyboardInterrupt()
        time.sleep = fake_sleep
        try:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = cmd_watch(args)
        finally:
            time.sleep = orig
        self.assertEqual(rc, 0)
        self.assertIn('watching', out.getvalue())
        self.assertIn('rebuild', out.getvalue())


    def test_repl_evaluates_a_one_line_program(self):
        if find_cxx_compiler()[1] is None:
            self.skipTest('no C++ compiler on PATH')
        builtins = __import__('builtins')
        orig_input = builtins.input
        rows = iter(['print_i32(1)', ''])
        def fake_input(prompt=''):
            try:
                return next(rows)
            except StopIteration:
                raise EOFError()
        builtins.input = fake_input
        try:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = cmd_repl(None)
        finally:
            builtins.input = orig_input
        self.assertEqual(rc, 0)
        self.assertIn('>>>', out.getvalue())

if __name__ == '__main__':
    unittest.main()
