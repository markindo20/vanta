import os
import sys
import tempfile
import shutil
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from compiler.lsp import LanguageServer, path_to_uri
from compiler.loader import load_program, load_program_cached, MemoryModuleCache


class LspIncrementalGraphTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='vanta_lsp_graph_')
        self.server = LanguageServer()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, name, source):
        path = os.path.join(self.tmp, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8', newline='\n') as f:
            f.write(source)
        return path

    def open_file(self, path, source=None):
        if source is None:
            with open(path, 'r', encoding='utf-8') as f:
                source = f.read()
        uri = path_to_uri(path)
        self.server.handle_message({
            'jsonrpc': '2.0', 'method': 'textDocument/didOpen',
            'params': {'textDocument': {
                'uri': uri, 'languageId': 'vanta', 'version': 1,
                'text': source,
            }},
        })
        return uri

    def change_file(self, uri, source, version=2):
        return self.server.handle_message({
            'jsonrpc': '2.0', 'method': 'textDocument/didChange',
            'params': {
                'textDocument': {'uri': uri, 'version': version},
                'contentChanges': [{'text': source}],
            },
        })

    def published(self, messages):
        return [m for m in messages
                if m.get('method') == 'textDocument/publishDiagnostics']

    def diag_paths(self, messages):
        return {
            m['params']['uri']: len(m['params']['diagnostics'])
            for m in self.published(messages)
        }

    def test_a_invalid_dep_propagates_on_second_call(self):
        dep = self.write('lib/dep.vnt', 'func foo() -> i32:\n    return 1\n')
        main = self.write('main.vnt',
                          'import "lib/dep.vnt"\nfunc main() -> void:\n'
                          '    print_i32(foo())\n')
        dep_uri = self.open_file(dep)
        main_uri = self.open_file(main)
        invalid = 'func foo() -> str:\n    return 1\n'
        msgs1 = self.change_file(dep_uri, invalid, 2)
        paths1 = self.diag_paths(msgs1)
        # trigger main revalidation (second call)
        main_text = open(main).read()
        msgs2 = self.change_file(main_uri, main_text, 2)
        paths2 = self.diag_paths(msgs1 + msgs2)
        # Collect all published diagnostics across both calls.
        all_msgs = msgs1 + msgs2
        combined = {}
        for m in self.published(all_msgs):
            combined[m['params']['uri']] = combined.get(
                m['params']['uri'], 0) + len(m['params']['diagnostics'])
        dep_uri_s = path_to_uri(dep)
        main_uri_s = path_to_uri(main)
        self.assertTrue(combined.get(dep_uri_s, 0) > 0,
                        combined)
        self.assertTrue(combined.get(main_uri_s, 0) > 0,
                        combined)

    def test_b_revert_clears_errors(self):
        dep = self.write('lib/dep.vnt', 'func foo() -> i32:\n    return 1\n')
        main = self.write('main.vnt',
                          'import "lib/dep.vnt"\nfunc main() -> void:\n'
                          '    print_i32(foo())\n')
        dep_uri = self.open_file(dep)
        main_uri = self.open_file(main)
        invalid = 'func foo() -> str:\n    return 1\n'
        self.change_file(dep_uri, invalid, 2)
        # force main rebuild
        self.change_file(main_uri, open(main).read(), 2)
        valid = 'func foo() -> i32:\n    return 1\n'
        msgs = self.change_file(dep_uri, valid, 3)
        # force main rebuild again
        msgs2 = self.change_file(main_uri, open(main).read(), 3)
        combined = {}
        for m in self.published(msgs + msgs2):
            combined[m['params']['uri']] = combined.get(
                m['params']['uri'], 0) + len(m['params']['diagnostics'])
        dep_uri_s = path_to_uri(dep)
        main_uri_s = path_to_uri(main)
        self.assertEqual(combined.get(dep_uri_s, 0), 0)
        self.assertEqual(combined.get(main_uri_s, 0), 0)

    def test_c_cache_invariant(self):
        N = 4
        # Build N simple healthy modules as separate temp project.
        tmp2 = tempfile.mkdtemp(prefix='vanta_cache_inv_')
        try:
            mods = []
            for i in range(N):
                p = os.path.join(tmp2, 'm%d.vnt' % i)
                with open(p, 'w', encoding='utf-8', newline='\n') as f:
                    f.write('func f%d() -> i32:\n    return %d\n' % (i, i))
                mods.append(p)
            entry = os.path.join(tmp2, 'main.vnt')
            text = ''
            for i in range(N):
                text += 'import "m%d.vnt"\n' % i
            text += 'func main() -> void:\n'
            for i in range(N):
                text += '    print_i32(f%d())\n' % i
            with open(entry, 'w', encoding='utf-8', newline='\n') as f:
                f.write(text)

            # Cold run: use fresh server no cache
            cold_server = LanguageServer()
            cold_server._module_cache = None
            cold_server.handle_message({'jsonrpc': '2.0', 'id': 1,
                                       'method': 'initialize',
                                       'params': {'rootUri': None, 'capabilities': {}}})
            uri = path_to_uri(entry)
            cold_server.handle_message({'jsonrpc': '2.0', 'method': 'textDocument/didOpen',
                                       'params': {'textDocument': {'uri': uri, 'languageId': 'vanta',
                                                                    'version': 1, 'text': text}}})
            cold_count = sum(len(m['params']['diagnostics'])
                             for m in cold_server.outbox
                             if m.get('method') == 'textDocument/publishDiagnostics')

            # Cached runs over randomized small mutates.
            import random
            random.seed(12345)
            maxdiff = 0
            for trial in range(5):
                cache = MemoryModuleCache()
                # mutate entry file slightly (valid int)
                mutated = text.replace('print_i32(f0())', 'print_i32(f0())')
                # introduce randomized small mutate: change one return value in dependency? Instead append a comment? Simpler: mutate a number.
                # Do a harmless mutate that keeps healthy.
                mutated = text
                # Randomly flip one of the return constants to another int.
                i = random.randrange(N)
                mutated = mutated.replace('return %d\n' % i, 'return %d\n' % (i + 7))
                # write mutate to disk copy
                cdir = tempfile.mkdtemp()
                # replicate modules
                for j in range(N):
                    dp = os.path.join(cdir, 'm%d.vnt' % j)
                    os.makedirs(os.path.dirname(dp), exist_ok=True)
                    with open(dp, 'w', encoding='utf-8', newline='\n') as f:
                        v = j + 7 if j == i else j
                        f.write('func f%d() -> i32:\n    return %d\n' % (j, v))
                cmain = os.path.join(cdir, 'main.vnt')
                with open(cmain, 'w', encoding='utf-8', newline='\n') as f:
                    f.write(text)
                # read main text fresh
                with open(cmain, 'r', encoding='utf-8') as f:
                    ctext = f.read()

                srv = LanguageServer()
                srv._module_cache = cache
                srv.handle_message({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
                                   'params': {'rootUri': None, 'capabilities': {}}})
                uri = path_to_uri(cmain)
                srv.handle_message({'jsonrpc': '2.0', 'method': 'textDocument/didOpen',
                                   'params': {'textDocument': {'uri': uri, 'languageId': 'vanta',
                                                                'version': 1, 'text': ctext}}})
                cached_count = sum(len(m['params']['diagnostics'])
                                  for m in srv.outbox
                                  if m.get('method') == 'textDocument/publishDiagnostics')
                # Cold recompute same inputs with cache disabled
                cold = LanguageServer()
                cold._module_cache = None
                cold.handle_message({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
                                    'params': {'rootUri': None, 'capabilities': {}}})
                cold.handle_message({'jsonrpc': '2.0', 'method': 'textDocument/didOpen',
                                    'params': {'textDocument': {'uri': uri, 'languageId': 'vanta',
                                                                 'version': 1, 'text': ctext}}})
                cold_count_trial = sum(len(m['params']['diagnostics'])
                                       for m in cold.outbox
                                       if m.get('method') == 'textDocument/publishDiagnostics')
                self.assertEqual(cached_count, cold_count_trial)
        finally:
            shutil.rmtree(tmp2, ignore_errors=True)

    def test_cache_wrapper_reuse(self):
        tmp = self.tmp
        main = os.path.join(tmp, 'main.vnt')
        dep = os.path.join(tmp, 'dep.vnt')
        with open(dep, 'w', encoding='utf-8', newline='\n') as f:
            f.write('func foo() -> i32:\n    return 1\n')
        with open(main, 'w', encoding='utf-8', newline='\n') as f:
            f.write('import "dep.vnt"\nfunc main() -> void:\n    print_i32(foo())\n')
        sources = {main: open(main).read(), dep: open(dep).read()}
        cache = MemoryModuleCache()
        p1 = load_program_cached(main, sources=sources, search_paths=[], cache=cache)
        p2 = load_program_cached(main, sources=sources, search_paths=[], cache=cache)
        self.assertIs(p1, p2)
        # change dep
        sources2 = dict(sources)
        sources2[dep] = 'func foo() -> i32:\n    return 2\n'
        p3 = load_program_cached(main, sources=sources2, search_paths=[], cache=cache)
        self.assertIsNot(p3, p1)
        # invalid bytes changes result decl? ensure no crash
        self.assertTrue(hasattr(p3, 'decls'))


if __name__ == '__main__':
    unittest.main()