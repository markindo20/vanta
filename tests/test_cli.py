import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from compiler.driver import (
    _auto_link_libs,
    _frontend_only,
    _merge_link_libs,
    _normalize_argv,
)


HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXAMPLES = os.path.join(HERE, 'examples')


class CliTests(unittest.TestCase):
    def test_bare_source_is_run_shorthand(self):
        self.assertEqual(_normalize_argv(['game.vnt']), ['run', 'game.vnt'])
        self.assertEqual(_normalize_argv(['examples/strike.vnt', '60']),
                         ['run', 'examples/strike.vnt', '60'])
        self.assertEqual(_normalize_argv(['run', 'game.vnt']),
                         ['run', 'game.vnt'])
        self.assertEqual(_normalize_argv(['--version']), ['--version'])
        self.assertEqual(_normalize_argv([]), [])

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
