import json
import os
import subprocess
import sys
import tempfile
import shutil
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from compiler.lsp import LanguageServer, path_to_uri, uri_to_path
from compiler.loader import load_program


HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAIN = os.path.join(HERE, 'main.py')


class LspTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='vanta_lsp_')
        self.server = LanguageServer()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, name, source):
        path = os.path.join(self.tmp, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8', newline='\n') as f:
            f.write(source)
        return path

    def open(self, path, source=None):
        if source is None:
            with open(path, 'r', encoding='utf-8-sig') as f:
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

    def change(self, uri, source, version=2):
        return self.server.handle_message({
            'jsonrpc': '2.0', 'method': 'textDocument/didChange',
            'params': {
                'textDocument': {'uri': uri, 'version': version},
                'contentChanges': [{'text': source}],
            },
        })

    def request(self, method, params, msg_id=1):
        return self.server.handle_message({
            'jsonrpc': '2.0', 'id': msg_id, 'method': method,
            'params': params,
        })

    def diagnostics(self, messages):
        return [m for m in messages
                if m.get('method') == 'textDocument/publishDiagnostics']

    def completion_labels(self, uri, line, character):
        response = self.request('textDocument/completion', {
            'textDocument': {'uri': uri},
            'position': {'line': line, 'character': character},
        })[0]
        return {item['label']: item for item in response['result']}

    def test_initialize_capabilities(self):
        result = self.request('initialize', {}, 1)[0]['result']
        caps = result['capabilities']
        self.assertTrue(caps['hoverProvider'])
        self.assertTrue(caps['definitionProvider'])
        self.assertTrue(caps['documentSymbolProvider'])
        self.assertEqual(caps['textDocumentSync']['change'], 1)
        self.assertIn('.', caps['completionProvider']['triggerCharacters'])
        self.assertEqual(result['serverInfo']['name'], 'vanta-lsp')

    def test_did_open_publishes_diagnostic_and_change_clears_it(self):
        path = self.write('main.vnt',
                          'func main() -> void:\n    let x: i32 = "oops"\n')
        uri = self.open(path)
        published = self.diagnostics(self.server.outbox)
        self.assertEqual(len(published), 1)
        diags = published[0]['params']['diagnostics']
        self.assertEqual(len(diags), 1)
        self.assertEqual(diags[0]['severity'], 1)
        self.assertIn('i32', diags[0]['message'])

        messages = self.change(
            uri, 'func main() -> void:\n    let x: i32 = 1\n')
        published = self.diagnostics(messages)
        self.assertEqual(len(published), 1)
        self.assertEqual(published[0]['params']['diagnostics'], [])

    def test_diagnostics_use_unsaved_buffer(self):
        path = self.write('main.vnt',
                          'func main() -> void:\n    let x: i32 = 1\n')
        uri = self.open(path, 'func main() -> void:\n    let x: i32 = "no"\n')
        published = self.diagnostics(self.server.outbox)
        self.assertEqual(len(published), 1)
        self.assertTrue(published[0]['params']['diagnostics'])
        # The disk file is still valid, proving the overlay was used.
        self.assertEqual(self.diagnostics(self.change(uri,
                          'func main() -> void:\n    return\n'))[-1]
                         ['params']['diagnostics'], [])

    def test_diagnostic_for_imported_unsaved_file(self):
        lib = self.write('lib.vnt', 'func helper() -> i32:\n    return 1\n')
        main = self.write('main.vnt',
                          'import "lib.vnt"\nfunc main() -> void:\n'
                          '    print_i32(helper())\n')
        uri = self.open(main)
        # An unsaved edit in lib.vnt should make the error appear there.
        lib_uri = path_to_uri(lib)
        self.server.handle_message({
            'jsonrpc': '2.0', 'method': 'textDocument/didOpen',
            'params': {'textDocument': {
                'uri': lib_uri, 'languageId': 'vanta', 'version': 1,
                'text': 'func helper() -> i32:\n    return "bad"\n',
            }},
        })
        with open(main, 'r', encoding='utf-8') as f:
            main_text = f.read()
        published = self.diagnostics(self.change(uri, main_text, 2))
        self.assertTrue(any(m['params']['uri'] == lib_uri
                            and m['params']['diagnostics']
                            for m in published))

    def test_general_completion_has_locals_declarations_builtins_keywords(self):
        path = self.write('main.vnt', '''\
func helper(value: i32) -> i32:
    return value

func main() -> void:
    let local_value: i32 = helper(1)
    
''')
        uri = self.open(path)
        labels = self.completion_labels(uri, 5, 4)
        self.assertIn('local_value', labels)
        self.assertIn('helper', labels)
        self.assertIn('print_i32', labels)
        self.assertIn('func', labels)
        self.assertEqual(labels['local_value']['kind'], 6)

    def test_enum_member_completion_at_incomplete_line(self):
        path = self.write('main.vnt', '''\
enum Color:
    Red
    Green
    Blue

func main() -> void:
    let c = Color.
''')
        uri = self.open(path)
        labels = self.completion_labels(uri, 6, len('    let c = Color.'))
        self.assertEqual({'Red', 'Green', 'Blue'}.issubset(labels), True)
        self.assertEqual(labels['Red']['kind'], 20)
        self.assertEqual(labels['Red']['textEdit']['range']['start']['line'], 6)

    def test_struct_field_completion_uses_local_annotation(self):
        path = self.write('main.vnt', '''\
struct Point:
    x: i32
    y: i32

func main() -> void:
    let p: Point = Point(1, 2)
    print_i32(p.
''')
        uri = self.open(path)
        response = self.request('textDocument/completion', {
            'textDocument': {'uri': uri},
            'position': {'line': 6, 'character': len('    print_i32(p.')},
        })[0]
        labels = {i['label']: i for i in response['result']}
        self.assertIn('x', labels)
        self.assertIn('y', labels)
        self.assertEqual(labels['x']['kind'], 5)

    def test_list_method_completion_is_inferred_from_text(self):
        path = self.write('main.vnt', '''\
func main() -> void:
    let arena = Arena(64)
    let xs = arena.list::<i32>()
    xs.
''')
        uri = self.open(path)
        labels = self.completion_labels(uri, 3, len('    xs.'))
        self.assertIn('push', labels)
        self.assertIn('pop', labels)
        self.assertEqual(labels['push']['kind'], 2)
        self.assertEqual(labels['push']['insertTextFormat'], 2)

    def test_alias_module_completion(self):
        self.write('math.vnt', '''\
module math
pub func add(a: i32, b: i32) -> i32:
    return a + b
''')
        path = self.write('main.vnt', '''\
import "math.vnt" as math
func main() -> void:
    math.
''')
        uri = self.open(path)
        labels = self.completion_labels(uri, 2, len('    math.'))
        self.assertIn('add', labels)
        self.assertEqual(labels['add']['kind'], 3)

    def test_hover_function_and_local(self):
        path = self.write('main.vnt', '''\
struct Point:
    x: i32

func add(a: i32, b: i32) -> i32:
    return a + b

func main() -> void:
    let p: Point = Point(1)
    print_i32(add(1, 2))
    print_i32(p.x)
    let xs = Arena(1).list::<i32>()
    xs.push(1)
''')
        uri = self.open(path)
        hover = self.request('textDocument/hover', {
            'textDocument': {'uri': uri},
            'position': {'line': 8, 'character': 14},
        })[0]['result']
        self.assertIn('func add(a: i32, b: i32) -> i32',
                      hover['contents']['value'])
        hover = self.request('textDocument/hover', {
            'textDocument': {'uri': uri},
            'position': {'line': 9, 'character': 14},
        })[0]['result']
        self.assertIn('let p: Point', hover['contents']['value'])
        hover = self.request('textDocument/hover', {
            'textDocument': {'uri': uri},
            'position': {'line': 9, 'character': 16},
        })[0]['result']
        self.assertIn('Point.x: i32', hover['contents']['value'])
        hover = self.request('textDocument/hover', {
            'textDocument': {'uri': uri},
            'position': {'line': 11, 'character': 8},
        })[0]['result']
        self.assertIn('func push(value: T) -> void',
                      hover['contents']['value'])

    def test_definition_jumps_to_function_and_field(self):
        path = self.write('main.vnt', '''\
struct Point:
    x: i32

func add(a: i32, b: i32) -> i32:
    return a + b

func main() -> void:
    let p: Point = Point(1)
    print_i32(add(1, 2))
    print_i32(p.x)
''')
        uri = self.open(path)
        definition = self.request('textDocument/definition', {
            'textDocument': {'uri': uri},
            'position': {'line': 8, 'character': 14},
        })[0]['result']
        self.assertEqual(definition[0]['uri'], uri)
        self.assertEqual(definition[0]['range']['start']['line'], 3)
        definition = self.request('textDocument/definition', {
            'textDocument': {'uri': uri},
            'position': {'line': 9, 'character': 16},
        })[0]['result']
        self.assertEqual(definition[0]['range']['start']['line'], 1)
        self.assertEqual(definition[0]['range']['start']['character'], 4)

    def test_document_symbols_include_struct_and_enum_children(self):
        path = self.write('main.vnt', '''\
struct Point:
    x: i32
    y: i32

enum Color:
    Red
    Green

func main() -> void:
    return
''')
        uri = self.open(path)
        symbols = self.request('textDocument/documentSymbol', {
            'textDocument': {'uri': uri},
        })[0]['result']
        by_name = {s['name']: s for s in symbols}
        self.assertEqual(by_name['Point']['kind'], 23)
        self.assertEqual([c['name'] for c in by_name['Point']['children']],
                         ['x', 'y'])
        self.assertEqual(by_name['Color']['kind'], 10)
        self.assertEqual([c['name'] for c in by_name['Color']['children']],
                         ['Red', 'Green'])
        self.assertEqual(by_name['main']['kind'], 12)

    def test_utf16_positions_after_non_bmp_text(self):
        path = self.write('main.vnt', '''\
func add(a: i32, b: i32) -> i32:
    return a + b

func main() -> void:
    let smile = "😀"
    print_i32(add(1, 2))
''')
        uri = self.open(path)
        # Put a non-BMP character directly before the identifier.  The emoji
        # is one Python code point but two UTF-16 code units, which is the
        # position encoding LSP clients use.
        with open(path, 'r', encoding='utf-8') as f:
            source = f.read().replace(
                '    print_i32(add(1, 2))',
                '    let s = "😀"; print_i32(add(1, 2))')
        self.change(uri, source)
        line_text = source.splitlines()[5]
        lsp_col = line_text.index('add') + 1  # one extra unit for the emoji
        definition = self.request('textDocument/definition', {
            'textDocument': {'uri': uri},
            'position': {'line': 5, 'character': lsp_col},
        })[0]['result']
        self.assertEqual(definition[0]['range']['start']['line'], 0)

    def test_uri_round_trip(self):
        path = self.write('a b.vnt', 'func main() -> void:\n    return\n')
        self.assertEqual(uri_to_path(path_to_uri(path)),
                         os.path.normpath(path))

    def test_stdio_cli_transport(self):
        messages = [
            {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {}},
            {'jsonrpc': '2.0', 'id': 2, 'method': 'shutdown'},
            {'jsonrpc': '2.0', 'method': 'exit'},
        ]
        payload = b''
        for message in messages:
            body = json.dumps(message).encode('utf-8')
            payload += (f'Content-Length: {len(body)}\r\n\r\n'.encode('ascii')
                        + body)
        for command in ([sys.executable, MAIN, 'lsp'],
                        [sys.executable, '-m', 'compiler', 'lsp']):
            proc = subprocess.Popen(
                command, cwd=HERE,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE)
            out, err = proc.communicate(payload, timeout=15)
            self.assertEqual(proc.returncode, 0,
                             err.decode('utf-8', 'replace'))
            decoded = _decode_frames(out)
            self.assertEqual(decoded[0]['id'], 1)
            self.assertIn('capabilities', decoded[0]['result'])
            self.assertEqual(decoded[1]['id'], 2)
            self.assertIsNone(decoded[1]['result'])


def _decode_frames(data):
    messages = []
    pos = 0
    while pos < len(data):
        end = data.find(b'\r\n\r\n', pos)
        if end < 0:
            break
        header = data[pos:end].decode('ascii')
        length = int(header.split(':', 1)[1].strip())
        body_start = end + 4
        body = data[body_start:body_start + length]
        messages.append(json.loads(body.decode('utf-8')))
        pos = body_start + length
    return messages


if __name__ == '__main__':
    unittest.main()
