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
    _mi_quote,
    _vanta_type,
    find_gdb,
    parse_mi_line,
    read_dap_message,
    write_dap_message,
)
from compiler.driver import build_debug, find_debug_compiler


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


class DapStdioIntegrationTests(unittest.TestCase):
    """Exercise the real adapter process, not just its helpers."""

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
            f.write('func main() -> void:\n'
                    '    let x = 41\n'
                    '    let y = x + 1\n'
                    '    print_i32(y)\n')
        self.process = None
        self.messages: queue.Queue = queue.Queue()
        self.seq = 0

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

    def expect(self, predicate, timeout=30):
        seen = []
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                message = self.messages.get(timeout=max(0.1, deadline - time.time()))
            except queue.Empty:
                continue
            if message is None:
                self.fail(f'adapter exited; messages={seen!r}')
            seen.append(message)
            if predicate(message):
                return message
        self.fail(f'timed out; messages={seen!r}')

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


if __name__ == '__main__':
    unittest.main()
