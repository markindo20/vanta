import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from compiler.driver import (
    find_cxx_compiler, _compiler_cmd, _emit_source, _frontend_only)


class StdlibListsTests(unittest.TestCase):
    def _source(self, body):
        return 'import "std/lists.vnt" as lists\n\nfunc main() -> void:\n' + body

    def _compile_and_run(self, root, text):
        source = os.path.join(root, 'listsdemo.vnt')
        with open(source, 'w', encoding='utf-8', newline='\n') as f:
            f.write(text)
        name, compiler = find_cxx_compiler()
        if compiler is None:
            self.skipTest('no C++ compiler on PATH')
        program, typed = _frontend_only(source)
        cpp = os.path.join(root, 'listsdemo.cpp')
        exe = os.path.join(root, 'listsdemo.exe' if os.name == 'nt' else 'listsdemo')
        _emit_source(program, typed, cpp)
        build = subprocess.run(_compiler_cmd(name, compiler, cpp, exe, release=True),
                               capture_output=True, text=True)
        self.assertEqual(build.returncode, 0, msg=build.stderr)
        run = subprocess.run([exe], capture_output=True)
        self.assertEqual(run.returncode, 0, msg=run.stderr.decode('utf-8', 'replace'))
        return run.stdout.decode('utf-8').strip().replace('\r', '')

    def test_lists_helpers_typecheck_and_run(self):
        text = self._source(
            '    let arena = Arena(4096)\n'
            '    let xs = arena.list::<i32>()\n'
            '    xs.push(1)\n'
            '    xs.push(2)\n'
            '    xs.push(3)\n'
            '    print_i32(lists.sum(xs))\n'
            '    print_i32(lists.product(xs))\n'
            '    print_i32(lists.min_or(xs, 0))\n'
            '    print_i32(lists.max_or(xs, 0))\n'
            '    print_bool(lists.contains_i32(xs, 2))\n'
            '    print_i32(lists.index_of(xs, 3))\n'
            '    let rev = arena.list::<i32>()\n'
            '    lists.reverse_into(rev, xs)\n'
            '    for i in range(0, len(rev)):\n'
            '        print_i32(rev.at(i))\n'
            '    print_i32(lists.unique_into(rev, xs))\n'
            '    let cat = arena.list::<str>()\n'
            '    cat.push("a")\n'
            '    cat.push("b")\n'
            '    print_str(lists.join(cat, ","))\n')
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(self._compile_and_run(root, text),
                             '6\n6\n1\n3\ntrue\n2\n3\n2\n1\n0\na,b')


if __name__ == '__main__':
    unittest.main()
