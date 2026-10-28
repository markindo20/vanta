"""Smoke test for scripts/lsp_profile.py: run one tiny scenario end to end
and sanity-check the percentile helper, without re-running the whole
documented benchmark in the test suite."""
import importlib.util
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

_SCRIPT = os.path.join(HERE, 'scripts', 'lsp_profile.py')

_spec = importlib.util.spec_from_file_location('vanta_lsp_profile', _SCRIPT)
lsp_profile = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lsp_profile)


class LspProfileScriptTests(unittest.TestCase):
    def test_percentile_bounds(self):
        self.assertEqual(lsp_profile.percentile([], 0.5), 0.0)
        self.assertEqual(lsp_profile.percentile([1.0], 0.99), 1.0)
        values = [float(i) for i in range(100)]
        # Nearest-rank: index = round(p * (n - 1)); p50 of 0..99 lands on 50.
        self.assertEqual(lsp_profile.percentile(values, 0.5), 50.0)
        self.assertEqual(lsp_profile.percentile(values, 0.95), 94.0)
        self.assertEqual(lsp_profile.percentile(values, 0.99), 98.0)
        # Clamped at both ends for extreme p.
        self.assertEqual(lsp_profile.percentile(values, 0.0), 0.0)
        self.assertEqual(lsp_profile.percentile(values, 1.0), 99.0)

    def test_append_tap_records_completion_position(self):
        text, (line, char) = lsp_profile._append_tap('func main() -> void:\n'
                                                     '    print_i32(0)\n', 3)
        self.assertIn('func tap_3() -> i32:', text)
        self.assertEqual(line, 4)
        self.assertTrue(char > 0)

    def test_single_file_scenario_runs(self):
        if importlib.util.find_spec('compiler.lsp') is None:
            self.skipTest('compiler.lsp unavailable')
        tmp = tempfile.mkdtemp(prefix='vanta_lsp_script_')
        try:
            path = os.path.join(tmp, 'tiny.vnt')
            with open(path, 'w', encoding='utf-8', newline='\n') as f:
                f.write('func main() -> void:\n'
                        '    print_i32(1)\n')
            os.environ['VANTA_LSP_PROFILE'] = '1'
            self.addCleanup(os.environ.pop, 'VANTA_LSP_PROFILE', None)
            server = lsp_profile.LanguageServer()
            server.handle_message({
                'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
                'params': {'rootUri': None},
            })
            bench = lsp_profile.Bench()
            lsp_profile.scenario_single(bench, server, path, edits=2)
            self.assertIn('single.edit', bench.samples)
            self.assertIn('single.completion', bench.samples)
            for bucket in ('single.edit', 'single.completion'):
                for ms, _files in bench.samples[bucket]:
                    self.assertGreater(ms, 0.0)
            # The diagnostics profile lines carry a real elapsed value.
            self.assertEqual(len(bench.samples['single.edit']), 2)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
