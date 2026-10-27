import ast
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from compiler import ast_nodes as A
from compiler.codegen_cpp import BUILTIN_FN, BUILTIN_MATH_CTOR
from compiler.type_checker import TypeChecker


HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Builtins implemented directly in codegen rather than through BUILTIN_FN or
# BUILTIN_MATH_CTOR (format lowering, assertions, pointer helpers, and len are
# handled before the generic call path).
DIRECT_CODEGEN = {'assert'}


class CompilerTableTests(unittest.TestCase):
    def test_builtin_table_has_no_duplicate_keys(self):
        path = os.path.join(HERE, 'compiler', 'codegen_cpp.py')
        with open(path, encoding='utf-8') as f:
            tree = ast.parse(f.read())
        found = False
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            if not any(isinstance(t, ast.Name) and t.id == 'BUILTIN_FN'
                       for t in node.targets):
                continue
            found = True
            keys = [k.value for k in node.value.keys
                    if isinstance(k, ast.Constant)]
            duplicates = sorted({k for k in keys if keys.count(k) > 1})
            self.assertEqual(duplicates, [],
                             f'duplicate BUILTIN_FN entries: {duplicates}')
        self.assertTrue(found, 'BUILTIN_FN dictionary not found')

    def test_checker_and_codegen_builtin_tables_agree(self):
        tc = TypeChecker(A.Program([]))
        checker = set(tc.functions)
        generated = (set(BUILTIN_FN) | set(BUILTIN_MATH_CTOR)
                     | DIRECT_CODEGEN)
        missing_codegen = sorted(checker - generated)
        missing_checker = sorted(set(BUILTIN_FN) - checker)
        self.assertEqual(missing_codegen, [],
                         'checker builtins with no codegen mapping: '
                         f'{missing_codegen}')
        self.assertEqual(missing_checker, [],
                         'codegen builtins the checker does not know: '
                         f'{missing_checker}')


if __name__ == '__main__':
    unittest.main()
