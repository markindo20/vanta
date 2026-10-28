#!/usr/bin/env python
"""Measure real editor scenarios against the Vanta language server.

Drives the actual ``LanguageServer`` message paths in-process: initialize,
textDocument/didOpen, textDocument/didChange (full sync, as the advertised
capability requests), and textDocument/completion. Diagnostics timings come
from the server's own ``VANTA_LSP_PROFILE`` stderr records, so the numbers
are what an editor would wait for.

Scenarios
---------
single-file   cold open of examples/pong.vnt, then repeated full-content
              edits followed by a completion request (the dominant typing
              loop).
multi-file    the same edit loop while three documents are open and the
              edited file is an imported module (gamekit/input.vnt).
workspace-wide didOpen every example and game kit module (per-file cold
              validation), then a full sweep of one edit per open document,
              reporting per-operation and total wall times.

Usage:  python scripts/lsp_profile.py [--edits N] [--json PATH]
"""
import argparse
import io
import json
import os
import re
import shutil
import sys
import tempfile
import time
from contextlib import redirect_stderr

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from compiler.lsp import LanguageServer, path_to_uri  # noqa: E402

_PROFILE_RE = re.compile(
    r'vanta lsp profile: phase=(\S+) .*elapsed_ms=([0-9.]+)'
    r'(?: files=(\d+) published=(\d+))?')


def percentile(values, p):
    """Nearest-rank percentile; values already sorted."""
    if not values:
        return 0.0
    index = max(0, min(len(values) - 1, int(p * (len(values) - 1) + 0.5)))
    return values[index]


class Bench:
    def __init__(self):
        self.samples = {}

    def record(self, bucket, ms, files=None):
        self.samples.setdefault(bucket, []).append((ms, files))

    def call(self, server, message, bucket):
        """Run one message, recording wall time and the server's own
        diagnostics profile line when present."""
        err = io.StringIO()
        started = time.perf_counter()
        with redirect_stderr(err):
            responses = server.handle_message(message)
        wall_ms = (time.perf_counter() - started) * 1000.0
        phase_ms = None
        files = None
        for line in err.getvalue().splitlines():
            m = _PROFILE_RE.match(line)
            if m and m.group(1) in ('diagnostics', 'stale diagnostic'):
                phase_ms = float(m.group(2))
                if m.group(3) is not None:
                    files = int(m.group(3))
        # Prefer the server's own measurement of the diagnostic phase; the
        # surrounding wall time stays available for requests without one.
        self.record(bucket, phase_ms if phase_ms is not None else wall_ms,
                    files)
        return responses


def _did_open(path):
    with open(path, encoding='utf-8-sig') as f:
        text = f.read()
    return {
        'jsonrpc': '2.0',
        'method': 'textDocument/didOpen',
        'params': {'textDocument': {
            'uri': path_to_uri(os.path.abspath(path)),
            'languageId': 'vanta', 'version': 1, 'text': text,
        }},
    }


def _did_change(uri, text, version):
    return {
        'jsonrpc': '2.0',
        'method': 'textDocument/didChange',
        'params': {'textDocument': {'uri': uri, 'version': version},
                   'contentChanges': [{'text': text}]},
    }


def _completion(uri, line, character):
    return {
        'jsonrpc': '2.0', 'id': 7,
        'method': 'textDocument/completion',
        'params': {'textDocument': {'uri': uri},
                   'position': {'line': line, 'character': character}},
    }


def _append_tap(text, index):
    """Append one tiny function; returns (new text, completion position)."""
    addition = f'\nfunc tap_{index}() -> i32:\n    return {index}\n'
    new_text = text + addition
    lines = new_text.splitlines()
    return new_text, (len(lines) - 1, len(lines[-1]))


def scenario_single(bench, server, path, edits):
    text = open(path, encoding='utf-8-sig').read()
    uri = path_to_uri(os.path.abspath(path))
    bench.call(server, _did_open(path), 'single.open')
    for i in range(edits):
        new_text, pos = _append_tap(text, i)
        bench.call(server, _did_change(uri, new_text, 2 + i), 'single.edit')
        bench.call(server, _completion(uri, *pos), 'single.completion')
        text = new_text


def scenario_multi(bench, server, root, edits):
    """Edit gamekit/input.vnt while three documents stay open."""
    gamekit = os.path.join(root, 'gamekit')
    main_path = os.path.join(root, 'bench_main.vnt')
    with open(main_path, 'w', encoding='utf-8', newline='\n') as f:
        f.write('import "gamekit/input.vnt"\n'
                '\n'
                'func main() -> void:\n'
                '    print_i32(EV_MOUSEMOTION)\n')

    input_uri = path_to_uri(os.path.abspath(os.path.join(gamekit, 'input.vnt')))
    for rel in ('input.vnt', 'gfx.vnt'):
        bench.call(server, _did_open(os.path.join(gamekit, rel)),
                   'multi.open')
    bench.call(server, _did_open(main_path), 'multi.open')

    text = open(os.path.join(gamekit, 'input.vnt'),
                encoding='utf-8-sig').read()
    for i in range(edits):
        new_text, pos = _append_tap(text, i)
        bench.call(server, _did_change(input_uri, new_text, 2 + i),
                   'multi.edit')
        bench.call(server, _completion(input_uri, *pos),
                   'multi.completion')
        text = new_text
    os.remove(main_path)


def scenario_workspace(bench, server, root):
    paths = []
    for base in (os.path.join(root), os.path.join(root, 'gamekit')):
        for name in sorted(os.listdir(base)):
            if name.endswith('.vnt'):
                paths.append(os.path.join(base, name))
    opened = {}
    for path in paths:
        bench.call(server, _did_open(path), 'workspace.open')
        opened[path_to_uri(os.path.abspath(path))] = \
            open(path, encoding='utf-8-sig').read()

    started = time.perf_counter()
    for i, path in enumerate(paths):
        uri = path_to_uri(os.path.abspath(path))
        text, _ = _append_tap(opened[uri], i)
        opened[uri] = text
        bench.call(server, _did_change(uri, text, 2 + i), 'workspace.edit')
    sweep_ms = (time.perf_counter() - started) * 1000.0
    bench.record('workspace.sweep', sweep_ms)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--edits', type=int, default=30,
                        help='edits per single/multi scenario')
    parser.add_argument('--json', metavar='PATH',
                        help='also write the raw samples as JSON')
    args = parser.parse_args()

    os.environ['VANTA_LSP_PROFILE'] = '1'
    root = os.path.join(HERE, 'examples')

    server = LanguageServer()
    bench = Bench()
    server.handle_message({
        'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
        'params': {'rootUri': path_to_uri(root), 'capabilities': {}},
    })

    scenario_single(bench, server, os.path.join(root, 'pong.vnt'),
                    args.edits)
    tmp = tempfile.mkdtemp(prefix='vanta_lsp_multi_')
    try:
        shutil.copytree(os.path.join(root, 'gamekit'),
                        os.path.join(tmp, 'gamekit'))
        scenario_multi(bench, server, tmp, args.edits)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    scenario_workspace(bench, server, root)

    rows = []
    for bucket, samples in bench.samples.items():
        values = sorted(v for v, _ in samples)
        file_counts = [f for _, f in samples if f is not None]
        rows.append({
            'scenario': bucket,
            'n': len(values),
            'p50_ms': round(percentile(values, 0.50), 2),
            'p95_ms': round(percentile(values, 0.95), 2),
            'p99_ms': round(percentile(values, 0.99), 2),
            'max_ms': round(values[-1], 2),
            'files_max': max(file_counts) if file_counts else None,
        })
    if args.json:
        with open(args.json, 'w', encoding='utf-8', newline='\n') as f:
            json.dump({'rows': rows}, f, indent=2)
            f.write('\n')
    header = f"{'scenario':<20}{'n':>5}{'p50':>9}{'p95':>9}{'p99':>9}{'max':>9}"
    print(header + '  files')
    for row in rows:
        suffix = str(row['files_max']) if row['files_max'] is not None else ''
        print(f"{row['scenario']:<20}{row['n']:>5}"
              f"{row['p50_ms']:>9.2f}{row['p95_ms']:>9.2f}"
              f"{row['p99_ms']:>9.2f}{row['max_ms']:>9.2f}  {suffix}")


if __name__ == '__main__':
    main()
