import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from compiler.lsp import LanguageServer, path_to_uri


def _msg(method, params):
    return {'jsonrpc': '2.0', 'params': params, 'method': method}


def _init(server):
    server.handle_message({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
                          'params': {'rootUri': None, 'capabilities': {}}})


def _did_open(path, text):
    return _msg('textDocument/didOpen', {'textDocument': {
        'uri': path_to_uri(path), 'languageId': 'vanta', 'version': 1,
        'text': text}})


def _did_change(path, text, version):
    return _msg('textDocument/didChange', {'textDocument': {
        'uri': path_to_uri(path), 'version': version},
        'contentChanges': [{'text': text}]})


class LspDiagnosticCacheTests(unittest.TestCase):
    def test_identical_revalidation_hits_cache(self):
        src = 'func main() -> void:\n    print_i32(x)\n'
        tmp = tempfile.TemporaryDirectory()
        try:
            path = os.path.join(tmp.name, 'main.vnt')
            with open(path, 'w', encoding='utf-8', newline='\n') as f:
                f.write(src)
            server = LanguageServer()
            _init(server)
            server.handle_message(_did_open(path, src))
            import compiler.lsp as lspmod
            calls = {'n': 0}
            real = lspmod.load_program

            def counted(*a, **k):
                calls['n'] += 1
                return real(*a, **k)

            with mock.patch.object(lspmod, 'load_program', counted):
                server.handle_message(_did_change(path, src, 2))
                server.handle_message(_did_change(path, src, 3))
            self.assertEqual(calls['n'], 0)
        finally:
            tmp.cleanup()

    def test_changed_content_invalidates_cache(self):
        src_a = 'func main() -> void:\n    print_i32(x)\n'
        src_b = 'func main() -> void:\n    print_i32(y)\n'
        tmp = tempfile.TemporaryDirectory()
        try:
            path = os.path.join(tmp.name, 'main.vnt')
            with open(path, 'w', encoding='utf-8', newline='\n') as f:
                f.write(src_a)
            server = LanguageServer()
            _init(server)
            server.handle_message(_did_open(path, src_a))
            import compiler.lsp as lspmod
            calls = {'n': 0}
            real = lspmod.load_program

            def counted(*a, **k):
                calls['n'] += 1
                return real(*a, **k)

            with mock.patch.object(lspmod, 'load_program', counted):
                server.handle_message(_did_change(path, src_a, 2))
                self.assertEqual(calls['n'], 0)
                server.handle_message(_did_change(path, src_b, 3))
                self.assertEqual(calls['n'], 1)
                server.handle_message(_did_change(path, src_b, 4))
                self.assertEqual(calls['n'], 1)
        finally:
            tmp.cleanup()


if __name__ == '__main__':
    unittest.main()
