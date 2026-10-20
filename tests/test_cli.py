import contextlib
import io
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from compiler.driver import (
    _auto_link_libs,
    _frontend_only,
    _merge_link_libs,
    _normalize_argv,
    _starter_source,
    cmd_new,
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
