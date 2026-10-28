import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from compiler.driver import (
    find_cxx_compiler, _compiler_cmd, _emit_source, _frontend_only)

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOOM = os.path.join(HERE, 'examples', 'doom.vnt')


class DoomExampleTests(unittest.TestCase):
    def test_doom_typechecks_and_emits(self):
        name, compiler = find_cxx_compiler()
        if compiler is None:
            self.skipTest('no C++ compiler on PATH')
        program, typed = _frontend_only(DOOM)
        with tempfile.TemporaryDirectory() as root:
            cpp = os.path.join(root, 'doom.cpp')
            _emit_source(program, typed, cpp)
            with open(cpp, encoding='utf-8') as f:
                text = f.read()
            self.assertIn('int main', text)
            self.assertGreater(len(text), 5000)


if __name__ == '__main__':
    unittest.main()
