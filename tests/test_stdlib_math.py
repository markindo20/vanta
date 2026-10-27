import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from compiler.driver import (
    find_cxx_compiler, _compiler_cmd, _emit_source, _frontend_only)


class StdlibMathTests(unittest.TestCase):
    def _source(self, body):
        return ("import \"std/math.vnt\" as math" + chr(10) + chr(10) +
                "func main() -> void:" + chr(10) +
                body.replace(chr(92) + chr(110), chr(10)))

    def _compile_and_run(self, root, text):
        source = os.path.join(root, 'mathdemo.vnt')
        with open(source, 'w', encoding='utf-8', newline='\n') as f:
            f.write(text)
        name, compiler = find_cxx_compiler()
        if compiler is None:
            self.skipTest('no C++ compiler on PATH')
        program, typed = _frontend_only(source)
        cpp = os.path.join(root, 'mathdemo.cpp')
        exe = os.path.join(root, 'mathdemo.exe' if os.name == 'nt' else 'mathdemo')
        _emit_source(program, typed, cpp)
        build = subprocess.run(_compiler_cmd(name, compiler, cpp, exe, release=True),
                               capture_output=True, text=True)
        self.assertEqual(build.returncode, 0, msg=build.stderr)
        run = subprocess.run([exe], capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, msg=run.stderr)
        return run.stdout.strip().replace('\\r', '')

    def test_math_helpers_typecheck_and_run(self):
        import subprocess
        text = self._source(
            '    print_i32(math.abs_i32(-4))\n'
            '    print_i32(math.min_i32(3, 7))\n'
            '    print_i32(math.max_i32(3, 7))\n'
            '    print_i32(math.clamp_i32(9, 2, 5))\n'
            '    print_i32(math.sign_i32(0))\n'
            '    print_f32(math.lerp_f32(3.0, 5.0, 0.25))\n')
        with tempfile.TemporaryDirectory() as root:
            got = self._compile_and_run(root, text)
            self.assertEqual(got, '4\n3\n7\n5\n0\n3.500000')

    def test_math_helpers_branch_boundaries(self):
        import subprocess
        text = self._source(
            '    print_i32(math.abs_i32(0))\n'
            '    print_i32(math.min_i32(-1, -2))\n'
            '    print_i32(math.max_i32(-1, -2))\n'
            '    print_i32(math.clamp_i32(0, 2, 5))\n'
            '    print_i32(math.clamp_i32(7, 2, 5))\n'
            '    print_i32(math.sign_i32(-9))\n'
            '    print_i32(math.sign_i32(3))\n')
        with tempfile.TemporaryDirectory() as root:
            got = self._compile_and_run(root, text)
            self.assertEqual(got, '0\n-2\n-1\n2\n5\n-1\n1')


if __name__ == '__main__':
    unittest.main()
