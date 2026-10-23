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

    def code_actions(self, uri, line, character, diagnostics=None):
        response = self.request('textDocument/codeAction', {
            'textDocument': {'uri': uri},
            'range': {'start': {'line': line, 'character': character},
                      'end': {'line': line, 'character': character}},
            'context': {'diagnostics': diagnostics or []},
        })[0]
        return response['result']

    def workspace_symbols(self, query):
        return self.request('workspace/symbol', {'query': query})[0]['result']

    def semantic_tokens(self, uri):
        return self.request('textDocument/semanticTokens/full', {
            'textDocument': {'uri': uri},
        })[0]['result']['data']

    def decode_tokens(self, data):
        """Turn the flat semantic token array into readable entries."""
        types = ['namespace', 'type', 'class', 'enum', 'interface', 'struct',
                 'typeParameter', 'parameter', 'variable', 'property',
                 'enumMember', 'event', 'function', 'method', 'macro',
                 'keyword', 'modifier', 'comment', 'string', 'number',
                 'regexp', 'operator', 'decorator']
        modifiers = ['declaration', 'definition', 'readonly', 'static',
                     'deprecated', 'abstract', 'async', 'modification',
                     'documentation', 'defaultLibrary']
        result = []
        line = 0
        char = 0
        for i in range(0, len(data), 5):
            delta_line, delta_char, length, token_type, token_mod = \
                data[i:i + 5]
            line += delta_line
            char = delta_char if delta_line else char + delta_char
            result.append((line, char, length, types[token_type],
                           [modifiers[bit] for bit in range(len(modifiers))
                            if token_mod & (1 << bit)]))
        return result

    def test_initialize_capabilities(self):
        result = self.request('initialize', {}, 1)[0]['result']
        caps = result['capabilities']
        self.assertTrue(caps['hoverProvider'])
        self.assertTrue(caps['definitionProvider'])
        self.assertTrue(caps['referencesProvider'])
        self.assertEqual(caps['renameProvider'], {'prepareProvider': True})
        self.assertEqual(caps['codeActionProvider'],
                         {'codeActionKinds': ['quickfix']})
        self.assertTrue(caps['workspaceSymbolProvider'])
        self.assertTrue(caps['documentHighlightProvider'])
        self.assertEqual(caps['documentLinkProvider'],
                         {'resolveProvider': False})
        self.assertTrue(caps['foldingRangeProvider'])
        self.assertTrue(caps['documentFormattingProvider'])
        self.assertTrue(caps['inlayHintProvider'])
        self.assertEqual(caps['codeLensProvider'], {'resolveProvider': False})
        self.assertTrue(caps['callHierarchyProvider'])
        self.assertTrue(caps['typeHierarchyProvider'])
        self.assertEqual(caps['semanticTokensProvider']['full'], True)
        self.assertIn('function', caps['semanticTokensProvider']['legend']
                      ['tokenTypes'])
        self.assertIn('declaration', caps['semanticTokensProvider']['legend']
                      ['tokenModifiers'])
        self.assertTrue(caps['documentSymbolProvider'])
        self.assertEqual(caps['textDocumentSync']['change'], 1)
        self.assertIn('.', caps['completionProvider']['triggerCharacters'])
        self.assertEqual(
            caps['signatureHelpProvider']['triggerCharacters'], ['(', ','])
        self.assertEqual(
            caps['signatureHelpProvider']['retriggerCharacters'], [','])
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

    def signature(self, uri, line, character):
        return self.request('textDocument/signatureHelp', {
            'textDocument': {'uri': uri},
            'position': {'line': line, 'character': character},
        })[0]['result']

    def test_signature_help_for_user_function(self):
        path = self.write('main.vnt', '''\
func add(a: i32, b: i32) -> i32:
    return a + b

func main() -> void:
    let total: i32 = add(1, 2)
''')
        uri = self.open(path)
        result = self.signature(uri, 4, len('    let total: i32 = add('))
        signature = result['signatures'][0]
        self.assertEqual(signature['label'],
                         'func add(a: i32, b: i32) -> i32')
        self.assertEqual([p['label'] for p in signature['parameters']],
                         ['a: i32', 'b: i32'])
        self.assertEqual(signature['activeParameter'], 0)
        self.assertEqual(result['activeParameter'], 0)

        result = self.signature(uri, 4, len('    let total: i32 = add(1,'))
        self.assertEqual(result['signatures'][0]['activeParameter'], 1)
        self.assertEqual(result['activeParameter'], 1)

    def test_signature_help_across_lines(self):
        path = self.write('main.vnt', '''\
func add(a: i32, b: i32) -> i32:
    return a + b

func main() -> void:
    let total: i32 = add(
        1,
        2)
''')
        uri = self.open(path)
        result = self.signature(uri, 6, len('        '))
        self.assertEqual(result['signatures'][0]['label'],
                         'func add(a: i32, b: i32) -> i32')
        self.assertEqual(result['activeParameter'], 1)

    def test_signature_help_picks_innermost_call(self):
        path = self.write('main.vnt', '''\
func add(a: i32, b: i32) -> i32:
    return a + b

func main() -> void:
    print_i32(add(1, 2))
''')
        uri = self.open(path)
        result = self.signature(uri, 4, len('    print_i32(add(1,'))
        self.assertEqual(result['signatures'][0]['label'],
                         'func add(a: i32, b: i32) -> i32')
        self.assertEqual(result['activeParameter'], 1)

    def test_signature_help_ignores_commas_in_strings_and_comments(self):
        path = self.write('main.vnt', '''\
func tag(name: str, count: i32) -> void:
    return

func main() -> void:
    tag("a,b", 2)  # tag(9, 8
''')
        uri = self.open(path)
        result = self.signature(uri, 4, len('    tag("a,b", '))
        self.assertEqual(result['signatures'][0]['label'],
                         'func tag(name: str, count: i32) -> void')
        self.assertEqual(result['activeParameter'], 1)
        line = '    tag("a,b", 2)  # tag(9, 8'
        self.assertIsNone(self.signature(uri, 4, len(line)))

    def test_signature_help_for_struct_constructor(self):
        path = self.write('main.vnt', '''\
struct Enemy:
    hp: i32
    name: str

func main() -> void:
    let e: Enemy = Enemy(hp: 3, name: "orc")
''')
        uri = self.open(path)
        result = self.signature(uri, 5,
                                len('    let e: Enemy = Enemy(hp: 3,'))
        self.assertEqual(result['signatures'][0]['label'],
                         'Enemy(hp: i32, name: str)')
        self.assertEqual(result['activeParameter'], 1)

    def test_signature_help_for_builtin_function_and_method(self):
        path = self.write('main.vnt', '''\
func take(xs: List<i32>) -> void:
    xs.push(2)

func main() -> void:
    print_i32(1)
''')
        uri = self.open(path)
        result = self.signature(uri, 1, len('    xs.push('))
        self.assertEqual(result['signatures'][0]['label'],
                         'func push(value: T) -> void')
        result = self.signature(uri, 4, len('    print_i32('))
        self.assertEqual(result['signatures'][0]['label'],
                         'func print_i32(v: i32) -> void')

    def test_signature_help_for_imported_function(self):
        self.write('math.vnt', '''\
module math
pub func add(a: i32, b: i32) -> i32:
    return a + b
''')
        path = self.write('main.vnt', '''\
import "math.vnt" as math
func main() -> void:
    math.add(1, 2)
''')
        uri = self.open(path)
        result = self.signature(uri, 2, len('    math.add(1,'))
        self.assertEqual(result['signatures'][0]['label'],
                         'func add(a: i32, b: i32) -> i32')
        self.assertEqual(result['activeParameter'], 1)

    def test_signature_help_for_enum_payload(self):
        path = self.write('main.vnt', '''\
enum Shape:
    circle(f64)
    label(str, i32)

func main() -> void:
    let s: Shape = Shape.label("x", 2)
''')
        uri = self.open(path)
        result = self.signature(uri, 5,
                                len('    let s: Shape = Shape.label("x",'))
        self.assertEqual(result['signatures'][0]['label'],
                         'Shape.label(str, i32)')
        self.assertEqual([p['label'] for p in
                          result['signatures'][0]['parameters']],
                         ['str', 'i32'])
        self.assertEqual(result['activeParameter'], 1)

    def test_signature_help_returns_null_without_a_call(self):
        path = self.write('main.vnt',
                          'func main() -> void:\n    let x: i32 = 1\n')
        uri = self.open(path)
        self.assertIsNone(
            self.signature(uri, 1, len('    let x: i32 = 1')))

    def test_signature_help_skips_declarations(self):
        path = self.write('main.vnt', '''\
func add(a: i32, b: i32) -> i32:
    return a + b
''')
        uri = self.open(path)
        self.assertIsNone(
            self.signature(uri, 0, len('func add(a: i32,')))

    def test_signature_help_for_function_value(self):
        path = self.write('main.vnt', '''\
func apply(cb: func(i32, i32) -> i32, a: i32) -> i32:
    return cb(a, a)
''')
        uri = self.open(path)
        result = self.signature(uri, 1, len('    return cb('))
        self.assertEqual(result['signatures'][0]['label'],
                         'func(i32, i32) -> i32')
        self.assertEqual(result['activeParameter'], 0)

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

    def test_references_local_scope_and_shadowing(self):
        path = self.write('main.vnt', '''\
func main() -> i32:
    let x: i32 = 1
    if x > 0:
        let x: i32 = 2
        return x
    return x
''')
        uri = self.open(path)

        def refs(line, char, include_declaration=True):
            ctx = {'includeDeclaration': include_declaration}
            result = self.request('textDocument/references', {
                'textDocument': {'uri': uri},
                'position': {'line': line, 'character': char},
                'context': ctx,
            })[0]['result']
            return {(loc['range']['start']['line'],
                     loc['range']['start']['character']) for loc in result}

        # The outer binding does not include the shadowing inner binding.
        self.assertEqual(refs(1, 8), {(1, 8), (2, 7), (5, 11)})
        self.assertEqual(refs(1, 8, False), {(2, 7), (5, 11)})
        self.assertEqual(refs(3, 12), {(3, 12), (4, 15)})

        changes = self.request('textDocument/rename', {
            'textDocument': {'uri': uri},
            'position': {'line': 1, 'character': 8},
            'newName': 'y',
        })[0]['result']['changes']
        edits = changes[uri]
        self.assertEqual(
            [(e['range']['start']['line'], e['range']['start']['character'],
              e['newText']) for e in edits],
            [(1, 8, 'y'), (2, 7, 'y'), (5, 11, 'y')])

    def test_references_and_rename_imported_function(self):
        math_path = self.write('math.vnt', '''\
module math

pub func add(a: i32, b: i32) -> i32:
    return a + b
''')
        main_path = self.write('main.vnt', '''\
module main

import "math.vnt" as math

func main() -> i32:
    return math.add(1, 2)
''')
        self.open(math_path)
        uri = self.open(main_path)
        result = self.request('textDocument/references', {
            'textDocument': {'uri': uri},
            'position': {'line': 5, 'character': 16},
        })[0]['result']
        math_uri = path_to_uri(math_path)
        self.assertEqual(
            {(loc['uri'], loc['range']['start']['line'],
              loc['range']['start']['character']) for loc in result},
            {(uri, 5, 16), (math_uri, 2, 9)})

        without_decl = self.request('textDocument/references', {
            'textDocument': {'uri': uri},
            'position': {'line': 5, 'character': 16},
            'context': {'includeDeclaration': False},
        })[0]['result']
        self.assertEqual(
            {(loc['uri'], loc['range']['start']['line']) for loc in without_decl},
            {(uri, 5)})

        changes = self.request('textDocument/rename', {
            'textDocument': {'uri': uri},
            'position': {'line': 5, 'character': 16},
            'newName': 'plus',
        })[0]['result']['changes']
        self.assertEqual(sorted(changes), sorted([uri, math_uri]))
        self.assertEqual(changes[uri][0]['range']['start']['character'], 16)
        self.assertEqual(changes[uri][0]['newText'], 'plus')
        self.assertEqual(changes[math_uri][0]['range']['start']['line'], 2)
        self.assertEqual(changes[math_uri][0]['range']['start']['character'], 9)

    def test_references_struct_field_writes_and_labels(self):
        path = self.write('main.vnt', '''\
struct Enemy:
    hp: i32
    name: i32

func main() -> i32:
    let e: Enemy = Enemy(hp: 1, name: 2)
    e.hp = 3
    return e.hp
''')
        uri = self.open(path)
        result = self.request('textDocument/references', {
            'textDocument': {'uri': uri},
            'position': {'line': 1, 'character': 4},
        })[0]['result']
        positions = {(loc['range']['start']['line'],
                      loc['range']['start']['character']) for loc in result}
        self.assertEqual(positions, {(1, 4), (5, 25), (6, 6), (7, 13)})

        # Renaming the field also renames the constructor label, and never the
        # same-named `name` field.
        edits = self.request('textDocument/rename', {
            'textDocument': {'uri': uri},
            'position': {'line': 1, 'character': 4},
            'newName': 'health',
        })[0]['result']['changes'][uri]
        self.assertEqual(
            [(e['range']['start']['line'], e['range']['start']['character'])
             for e in edits],
            [(1, 4), (5, 25), (6, 6), (7, 13)])
        self.assertNotIn('name', [e['newText'] for e in edits])

    def test_references_enum_member_payload_and_match(self):
        path = self.write('main.vnt', '''\
enum Color:
    red
    green
    blue(i32)

func main() -> i32:
    let c: Color = Color.red
    let b: Color = Color.blue(7)
    match c:
        Color.red:
            return 1
        Color.blue(n):
            return n
        Color.green:
            return 0
''')
        uri = self.open(path)
        result = self.request('textDocument/references', {
            'textDocument': {'uri': uri},
            'position': {'line': 3, 'character': 4},
        })[0]['result']
        positions = {(loc['range']['start']['line'],
                      loc['range']['start']['character']) for loc in result}
        self.assertEqual(positions, {(3, 4), (7, 25), (11, 14)})

        # Renaming from a match pattern renames the declaration and every use.
        edits = self.request('textDocument/rename', {
            'textDocument': {'uri': uri},
            'position': {'line': 11, 'character': 14},
            'newName': 'azure',
        })[0]['result']['changes'][uri]
        self.assertEqual(
            [(e['range']['start']['line'], e['range']['start']['character'])
             for e in edits],
            [(3, 4), (7, 25), (11, 14)])

    def test_references_type_annotations_and_prepare_rename(self):
        path = self.write('main.vnt', '''\
struct Point:
    x: i32

func take(p: Point) -> Point:
    let q: Point = p
    return q
''')
        uri = self.open(path)
        result = self.request('textDocument/references', {
            'textDocument': {'uri': uri},
            'position': {'line': 0, 'character': 7},
        })[0]['result']
        positions = {(loc['range']['start']['line'],
                      loc['range']['start']['character']) for loc in result}
        self.assertEqual(positions, {(0, 7), (3, 13), (3, 23), (4, 11)})

        prepared = self.request('textDocument/prepareRename', {
            'textDocument': {'uri': uri},
            'position': {'line': 3, 'character': 14},
        })[0]['result']
        self.assertEqual(prepared['placeholder'], 'Point')
        self.assertEqual(prepared['range'], {
            'start': {'line': 3, 'character': 13},
            'end': {'line': 3, 'character': 18},
        })

        edits = self.request('textDocument/rename', {
            'textDocument': {'uri': uri},
            'position': {'line': 0, 'character': 7},
            'newName': 'Coord',
        })[0]['result']['changes'][uri]
        self.assertEqual(len(edits), 4)
        self.assertTrue(all(e['newText'] == 'Coord' for e in edits))

    def test_references_module_alias(self):
        math_path = self.write('math.vnt', '''\
module math

pub func add(a: i32, b: i32) -> i32:
    return a + b
''')
        main_path = self.write('main.vnt', '''\
module main

import "math.vnt" as m

func main() -> i32:
    return m.add(1, 2)
''')
        self.open(math_path)
        uri = self.open(main_path)
        result = self.request('textDocument/references', {
            'textDocument': {'uri': uri},
            'position': {'line': 5, 'character': 11},
        })[0]['result']
        positions = {(loc['range']['start']['line'],
                      loc['range']['start']['character']) for loc in result}
        self.assertEqual(positions, {(2, 21), (5, 11)})

        edits = self.request('textDocument/rename', {
            'textDocument': {'uri': uri},
            'position': {'line': 5, 'character': 11},
            'newName': 'math',
        })[0]['result']['changes'][uri]
        self.assertEqual(
            [(e['range']['start']['line'], e['range']['start']['character'])
             for e in edits],
            [(2, 21), (5, 11)])

    def test_rename_refuses_builtins_unknown_names_and_keywords(self):
        path = self.write('main.vnt', '''\
func main() -> void:
    print_i32(1)
    let x: i32 = 1
    return
''')
        uri = self.open(path)

        def rename(line, char, new_name):
            return self.request('textDocument/rename', {
                'textDocument': {'uri': uri},
                'position': {'line': line, 'character': char},
                'newName': new_name,
            })[0]['result']

        def prepare(line, char):
            return self.request('textDocument/prepareRename', {
                'textDocument': {'uri': uri},
                'position': {'line': line, 'character': char},
            })[0]['result']

        self.assertIsNone(rename(1, 4, 'print_u32'))   # builtin
        self.assertIsNone(prepare(1, 4))
        self.assertIsNone(rename(2, 8, '1bad'))        # invalid identifier
        self.assertIsNone(rename(2, 8, 'func'))        # keyword
        self.assertIsNotNone(rename(2, 8, 'value'))    # local variable

    def test_rename_tolerates_unparsed_buffer(self):
        path = self.write('main.vnt', '''\
func main() -> i32:
    return 1
func broken(:
''')
        uri = self.open(path)
        prepared = self.request('textDocument/prepareRename', {
            'textDocument': {'uri': uri},
            'position': {'line': 0, 'character': 6},
        })[0]['result']
        self.assertEqual(prepared['placeholder'], 'main')
        changes = self.request('textDocument/rename', {
            'textDocument': {'uri': uri},
            'position': {'line': 0, 'character': 6},
            'newName': 'run',
        })[0]['result']['changes']
        self.assertEqual(changes[uri][0]['range']['start'],
                         {'line': 0, 'character': 5})
        self.assertEqual(changes[uri][0]['newText'], 'run')

    def test_references_enum_through_alias_and_patterns(self):
        math_path = self.write('math.vnt', '''\
module math

pub enum Shape:
    circle(i32)
    square(i32)
''')
        main_path = self.write('main.vnt', '''\
module main

import "math.vnt" as m

func area(s: m.Shape) -> i32:
    match s:
        m.Shape.circle(r):
            return r
        m.Shape.square(w):
            return w
    return 0
''')
        self.open(math_path)
        uri = self.open(main_path)
        math_uri = path_to_uri(math_path)

        def refs(line, char):
            result = self.request('textDocument/references', {
                'textDocument': {'uri': uri},
                'position': {'line': line, 'character': char},
            })[0]['result']
            return {(loc['uri'], loc['range']['start']['line'],
                     loc['range']['start']['character']) for loc in result}

        self.assertEqual(refs(6, 16), {(math_uri, 3, 4), (uri, 6, 16)})
        self.assertEqual(refs(6, 10), {
            (math_uri, 2, 9), (uri, 4, 15), (uri, 6, 10), (uri, 8, 10)})
        self.assertEqual(refs(6, 8), {
            (uri, 2, 21), (uri, 4, 13), (uri, 6, 8), (uri, 8, 8)})

        edits = self.request('textDocument/rename', {
            'textDocument': {'uri': uri},
            'position': {'line': 6, 'character': 10},
            'newName': 'Form',
        })[0]['result']['changes']
        self.assertEqual(
            [(e['range']['start']['line'], e['range']['start']['character'])
             for e in edits[uri]],
            [(4, 15), (6, 10), (8, 10)])
        self.assertEqual(len(edits[math_uri]), 1)

    def test_references_nested_imported_field_and_list_element(self):
        game_path = self.write('game.vnt', '''\
module game

pub struct Inner:
    hp: i32

pub struct Outer:
    inner: Inner
    items: List<Inner>
''')
        main_path = self.write('main.vnt', '''\
module main

import "game.vnt" as g

func total(o: g.Outer) -> i32:
    let inner = o.inner
    let h: i32 = inner.hp
    for item in o.items:
        h = item.hp
    return h
''')
        self.open(game_path)
        uri = self.open(main_path)
        game_uri = path_to_uri(game_path)
        result = self.request('textDocument/references', {
            'textDocument': {'uri': uri},
            'position': {'line': 8, 'character': 17},
        })[0]['result']
        self.assertEqual(
            {(loc['uri'], loc['range']['start']['line'],
              loc['range']['start']['character']) for loc in result},
            {(game_uri, 3, 4), (uri, 6, 23), (uri, 8, 17)})

    def test_code_actions_suggest_unknown_name(self):
        path = self.write('main.vnt', '''\
func main() -> i32:
    let value: i32 = 1
    return valeu
''')
        uri = self.open(path)
        actions = self.code_actions(uri, 2, 12)
        self.assertTrue(actions)
        self.assertEqual(actions[0]['title'], "Change 'valeu' to 'value'")
        self.assertTrue(actions[0]['isPreferred'])
        self.assertEqual(actions[0]['kind'], 'quickfix')
        edit = actions[0]['edit']['changes'][uri][0]
        self.assertEqual(edit['newText'], 'value')
        self.assertEqual(edit['range'], {
            'start': {'line': 2, 'character': 11},
            'end': {'line': 2, 'character': 16},
        })
        self.assertEqual(actions[0]['diagnostics'][0]['message'],
                         "unknown name 'valeu'")

        # A client that sends its diagnostics gets the same result without
        # the server recomputing them.
        supplied = self.code_actions(uri, 2, 12,
                                     actions[0]['diagnostics'])
        self.assertEqual([a['title'] for a in supplied],
                         [a['title'] for a in actions])

    def test_code_actions_suggest_struct_field(self):
        path = self.write('main.vnt', '''\
struct Enemy:
    hp: i32

func main() -> i32:
    let e: Enemy = Enemy(hp: 1)
    return e.hpp
''')
        uri = self.open(path)
        actions = self.code_actions(uri, 5, 14)
        self.assertTrue(actions)
        self.assertEqual(actions[0]['title'], "Change 'hpp' to 'hp'")
        edit = actions[0]['edit']['changes'][uri][0]
        self.assertEqual(edit['newText'], 'hp')
        self.assertEqual(edit['range']['start'], {'line': 5, 'character': 13})
        self.assertEqual(edit['range']['end'], {'line': 5, 'character': 16})

    def test_code_actions_suggest_constructor_field(self):
        path = self.write('main.vnt', '''\
struct Enemy:
    hp: i32

func main() -> i32:
    let e: Enemy = Enemy(hpp: 1)
    return e.hp
''')
        uri = self.open(path)
        actions = self.code_actions(uri, 4, 25)
        self.assertTrue(actions)
        self.assertEqual(actions[0]['title'], "Change 'hpp' to 'hp'")
        edit = actions[0]['edit']['changes'][uri][0]
        self.assertEqual(edit['newText'], 'hp')
        self.assertEqual(edit['range']['start'], {'line': 4, 'character': 25})
        self.assertEqual(edit['range']['end'], {'line': 4, 'character': 28})

    def test_code_actions_suggest_enum_member(self):
        path = self.write('main.vnt', '''\
enum Color:
    red
    blue

func main() -> i32:
    let c: Color = Color.reed
    return 0
''')
        uri = self.open(path)
        actions = self.code_actions(uri, 5, 25)
        self.assertTrue(actions)
        self.assertEqual(actions[0]['title'], "Change 'reed' to 'red'")
        edit = actions[0]['edit']['changes'][uri][0]
        self.assertEqual(edit['newText'], 'red')
        self.assertEqual(edit['range']['start'], {'line': 5, 'character': 25})

    def test_code_actions_make_let_mutable(self):
        path = self.write('main.vnt', '''\
func main() -> i32:
    let x: i32 = 1
    x = 2
    return x
''')
        uri = self.open(path)
        actions = self.code_actions(uri, 2, 4)
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]['title'], "Make 'x' mutable")
        self.assertTrue(actions[0]['isPreferred'])
        edit = actions[0]['edit']['changes'][uri][0]
        self.assertEqual(edit['newText'], 'mut')
        self.assertEqual(edit['range'], {
            'start': {'line': 1, 'character': 4},
            'end': {'line': 1, 'character': 7},
        })

        # Parameters have no declaration keyword to rewrite.
        param_path = self.write('param.vnt', '''\
func f(x: i32) -> i32:
    x = 2
    return x
''')
        param_uri = self.open(param_path)
        self.assertEqual(self.code_actions(param_uri, 1, 4), [])

    def test_code_actions_use_server_diagnostics_for_stale_client_one(self):
        path = self.write('main.vnt', '''\
struct Enemy:
    hp: i32

func main() -> i32:
    let e: Enemy = Enemy(hp: 1)
    return e.hpp
''')
        uri = self.open(path)
        stale = [{
            'range': {'start': {'line': 0, 'character': 0},
                      'end': {'line': 0, 'character': 0}},
            'severity': 1,
            'message': "unknown name 'nope'",
        }]
        actions = self.code_actions(uri, 5, 14, stale)
        self.assertTrue(actions)
        self.assertEqual(actions[0]['title'], "Change 'hpp' to 'hp'")
        edit = actions[0]['edit']['changes'][uri][0]
        self.assertEqual(edit['range']['start'], {'line': 5, 'character': 13})

    def test_code_actions_work_through_a_module_alias(self):
        game_path = self.write('game.vnt', '''\
module game

pub struct Enemy:
    hp: i32
''')
        label_path = self.write('label.vnt', '''\
module label

import "game.vnt" as g

func main() -> i32:
    let e: g.Enemy = g.Enemy(hpp: 1)
    return e.hp
''')
        field_path = self.write('field.vnt', '''\
module field

import "game.vnt" as g

func main() -> i32:
    let e: g.Enemy = g.Enemy(hp: 1)
    return e.hpp
''')
        self.open(game_path)
        label_uri = self.open(label_path)
        actions = self.code_actions(label_uri, 5, 29)
        self.assertTrue(actions)
        self.assertEqual(actions[0]['title'], "Change 'hpp' to 'hp'")
        edit = actions[0]['edit']['changes'][label_uri][0]
        self.assertEqual(edit['newText'], 'hp')
        self.assertEqual(edit['range']['start'], {'line': 5, 'character': 29})
        self.assertEqual(edit['range']['end'], {'line': 5, 'character': 32})

        field_uri = self.open(field_path)
        actions = self.code_actions(field_uri, 6, 13)
        self.assertTrue(actions)
        self.assertEqual(actions[0]['title'], "Change 'hpp' to 'hp'")
        edit = actions[0]['edit']['changes'][field_uri][0]
        self.assertEqual(edit['newText'], 'hp')
        self.assertEqual(edit['range']['start'], {'line': 6, 'character': 13})
        self.assertEqual(edit['range']['end'], {'line': 6, 'character': 16})

    def test_code_actions_use_the_receiver_type_for_field_suggestions(self):
        path = self.write('main.vnt', '''\
struct Enemy:
    hp: i32
    armor: i32

struct Potion:
    heal: i32
    mana: i32

func main() -> i32:
    let e: Enemy = Enemy(hp: 1, armor: 2)
    let p: Potion = Potion(heal: 1, mana: 2)
    return e.hel
''')
        uri = self.open(path)
        actions = self.code_actions(uri, 10, 16)
        self.assertEqual(actions, [])

    def test_code_actions_honour_the_requested_kind(self):
        path = self.write('main.vnt', '''\
func main() -> i32:
    let value: i32 = 1
    return valeu
''')
        uri = self.open(path)
        response = self.request('textDocument/codeAction', {
            'textDocument': {'uri': uri},
            'range': {'start': {'line': 2, 'character': 11},
                      'end': {'line': 2, 'character': 16}},
            'context': {'diagnostics': [], 'only': ['refactor']},
        })[0]
        self.assertEqual(response['result'], [])

    def test_code_actions_ignore_unrelated_diagnostics(self):
        path = self.write('main.vnt', '''\
func main() -> i32:
    let x: i32 = 1
    return "no"
''')
        uri = self.open(path)
        self.assertEqual(self.code_actions(uri, 2, 13), [])

    def test_workspace_symbols_find_declarations_across_the_workspace(self):
        self.write('game.vnt', '''\
module game

pub struct Enemy:
    hp: i32
    damage: i32

pub enum Color:
    red
    blue

pub func spawn_enemy() -> i32:
    return 1
''')
        main_path = self.write('main.vnt', '''\
module main

import "game.vnt" as g

func main() -> i32:
    return g.spawn_enemy()
''')
        self.open(main_path)
        self.server.root_path = self.tmp
        self.server.root_uri = path_to_uri(self.tmp)

        symbols = self.workspace_symbols('spawn')
        self.assertEqual([s['name'] for s in symbols], ['spawn_enemy'])
        self.assertEqual(symbols[0]['kind'], 12)          # Function
        self.assertEqual(symbols[0]['containerName'], 'game')
        location = symbols[0]['location']
        self.assertEqual(location['uri'], path_to_uri(
            os.path.join(self.tmp, 'game.vnt')))
        self.assertEqual(location['range']['start'], {'line': 10, 'character': 9})
        self.assertEqual(location['range']['end'], {'line': 10, 'character': 20})

        # A struct, its fields, and an enum with its members are symbols too.
        names = [s['name'] for s in self.workspace_symbols('')]
        self.assertEqual(names, ['Color', 'Enemy', 'blue', 'damage', 'hp',
                                 'main', 'red', 'spawn_enemy'])
        fields = {s['name']: s for s in self.workspace_symbols('hp')}
        self.assertEqual(list(fields), ['hp'])
        self.assertEqual(fields['hp']['kind'], 8)          # Field
        self.assertEqual(fields['hp']['containerName'], 'Enemy')

    def test_workspace_symbols_match_by_prefix_and_substring(self):
        self.write('main.vnt', '''\
struct Point:
    x: i32

func draw_player() -> void:
    return
''')
        self.open(os.path.join(self.tmp, 'main.vnt'))
        self.server.root_path = self.tmp
        self.server.root_uri = path_to_uri(self.tmp)

        self.assertEqual([s['name'] for s in self.workspace_symbols('draw')],
                         ['draw_player'])
        self.assertEqual([s['name'] for s in self.workspace_symbols('Point')],
                         ['Point'])
        self.assertEqual([s['name'] for s in self.workspace_symbols('oint')],
                         ['Point'])
        self.assertEqual(self.workspace_symbols('nothing_here'), [])

    def test_workspace_symbols_use_the_unsaved_buffer(self):
        path = self.write('main.vnt', 'func main() -> void:\n    return\n')
        uri = self.open(path)
        self.server.root_path = self.tmp
        self.server.root_uri = path_to_uri(self.tmp)
        self.assertEqual(
            [s['name'] for s in self.workspace_symbols('main')], ['main'])
        self.change(uri, 'func renamed() -> void:\n    return\n')
        self.assertEqual(
            [s['name'] for s in self.workspace_symbols('renamed')],
            ['renamed'])
        self.assertEqual(self.workspace_symbols('main'), [])

    def test_workspace_symbols_without_a_root_use_open_documents(self):
        self.write('game.vnt', '''\
module game

pub func helper() -> i32:
    return 1
''')
        main_path = self.write('main.vnt', '''\
module main

import "game.vnt" as g

func main() -> i32:
    return g.helper()
''')
        self.open(main_path)
        # No workspace root: only the open document and its import are known.
        names = [s['name'] for s in self.workspace_symbols('')]
        self.assertEqual(sorted(names), ['helper', 'main'])

    def test_semantic_tokens_classify_declarations_and_uses(self):
        path = self.write('main.vnt', '''\
struct Enemy:
    hp: i32

enum Color:
    red

const LIMIT: i32 = 10

func damage(e: Enemy, amount: i32) -> i32:
    # Subtract the armor first.
    let total: i32 = e.hp + amount
    let c: Color = Color.red
    return total + LIMIT
''')
        uri = self.open(path)
        tokens = self.decode_tokens(self.semantic_tokens(uri))
        kinds = {(line, char): (kind, mods)
                  for line, char, _length, kind, mods in tokens}
        with open(path, encoding='utf-8') as f:
            source = f.read().splitlines()

        def word_at(line, char):
            return source[line][char:char + 5]

        # The struct name, its field, the enum, and its member.
        self.assertEqual(kinds[(0, 7)][0], 'struct')
        self.assertIn('declaration', kinds[(0, 7)][1])
        self.assertEqual(kinds[(1, 4)][0], 'property')
        self.assertEqual(kinds[(3, 5)][0], 'enum')
        self.assertEqual(kinds[(4, 4)][0], 'enumMember')
        # A constant is a read-only variable.
        self.assertEqual(kinds[(6, 6)][0], 'variable')
        self.assertIn('readonly', kinds[(6, 6)][1])
        # A function, its parameters, and a local.
        self.assertEqual(kinds[(8, 5)][0], 'function')
        self.assertIn('declaration', kinds[(8, 5)][1])
        self.assertEqual(kinds[(8, 12)][0], 'parameter')
        self.assertEqual(kinds[(8, 22)][0], 'parameter')
        self.assertEqual(kinds[(10, 8)][0], 'variable')
        # A use of a parameter and of a field.
        self.assertEqual(kinds[(10, 21)][0], 'parameter')
        self.assertEqual(kinds[(10, 23)][0], 'property')
        # A type annotation and an enum member in an expression.
        self.assertEqual(kinds[(11, 11)][0], 'enum')
        self.assertEqual(kinds[(11, 25)][0], 'enumMember')
        # Comments and keywords are lexical tokens.
        self.assertEqual(kinds[(9, 4)][0], 'comment')
        self.assertEqual(kinds[(8, 0)][0], 'keyword')
        self.assertEqual(word_at(8, 5), 'damag')

    def test_semantic_tokens_mark_builtins_as_library(self):
        path = self.write('main.vnt', '''\
func main() -> i32:
    let x: i32 = print_i32(3)
    return x
''')
        uri = self.open(path)
        tokens = self.decode_tokens(self.semantic_tokens(uri))
        kinds = {(line, char): (kind, mods)
                  for line, char, _length, kind, mods in tokens}
        self.assertEqual(kinds[(1, 17)][0], 'function')
        self.assertIn('defaultLibrary', kinds[(1, 17)][1])
        self.assertEqual(kinds[(0, 15)][0], 'type')
        self.assertIn('defaultLibrary', kinds[(0, 15)][1])

    def test_semantic_tokens_survive_an_unparsed_buffer(self):
        path = self.write('main.vnt', 'func main() -> void:\n    return\n')
        uri = self.open(path, 'func main() -> void:\n    let x: i32 = 1\n')
        tokens = self.decode_tokens(self.semantic_tokens(uri))
        self.assertTrue(tokens)
        kinds = {kind for _line, _char, _length, kind, _mods in tokens}
        self.assertIn('variable', kinds)

    def test_formatting_rewrites_the_document(self):
        path = self.write('main.vnt', 'func main() -> void:\n'
                          '  return\n')
        uri = self.open(path)
        self.assertTrue(self.server.handle_message({
            'jsonrpc': '2.0', 'id': 1, 'method': 'textDocument/formatting',
            'params': {'textDocument': {'uri': uri},
                       'options': {'tabSize': 4, 'insertSpaces': True}},
        }))
        edits = self.server.outbox[-1]['result']
        self.assertEqual(len(edits), 1)
        self.assertEqual(edits[0]['newText'],
                         'func main() -> void:\n    return\n')
        self.assertEqual(edits[0]['range']['start'],
                         {'line': 0, 'character': 0})

    def test_formatting_an_already_formatted_document_returns_no_edits(self):
        path = self.write('main.vnt', 'func main() -> void:\n    return\n')
        uri = self.open(path)
        self.request('textDocument/formatting', {
            'textDocument': {'uri': uri},
            'options': {'tabSize': 4, 'insertSpaces': True},
        })
        self.assertEqual(self.server.outbox[-1]['result'], [])

    def test_inlay_hints_show_inferred_types(self):
        path = self.write('main.vnt', '''\
struct Enemy:
    hp: i32

func add(a: i32, b: i32) -> i32:
    return a + b

func main() -> i32:
    let x = add(1, 2)
    let e = Enemy(hp: 1)
    let h = e.hp
    let name = "hero"
    let listed: List<i32> = [1, 2]
    return x
''')
        uri = self.open(path)
        hints = self.request('textDocument/inlayHint', {
            'textDocument': {'uri': uri},
            'range': {'start': {'line': 0, 'character': 0},
                      'end': {'line': 20, 'character': 0}},
        })[0]['result']
        labels = {hint['label'] for hint in hints}
        self.assertEqual(labels, {': i32', ': Enemy', ': str'})
        lines = [hint['position']['line'] for hint in hints
                 if hint['label'] == ': i32']
        self.assertEqual(sorted(lines), [7, 9])

    def test_code_lenses_count_the_uses_of_a_function(self):
        path = self.write('main.vnt', '''\
func helper() -> i32:
    return 1

func main() -> i32:
    let a = helper()
    let b = helper()
    return a + b
''')
        uri = self.open(path)
        lenses = self.request('textDocument/codeLens', {
            'textDocument': {'uri': uri},
        })[0]['result']
        self.assertEqual(len(lenses), 1)
        command = lenses[0]['command']
        self.assertEqual(command['title'], '2 references')
        self.assertEqual(command['command'], 'editor.action.showReferences')
        locations = command['arguments'][2]
        self.assertEqual(len(locations), 2)
        self.assertEqual({loc['range']['start']['line'] for loc in locations},
                         {4, 5})

    def test_code_lenses_skip_an_unused_function(self):
        path = self.write('main.vnt', '''\
func unused() -> i32:
    return 1

func main() -> i32:
    return 2
''')
        uri = self.open(path)
        lenses = self.request('textDocument/codeLens', {
            'textDocument': {'uri': uri},
        })[0]['result']
        self.assertEqual(lenses, [])

    def test_call_hierarchy_shows_callers_and_callees(self):
        path = self.write('main.vnt', '''\
func helper() -> i32:
    return 1

func main() -> i32:
    let a = helper()
    return a
''')
        uri = self.open(path)
        items = self.request('textDocument/prepareCallHierarchy', {
            'textDocument': {'uri': uri},
            'position': {'line': 0, 'character': 6},
        })[0]['result']
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['name'], 'helper')

        incoming = self.request('callHierarchy/incomingCalls', {
            'item': items[0],
        })[0]['result']
        self.assertEqual(len(incoming), 1)
        self.assertEqual(incoming[0]['from']['name'], 'main')
        self.assertEqual(incoming[0]['fromRanges'][0]['start']['line'], 4)

        outgoing = self.request('callHierarchy/outgoingCalls', {
            'item': items[0],
        })[0]['result']
        self.assertEqual(outgoing, [])

    def test_call_hierarchy_lists_what_a_function_calls(self):
        path = self.write('main.vnt', '''\
func helper() -> i32:
    return 1

func main() -> i32:
    let a = helper()
    return a
''')
        uri = self.open(path)
        items = self.request('textDocument/prepareCallHierarchy', {
            'textDocument': {'uri': uri},
            'position': {'line': 3, 'character': 6},
        })[0]['result']
        self.assertEqual(items[0]['name'], 'main')
        outgoing = self.request('callHierarchy/outgoingCalls', {
            'item': items[0],
        })[0]['result']
        self.assertEqual(len(outgoing), 1)
        self.assertEqual(outgoing[0]['to']['name'], 'helper')
        self.assertEqual(outgoing[0]['fromRanges'][0]['start']['line'], 4)

    def test_type_hierarchy_shows_the_structs_a_type_is_held_by(self):
        path = self.write('main.vnt', '''\
struct Inner:
    hp: i32

struct Outer:
    inner: Inner

struct Holder:
    p: ptr<Outer>
''')
        uri = self.open(path)
        items = self.request('textDocument/prepareTypeHierarchy', {
            'textDocument': {'uri': uri},
            'position': {'line': 0, 'character': 8},
        })[0]['result']
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['name'], 'Inner')
        self.assertEqual(items[0]['kind'], 23)      # Struct

        supertypes = self.request('typeHierarchy/supertypes', {
            'item': items[0],
        })[0]['result']
        self.assertEqual([entry['type']['name'] for entry in supertypes],
                         ['Outer'])

        subtypes = self.request('typeHierarchy/subtypes', {
            'item': items[0],
        })[0]['result']
        self.assertEqual(subtypes, [])

    def test_type_hierarchy_ignores_a_pointer_field(self):
        path = self.write('main.vnt', '''\
struct Inner:
    hp: i32

struct Holder:
    p: ptr<Inner>
''')
        uri = self.open(path)
        items = self.request('textDocument/prepareTypeHierarchy', {
            'textDocument': {'uri': uri},
            'position': {'line': 0, 'character': 8},
        })[0]['result']
        supertypes = self.request('typeHierarchy/supertypes', {
            'item': items[0],
        })[0]['result']
        self.assertEqual(supertypes, [])

    def test_document_highlight_marks_a_local_and_its_uses(self):
        path = self.write('main.vnt', '''\
func main() -> i32:
    let total: i32 = 0
    if total > 0:
        return total
    return total
''')
        uri = self.open(path)
        result = self.request('textDocument/documentHighlight', {
            'textDocument': {'uri': uri},
            'position': {'line': 2, 'character': 8},
        })[0]['result']
        self.assertEqual(len(result), 4)
        # The declaration is text; each use is a read.
        kinds = {h['range']['start']['line']: h['kind'] for h in result}
        self.assertEqual(kinds, {1: 1, 2: 2, 3: 2, 4: 2})

    def test_document_highlight_does_not_mix_shadowing_names(self):
        path = self.write('main.vnt', '''\
func main() -> i32:
    let x: i32 = 1
    if x > 0:
        let x: i32 = 2
        return x
    return x
''')
        uri = self.open(path)
        inner_pos = (4, 15)  # the second 'x'
        result = self.request('textDocument/documentHighlight', {
            'textDocument': {'uri': uri},
            'position': {'line': inner_pos[0], 'character': inner_pos[1]},
        })[0]['result']
        lines = [h['range']['start']['line'] for h in result]
        self.assertEqual(sorted(lines), [3, 4])

    def test_document_highlight_falls_back_to_text_for_unknown_word(self):
        path = self.write('main.vnt', 'func main() -> void:\n'
                          '    return nope or NOPE\n')
        uri = self.open(path)
        result = self.request('textDocument/documentHighlight', {
            'textDocument': {'uri': uri},
            'position': {'line': 1, 'character': 11},
        })[0]['result']
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['range']['start']['line'], 1)

    def test_document_highlight_tracks_a_struct_field(self):
        path = self.write('main.vnt', '''\
struct Enemy:
    hp: i32

func heal(e: Enemy) -> void:
    e.hp = e.hp + 1
''')
        uri = self.open(path)
        result = self.request('textDocument/documentHighlight', {
            'textDocument': {'uri': uri},
            'position': {'line': 1, 'character': 5},
        })[0]['result']
        self.assertEqual(len(result), 3)
        self.assertEqual(
            sorted(h['range']['start']['line'] for h in result),
            [1, 4, 4])

    def test_document_highlight_highlights_a_function(self):
        path = self.write('main.vnt', '''\
func helper() -> i32:
    return 1

func main() -> i32:
    return helper() + helper()
''')
        uri = self.open(path)
        result = self.request('textDocument/documentHighlight', {
            'textDocument': {'uri': uri},
            'position': {'line': 0, 'character': 7},
        })[0]['result']
        self.assertEqual(len(result), 3)
        self.assertEqual(
            sorted(h['range']['start']['line'] for h in result),
            [0, 4, 4])

    def test_document_link_points_at_an_imported_file(self):
        dep = self.write('dep.vnt', 'func helper() -> i32:\n    return 1\n')
        path = self.write('main.vnt', 'import "dep.vnt"\n\n'
                          'func main() -> i32:\n    return helper()\n')
        uri = self.open(path)
        links = self.request('textDocument/documentLink', {
            'textDocument': {'uri': uri},
        })[0]['result']
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0]['target'], path_to_uri(dep))
        self.assertEqual(links[0]['range']['start'],
                         {'line': 0, 'character': 7})
        self.assertEqual(links[0]['range']['end'],
                         {'line': 0, 'character': 16})

    def test_document_link_covers_an_aliased_import(self):
        dep = self.write('dep.vnt', 'func helper() -> i32:\n    return 1\n')
        path = self.write('main.vnt', 'import "dep.vnt" as util\n\n'
                          'func main() -> i32:\n    return util.helper()\n')
        uri = self.open(path)
        links = self.request('textDocument/documentLink', {
            'textDocument': {'uri': uri},
        })[0]['result']
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0]['target'], path_to_uri(dep))

    def test_document_link_marks_an_unresolved_import(self):
        path = self.write('main.vnt', 'import "missing.vnt"\n')
        uri = self.open(path)
        links = self.request('textDocument/documentLink', {
            'textDocument': {'uri': uri},
        })[0]['result']
        self.assertEqual(len(links), 1)
        self.assertNotIn('target', links[0])
        self.assertIn('unresolved', links[0]['tooltip'])

    def test_folding_range_folds_a_function_body(self):
        path = self.write('main.vnt', '''\
func main() -> void:
    let a = 1
    let b = 2
''')
        uri = self.open(path)
        ranges = self.request('textDocument/foldingRange', {
            'textDocument': {'uri': uri},
        })[0]['result']
        self.assertEqual([(r['startLine'], r['endLine']) for r in ranges],
                         [(0, 2)])

    def test_folding_range_nests_blocks(self):
        path = self.write('main.vnt', '''\
func main() -> void:
    if true:
        print_str("a")
    print_str("b")
''')
        uri = self.open(path)
        ranges = self.request('textDocument/foldingRange', {
            'textDocument': {'uri': uri},
        })[0]['result']
        self.assertEqual(
            {(r['startLine'], r['endLine']) for r in ranges},
            {(0, 3), (1, 2)})

    def test_folding_range_covers_a_struct_body(self):
        path = self.write('main.vnt', '''\
struct Enemy:
    hp: i32
    name: str
''')
        uri = self.open(path)
        ranges = self.request('textDocument/foldingRange', {
            'textDocument': {'uri': uri},
        })[0]['result']
        self.assertEqual([(r['startLine'], r['endLine']) for r in ranges],
                         [(0, 2)])

    def test_folding_range_folds_comments_and_imports(self):
        path = self.write('main.vnt', '''\
import "a.vnt"
import "b.vnt"

# one
# two
# three

func main() -> void:
    return
''')
        uri = self.open(path)
        ranges = self.request('textDocument/foldingRange', {
            'textDocument': {'uri': uri},
        })[0]['result']
        got = {(r['startLine'], r['endLine'], r.get('kind', ''))
               for r in ranges}
        self.assertIn((0, 1, 'imports'), got)
        self.assertIn((3, 5, 'comment'), got)
        self.assertIn((7, 8, ''), got)

    def test_folding_range_trims_blank_lines(self):
        path = self.write('main.vnt', '''\
func main() -> void:
    let a = 1

    let b = 2

func other() -> void:
    return
''')
        uri = self.open(path)
        ranges = self.request('textDocument/foldingRange', {
            'textDocument': {'uri': uri},
        })[0]['result']
        self.assertEqual(
            {(r['startLine'], r['endLine']) for r in ranges},
            {(0, 3), (5, 6)})

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
