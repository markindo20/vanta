"""A Debug Adapter Protocol server for Vanta, backed by GDB/MI.

The adapter compiles the requested Vanta program as an unoptimized native
executable with ``#line`` markers (see :class:`compiler.codegen_cpp.CodeGen`)
and drives GDB's machine interface.  Editors only need to speak DAP; GDB is an
implementation detail of this module.

The implementation intentionally covers the core debugging workflow:
breakpoints, stack frames, locals/arguments, continue/step/pause, program
output, and termination.  It is deliberately strict about one thing: a debug
build must use a GCC/Clang toolchain that emits DWARF.  MSVC's PDB format is
not readable by GDB, so an MSVC-only machine gets a clear error instead of a
mysterious failed session.
"""

from __future__ import annotations

import glob
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

from . import VERSION
from .driver import DebugBuildError, build_debug, find_debug_compiler


# ---------------------------------------------------------------------------
# DAP framing
# ---------------------------------------------------------------------------


def read_dap_message(reader) -> Optional[dict]:
    """Read one ``Content-Length`` framed JSON message."""
    headers: dict[str, str] = {}
    while True:
        line = reader.readline()
        if not line:
            return None
        if isinstance(line, str):
            line = line.encode('ascii', 'ignore')
        line = line.rstrip(b'\r\n')
        if not line:
            break
        if b':' not in line:
            continue
        key, value = line.split(b':', 1)
        headers[key.strip().decode('ascii', 'ignore').lower()] = \
            value.strip().decode('ascii', 'ignore')
    raw_length = headers.get('content-length')
    if raw_length is None:
        return None
    try:
        length = int(raw_length)
    except ValueError:
        return None
    body = reader.read(length)
    if not body:
        return None
    try:
        return json.loads(body.decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


def write_dap_message(writer, message: dict) -> None:
    payload = json.dumps(message, separators=(',', ':')).encode('utf-8')
    header = f'Content-Length: {len(payload)}\r\n\r\n'.encode('ascii')
    writer.write(header)
    writer.write(payload)
    writer.flush()


def _as_list(value) -> list:
    """Accept either a scalar or a DAP array for repeatable launch fields."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return list(value)


def _path_from_dap(value: Optional[str]) -> Optional[str]:
    """Accept native paths, file URIs, and the odd URL-encoded path."""
    if not value:
        return None
    if value.startswith('file://'):
        parsed = urlparse(value)
        path = url2pathname(unquote(parsed.path))
        if parsed.netloc and parsed.netloc not in ('', 'localhost'):
            path = '//' + parsed.netloc + path
        if os.name == 'nt' and path.startswith('/') and len(path) > 2 \
                and path[2] == ':':
            path = path[1:]
        return os.path.normpath(path)
    return os.path.normpath(os.path.abspath(os.path.expanduser(value)))


# ---------------------------------------------------------------------------
# GDB/MI parsing
# ---------------------------------------------------------------------------


@dataclass
class MiRecord:
    """One line of GDB/MI output.

    ``sign`` is one of ``^`` (result), ``*`` (exec-async), ``+`` (status),
    ``=`` (notify), ``~``/``@``/``&`` (streams), ``eof``, or ``plain`` for
    GDB's occasional non-MI text.
    """

    sign: str
    token: str = ''
    class_: str = ''
    results: dict = field(default_factory=dict)
    text: str = ''


_STRING_ESCAPES = {
    'a': '\a', 'b': '\b', 'f': '\f', 'n': '\n', 'r': '\r',
    't': '\t', 'v': '\v', '\\': '\\', '"': '"',
}


def _parse_mi_string(text: str, start: int):
    """Parse a quoted MI string starting at ``start``; return (value, end)."""
    if start >= len(text) or text[start] != '"':
        return '', start
    i = start + 1
    out = []
    while i < len(text):
        ch = text[i]
        if ch == '"':
            return ''.join(out), i + 1
        if ch != '\\':
            out.append(ch)
            i += 1
            continue
        i += 1
        if i >= len(text):
            break
        esc = text[i]
        if esc in _STRING_ESCAPES:
            out.append(_STRING_ESCAPES[esc])
            i += 1
        elif esc == 'x':
            i += 1
            digits = text[i:i + 2]
            if len(digits) == 2:
                try:
                    out.append(chr(int(digits, 16)))
                    i += 2
                    continue
                except ValueError:
                    pass
            out.append('x')
        elif esc.isdigit():
            digits = ''
            while i < len(text) and len(digits) < 3 and text[i].isdigit():
                digits += text[i]
                i += 1
            try:
                out.append(chr(int(digits, 8)))
            except ValueError:
                out.append('?')
        else:
            out.append(esc)
            i += 1
    return ''.join(out), i


def _skip_space(text: str, i: int) -> int:
    while i < len(text) and text[i] in ' \t':
        i += 1
    return i


def _parse_mi_value(text: str, i: int):
    i = _skip_space(text, i)
    if i >= len(text):
        return '', i
    ch = text[i]
    if ch == '"':
        return _parse_mi_string(text, i)
    if ch == '{':
        return _parse_mi_tuple(text, i)
    if ch == '[':
        return _parse_mi_list(text, i)
    start = i
    while i < len(text) and text[i] not in ',]}':
        i += 1
    return text[start:i].strip(), i


def _parse_mi_tuple(text: str, i: int):
    # i points at '{'
    i += 1
    out: dict = {}
    while True:
        i = _skip_space(text, i)
        if i >= len(text) or text[i] == '}':
            return out, min(i + 1, len(text))
        key_start = i
        while i < len(text) and text[i] not in '=,}':
            i += 1
        key = text[key_start:i].strip()
        if i >= len(text) or text[i] != '=':
            # Malformed; consume the character and keep going.
            if i < len(text):
                i += 1
            continue
        value, i = _parse_mi_value(text, i + 1)
        out[key] = value
        i = _skip_space(text, i)
        if i < len(text) and text[i] == ',':
            i += 1


def _looks_like_result(text: str, i: int) -> bool:
    j = i
    if j >= len(text) or not (text[j].isalpha() or text[j] == '_'):
        return False
    while j < len(text) and (text[j].isalnum() or text[j] in '_-'):
        j += 1
    while j < len(text) and text[j] in ' \t':
        j += 1
    return j < len(text) and text[j] == '='


def _parse_mi_list(text: str, i: int):
    # i points at '['
    i += 1
    out: list = []
    while True:
        i = _skip_space(text, i)
        if i >= len(text) or text[i] == ']':
            return out, min(i + 1, len(text))
        if _looks_like_result(text, i):
            key_start = i
            while i < len(text) and text[i] != '=':
                i += 1
            key = text[key_start:i].strip()
            value, i = _parse_mi_value(text, i + 1)
            out.append({key: value})
        else:
            value, i = _parse_mi_value(text, i)
            out.append(value)
        i = _skip_space(text, i)
        if i < len(text) and text[i] == ',':
            i += 1


def parse_mi_line(line: str) -> Optional[MiRecord]:
    """Parse one GDB/MI output line into a :class:`MiRecord`."""
    line = line.rstrip('\r\n')
    if not line:
        return None
    i = 0
    while i < len(line) and line[i].isdigit():
        i += 1
    token = line[:i]
    if i >= len(line):
        return MiRecord('plain', text=line)
    sign = line[i]
    if sign in '~@&':
        text = ''
        if i + 1 < len(line) and line[i + 1] == '"':
            text, _ = _parse_mi_string(line, i + 1)
        return MiRecord(sign, token=token, text=text)
    if sign not in '^=*+':
        return MiRecord('plain', text=line)
    i += 1
    class_start = i
    while i < len(line) and line[i] not in ',': 
        i += 1
    class_ = line[class_start:i].strip()
    results: dict = {}
    if i < len(line) and line[i] == ',':
        i += 1
        while i < len(line):
            i = _skip_space(line, i)
            if i >= len(line):
                break
            key_start = i
            while i < len(line) and line[i] not in '=,':
                i += 1
            key = line[key_start:i].strip()
            if i >= len(line) or line[i] != '=':
                break
            value, i = _parse_mi_value(line, i + 1)
            if key:
                results[key] = value
            i = _skip_space(line, i)
            if i < len(line) and line[i] == ',':
                i += 1
    return MiRecord(sign, token=token, class_=class_, results=results)


def _mi_quote(value: str) -> str:
    out = ['"']
    for ch in value:
        if ch == '\\':
            out.append('\\\\')
        elif ch == '"':
            out.append('\\"')
        elif ch == '\n':
            out.append('\\n')
        elif ch == '\r':
            out.append('\\r')
        elif ch == '\t':
            out.append('\\t')
        else:
            out.append(ch)
    out.append('"')
    return ''.join(out)


class GdbError(RuntimeError):
    pass


class GdbTimeout(GdbError):
    pass


class GdbMi:
    """Small synchronous wrapper around a GDB/MI subprocess."""

    def __init__(self, gdb_path: str, executable: str, env=None, cwd=None):
        self.gdb_path = gdb_path
        self.executable = executable
        self.events: queue.Queue = queue.Queue()
        self._pending: dict[str, tuple[threading.Event, dict]] = {}
        self._lock = threading.Lock()
        self._next_token = 1
        self._closed = False
        self.process = subprocess.Popen(
            [gdb_path, '--interpreter=mi2', '--quiet', '--nx', executable],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8',
            errors='replace',
            bufsize=1,
            env=env,
            cwd=cwd,
        )
        self.reader = threading.Thread(target=self._read_loop, daemon=True)
        self.reader.start()
        self.stderr_reader = threading.Thread(target=self._read_stderr, daemon=True)
        self.stderr_reader.start()

    def _read_loop(self):
        try:
            for line in self.process.stdout:
                record = parse_mi_line(line)
                if record is None:
                    continue
                if record.sign == 'plain':
                    # GDB passes unadorned inferior stdout through this
                    # channel.  Keep the original terminator; parse_mi_line
                    # strips it for protocol records.
                    if line.endswith('\n'):
                        record.text += '\n'
                if record.sign == '^':
                    with self._lock:
                        slot = self._pending.pop(record.token, None)
                    if slot is not None:
                        event, box = slot
                        box['record'] = record
                        event.set()
                    else:
                        self.events.put(record)
                else:
                    self.events.put(record)
        finally:
            with self._lock:
                pending = list(self._pending.values())
                self._pending.clear()
            for event, box in pending:
                box['record'] = MiRecord('^', class_='error',
                                         results={'msg': 'GDB exited'})
                event.set()
            self.events.put(MiRecord('eof'))

    def _read_stderr(self):
        # GDB sends the inferior's stdout and stderr here; its MI channel is
        # stdout.  Forward those lines as target output rather than letting
        # them disappear as unparsed MI text.
        try:
            for line in self.process.stderr:
                self.events.put(MiRecord('@', text=line))
        except Exception:
            pass

    def write_raw(self, text: str):
        if self.process.stdin is None or self.process.poll() is not None:
            raise GdbError('GDB is not running')
        try:
            self.process.stdin.write(text + '\n')
            self.process.stdin.flush()
        except (OSError, ValueError) as exc:
            raise GdbError(f'could not write to GDB: {exc}') from exc

    def command(self, command: str, timeout: float = 30.0) -> MiRecord:
        with self._lock:
            token = str(self._next_token)
            self._next_token += 1
            event = threading.Event()
            box: dict = {'record': None}
            self._pending[token] = (event, box)
        self.write_raw(token + command)
        if not event.wait(timeout):
            with self._lock:
                self._pending.pop(token, None)
            raise GdbTimeout(f'GDB did not answer {command!r} in {timeout:.0f}s')
        record = box.get('record')
        if record is None:
            raise GdbError(f'GDB did not answer {command!r}')
        if record.class_ == 'error':
            message = record.results.get('msg', 'GDB command failed')
            raise GdbError(str(message))
        return record

    def run_command(self, command: str, timeout: float = 30.0) -> MiRecord:
        record = self.command(command, timeout=timeout)
        # -exec-run/-exec-continue answer ^running, while configuration
        # commands answer ^done.  Both mean the command was accepted.
        if record.class_ not in ('done', 'running', 'exit'):
            message = record.results.get('msg', record.class_ or 'unknown result')
            raise GdbError(str(message))
        return record

    def close(self):
        if self._closed:
            return
        self._closed = True
        if self.process.poll() is None:
            try:
                self.command('-gdb-exit', timeout=3.0)
            except Exception:
                try:
                    self.process.terminate()
                except Exception:
                    pass
        try:
            self.process.wait(timeout=5)
        except Exception:
            try:
                self.process.kill()
            except Exception:
                pass
        for thread in (self.reader, self.stderr_reader):
            try:
                thread.join(timeout=1)
            except Exception:
                pass
        for stream in (self.process.stdin, self.process.stdout,
                       self.process.stderr):
            try:
                if stream:
                    stream.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# GDB discovery
# ---------------------------------------------------------------------------


def _gdb_candidates(explicit=None):
    seen = set()

    def add(value):
        if not value:
            return
        key = os.path.normcase(os.path.abspath(value)) if os.path.exists(value) \
            else value.lower()
        if key in seen:
            return
        seen.add(key)
        yield value

    if explicit:
        yield from add(explicit)
    env = os.environ.get('VANTA_GDB')
    if env:
        yield from add(env)

    _, compiler = find_debug_compiler()
    if compiler:
        directory = os.path.dirname(os.path.abspath(compiler))
        for name in ('gdb.exe', 'gdb'):
            candidate = os.path.join(directory, name)
            if os.path.exists(candidate):
                yield from add(candidate)

    if os.name == 'nt':
        local = os.environ.get('LOCALAPPDATA', '')
        patterns = [
            os.path.join(local, 'Microsoft', 'WinGet', 'Packages',
                         'BrechtSanders.WinLibs.*', 'mingw64', 'bin', 'gdb.exe'),
            r'C:\msys64\mingw64\bin\gdb.exe',
            r'C:\msys64\ucrt64\bin\gdb.exe',
            r'C:\msys64\clang64\bin\gdb.exe',
        ]
        for pattern in patterns:
            for candidate in glob.glob(pattern):
                yield from add(candidate)

    found = shutil.which('gdb')
    if found:
        yield from add(found)
    for candidate in ('/usr/bin/gdb', '/usr/local/bin/gdb',
                      '/opt/homebrew/bin/gdb'):
        if os.path.exists(candidate):
            yield from add(candidate)


def _probe_gdb(path: str) -> bool:
    try:
        proc = subprocess.run([path, '--version'], capture_output=True,
                              text=True, timeout=8,
                              stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0 and 'GDB' in (proc.stdout + proc.stderr)


def find_gdb(explicit=None) -> str:
    """Find a working GDB executable, preferring an explicit setting."""
    for candidate in _gdb_candidates(explicit):
        if os.path.isabs(candidate):
            if not os.path.exists(candidate):
                continue
            path = candidate
        else:
            path = shutil.which(candidate)
            if not path:
                continue
        if _probe_gdb(path):
            return os.path.abspath(path)
    raise GdbError(
        'no working GDB found. Install GDB and put it on PATH, or set '
        'GDB explicitly (VS Code: vanta.debug.gdbPath; CLI: VANTA_GDB).')


# ---------------------------------------------------------------------------
# DAP adapter
# ---------------------------------------------------------------------------


class DapAdapter:
    """A single debug session speaking DAP over a pair of streams."""

    def __init__(self, reader=None, writer=None):
        self.reader = reader or sys.stdin.buffer
        self.writer = writer or sys.stdout.buffer
        self._write_lock = threading.Lock()
        self._inbox: queue.Queue = queue.Queue()
        self._reader_thread = None
        self._running = True
        self._seq = 1
        self._client_capabilities: dict = {}
        self._launch_args: dict = {}
        self._build: Optional[dict] = None
        self._source: Optional[str] = None
        self._gdb: Optional[GdbMi] = None
        self._configuration_done = False
        self._stop_on_entry = False
        self._entry_bp_number: Optional[str] = None
        self._breakpoints: dict[str, tuple[str, list[dict]]] = {}
        self._gdb_breakpoints: dict[str, list[str]] = {}
        self._bp_meta: dict[str, dict] = {}
        self._function_requests: list[dict] = []
        self._function_breakpoints: list[str] = []
        self._watch_expressions: list[dict] = []
        self._threads: dict[int, dict] = {}
        self._current_thread: Optional[int] = None
        self._stopped = False
        self._running_inferior = False
        self._terminated = False
        self._variable_refs: dict[int, tuple[int, int, str]] = {}
        self._next_var_ref = 1

    # -- protocol ----------------------------------------------------------

    def send(self, message: dict):
        with self._write_lock:
            write_dap_message(self.writer, message)

    def event(self, name: str, body: Optional[dict] = None):
        message = {'type': 'event', 'event': name, 'seq': self._next_seq()}
        if body is not None:
            message['body'] = body
        self.send(message)

    def response(self, request: dict, body: Optional[dict] = None,
                 success=True, message=None):
        reply = {
            'type': 'response',
            'request_seq': request.get('seq', 0),
            'command': request.get('command', ''),
            'success': bool(success),
            'seq': self._next_seq(),
        }
        if body is not None:
            reply['body'] = body
        if message:
            reply['message'] = str(message)
        self.send(reply)

    def error(self, request: dict, message, show_user=False):
        reply = {
            'type': 'response',
            'request_seq': request.get('seq', 0),
            'command': request.get('command', ''),
            'success': False,
            'seq': self._next_seq(),
            'message': str(message),
            'body': {'error': {'id': 1, 'format': str(message),
                               'showUser': bool(show_user)}},
        }
        self.send(reply)

    def output(self, category: str, text: str):
        if text:
            self.event('output', {'category': category, 'output': text})

    def _next_seq(self):
        value = self._seq
        self._seq += 1
        return value

    def _read_messages(self):
        while True:
            try:
                message = read_dap_message(self.reader)
            except Exception as exc:
                self._inbox.put(('error', exc))
                return
            if message is None:
                self._inbox.put(('eof', None))
                return
            self._inbox.put(('message', message))

    def serve(self) -> int:
        self._reader_thread = threading.Thread(target=self._read_messages,
                                               daemon=True)
        self._reader_thread.start()
        try:
            while self._running:
                try:
                    kind, payload = self._inbox.get(timeout=0.02)
                except queue.Empty:
                    kind, payload = None, None
                if kind == 'eof':
                    break
                if kind == 'error':
                    break
                if kind == 'message':
                    self._dispatch(payload)
                self._pump_gdb()
        finally:
            self._shutdown(cleanup=True)
        return 0

    def _pump_gdb(self):
        if self._gdb is None:
            return
        while True:
            try:
                record = self._gdb.events.get_nowait()
            except queue.Empty:
                return
            try:
                self._handle_gdb_event(record)
            except Exception as exc:
                # A malformed or unsupported notification must not kill the
                # whole session; report it and keep the adapter responsive.
                self.output('console', f'vanta debugger: {exc}\n')

    def _dispatch(self, message: dict):
        if not isinstance(message, dict):
            return
        if message.get('type') != 'request':
            return
        command = message.get('command', '')
        handler = getattr(self, '_request_' + command.replace('-', '_'), None)
        if handler is None:
            self.response(message, success=False,
                          message=f'unsupported request: {command}')
            return
        try:
            handler(message, message.get('arguments') or {})
        except Exception as exc:
            self.error(message, exc)

    # -- requests ----------------------------------------------------------

    def _request_initialize(self, request, args):
        self._client_capabilities = args or {}
        capabilities = {
            'supportsConfigurationDoneRequest': True,
            'supportsTerminateRequest': True,
            'supportsTerminateDebuggee': True,
            'supportsFunctionBreakpoints': True,
            'supportsConditionalBreakpoints': True,
            'supportsHitConditionalBreakpoints': True,
            'supportsLogPoints': True,
            'supportsEvaluateForHovers': False,
            'supportsSetVariable': False,
            'supportsRestartFrame': False,
            'supportsGotoTargetsRequest': False,
            'supportsCompletionsRequest': False,
            'supportsModulesRequest': False,
            'supportsRestartRequest': True,
            'supportsExceptionOptions': False,
            'supportsValueFormattingOptions': False,
            'supportsExceptionInfoRequest': False,
            'supportsDataBreakpoints': False,
            'supportsReadMemoryRequest': False,
            'supportsDisassembleRequest': False,
            'supportsCancelRequest': False,
            'supportsBreakpointLocationsRequest': False,
            'supportsClipboardContext': False,
            'supportsSteppingGranularity': False,
            'supportsInstructionBreakpoints': False,
            'supportsLoadedSourcesRequest': False,
            'exceptionBreakpointFilters': [],
            'supportsDelayedStackTraceLoading': False,
        }
        self.response(request, capabilities)
        self.event('initialized')

    def _request_launch(self, request, args):
        self._launch_args = dict(args or {})
        source = _path_from_dap(self._launch_args.get('program'))
        if not source:
            self.error(request, 'launch configuration is missing "program"',
                       show_user=True)
            return
        if not os.path.isfile(source):
            self.error(request, f'program not found: {source}', show_user=True)
            return
        cwd = _path_from_dap(self._launch_args.get('cwd')) or \
            os.path.dirname(source) or os.getcwd()
        if not os.path.isdir(cwd):
            self.error(request, f'working directory not found: {cwd}',
                       show_user=True)
            return
        self._stop_on_entry = bool(self._launch_args.get('stopOnEntry'))
        self._source = source

        self.output('console', f'Building {os.path.basename(source)}...\n')
        try:
            build = build_debug(
                source,
                include_dirs=_as_list(self._launch_args.get('includeDirs')),
                lib_dirs=_as_list(self._launch_args.get('libDirs')),
                link=_as_list(self._launch_args.get('libs')),
            )
        except DebugBuildError as exc:
            if exc.tempdir:
                shutil.rmtree(exc.tempdir, ignore_errors=True)
            if exc.output:
                self.output('stderr', exc.output.rstrip() + '\n')
            self.error(request, exc.message, show_user=True)
            return
        except Exception as exc:
            self.error(request, f'debug build failed: {exc}', show_user=True)
            return
        self._build = build

        gdb_path = self._launch_args.get('gdbPath') or self._launch_args.get('miDebuggerPath')
        try:
            gdb_path = find_gdb(gdb_path)
            gdb = GdbMi(gdb_path, build['exe'], env=build['env'], cwd=cwd)
        except Exception as exc:
            self._cleanup_build()
            self.error(request, str(exc), show_user=True)
            return
        self._gdb = gdb
        try:
            self._initialize_gdb(cwd)
        except Exception as exc:
            self._shutdown(cleanup=True)
            self.error(request, f'could not start GDB: {exc}', show_user=True)
            return

        self.output('console', f'Debugging {source}\n')
        self.response(request)

    def _initialize_gdb(self, cwd):
        gdb = self._gdb
        assert gdb is not None
        gdb.command('-gdb-set pagination off')
        gdb.command('-gdb-set confirm off')
        gdb.command('-gdb-set width 0')
        gdb.command('-gdb-set print pretty on')
        gdb.command('-gdb-set print elements 200')
        gdb.command('-gdb-set mi-async on')
        # GDB's cwd is the inferior's cwd.  The process was launched with the
        # requested cwd, so nothing else is required for ordinary programs.
        args = _as_list(self._launch_args.get('args'))
        if args:
            gdb.command('-exec-arguments ' +
                        ' '.join(_mi_quote(str(a)) for a in args))

    def _request_setBreakpoints(self, request, args):
        source_info = args.get('source') or {}
        source = _path_from_dap(source_info.get('path'))
        requested = args.get('breakpoints') or []
        if not source:
            self.error(request, 'setBreakpoints requires source.path')
            return
        key = os.path.normcase(os.path.abspath(source))
        self._breakpoints[key] = (source, [dict(bp) for bp in requested])
        if self._gdb is None:
            self.response(request, {'breakpoints': [
                {'verified': False, 'line': bp.get('line', 1),
                 'message': 'debugger has not started'}
                for bp in requested
            ]})
            return
        try:
            result = self._apply_breakpoints(source, requested)
        except Exception as exc:
            self.error(request, exc)
            return
        self.response(request, {'breakpoints': result})

    def _request_setFunctionBreakpoints(self, request, args):
        requested = [dict(bp) for bp in (args.get('breakpoints') or [])]
        self._function_requests = requested
        if self._gdb is None:
            self.response(request, {'breakpoints': [
                {'verified': False, 'message': 'debugger has not started'}
                for _ in requested
            ]})
            return
        self._delete_function_breakpoints()
        out = [self._insert_function_breakpoint(bp) for bp in requested]
        self.response(request, {'breakpoints': out})

    def _request_setExceptionBreakpoints(self, request, args):
        self.response(request, {'breakpoints': []})

    def _request_setExpression(self, request, args):
        expression = str(args.get('expression') or '')
        if not expression:
            self.error(request, 'setExpression requires an expression')
            return
        value = str(args.get('value') or expression)
        context = str(args.get('context') or '')
        frame_id = _int_or_none(args.get('frameId'))
        if context == 'watch':
            self._add_watch(expression, frame_id)
            result, ok = self._evaluate_expression(expression)
            self.response(request, {'value': result if ok else expression,
                                    'variablesReference': 0})
            return
        result, ok = self._evaluate_expression(value)
        if not ok:
            self.error(request, f'cannot evaluate {value!r}')
            return
        self.response(request, {'value': result, 'variablesReference': 0})

    def _request_configurationDone(self, request, args):
        if self._gdb is None:
            self.error(request, 'debugger has not been launched')
            return
        # Breakpoints may have arrived before launch in exotic clients.
        for source, bps in list(self._breakpoints.values()):
            try:
                self._apply_breakpoints(source, bps)
            except Exception as exc:
                self.output('console', f'vanta debugger: {exc}\n')
        for bp in list(self._function_requests):
            try:
                self._insert_function_breakpoint(bp)
            except Exception as exc:
                self.output('console', f'vanta debugger: {exc}\n')
        if self._stop_on_entry:
            try:
                record = self._gdb.run_command('-break-insert -t vanta_user::fn_main')
                bkpt = record.results.get('bkpt') or {}
                if isinstance(bkpt, dict):
                    self._entry_bp_number = str(bkpt.get('number', ''))
            except Exception as exc:
                self.output('console', f'could not set entry breakpoint: {exc}\n')
        self._configuration_done = True
        try:
            self._gdb.run_command('-exec-run')
        except Exception as exc:
            self.error(request, f'could not start the program: {exc}',
                       show_user=True)
            return
        self._running_inferior = True
        self.response(request)

    def _request_threads(self, request, args):
        if self._gdb is None:
            self.response(request, {'threads': []})
            return
        try:
            record = self._gdb.command('-thread-info')
            threads = []
            current = None
            for item in record.results.get('threads', []) or []:
                if not isinstance(item, dict):
                    continue
                tid = _int_or_none(item.get('id'))
                if tid is None:
                    continue
                name = item.get('name') or item.get('target-id') or f'Thread {tid}'
                threads.append({'id': tid, 'name': str(name)})
                self._threads[tid] = item
            current = _int_or_none(record.results.get('current-thread-id'))
            if current is not None:
                self._current_thread = current
            if not threads and self._current_thread is not None:
                threads = [{'id': self._current_thread,
                            'name': f'Thread {self._current_thread}'}]
            self.response(request, {'threads': threads})
        except Exception as exc:
            self.response(request, {'threads': []})
            self.output('console', f'vanta debugger: {exc}\n')

    def _request_stackTrace(self, request, args):
        if self._gdb is None:
            self.response(request, {'stackFrames': [], 'totalFrames': 0})
            return
        thread_id = _int_or_none(args.get('threadId')) or self._current_thread or 1
        try:
            self._select_thread(thread_id)
            record = self._gdb.command('-stack-list-frames')
        except Exception as exc:
            self.error(request, exc)
            return
        raw = record.results.get('stack', []) or []
        frames = []
        for item in raw:
            frame = item.get('frame') if isinstance(item, dict) else None
            if not isinstance(frame, dict):
                continue
            frames.append(frame)
        start = max(0, int(args.get('startFrame') or 0))
        levels = args.get('levels')
        if levels is None:
            selected = frames[start:]
        else:
            selected = frames[start:start + max(0, int(levels))]
        out = []
        for frame in selected:
            level = _int_or_none(frame.get('level'))
            if level is None:
                level = len(out)
            fullname = frame.get('fullname') or frame.get('file') or ''
            line = _int_or_none(frame.get('line')) or 1
            name = _frame_name(frame.get('func') or '')
            source = None
            if fullname:
                source = {
                    'name': os.path.basename(fullname),
                    'path': os.path.normpath(fullname),
                }
            entry = {
                'id': level,
                'name': name,
                'line': line,
                'column': 1,
            }
            if source:
                entry['source'] = source
            address = frame.get('addr')
            if address:
                entry['instructionPointerReference'] = str(address)
            out.append(entry)
        self.response(request, {'stackFrames': out,
                                'totalFrames': len(frames)})

    def _request_scopes(self, request, args):
        thread_id = _int_or_none(args.get('threadId')) or self._current_thread or 1
        level = _int_or_none(args.get('frameId')) or 0
        try:
            self._select_frame(thread_id, level)
        except Exception:
            pass
        locals_ref = self._new_var_ref(thread_id, level, 'locals')
        args_ref = self._new_var_ref(thread_id, level, 'arguments')
        scopes = [
            {'name': 'Locals', 'presentationHint': 'locals',
             'variablesReference': locals_ref, 'expensive': False},
            {'name': 'Arguments', 'presentationHint': 'arguments',
             'variablesReference': args_ref, 'expensive': False},
        ]
        if self._watch_expressions:
            watch_ref = self._new_var_ref(thread_id, level, 'watch')
            scopes.append({'name': 'Watch', 'presentationHint': 'watch',
                           'variablesReference': watch_ref, 'expensive': False})
        self.response(request, {'scopes': scopes})

    def _request_variables(self, request, args):
        ref = _int_or_none(args.get('variablesReference'))
        info = self._variable_refs.get(ref)
        if info is None:
            self.response(request, {'variables': []})
            return
        thread_id, level, kind = info
        if self._gdb is None:
            self.response(request, {'variables': []})
            return
        try:
            self._select_frame(thread_id, level)
            variables = self._variables_for(thread_id, level, kind)
        except Exception as exc:
            self.error(request, exc)
            return
        self.response(request, {'variables': variables})

    def _request_continue(self, request, args):
        self._resume(request, '-exec-continue')

    def _request_next(self, request, args):
        self._resume(request, '-exec-next')

    def _request_stepIn(self, request, args):
        granularity = args.get('granularity', 'statement')
        if granularity == 'instruction':
            self._resume(request, '-exec-step-instruction')
        else:
            self._resume(request, '-exec-step')

    def _request_stepOut(self, request, args):
        self._resume(request, '-exec-finish')

    def _request_pause(self, request, args):
        if self._gdb is None:
            self.error(request, 'debugger has not been launched')
            return
        try:
            self._gdb.run_command('-exec-interrupt')
        except Exception as exc:
            self.error(request, exc)
            return
        self.response(request)

    def _request_evaluate(self, request, args):
        expression = str(args.get('expression') or '')
        if not expression or self._gdb is None:
            self.response(request, {'result': '', 'variablesReference': 0})
            return
        frame_id = _int_or_none(args.get('frameId'))
        if frame_id is not None:
            self._select_frame(self._current_thread or 1, frame_id)
        value, ok = self._evaluate_expression(expression)
        if not ok:
            self.error(request, f'cannot evaluate {expression!r}')
            return
        self.response(request, {'result': value, 'variablesReference': 0})

    def _request_source(self, request, args):
        source = args.get('source') or {}
        path = _path_from_dap(source.get('path'))
        if not path or not os.path.isfile(path):
            self.error(request, 'source not found')
            return
        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                text = f.read()
        except OSError as exc:
            self.error(request, exc)
            return
        self.response(request, {'content': text})

    def _request_disconnect(self, request, args):
        self._shutdown(cleanup=True)
        self.response(request)
        self._running = False

    def _request_terminate(self, request, args):
        self._terminate_inferior()
        self.response(request)
        self._emit_terminated(None)

    def _request_restart(self, request, args):
        """Rebuild the program and run it again in the same session."""
        if self._gdb is None or self._build is None or not self._source:
            self.error(request, 'debugger has not been launched')
            return
        self._stop_inferior()
        try:
            build = build_debug(
                self._source,
                include_dirs=_as_list(self._launch_args.get('includeDirs')),
                lib_dirs=_as_list(self._launch_args.get('libDirs')),
                link=_as_list(self._launch_args.get('libs')),
            )
        except DebugBuildError as exc:
            if exc.tempdir:
                shutil.rmtree(exc.tempdir, ignore_errors=True)
            if exc.output:
                self.output('stderr', exc.output.rstrip() + '\n')
            self.error(request, exc.message, show_user=True)
            return
        except Exception as exc:
            self.error(request, f'debug build failed: {exc}', show_user=True)
            return
        old_build = self._build
        self._build = build
        try:
            self._gdb.command('-file-exec-and-symbols ' +
                              _mi_quote(build['exe']))
        except Exception as exc:
            self._build = old_build
            shutil.rmtree(build.get('tempdir') or '', ignore_errors=True)
            self.error(request, f'could not reload the program: {exc}',
                       show_user=True)
            return
        if old_build:
            tempdir = old_build.get('tempdir')
            if tempdir:
                shutil.rmtree(tempdir, ignore_errors=True)
        # The new symbols shift every address, so the breakpoints are
        # recreated from the client's requests.
        self._gdb_breakpoints = {}
        self._bp_meta = {}
        self._function_breakpoints = []
        for source, bps in list(self._breakpoints.values()):
            try:
                self._apply_breakpoints(source, bps)
            except Exception as exc:
                self.output('console', f'vanta debugger: {exc}\n')
        for bp in list(self._function_requests):
            try:
                self._insert_function_breakpoint(bp)
            except Exception as exc:
                self.output('console', f'vanta debugger: {exc}\n')
        if self._stop_on_entry:
            try:
                record = self._gdb.run_command(
                    '-break-insert -t vanta_user::fn_main')
                bkpt = record.results.get('bkpt') or {}
                if isinstance(bkpt, dict):
                    self._entry_bp_number = str(bkpt.get('number', ''))
            except Exception as exc:
                self.output('console',
                            f'could not set entry breakpoint: {exc}\n')
        self._terminated = False
        self._running_inferior = True
        try:
            self._gdb.run_command('-exec-run')
        except Exception as exc:
            self.error(request, f'could not restart the program: {exc}',
                       show_user=True)
            return
        self.response(request)

    # -- breakpoints -------------------------------------------------------

    def _breakpoint_meta(self, bp: dict) -> dict:
        """Collect the DAP extras of a breakpoint request.

        Conditions, hit counts, and log messages are evaluated by the
        adapter itself: GDB cannot evaluate a Vanta condition before the
        program is running, and adapter-side evaluation keeps the Vanta
        variable names intact.
        """
        meta: dict = {}
        condition = bp.get('condition')
        if condition:
            meta['condition'] = str(condition)
        hit_condition = bp.get('hitCondition')
        if hit_condition:
            if _hit_condition_matches(hit_condition, 1) is None:
                meta['hitConditionError'] = (
                    f'unsupported hit condition: {hit_condition}')
            else:
                meta['hitCondition'] = str(hit_condition)
        log_message = bp.get('logMessage')
        if log_message:
            meta['logMessage'] = str(log_message)
        return meta

    def _insert_function_breakpoint(self, bp: dict) -> dict:
        """Insert a breakpoint on a Vanta function name."""
        name = str(bp.get('name') or '')
        entry: dict = {'verified': False,
                       'message': f'function {name!r} not found'}
        for symbol in self._function_symbol_candidates(name):
            try:
                record = self._gdb.command('-break-insert ' + _mi_quote(symbol))
            except Exception:
                continue
            bkpt = record.results.get('bkpt') or {}
            if not isinstance(bkpt, dict):
                continue
            number = str(bkpt.get('number', ''))
            if number:
                self._function_breakpoints.append(number)
                meta = self._breakpoint_meta(bp)
                if meta:
                    self._bp_meta[number] = meta
            entry = {'verified': True}
            if number:
                entry['id'] = _int_or_none(number) or 1
            line = _int_or_none(bkpt.get('line'))
            if line:
                entry['line'] = line
            fullname = bkpt.get('fullname') or bkpt.get('file') or ''
            if fullname:
                entry['source'] = {'name': os.path.basename(fullname),
                                   'path': os.path.normpath(fullname)}
            if meta.get('hitConditionError'):
                entry['message'] = meta['hitConditionError']
            return entry
        return entry

    def _function_symbol_candidates(self, name: str) -> list:
        """Candidate C++ symbols for a Vanta function name."""
        text = str(name or '').strip()
        if not text:
            return []
        candidates: list = []

        def add(value):
            if value and value not in candidates:
                candidates.append(value)

        if '.' in text:
            module, _, base = text.rpartition('.')
            add(f'vanta_user::fn_vanta_m_{module}__{base}')
            add(f'fn_vanta_m_{module}__{base}')
        add(f'vanta_user::fn_{text}')
        add(f'fn_{text}')
        add(text)
        return candidates

    def _delete_function_breakpoints(self):
        for number in self._function_breakpoints:
            try:
                self._gdb.command(f'-break-delete {number}')
            except Exception:
                pass
            self._bp_meta.pop(number, None)
        self._function_breakpoints = []

    def _apply_breakpoints(self, source, requested):
        assert self._gdb is not None
        key = os.path.normcase(os.path.abspath(source))
        for number in self._gdb_breakpoints.pop(key, []):
            try:
                self._gdb.command(f'-break-delete {number}')
            except Exception:
                pass
        numbers = []
        out = []
        path = os.path.abspath(source).replace('\\', '/')
        for bp in requested:
            line = _int_or_none(bp.get('line')) or 1
            location = f'{path}:{line}'
            try:
                record = self._gdb.command('-break-insert -f ' + _mi_quote(location))
                bkpt = record.results.get('bkpt') or {}
                if not isinstance(bkpt, dict):
                    out.append({'verified': False, 'line': line,
                                'message': 'GDB returned no breakpoint'})
                    continue
                number = str(bkpt.get('number', ''))
                meta = self._breakpoint_meta(bp)
                if number:
                    numbers.append(number)
                    if meta:
                        self._bp_meta[number] = meta
                actual_line = _int_or_none(bkpt.get('line')) or line
                pending = bool(bkpt.get('pending'))
                entry = {
                    'id': _int_or_none(number) or len(out) + 1,
                    'verified': bool(bkpt.get('addr')) and not pending,
                    'line': actual_line,
                    'source': {'name': os.path.basename(source), 'path': source},
                }
                if pending:
                    entry['message'] = 'pending until the code is loaded'
                if meta.get('hitConditionError'):
                    entry['message'] = meta['hitConditionError']
                out.append(entry)
            except Exception as exc:
                out.append({'verified': False, 'line': line,
                            'message': str(exc)})
        self._gdb_breakpoints[key] = numbers
        return out

    # -- execution helpers -------------------------------------------------

    def _evaluate_expression(self, expression: str):
        """Evaluate an expression in the current frame.

        Vanta names are tried first through the generated ``v_`` prefix, so
        conditions and log messages can be written in Vanta terms.  Returns a
        ``(value, ok)`` pair.
        """
        if self._gdb is None:
            return '', False
        text = str(expression or '').strip()
        if not text:
            return '', False
        candidates = [text]
        translated = _translate_vanta_expression(text)
        if translated != text:
            candidates.append(translated)
        for candidate in candidates:
            try:
                record = self._gdb.command('-data-evaluate-expression ' +
                                           _mi_quote(candidate))
            except Exception:
                continue
            return str(record.results.get('value', '')), True
        return '', False

    def _should_skip_breakpoint(self, meta: dict) -> bool:
        """Decide whether a breakpoint hit should pass without stopping."""
        hit_condition = meta.get('hitCondition')
        if hit_condition:
            count = int(meta.get('hits', 0)) + 1
            meta['hits'] = count
            matched = _hit_condition_matches(hit_condition, count)
            if matched is None:
                self.output('console',
                            f'vanta debugger: unsupported hit condition '
                            f'{hit_condition!r}\n')
            elif not matched:
                return True
        condition = meta.get('condition')
        if condition:
            value, ok = self._evaluate_expression(condition)
            if not ok:
                self.output('console',
                            f'vanta debugger: cannot evaluate breakpoint '
                            f'condition {condition!r}\n')
                return False
            if not _is_truthy(value):
                return True
        log_message = meta.get('logMessage')
        if log_message:
            text = _interpolate_log_message(log_message,
                                             self._evaluate_expression)
            self.output('console', text.rstrip('\n') + '\n')
            return True
        return False

    def _auto_continue(self):
        """Resume the program after a skipped breakpoint hit."""
        try:
            self._gdb.run_command('-exec-continue')
        except Exception as exc:
            self.output('console', f'vanta debugger: cannot continue: {exc}\n')
            return
        self._stopped = False
        self._running_inferior = True

    def _add_watch(self, expression: str, frame_id: Optional[int]):
        for watch in self._watch_expressions:
            if watch['expression'] == expression:
                watch['frameId'] = frame_id
                return
        self._watch_expressions.append({'expression': expression,
                                        'frameId': frame_id})

    def _resume(self, request, command):
        if self._gdb is None:
            self.error(request, 'debugger has not been launched')
            return
        try:
            self._gdb.run_command(command)
        except Exception as exc:
            self.error(request, exc)
            return
        self._stopped = False
        self._running_inferior = True
        self.event('continued', {
            'threadId': self._current_thread or 1,
            'allThreadsContinued': True,
        })
        self.response(request)

    def _select_thread(self, thread_id):
        if self._gdb is None:
            return
        if self._current_thread == thread_id:
            return
        try:
            self._gdb.command(f'-thread-select {thread_id}')
            self._current_thread = thread_id
        except Exception:
            pass

    def _select_frame(self, thread_id, level):
        self._select_thread(thread_id)
        if self._gdb is None:
            return
        try:
            self._gdb.command(f'-stack-select-frame {level}')
        except Exception:
            pass

    def _new_var_ref(self, thread_id, level, kind):
        ref = self._next_var_ref
        self._next_var_ref += 1
        self._variable_refs[ref] = (thread_id, level, kind)
        return ref

    def _variables_for(self, thread_id, level, kind):
        if kind == 'watch':
            return self._watch_variables()
        if kind == 'arguments':
            record = self._gdb.command('-stack-list-arguments --simple-values')
            args = []
            for item in record.results.get('stack-args', []) or []:
                if not isinstance(item, dict):
                    continue
                frame = item.get('frame', {})
                if _int_or_none(frame.get('level')) not in (None, level):
                    continue
                args.extend(frame.get('args', []) or [])
            return self._format_variables(args)
        record = self._gdb.command('-stack-list-variables --simple-values')
        return self._format_variables(record.results.get('variables', []) or [],
                                      include_arguments=False)

    def _watch_variables(self):
        """Evaluate the watch expressions for the Watch scope."""
        out = []
        for watch in self._watch_expressions:
            expression = watch['expression']
            value, ok = self._evaluate_expression(expression)
            out.append({
                'name': expression,
                'value': value if ok else '<not available>',
                'type': '',
                'variablesReference': 0,
            })
        return out

    def _format_variables(self, raw, include_arguments=True):
        out = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            name = str(item.get('name', ''))
            if not name:
                continue
            if name.startswith('__'):
                continue
            if not include_arguments and str(item.get('arg', '')) == '1':
                continue
            display = name[2:] if name.startswith('v_') else name
            if display.startswith('__'):
                continue
            value = item.get('value', '')
            if value is None:
                value = ''
            type_name = _vanta_type(item.get('type', ''))
            out.append({
                'name': display,
                'value': str(value),
                'type': type_name,
                'variablesReference': 0,
            })
        return out

    # -- GDB events --------------------------------------------------------

    def _handle_gdb_event(self, record: MiRecord):
        if record is None:
            return
        if record.sign in ('~', '@', '&'):
            text = record.text or ''
            if text.strip() == '(gdb)':
                return
            if record.sign == '&':
                self.output('console', text)
            elif _is_gdb_console_text(text):
                self.output('console', text)
            elif record.sign == '@':
                # GDB wraps the inferior's stderr as @ records on its own
                # stderr pipe.  Keep the DAP category honest.
                self.output('stderr', text)
            else:
                self.output('stdout', text)
            return
        if record.sign == 'eof':
            if not self._terminated:
                self._emit_terminated(None)
            return
        if record.sign == 'plain':
            text = record.text or ''
            if text.strip() and text.strip() != '(gdb)':
                self.output('stdout', text)
            return
        if record.sign == '^':
            return
        if record.sign == '=':
            if record.class_ == 'thread-created':
                tid = _int_or_none(record.results.get('id'))
                if tid is not None:
                    self._threads[tid] = record.results
            return
        if record.sign == '*':
            if record.class_ == 'running':
                self._running_inferior = True
                self._stopped = False
                return
            if record.class_ == 'stopped':
                self._handle_stopped(record.results)
                return

    def _handle_stopped(self, results):
        reason = str(results.get('reason', 'stop'))
        thread_id = _int_or_none(results.get('thread-id'))
        if thread_id is not None:
            self._current_thread = thread_id
        frame = results.get('frame') or {}
        func = str(frame.get('func', ''))
        bkptno = str(results.get('bkptno', ''))

        if reason in ('exited-normally', 'exited', 'exited-signalled'):
            code = _int_or_none(results.get('exit-code'))
            if code is None:
                code = 1 if reason == 'exited-signalled' else 0
            self._emit_terminated(code)
            return

        self._stopped = True
        self._running_inferior = False
        self._variable_refs.clear()

        meta = self._bp_meta.get(bkptno) if bkptno else None
        if meta and self._should_skip_breakpoint(meta):
            self._auto_continue()
            return

        dap_reason = 'breakpoint'
        if reason in ('end-stepping-range', 'function-finished'):
            dap_reason = 'step'
        elif reason == 'signal-received':
            dap_reason = 'exception'
        elif reason in ('entry', 'starting'):
            dap_reason = 'entry'
        elif reason in ('breakpoint-hit',):
            dap_reason = 'breakpoint'
        elif reason == 'watchpoint-trigger':
            dap_reason = 'data breakpoint'
        if self._entry_bp_number and bkptno == self._entry_bp_number:
            dap_reason = 'entry'
            self._entry_bp_number = None

        body = {
            'reason': dap_reason,
            'threadId': self._current_thread or 1,
            'allThreadsStopped': True,
            'preserveFocusHint': False,
        }
        if dap_reason == 'breakpoint' and bkptno:
            breakpoint_id = _int_or_none(bkptno)
            if breakpoint_id is not None:
                body['hitBreakpointIds'] = [breakpoint_id]
        if dap_reason == 'exception':
            name = results.get('signal-name', 'signal')
            meaning = results.get('signal-meaning', '')
            body['text'] = f'{name} {meaning}'.strip()
            body['description'] = body['text']
        self.event('stopped', body)

    def _emit_terminated(self, exit_code):
        if self._terminated:
            return
        self._terminated = True
        self._running_inferior = False
        self._stopped = False
        self._last_exit_code = exit_code
        self.event('exited', {'exitCode': exit_code if exit_code is not None else 0})
        self.event('terminated')

    def _terminate_inferior(self):
        if self._gdb is None:
            return
        try:
            # Let GDB kill the inferior cleanly before the adapter shuts down.
            self._gdb.run_command('-exec-interrupt')
        except Exception:
            pass
        self._shutdown(cleanup=True)

    def _stop_inferior(self):
        """Stop a running inferior so the program can be restarted."""
        if self._gdb is None:
            return
        try:
            self._gdb.run_command('-exec-interrupt')
        except Exception:
            pass
        for command in ('-exec-terminate',
                        '-interpreter-exec console "kill"'):
            try:
                self._gdb.run_command(command)
                return
            except Exception:
                continue

    # -- cleanup -----------------------------------------------------------

    def _cleanup_build(self):
        if self._build:
            tempdir = self._build.get('tempdir')
            if tempdir:
                shutil.rmtree(tempdir, ignore_errors=True)
            self._build = None

    def _shutdown(self, cleanup=False):
        self._running = False
        if self._gdb is not None:
            try:
                self._gdb.close()
            except Exception:
                pass
            self._gdb = None
        if cleanup:
            self._cleanup_build()


# ---------------------------------------------------------------------------
# Small formatting helpers
# ---------------------------------------------------------------------------


def _int_or_none(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _frame_name(func: str) -> str:
    func = func.strip()
    if '(' in func:
        func = func.split('(', 1)[0]
    if '::' in func:
        func = func.rsplit('::', 1)[-1]
    if func.startswith('fn_'):
        func = func[3:]
    # Module functions are emitted as fn_vanta_m_<module>__<name>.  Show the
    # source-level qualified name rather than the loader's internal spelling.
    if func.startswith('vanta_m_'):
        module_and_name = func[len('vanta_m_'):]
        if '__' in module_and_name:
            module, name = module_and_name.split('__', 1)
            func = f'{module}.{name}'
    return func or '<unknown>'


def _vanta_type(type_name: str) -> str:
    if not type_name:
        return ''
    out = str(type_name)
    replacements = {
        'int8_t': 'i8', 'uint8_t': 'u8',
        'int16_t': 'i16', 'uint16_t': 'u16',
        'int32_t': 'i32', 'uint32_t': 'u32',
        'float': 'f32', 'double': 'f64', 'bool': 'bool',
    }
    for cpp, vanta in replacements.items():
        out = re.sub(r'\b' + re.escape(cpp) + r'\b', vanta, out)
    out = out.replace('vanta::', '')
    out = out.replace('std::', '')
    # Str is the runtime spelling of Vanta's str; StrBuilder stays as-is
    # because the two capital letters are part of a longer word.
    out = re.sub(r'\bStr\b', 'str', out)
    return out


# Identifiers that must keep their meaning when a Vanta expression is
# rewritten into the names the code generator emits.
_CPP_KEYWORDS = frozenset({
    'and', 'asm', 'auto', 'bool', 'break', 'case', 'catch', 'char', 'class',
    'const', 'constexpr', 'continue', 'decltype', 'default', 'delete', 'do',
    'double', 'else', 'enum', 'explicit', 'extern', 'false', 'float', 'for',
    'friend', 'goto', 'if', 'inline', 'int', 'long', 'mutable', 'namespace',
    'new', 'noexcept', 'not', 'nullptr', 'operator', 'or', 'private',
    'protected', 'public', 'register', 'restrict', 'return', 'short',
    'signed', 'sizeof', 'static', 'struct', 'switch', 'template', 'this',
    'throw', 'true', 'try', 'typedef', 'typeid', 'typename', 'union',
    'unsigned', 'using', 'virtual', 'void', 'volatile', 'while', 'xor',
})

_HIT_CONDITION_RE = re.compile(r'^\s*(==|>=|<=|!=|>|<)?\s*(\d+)\s*$')
_HIT_MODULO_RE = re.compile(r'^\s*%\s*(\d+)\s*==\s*0\s*$')


def _translate_vanta_expression(expression: str) -> str:
    """Rewrite a Vanta-flavoured expression into the generated C++ names.

    User variables are emitted as ``v_<name>``, so a condition like
    ``x > 5`` has to become ``v_x > 5`` before GDB can evaluate it.  String
    literals are left alone, C++ keywords keep their meaning, and ``len(x)``
    is rewritten to the field the code generator inlines.
    """
    if not expression:
        return expression

    def rewrite_identifier(match):
        name = match.group(0)
        if name in _CPP_KEYWORDS or name.startswith('v_'):
            return name
        return 'v_' + name

    def rewrite_part(part: str) -> str:
        part = re.sub(r'\b[A-Za-z_][A-Za-z0-9_]*\b', rewrite_identifier, part)
        # The code generator inlines len(x) as (x).h->len, so the rewritten
        # v_len(x) has to become the same field access.
        part = re.sub(r'\bv_len\(([^()]*)\)', r'(\1).h->len', part)
        return part

    # Split out string literals so their contents are never rewritten.
    parts = re.split(r'("(?:[^"\\]|\\.)*")', expression)
    for index, part in enumerate(parts):
        if index % 2:
            continue
        parts[index] = rewrite_part(part)
    return ''.join(parts)


def _hit_condition_matches(spec, count: int) -> Optional[bool]:
    """Evaluate a DAP hit condition against a hit count.

    Returns True when the breakpoint should stop, False when the hit should
    be skipped, and None when the condition is not understood.
    """
    if spec is None:
        return None
    text = str(spec).strip()
    if not text:
        return None
    match = _HIT_MODULO_RE.match(text)
    if match:
        period = int(match.group(1))
        if period <= 0:
            return None
        return count % period == 0
    match = _HIT_CONDITION_RE.match(text)
    if not match:
        return None
    operator = match.group(1) or '=='
    value = int(match.group(2))
    if operator == '==':
        return count == value
    if operator == '>=':
        return count >= value
    if operator == '<=':
        return count <= value
    if operator == '>':
        return count > value
    if operator == '<':
        return count < value
    if operator == '!=':
        return count != value
    return None


def _interpolate_log_message(message: str, evaluate) -> str:
    """Fill a DAP ``logMessage`` template, evaluating ``{expression}`` holes.

    ``evaluate`` is called with the expression text and returns a
    ``(value, ok)`` pair.
    """
    if not message:
        return ''
    out = []
    index = 0
    while index < len(message):
        char = message[index]
        if char == '{':
            end = message.find('}', index)
            if end != -1:
                expression = message[index + 1:end]
                value, ok = evaluate(expression)
                out.append(value if ok else '{' + expression + '}')
                index = end + 1
                continue
        out.append(char)
        index += 1
    return ''.join(out)


def _is_truthy(value) -> bool:
    """Interpret a GDB expression result as a boolean."""
    text = str(value).strip()
    if not text:
        return False
    return text not in ('0', 'false', 'False', 'FALSE')


def _is_gdb_console_text(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    prefixes = (
        'Reading symbols', 'Thread ', '[New Thread', '[Thread',
        'Breakpoint ', 'Temporary breakpoint ', 'Program received',
        'Program exited', 'Inferior ', '[Inferior', 'warning:',
        'Cannot ', 'No symbol', 'The program',
    )
    return stripped.startswith(prefixes)


def run_stdio() -> int:
    """Run the Vanta debug adapter on stdin/stdout."""
    adapter = DapAdapter()
    try:
        adapter.serve()
    finally:
        # DAP's stdin reader is a daemon thread blocked in readline() unless
        # the client closed the pipe.  Letting interpreter shutdown fight
        # that thread over the buffered stdin lock produces a fatal Python
        # error, so a stdio adapter exits after its cleanup is complete.
        try:
            sys.stdout.flush()
            sys.stderr.flush()
        except Exception:
            pass
        os._exit(0)
    return 0
