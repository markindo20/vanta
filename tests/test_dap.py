import io
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest

from compiler.codegen_cpp import CodeGen
from compiler.dap import (
    DapAdapter,
    GdbError,
    GdbMi,
    MiRecord,
    _frame_name,
    _hit_condition_matches,
    _internal_function_name,
    _interpolate_log_message,
    _is_truthy,
    _mi_quote,
    _translate_vanta_expression,
    _value_type_problem,
    _vanta_type,
    find_gdb,
    parse_mi_line,
    read_dap_message,
    write_dap_message,
)
from compiler.driver import (
    build_debug,
    find_debug_compiler,
    mutable_locals,
)


def _messages(data: bytes):
    stream = io.BytesIO(data)
    out = []
    while True:
        message = read_dap_message(stream)
        if message is None:
            return out
        out.append(message)


def _debug_toolchain_available():
    name, path = find_debug_compiler()
    if path is None:
        return False
    return os.path.basename(name).lower() not in ('cl', 'clang-cl')


class DapFramingTests(unittest.TestCase):
    def test_round_trip(self):
        buffer = io.BytesIO()
        write_dap_message(buffer, {'seq': 1, 'type': 'event',
                                   'event': 'output',
                                   'body': {'category': 'stdout',
                                            'output': 'hello\n'}})
        messages = _messages(buffer.getvalue())
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]['event'], 'output')
        self.assertEqual(messages[0]['body']['output'], 'hello\n')

    def test_multiple_messages(self):
        buffer = io.BytesIO()
        write_dap_message(buffer, {'seq': 1, 'type': 'response'})
        write_dap_message(buffer, {'seq': 2, 'type': 'event', 'event': 'x'})
        messages = _messages(buffer.getvalue())
        self.assertEqual([m['seq'] for m in messages], [1, 2])


class MiParserTests(unittest.TestCase):
    def test_result_tuple(self):
        record = parse_mi_line(
            '7^done,bkpt={number="3",line="12",file="C:/work/main.vnt"}')
        self.assertIsInstance(record, MiRecord)
        self.assertEqual(record.token, '7')
        self.assertEqual(record.class_, 'done')
        self.assertEqual(record.results['bkpt']['number'], '3')
        self.assertEqual(record.results['bkpt']['line'], '12')

    def test_stopped_frame(self):
        record = parse_mi_line(
            '*stopped,reason="breakpoint-hit",bkptno="2",thread-id="1",'
            'frame={level="0",func="vanta_user::fn_main()",'
            'fullname="C:/work/game.vnt",line="9"},stopped-threads="all"')
        self.assertEqual(record.class_, 'stopped')
        frame = record.results['frame']
        self.assertEqual(frame['func'], 'vanta_user::fn_main()')
        self.assertEqual(record.results['thread-id'], '1')

    def test_lists_of_results(self):
        record = parse_mi_line(
            '^done,stack=[frame={level="0",func="main",line="2"},'
            'frame={level="1",func="start",line="8"}]')
        self.assertEqual(len(record.results['stack']), 2)
        self.assertEqual(record.results['stack'][1]['frame']['func'], 'start')

    def test_nested_lists(self):
        record = parse_mi_line(
            '=library-loaded,id="x",ranges=[{from="0x1",to="0x2"},'
            '{from="0x3",to="0x4"}]')
        self.assertEqual(record.class_, 'library-loaded')
        self.assertEqual(record.results['ranges'][1]['to'], '0x4')

    def test_stream_escapes(self):
        record = parse_mi_line(r'~"line one\nline \"two\"\\tail"')
        self.assertEqual(record.sign, '~')
        self.assertEqual(record.text, 'line one\nline "two"\\tail')

    def test_error_and_exit(self):
        error = parse_mi_line('4^error,msg="No symbol \\"x\\" in context."')
        self.assertEqual(error.class_, 'error')
        self.assertIn('No symbol', error.results['msg'])
        exit_record = parse_mi_line('9^exit')
        self.assertEqual(exit_record.class_, 'exit')

    def test_plain_output(self):
        record = parse_mi_line('42')
        self.assertEqual(record.sign, 'plain')
        self.assertEqual(record.text, '42')

    def test_quote(self):
        self.assertEqual(_mi_quote(r'C:\work\a b.vnt'),
                         r'"C:\\work\\a b.vnt"')


class AdapterFormattingTests(unittest.TestCase):
    def test_initialize(self):
        writer = io.BytesIO()
        adapter = DapAdapter(io.BytesIO(), writer)
        request = {'seq': 1, 'type': 'request', 'command': 'initialize'}
        adapter._request_initialize(request, {'clientID': 'test'})
        messages = _messages(writer.getvalue())
        self.assertEqual(messages[0]['command'], 'initialize')
        self.assertTrue(messages[0]['success'])
        self.assertTrue(messages[0]['body']['supportsConfigurationDoneRequest'])
        self.assertEqual(messages[1]['event'], 'initialized')

    def test_frame_names(self):
        self.assertEqual(_frame_name('vanta_user::fn_main()'), 'main')
        self.assertEqual(_frame_name('vanta::print_i32()'), 'print_i32')
        self.assertEqual(_frame_name('vanta_user::fn_add(int, int)'), 'add')
        self.assertEqual(_frame_name('fn_add'), 'add')
        self.assertEqual(_frame_name('vanta_user::fn_vanta_m_math__add()'),
                         'math.add')

    def test_vanta_types(self):
        self.assertEqual(_vanta_type('int32_t'), 'i32')
        self.assertEqual(_vanta_type('vanta::List<int32_t>'), 'List<i32>')
        self.assertEqual(_vanta_type('float'), 'f32')
        self.assertEqual(_vanta_type('vanta::Str'), 'str')
        self.assertEqual(_vanta_type('vanta::StrBuilder'), 'StrBuilder')

    def test_locals_hide_arguments(self):
        adapter = DapAdapter(io.BytesIO(), io.BytesIO())
        variables = adapter._format_variables([
            {'name': 'v_a', 'arg': '1', 'type': 'int32_t', 'value': '2'},
            {'name': 'v_c', 'arg': '0', 'type': 'int32_t', 'value': '5'},
            {'name': '__it_1', 'arg': '0', 'type': 'int', 'value': '0'},
        ], include_arguments=False)
        self.assertEqual([v['name'] for v in variables], ['c'])
        self.assertEqual(variables[0]['type'], 'i32')


class DebugBuildTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.mkdtemp(prefix='vanta-dap-test-')
        self.source = os.path.join(self.tempdir, 'main.vnt')
        with open(self.source, 'w', encoding='utf-8', newline='\n') as f:
            f.write('func add(a: i32, b: i32) -> i32:\n'
                    '    let c = a + b\n'
                    '    return c\n'
                    '\n'
                    'func main() -> void:\n'
                    '    let x = add(2, 3)\n'
                    '    print_i32(x)\n')

    def tearDown(self):
        shutil.rmtree(self.tempdir, ignore_errors=True)

    @unittest.skipIf(_debug_toolchain_available() is False, 'no GCC/Clang compiler')
    def test_debug_build_has_source_markers(self):
        build = build_debug(self.source, output=os.path.join(self.tempdir, 'prog'))
        try:
            self.assertTrue(os.path.isfile(build['exe']))
            with open(build['cpp'], 'r', encoding='utf-8') as f:
                generated = f.read()
            absolute = os.path.abspath(self.source).replace('\\', '/')
            self.assertIn(f'#line 1 "{absolute}"', generated)
            self.assertIn(f'#line 6 "{absolute}"', generated)
            self.assertIn('#line 1 "', generated)
        finally:
            shutil.rmtree(build['tempdir'], ignore_errors=True)

    @unittest.skipIf(_debug_toolchain_available() is False, 'no GCC/Clang compiler')
    def test_normal_codegen_has_no_source_markers(self):
        from compiler.driver import _frontend_only
        program, tc = _frontend_only(self.source)
        generated = CodeGen(program, tc).generate()
        self.assertNotIn('#line', generated)


class DebuggerIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.gdb = find_gdb()
        except GdbError:
            raise unittest.SkipTest('no working GDB')
        if _debug_toolchain_available() is False:
            raise unittest.SkipTest('no GCC/Clang compiler')

    def test_breakpoint_and_source_mapping(self):
        tempdir = tempfile.mkdtemp(prefix='vanta-gdb-test-')
        source = os.path.join(tempdir, 'main.vnt')
        with open(source, 'w', encoding='utf-8', newline='\n') as f:
            f.write('func main() -> void:\n'
                    '    let x = 41\n'
                    '    let y = x + 1\n'
                    '    print_i32(y)\n')
        build = build_debug(source)
        gdb = None
        try:
            gdb = GdbMi(self.gdb, build['exe'], env=build['env'], cwd=tempdir)
            gdb.command('-gdb-set pagination off')
            gdb.command('-gdb-set confirm off')
            gdb.command('-gdb-set mi-async on')
            location = os.path.abspath(source).replace('\\', '/') + ':3'
            gdb.command('-break-insert -f ' + _mi_quote(location))
            gdb.run_command('-exec-run')
            stopped = None
            deadline = time.time() + 20
            while time.time() < deadline:
                try:
                    record = gdb.events.get(timeout=1)
                except queue.Empty:
                    continue
                if record.sign == '*' and record.class_ == 'stopped':
                    stopped = record
                    break
            self.assertIsNotNone(stopped)
            self.assertEqual(stopped.results['reason'], 'breakpoint-hit')
            frame = stopped.results['frame']
            self.assertEqual(os.path.normcase(frame['fullname']),
                             os.path.normcase(os.path.abspath(source)))
            self.assertEqual(frame['line'], '3')
        finally:
            if gdb is not None:
                gdb.close()
            shutil.rmtree(build['tempdir'], ignore_errors=True)
            shutil.rmtree(tempdir, ignore_errors=True)


class _DapSessionTestCase(unittest.TestCase):
    """Shared plumbing for tests that drive a real adapter process."""

    PROGRAM = ('func main() -> void:\n'
               '    let x = 41\n'
               '    let y = x + 1\n'
               '    print_i32(y)\n')

    @classmethod
    def setUpClass(cls):
        try:
            find_gdb()
        except GdbError:
            raise unittest.SkipTest('no working GDB')
        if not _debug_toolchain_available():
            raise unittest.SkipTest('no GCC/Clang compiler')

    def setUp(self):
        self.tempdir = tempfile.mkdtemp(prefix='vanta-dap-stdio-')
        self.source = os.path.join(self.tempdir, 'main.vnt')
        with open(self.source, 'w', encoding='utf-8', newline='\n') as f:
            f.write(self.PROGRAM)
        self.process = None
        self.messages: queue.Queue = queue.Queue()
        self.seq = 0
        self.received: list = []

    def tearDown(self):
        if self.process is not None and self.process.poll() is None:
            try:
                self.send('disconnect', {'terminateDebuggee': True})
                self.expect(lambda m: m.get('type') == 'response' and
                            m.get('command') == 'disconnect', timeout=15)
            except Exception:
                pass
            try:
                self.process.wait(timeout=10)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
        if self.process is not None:
            try:
                self.process.wait(timeout=10)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
            for stream in (self.process.stdin, self.process.stdout,
                           self.process.stderr):
                try:
                    if stream is not None:
                        stream.close()
                except Exception:
                    pass
        shutil.rmtree(self.tempdir, ignore_errors=True)

    def _read_loop(self):
        while True:
            try:
                message = read_dap_message(self.process.stdout)
            except Exception:
                message = None
            self.messages.put(message)
            if message is None:
                return

    def start(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.process = subprocess.Popen(
            [sys.executable, '-m', 'compiler', 'dap'],
            cwd=root,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
        threading.Thread(target=self._read_loop, daemon=True).start()

    def send(self, command, arguments=None):
        self.seq += 1
        message = {'seq': self.seq, 'type': 'request', 'command': command}
        if arguments is not None:
            message['arguments'] = arguments
        write_dap_message(self.process.stdin, message)
        return self.seq

    def _adapter_stderr(self) -> str:
        """Whatever the adapter process wrote to stderr, for diagnostics."""
        if self.process is None or self.process.stderr is None:
            return ''
        try:
            self.process.stderr.flush()
        except Exception:
            pass
        return '(unavailable)'

    def expect(self, predicate, timeout=30):
        seen = []
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                message = self.messages.get(timeout=max(0.1, deadline - time.time()))
            except queue.Empty:
                continue
            if message is None:
                self.fail(f'adapter exited; messages={seen!r}; '
                          f'stderr={self._adapter_stderr()}')
            seen.append(message)
            self.received.append(message)
            if predicate(message):
                return message
        self.fail(f'timed out; messages={seen!r}')

    def initialize(self, capabilities=None):
        arguments = {'clientID': 'test'}
        if capabilities is not None:
            arguments['capabilities'] = capabilities
        self.start()
        self.send('initialize', arguments)
        response = self.expect(
            lambda m: m.get('type') == 'response' and
            m.get('command') == 'initialize')
        self.assertTrue(response['success'], response)
        self.expect(lambda m: m.get('event') == 'initialized')

    def launch(self, **extra):
        arguments = {'program': self.source, 'cwd': self.tempdir}
        arguments.update(extra)
        self.send('launch', arguments)
        response = self.expect(
            lambda m: m.get('type') == 'response' and
            m.get('command') == 'launch', timeout=90)
        self.assertTrue(response['success'], response)

    def set_breakpoints(self, breakpoints, source=None):
        self.send('setBreakpoints', {
            'source': {'name': 'main.vnt', 'path': source or self.source},
            'breakpoints': breakpoints,
        })
        response = self.expect(
            lambda m: m.get('type') == 'response' and
            m.get('command') == 'setBreakpoints')
        self.assertTrue(response['success'], response)
        return response

    def configuration_done(self):
        self.send('configurationDone')
        response = self.expect(
            lambda m: m.get('type') == 'response' and
            m.get('command') == 'configurationDone')
        self.assertTrue(response['success'], response)

    def outputs(self, category=None):
        out = []
        for message in self.received:
            if message.get('event') != 'output':
                continue
            body = message.get('body', {})
            if category is None or body.get('category') == category:
                out.append(body.get('output', ''))
        return ''.join(out)

    def stopped_event(self, timeout=40):
        return self.expect(lambda m: m.get('event') == 'stopped',
                            timeout=timeout)

    def terminated_event(self, timeout=40):
        return self.expect(lambda m: m.get('event') == 'terminated',
                            timeout=timeout)


class ExpressionTranslationTests(unittest.TestCase):
    def test_locals_get_the_generated_prefix(self):
        self.assertEqual(_translate_vanta_expression('x > 5'), 'v_x > 5')
        self.assertEqual(_translate_vanta_expression('x > 5 && y == 2'),
                         'v_x > 5 && v_y == 2')
        self.assertEqual(_translate_vanta_expression('total + 1'),
                         'v_total + 1')

    def test_existing_prefix_and_keywords_are_kept(self):
        self.assertEqual(_translate_vanta_expression('v_x > 5'), 'v_x > 5')
        self.assertEqual(_translate_vanta_expression('true && false'),
                         'true && false')
        self.assertEqual(_translate_vanta_expression('sizeof(int) == 4'),
                         'sizeof(int) == 4')

    def test_string_literals_are_untouched(self):
        self.assertEqual(_translate_vanta_expression('"hello world"'),
                         '"hello world"')
        self.assertEqual(_translate_vanta_expression('x == "total"'),
                         'v_x == "total"')

    def test_len_is_rewritten_to_the_inlined_field(self):
        self.assertEqual(_translate_vanta_expression('len(xs) == 3'),
                         '(v_xs).h->len == 3')

    def test_empty_expression(self):
        self.assertEqual(_translate_vanta_expression(''), '')


class HitConditionTests(unittest.TestCase):
    def test_plain_count(self):
        self.assertTrue(_hit_condition_matches('3', 3))
        self.assertFalse(_hit_condition_matches('3', 2))

    def test_comparison_forms(self):
        self.assertTrue(_hit_condition_matches('== 3', 3))
        self.assertTrue(_hit_condition_matches('>= 2', 3))
        self.assertTrue(_hit_condition_matches('<= 3', 3))
        self.assertTrue(_hit_condition_matches('> 2', 3))
        self.assertTrue(_hit_condition_matches('< 4', 3))
        self.assertTrue(_hit_condition_matches('!= 2', 3))

    def test_every_nth_hit(self):
        self.assertTrue(_hit_condition_matches('% 2 == 0', 4))
        self.assertFalse(_hit_condition_matches('% 2 == 0', 3))

    def test_unsupported_conditions(self):
        self.assertIsNone(_hit_condition_matches('nonsense', 1))
        self.assertIsNone(_hit_condition_matches('', 1))
        self.assertIsNone(_hit_condition_matches(None, 1))


class LogMessageTests(unittest.TestCase):
    def test_interpolation(self):
        text = _interpolate_log_message(
            'i is {i}', lambda expression: ('7', True))
        self.assertEqual(text, 'i is 7')

    def test_unknown_expression_keeps_the_placeholder(self):
        text = _interpolate_log_message(
            'i is {i}', lambda expression: ('', False))
        self.assertEqual(text, 'i is {i}')

    def test_text_without_placeholders(self):
        self.assertEqual(
            _interpolate_log_message('plain', lambda e: ('', False)),
            'plain')


class TruthinessTests(unittest.TestCase):
    def test_values(self):
        self.assertFalse(_is_truthy('0'))
        self.assertFalse(_is_truthy('false'))
        self.assertFalse(_is_truthy(''))
        self.assertTrue(_is_truthy('1'))
        self.assertTrue(_is_truthy('41'))


class ValueTypeTests(unittest.TestCase):
    def test_number_into_number(self):
        self.assertIsNone(_value_type_problem('42', 'i32'))
        self.assertIsNone(_value_type_problem('1.5', 'f32'))
        self.assertIsNone(_value_type_problem('1.5', 'f64'))

    def test_string_only_into_str(self):
        self.assertIsNone(_value_type_problem('"hi"', 'str'))
        self.assertIsNotNone(_value_type_problem('"hi"', 'i32'))

    def test_boolean_only_into_bool(self):
        self.assertIsNone(_value_type_problem('true', 'bool'))
        self.assertIsNotNone(_value_type_problem('true', 'i32'))

    def test_number_is_not_stored_in_a_string(self):
        self.assertIsNotNone(_value_type_problem('42', 'str'))
        self.assertIsNotNone(_value_type_problem('1.5', 'i32'))

    def test_unknown_type_is_allowed(self):
        self.assertIsNone(_value_type_problem('42', ''))
        self.assertIsNone(_value_type_problem('anything', ''))


class InternalNameTests(unittest.TestCase):
    def test_names(self):
        self.assertEqual(_internal_function_name('vanta_user::fn_main'), 'main')
        self.assertEqual(
            _internal_function_name('vanta_user::fn_vanta_m_math__add()'),
            'vanta_m_math__add')
        self.assertEqual(_internal_function_name('add'), 'add')


class MutableLocalTests(unittest.TestCase):
    def test_only_mut_bindings_are_mutable(self):
        from compiler.driver import _frontend_only
        import tempfile
        import os
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'main.vnt')
            with open(path, 'w', encoding='utf-8', newline='\n') as f:
                f.write('func main() -> void:\n'
                        '    let fixed = 1\n'
                        '    mut counter = 0\n'
                        '    while counter < 3:\n'
                        '        counter = counter + 1\n')
            program, _tc = _frontend_only(path)
            table = mutable_locals(program)
            self.assertIn('main', table)
            self.assertEqual(table['main'], {'counter'})


class SourceLineTests(unittest.TestCase):
    def test_source_lines_cover_every_statement(self):
        from compiler.driver import _frontend_only, source_lines
        import tempfile
        import os
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'main.vnt')
            with open(path, 'w', encoding='utf-8', newline='\n') as f:
                f.write('func main() -> void:\n'
                        '    let fixed = 1\n'
                        '    mut counter = 0\n'
                        '    while counter < 3:\n'
                        '        counter = counter + 1\n'
                        '    print_i32(fixed)\n')
            program, _tc = _frontend_only(path)
            table = source_lines(program)
            key = os.path.normcase(os.path.abspath(path))
            self.assertEqual(table['files'][key], [2, 3, 4, 5, 6])
            self.assertEqual(table['functions']['main'][key],
                             [2, 3, 4, 5, 6])

    def test_layouts_describe_structs_and_enums(self):
        from compiler.driver import _frontend_only, program_layouts
        import tempfile
        import os
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'main.vnt')
            with open(path, 'w', encoding='utf-8', newline='\n') as f:
                f.write('struct Player:\n'
                        '    hp: i32\n'
                        '    name: str\n'
                        '\n'
                        'enum State:\n'
                        '    Idle\n'
                        '    Playing\n'
                        '\n'
                        'func main() -> void:\n'
                        '    let p = Player(hp: 41, name: "hero")\n'
                        '    print_i32(p.hp)\n')
            program, tc = _frontend_only(path)
            layouts = program_layouts(tc)
            self.assertIn('Player', layouts['structs'])
            self.assertEqual([name for name, _ in layouts['structs']['Player']],
                             ['hp', 'name'])
            self.assertIn('State', layouts['enums'])
            self.assertEqual(layouts['enums']['State'],
                             {'Idle': 0, 'Playing': 1})


class DapStdioIntegrationTests(_DapSessionTestCase):
    """Exercise the real adapter process, not just its helpers."""

    def test_launch_breakpoint_locals_and_exit(self):
        self.start()
        self.send('initialize', {'clientID': 'test'})
        response = self.expect(
            lambda m: m.get('type') == 'response' and
            m.get('command') == 'initialize')
        self.assertTrue(response['success'], response)
        self.expect(lambda m: m.get('event') == 'initialized')

        self.send('launch', {'program': self.source, 'cwd': self.tempdir})
        response = self.expect(
            lambda m: m.get('type') == 'response' and
            m.get('command') == 'launch', timeout=60)
        self.assertTrue(response['success'], response)

        self.send('setBreakpoints', {
            'source': {'name': 'main.vnt', 'path': self.source},
            'breakpoints': [{'line': 3}],
        })
        response = self.expect(
            lambda m: m.get('type') == 'response' and
            m.get('command') == 'setBreakpoints')
        self.assertTrue(response['success'], response)
        self.assertTrue(response['body']['breakpoints'][0]['verified'],
                        response)

        self.send('configurationDone')
        response = self.expect(
            lambda m: m.get('type') == 'response' and
            m.get('command') == 'configurationDone')
        self.assertTrue(response['success'], response)
        stopped = self.expect(lambda m: m.get('event') == 'stopped')
        self.assertEqual(stopped['body']['reason'], 'breakpoint')

        self.send('stackTrace', {'threadId': 1})
        response = self.expect(
            lambda m: m.get('type') == 'response' and
            m.get('command') == 'stackTrace')
        frame = response['body']['stackFrames'][0]
        self.assertEqual(frame['name'], 'main')
        self.assertEqual(frame['line'], 3)
        self.assertEqual(os.path.normcase(frame['source']['path']),
                         os.path.normcase(os.path.abspath(self.source)))

        self.send('scopes', {'frameId': 0, 'threadId': 1})
        response = self.expect(
            lambda m: m.get('type') == 'response' and
            m.get('command') == 'scopes')
        locals_ref = next(scope['variablesReference']
                          for scope in response['body']['scopes']
                          if scope['name'] == 'Locals')
        self.send('variables', {'variablesReference': locals_ref})
        response = self.expect(
            lambda m: m.get('type') == 'response' and
            m.get('command') == 'variables')
        values = {v['name']: v['value'] for v in response['body']['variables']}
        self.assertEqual(values.get('x'), '41')

        self.send('continue', {'threadId': 1})
        self.expect(lambda m: m.get('type') == 'response' and
                    m.get('command') == 'continue')
        output = []
        terminated = False
        while not terminated:
            message = self.expect(
                lambda m: m.get('event') in ('output', 'terminated'), timeout=30)
            if message.get('event') == 'output':
                output.append(message.get('body', {}).get('output', ''))
            else:
                terminated = True
        self.assertIn('42', ''.join(output))

        self.send('disconnect', {'terminateDebuggee': True})
        self.expect(lambda m: m.get('type') == 'response' and
                    m.get('command') == 'disconnect', timeout=15)
        self.process.wait(timeout=15)
        self.assertEqual(self.process.returncode, 0)


class DapFeatureIntegrationTests(_DapSessionTestCase):
    """Conditional breakpoints, logpoints, watches, and restart."""

    PROGRAM = ('func main() -> void:\n'
               '    let x = 41\n'
               '    mut i = 0\n'
               '    mut total = 0\n'
               '    while i < 3:\n'
               '        total = total + i\n'
               '        i = i + 1\n'
               '    print_i32(total)\n')

    def test_logpoint_runs_without_stopping(self):
        self.initialize()
        self.launch()
        self.set_breakpoints([{'line': 6, 'logMessage': 'i is {i}'}])
        self.configuration_done()
        self.terminated_event()
        console = self.outputs('console')
        self.assertIn('i is 0', console)
        self.assertIn('i is 1', console)
        self.assertIn('i is 2', console)
        self.assertIn('3', self.outputs('stdout'))
        self.assertFalse([m for m in self.received
                          if m.get('event') == 'stopped'])

    def test_conditional_breakpoint_skips_the_stop(self):
        self.initialize()
        self.launch()
        self.set_breakpoints([{'line': 6, 'condition': 'x > 100'}])
        self.configuration_done()
        self.terminated_event()
        self.assertFalse([m for m in self.received
                          if m.get('event') == 'stopped'])
        self.assertIn('3', self.outputs('stdout'))

    def test_hit_condition_stops_on_the_second_hit(self):
        self.initialize()
        self.launch()
        self.set_breakpoints([{'line': 6, 'hitCondition': '2'}])
        self.configuration_done()
        self.stopped_event()
        self.send('scopes', {'frameId': 0, 'threadId': 1})
        response = self.expect(
            lambda m: m.get('type') == 'response' and
            m.get('command') == 'scopes')
        locals_ref = next(scope['variablesReference']
                          for scope in response['body']['scopes']
                          if scope['name'] == 'Locals')
        self.send('variables', {'variablesReference': locals_ref})
        response = self.expect(
            lambda m: m.get('type') == 'response' and
            m.get('command') == 'variables')
        values = {v['name']: v['value']
                  for v in response['body']['variables']}
        self.assertEqual(values.get('i'), '1')

    def test_function_breakpoint_stops_in_main(self):
        self.initialize()
        self.launch()
        self.send('setFunctionBreakpoints', {'breakpoints': [{'name': 'main'}]})
        response = self.expect(
            lambda m: m.get('type') == 'response' and
            m.get('command') == 'setFunctionBreakpoints')
        self.assertTrue(response['success'], response)
        self.assertTrue(response['body']['breakpoints'][0]['verified'],
                        response)
        self.configuration_done()
        self.stopped_event()
        self.send('stackTrace', {'threadId': 1})
        response = self.expect(
            lambda m: m.get('type') == 'response' and
            m.get('command') == 'stackTrace')
        self.assertEqual(response['body']['stackFrames'][0]['name'], 'main')

    def test_watch_expression_appears_in_the_watch_scope(self):
        self.initialize()
        self.launch()
        self.set_breakpoints([{'line': 6}])
        self.configuration_done()
        self.stopped_event()
        self.send('setExpression', {'expression': 'total', 'value': 'total',
                                    'context': 'watch', 'frameId': 0})
        response = self.expect(
            lambda m: m.get('type') == 'response' and
            m.get('command') == 'setExpression')
        self.assertTrue(response['success'], response)
        self.send('scopes', {'frameId': 0, 'threadId': 1})
        response = self.expect(
            lambda m: m.get('type') == 'response' and
            m.get('command') == 'scopes')
        watch = [scope for scope in response['body']['scopes']
                 if scope['name'] == 'Watch']
        self.assertTrue(watch, response)
        self.send('variables',
                  {'variablesReference': watch[0]['variablesReference']})
        response = self.expect(
            lambda m: m.get('type') == 'response' and
            m.get('command') == 'variables')
        values = {v['name']: v['value'] for v in response['body']['variables']}
        self.assertIn('total', values)

    def test_restart_rebuilds_and_stops_again(self):
        self.initialize()
        self.launch()
        self.set_breakpoints([{'line': 6}])
        self.configuration_done()
        self.stopped_event()
        self.send('restart', {})
        response = self.expect(
            lambda m: m.get('type') == 'response' and
            m.get('command') == 'restart', timeout=90)
        self.assertTrue(response['success'], response)
        self.stopped_event()
        self.send('stackTrace', {'threadId': 1})
        response = self.expect(
            lambda m: m.get('type') == 'response' and
            m.get('command') == 'stackTrace')
        self.assertEqual(response['body']['stackFrames'][0]['line'], 6)


class DapAttachIntegrationTests(_DapSessionTestCase):
    """Attaching to a program that is already running."""

    @classmethod
    def setUpClass(cls):
        try:
            find_gdb()
        except GdbError:
            raise unittest.SkipTest('no working GDB')
        name, path = find_debug_compiler()
        if path is None or os.path.basename(name).lower() in ('cl', 'clang-cl'):
            raise unittest.SkipTest('no GCC/Clang compiler')

    def setUp(self):
        super().setUp()
        self.tempdir = tempfile.mkdtemp(prefix='vanta-dap-attach-')
        self.source = os.path.join(self.tempdir, 'main.cpp')
        with open(self.source, 'w', encoding='utf-8', newline='\n') as f:
            f.write('#include <chrono>\n'
                    '#include <thread>\n'
                    'int main() {\n'
                    '    int total = 0;\n'
                    '    for (int i = 0; i < 200; i++) {\n'
                    '        total = total + i;\n'
                    '        std::this_thread::sleep_for('
                    'std::chrono::milliseconds(20));\n'
                    '    }\n'
                    '    return total;\n'
                    '}\n')
        self.executable = os.path.join(self.tempdir, 'target.exe')
        name, path = find_debug_compiler()
        result = subprocess.run(
            [path, '-O0', '-g3', self.source, '-o', self.executable],
            capture_output=True, text=True)
        if result.returncode != 0 or not os.path.isfile(self.executable):
            self.skipTest('could not build the attach target')
        self.target = subprocess.Popen(
            [self.executable], cwd=self.tempdir,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(0.5)

    def tearDown(self):
        # Detach first, then stop the program the session was watching.
        super().tearDown()
        if getattr(self, 'target', None) is not None:
            try:
                self.target.kill()
                self.target.wait(timeout=10)
            except Exception:
                pass
        if self.process is not None and self.process.poll() is None:
            try:
                self.process.kill()
                self.process.wait(timeout=10)
            except Exception:
                pass
        handle = getattr(self, 'stderr_file', None)
        if handle is not None:
            try:
                handle.close()
            except Exception:
                pass

    def start(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.stderr_path = os.path.join(self.tempdir, 'adapter-stderr.txt')
        self.stderr_file = open(self.stderr_path, 'wb')
        self.process = subprocess.Popen(
            [sys.executable, '-m', 'compiler', 'dap'],
            cwd=root,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self.stderr_file,
            bufsize=0,
        )
        threading.Thread(target=self._read_loop, daemon=True).start()

    def _adapter_stderr(self) -> str:
        path = getattr(self, 'stderr_path', None)
        if not path or not os.path.isfile(path):
            return '(no stderr file)'
        with open(path, 'rb') as f:
            return f.read().decode('utf-8', 'replace')[-2000:]

    def test_attach_watches_the_running_program(self):
        self.initialize()
        self.send('attach', {'processId': self.target.pid,
                             'executable': self.executable,
                             'cwd': self.tempdir})
        response = self.expect(
            lambda m: m.get('type') == 'response' and
            m.get('command') == 'attach', timeout=60)
        if not response['success']:
            self.skipTest(f'attach is not available here: '
                          f'{response.get("message", "")}')
        self.assertTrue(response['success'], response)
        self.send('setBreakpoints', {
            'source': {'name': 'main.cpp', 'path': self.source},
            'breakpoints': [{'line': 6}],
        })
        response = self.expect(
            lambda m: m.get('type') == 'response' and
            m.get('command') == 'setBreakpoints')
        self.assertTrue(response['success'], response)
        # The program is already running, so the session must not start it.
        self.send('configurationDone')
        response = self.expect(
            lambda m: m.get('type') == 'response' and
            m.get('command') == 'configurationDone')
        self.assertTrue(response['success'], response)
        time.sleep(0.5)
        self.assertIsNone(self.target.poll(),
                          'the attached program must keep running')
        self.send('continue', {'threadId': 1})
        self.expect(lambda m: m.get('type') == 'response' and
                    m.get('command') == 'continue')
        stopped = self.expect(lambda m: m.get('event') == 'stopped',
                               timeout=30)
        self.assertEqual(stopped['body']['reason'], 'breakpoint')
        self.send('stackTrace', {'threadId': 1})
        response = self.expect(
            lambda m: m.get('type') == 'response' and
            m.get('command') == 'stackTrace')
        frame = response['body']['stackFrames'][0]
        self.assertEqual(frame['line'], 6)


class DapNavigationIntegrationTests(_DapSessionTestCase):
    """Breakpoint locations, jump targets, and exception breakpoints."""

    PROGRAM = ('func main() -> void:\n'
               '    let fixed = 41\n'
               '    mut counter = 0\n'
               '    mut total = 0\n'
               '    while counter < 3:\n'
               '        total = total + counter\n'
               '        counter = counter + 1\n'
               '    print_i32(total)\n')

    def test_breakpoint_locations_list_the_statements(self):
        self.initialize()
        self.launch()
        self.send('breakpointLocations', {'source': {'path': self.source}})
        response = self.expect(
            lambda m: m.get('type') == 'response' and
            m.get('command') == 'breakpointLocations')
        lines = [b['line'] for b in response['body']['breakpoints']]
        self.assertEqual(lines, [2, 3, 4, 5, 6, 7, 8])

    def test_breakpoint_locations_for_one_line(self):
        self.initialize()
        self.launch()
        self.send('breakpointLocations', {'source': {'path': self.source},
                                          'line': 3})
        response = self.expect(
            lambda m: m.get('type') == 'response' and
            m.get('command') == 'breakpointLocations')
        self.assertEqual(response['body']['breakpoints'], [{'line': 3}])
        self.send('breakpointLocations', {'source': {'path': self.source},
                                          'line': 1})
        response = self.expect(
            lambda m: m.get('type') == 'response' and
            m.get('command') == 'breakpointLocations')
        self.assertEqual(response['body']['breakpoints'], [])

    def test_goto_targets_are_the_lines_of_the_function(self):
        self.initialize()
        self.launch()
        self.set_breakpoints([{'line': 6}])
        self.configuration_done()
        self.stopped_event()
        self.send('gotoTargets', {'source': {'path': self.source}})
        response = self.expect(
            lambda m: m.get('type') == 'response' and
            m.get('command') == 'gotoTargets')
        lines = [t['line'] for t in response['body']['targets']]
        self.assertIn(7, lines)
        self.assertNotIn(1, lines)

    def test_goto_continues_the_program(self):
        self.initialize()
        self.launch()
        self.set_breakpoints([{'line': 6}])
        self.configuration_done()
        self.stopped_event()
        self.send('goto', {'target': {'source': {'path': self.source},
                                      'line': 7}})
        response = self.expect(
            lambda m: m.get('type') == 'response' and
            m.get('command') == 'goto', timeout=60)
        self.assertTrue(response['success'], response)
        # The program keeps running and stops at the breakpoint again.
        stopped = self.stopped_event()
        self.assertEqual(stopped['body']['reason'], 'breakpoint')

    def test_goto_outside_the_function_is_refused(self):
        self.initialize()
        self.launch()
        self.set_breakpoints([{'line': 6}])
        self.configuration_done()
        self.stopped_event()
        self.send('goto', {'target': {'source': {'path': self.source},
                                      'line': 1}})
        response = self.expect(
            lambda m: m.get('type') == 'response' and
            m.get('command') == 'goto')
        self.assertFalse(response['success'], response)

    def test_exception_breakpoints_are_accepted(self):
        self.initialize()
        self.launch()
        self.send('setExceptionBreakpoints', {'filters': ['throw']})
        response = self.expect(
            lambda m: m.get('type') == 'response' and
            m.get('command') == 'setExceptionBreakpoints')
        self.assertTrue(response['success'], response)
        self.assertTrue(response['body']['breakpoints'][0]['verified'],
                        response)

    def test_the_current_instruction_can_be_disassembled(self):
        self.initialize()
        self.launch()
        self.set_breakpoints([{'line': 6}])
        self.configuration_done()
        self.stopped_event()
        self.send('stackTrace', {'threadId': 1})
        response = self.expect(
            lambda m: m.get('type') == 'response' and
            m.get('command') == 'stackTrace')
        address = response['body']['stackFrames'][0].get(
            'instructionPointerReference')
        self.assertTrue(address, response)
        self.send('disassemble', {'address': address, 'instructionCount': 4})
        response = self.expect(
            lambda m: m.get('type') == 'response' and
            m.get('command') == 'disassemble')
        self.assertTrue(response['success'], response)
        instructions = response['body']['instructions']
        self.assertTrue(instructions, response)
        self.assertLessEqual(len(instructions), 4)
        self.assertTrue(instructions[0]['instruction'])


class DapDataIntegrationTests(_DapSessionTestCase):
    """Structs expand and enums show their member."""

    PROGRAM = ('struct Player:\n'
               '    hp: i32\n'
               '    name: str\n'
               '\n'
               'enum State:\n'
               '    Idle\n'
               '    Playing\n'
               '\n'
               'func main() -> void:\n'
               '    let p = Player(hp: 41, name: "hero")\n'
               '    let s = State.Playing\n'
               '    print_i32(p.hp)\n')

    def locals(self):
        self.send('scopes', {'frameId': 0, 'threadId': 1})
        response = self.expect(
            lambda m: m.get('type') == 'response' and
            m.get('command') == 'scopes')
        reference = next(scope['variablesReference']
                         for scope in response['body']['scopes']
                         if scope['name'] == 'Locals')
        self.send('variables', {'variablesReference': reference})
        response = self.expect(
            lambda m: m.get('type') == 'response' and
            m.get('command') == 'variables')
        return {v['name']: v for v in response['body']['variables']}

    def test_a_struct_can_be_expanded(self):
        self.initialize()
        self.launch()
        self.set_breakpoints([{'line': 12}])
        self.configuration_done()
        self.stopped_event()
        variables = self.locals()
        player = variables['p']
        self.assertEqual(player['type'], 'Player')
        self.assertTrue(player['variablesReference'], player)
        self.send('variables',
                  {'variablesReference': player['variablesReference']})
        response = self.expect(
            lambda m: m.get('type') == 'response' and
            m.get('command') == 'variables')
        fields = {v['name']: v for v in response['body']['variables']}
        self.assertIn('hp', fields)
        self.assertEqual(fields['hp']['value'], '41')
        self.assertIn('name', fields)
        self.assertIn('hero', fields['name']['value'])

    def test_an_enum_shows_its_member(self):
        self.initialize()
        self.launch()
        self.set_breakpoints([{'line': 12}])
        self.configuration_done()
        self.stopped_event()
        variables = self.locals()
        self.assertEqual(variables['s']['value'], 'State::Playing')
        self.assertEqual(variables['s']['type'], 'State')

    def test_a_struct_field_can_be_watched(self):
        self.initialize({'supportsDataBreakpoints': True})
        self.launch()
        self.set_breakpoints([{'line': 12}])
        self.configuration_done()
        self.stopped_event()
        variables = self.locals()
        player = variables['p']
        self.send('variables',
                  {'variablesReference': player['variablesReference']})
        response = self.expect(
            lambda m: m.get('type') == 'response' and
            m.get('command') == 'variables')
        fields = {v['name']: v for v in response['body']['variables']}
        self.assertTrue(fields['hp'].get('memoryReference'), fields['hp'])
        self.send('setDataBreakpoints', {'breakpoints': [
            {'dataId': fields['hp']['memoryReference'], 'access': 'write'}]})
        response = self.expect(
            lambda m: m.get('type') == 'response' and
            m.get('command') == 'setDataBreakpoints')
        self.assertTrue(response['body']['breakpoints'][0]['verified'],
                        response)


class RemoteTargetTests(unittest.TestCase):
    def test_a_host_and_port_pair(self):
        from compiler.dap import _remote_target
        self.assertEqual(_remote_target({'host': '10.0.0.2', 'port': 1234}),
                         ('10.0.0.2', 1234))

    def test_a_host_and_port_string(self):
        from compiler.dap import _remote_target
        self.assertEqual(_remote_target('10.0.0.2:1234'), ('10.0.0.2', 1234))

    def test_nothing_usable(self):
        from compiler.dap import _remote_target
        self.assertIsNone(_remote_target(None))
        self.assertIsNone(_remote_target(''))
        self.assertIsNone(_remote_target('nonsense'))
        self.assertIsNone(_remote_target({'host': '10.0.0.2'}))


class DapRemoteIntegrationTests(_DapSessionTestCase):
    """A remote target that is not there is reported clearly."""

    def test_a_remote_target_that_cannot_be_reached_is_reported(self):
        self.initialize()
        self.send('launch', {'program': self.source,
                             'cwd': self.tempdir,
                             'remote': {'host': '127.0.0.1', 'port': 1}})
        response = self.expect(
            lambda m: m.get('type') == 'response' and
            m.get('command') == 'launch', timeout=90)
        self.assertTrue(response['success'], response)
        self.send('configurationDone')
        response = self.expect(
            lambda m: m.get('type') == 'response' and
            m.get('command') == 'configurationDone', timeout=90)
        self.assertFalse(response['success'], response)
        self.assertIn('127.0.0.1', response.get('message', ''))


class DapConditionIntegrationTests(_DapSessionTestCase):
    """A condition that only becomes true later still stops the program."""

    PROGRAM = ('func main() -> void:\n'
               '    let fixed = 41\n'
               '    mut counter = 0\n'
               '    mut total = 0\n'
               '    while counter < 5:\n'
               '        total = total + counter\n'
               '        counter = counter + 1\n'
               '    print_i32(total)\n')

    def test_a_condition_stops_when_it_becomes_true(self):
        self.initialize()
        self.launch()
        self.set_breakpoints([{'line': 6, 'condition': 'counter == 2'}])
        self.configuration_done()
        self.stopped_event()
        self.send('scopes', {'frameId': 0, 'threadId': 1})
        response = self.expect(
            lambda m: m.get('type') == 'response' and
            m.get('command') == 'scopes')
        reference = next(scope['variablesReference']
                         for scope in response['body']['scopes']
                         if scope['name'] == 'Locals')
        self.send('variables', {'variablesReference': reference})
        response = self.expect(
            lambda m: m.get('type') == 'response' and
            m.get('command') == 'variables')
        values = {v['name']: v['value']
                  for v in response['body']['variables']}
        self.assertEqual(values.get('counter'), '2')


class CommandLineDebugTests(unittest.TestCase):
    """`vanta debug` builds a source-mapped program and drives GDB."""

    @classmethod
    def setUpClass(cls):
        try:
            find_gdb()
        except GdbError:
            raise unittest.SkipTest('no working GDB')
        if not _debug_toolchain_available():
            raise unittest.SkipTest('no GCC/Clang compiler')

    def test_a_breakpoint_lands_on_the_vanta_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, 'main.vnt')
            with open(source, 'w', encoding='utf-8', newline='\n') as f:
                f.write('func main() -> void:\n'
                        '    let x = 41\n'
                        '    let y = x + 1\n'
                        '    print_i32(y)\n')
            result = subprocess.run(
                [sys.executable, '-m', 'compiler', 'debug', source,
                 '--build-dir', tmp,
                 '--exec', 'break 3', '--exec', 'info break'],
                capture_output=True, text=True,
                cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('main.vnt', result.stdout)
            self.assertIn('line 3', result.stdout)


class DapFieldEditingIntegrationTests(_DapSessionTestCase):
    """A field of a mutable struct can be edited."""

    PROGRAM = ('struct Player:\n'
               '    hp: i32\n'
               '    name: str\n'
               '\n'
               'func main() -> void:\n'
               '    mut p = Player(hp: 41, name: "hero")\n'
               '    let frozen = Player(hp: 1, name: "ice")\n'
               '    print_i32(p.hp)\n')

    def locals(self):
        self.send('scopes', {'frameId': 0, 'threadId': 1})
        response = self.expect(
            lambda m: m.get('type') == 'response' and
            m.get('command') == 'scopes')
        reference = next(scope['variablesReference']
                         for scope in response['body']['scopes']
                         if scope['name'] == 'Locals')
        self.send('variables', {'variablesReference': reference})
        response = self.expect(
            lambda m: m.get('type') == 'response' and
            m.get('command') == 'variables')
        return {v['name']: v for v in response['body']['variables']}

    def test_a_field_of_a_mutable_struct_can_be_edited(self):
        self.initialize()
        self.launch()
        self.set_breakpoints([{'line': 9}])
        self.configuration_done()
        self.stopped_event()
        variables = self.locals()
        player = variables['p']
        self.send('setVariable', {'variablesReference': player['variablesReference'],
                                  'name': 'hp', 'value': '99'})
        response = self.expect(
            lambda m: m.get('type') == 'response' and
            m.get('command') == 'setVariable')
        self.assertTrue(response['success'], response)
        self.send('variables',
                  {'variablesReference': player['variablesReference']})
        response = self.expect(
            lambda m: m.get('type') == 'response' and
            m.get('command') == 'variables')
        fields = {v['name']: v for v in response['body']['variables']}
        self.assertEqual(fields['hp']['value'], '99')

    def test_a_field_of_an_immutable_struct_is_refused(self):
        self.initialize()
        self.launch()
        self.set_breakpoints([{'line': 9}])
        self.configuration_done()
        self.stopped_event()
        variables = self.locals()
        frozen = variables['frozen']
        self.send('setVariable', {'variablesReference': frozen['variablesReference'],
                                  'name': 'hp', 'value': '99'})
        response = self.expect(
            lambda m: m.get('type') == 'response' and
            m.get('command') == 'setVariable')
        self.assertFalse(response['success'], response)
        self.assertIn('immutable', response.get('message', ''))


class DapEditingIntegrationTests(_DapSessionTestCase):
    """Editing variables, watching memory, and reading machine state."""

    PROGRAM = ('func main() -> void:\n'
               '    let fixed = 41\n'
               '    mut counter = 0\n'
               '    mut total = 0\n'
               '    while counter < 3:\n'
               '        total = total + counter\n'
               '        counter = counter + 1\n'
               '    print_i32(total)\n')

    def locals_reference(self, frame=0):
        self.send('scopes', {'frameId': frame, 'threadId': 1})
        response = self.expect(
            lambda m: m.get('type') == 'response' and
            m.get('command') == 'scopes')
        return next(scope['variablesReference']
                    for scope in response['body']['scopes']
                    if scope['name'] == 'Locals')

    def variables(self, reference):
        self.send('variables', {'variablesReference': reference})
        response = self.expect(
            lambda m: m.get('type') == 'response' and
            m.get('command') == 'variables')
        return response['body']['variables']

    def test_mutable_variable_can_be_edited(self):
        self.initialize()
        self.launch()
        self.set_breakpoints([{'line': 6}])
        self.configuration_done()
        self.stopped_event()
        reference = self.locals_reference()
        self.send('setVariable', {'variablesReference': reference,
                                  'name': 'counter', 'value': '7'})
        response = self.expect(
            lambda m: m.get('type') == 'response' and
            m.get('command') == 'setVariable')
        self.assertTrue(response['success'], response)
        values = {v['name']: v['value'] for v in self.variables(reference)}
        self.assertEqual(values.get('counter'), '7')

    def test_immutable_variable_is_rejected(self):
        self.initialize()
        self.launch()
        self.set_breakpoints([{'line': 6}])
        self.configuration_done()
        self.stopped_event()
        reference = self.locals_reference()
        self.send('setVariable', {'variablesReference': reference,
                                  'name': 'fixed', 'value': '7'})
        response = self.expect(
            lambda m: m.get('type') == 'response' and
            m.get('command') == 'setVariable')
        self.assertFalse(response['success'], response)
        self.assertIn('immutable', response.get('message', ''))
        values = {v['name']: v['value'] for v in self.variables(reference)}
        self.assertEqual(values.get('fixed'), '41')

    def test_wrong_value_type_is_rejected(self):
        self.initialize()
        self.launch()
        self.set_breakpoints([{'line': 6}])
        self.configuration_done()
        self.stopped_event()
        reference = self.locals_reference()
        self.send('setVariable', {'variablesReference': reference,
                                  'name': 'counter', 'value': '"text"'})
        response = self.expect(
            lambda m: m.get('type') == 'response' and
            m.get('command') == 'setVariable')
        self.assertFalse(response['success'], response)

    def test_data_breakpoint_watches_the_value(self):
        self.initialize({'supportsDataBreakpoints': True})
        self.launch()
        self.set_breakpoints([{'line': 6}])
        self.configuration_done()
        self.stopped_event()
        reference = self.locals_reference()
        target = next(v for v in self.variables(reference)
                      if v['name'] == 'counter')
        address = target.get('memoryReference')
        self.assertTrue(address, target)
        self.send('setDataBreakpoints', {
            'breakpoints': [{'dataId': address, 'access': 'write'}]})
        response = self.expect(
            lambda m: m.get('type') == 'response' and
            m.get('command') == 'setDataBreakpoints')
        self.assertTrue(response['success'], response)
        self.assertTrue(response['body']['breakpoints'][0]['verified'],
                        response)
        self.send('continue', {'threadId': 1})
        self.expect(lambda m: m.get('type') == 'response' and
                    m.get('command') == 'continue')
        stopped = self.stopped_event()
        self.assertEqual(stopped['body']['reason'], 'data breakpoint')

    def test_registers_are_listed(self):
        self.initialize()
        self.launch()
        self.set_breakpoints([{'line': 6}])
        self.configuration_done()
        self.stopped_event()
        self.send('registers', {})
        response = self.expect(
            lambda m: m.get('type') == 'response' and
            m.get('command') == 'registers')
        names = [r['name'] for r in response['body']['registers']]
        self.assertIn('rip', names)
        self.assertIn('rsp', names)

    def test_memory_can_be_read(self):
        self.initialize({'supportsDataBreakpoints': True})
        self.launch()
        self.set_breakpoints([{'line': 6}])
        self.configuration_done()
        self.stopped_event()
        reference = self.locals_reference()
        target = next(v for v in self.variables(reference)
                      if v['name'] == 'fixed')
        address = target.get('memoryReference')
        self.assertTrue(address, target)
        self.send('readMemory', {'address': address, 'count': 4})
        response = self.expect(
            lambda m: m.get('type') == 'response' and
            m.get('command') == 'readMemory')
        self.assertTrue(response['success'], response)
        self.assertEqual(len(response['body']['data']), 8)


if __name__ == '__main__':
    unittest.main()
