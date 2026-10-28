import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from compiler.driver import (
    find_cxx_compiler, _compiler_cmd, _emit_source, _frontend_only)


class StdlibStringsTests(unittest.TestCase):
    def _source(self, lines):
        return '\n'.join(
            ['import "std/strings.vnt" as strings', '', 'func main() -> void:']
            + ['    ' + line for line in lines]) + '\n'

    def _compile_and_run(self, root, text):
        source = os.path.join(root, 'stringsdemo.vnt')
        with open(source, 'w', encoding='utf-8', newline='\n') as f:
            f.write(text)
        name, compiler = find_cxx_compiler()
        if compiler is None:
            self.skipTest('no C++ compiler on PATH')
        program, typed = _frontend_only(source)
        cpp = os.path.join(root, 'stringsdemo.cpp')
        exe = os.path.join(root, 'stringsdemo.exe' if os.name == 'nt' else 'stringsdemo')
        _emit_source(program, typed, cpp)
        build = subprocess.run(_compiler_cmd(name, compiler, cpp, exe, release=True),
                               capture_output=True, text=True)
        self.assertEqual(build.returncode, 0, msg=build.stderr)
        run = subprocess.run([exe], capture_output=True)
        self.assertEqual(run.returncode, 0, msg=run.stderr.decode('utf-8', 'replace'))
        return run.stdout.decode('utf-8').strip().replace('\r', '')

    def test_string_helpers_end_to_end(self):
        text = self._source([
            'print_bool(strings.starts_with("hello", "hel"))',
            'print_bool(strings.ends_with("hello.txt", ".txt"))',
            'print_bool(strings.contains("needle", "edl"))',
            'print_i32(strings.find("needle", "edl"))',
            'print_str(strings.substring("abcdef", 2, 2))',
            'print_str(strings.suffix_after("a/b/c", "/"))',
            'print_str(strings.prefixed("hello", "say: "))',
            'print_bool(strings.is_empty(""))',
        ])
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(self._compile_and_run(root, text),
                             'true\ntrue\ntrue\n2\ncd\nb/c\nsay: hello\ntrue')

    def test_string_helpers_boundaries(self):
        text = self._source([
            'print_bool(strings.starts_with("hello", "longer"))',
            'print_bool(strings.is_empty("x"))',
            'print_str(strings.substring("abc", -1, 2))',
            'print_str(strings.substring("abc", 1, -1))',
            'print_str(strings.substring("abc", 10, 2))',
            'print_i32(strings.find("abc", "z"))',
            'print_str(strings.suffix_after("abc", "/"))',
        ])
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(self._compile_and_run(root, text),
                             'false\nfalse\n\n\n\n-1')

    def test_utf8_helpers_end_to_end(self):
        chrs = chr(233) + chr(128512)
        text = (
            "import \"std/strings.vnt\" as strings\n\n"
            "func main() -> void:\n"
            "    let t = \"" + chrs + "\"\n"
            "    print_i32(strings.char_count(t))\n"
            "    print_bool(strings.is_valid_utf8(t))\n"
            "    print_str(strings.utf8_char(t, 1))\n"
            "    print_str(strings.utf8_substring(t, 0, 2))\n"
            "    print_i32(strings.byte_offset_of_char(t, 1))\n"
        )
        expected = "2\ntrue\n" + chrs[1] + "\n" + chrs + "\n2"
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(self._compile_and_run(root, text), expected)


if __name__ == "__main__":
    unittest.main()
