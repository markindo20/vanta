import os
import random
import shutil
import tempfile
import time
import unittest

sys_path_inserted = False
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from compiler.driver import (
    _build_cache_key,
    _build_cache_root,
    _dependency_files_for_cache,
    _prune_build_cache_root,
)

NSEED = 0x534F4C41522042414443  # fixed seed for reproducible CI behaviour
MAX_CASES = 24


def write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(content)


class BuildCachePropertyTests(unittest.TestCase):
    def setUp(self):
        self._saved_env = {
            'VANTA_PATH': os.environ.get('VANTA_PATH'),
            'VANTA_CACHE_MAX_MB': os.environ.get('VANTA_CACHE_MAX_MB'),
            'VANTA_CACHE_MAX_AGE_DAYS': os.environ.get(
                'VANTA_CACHE_MAX_AGE_DAYS'),
        }

    def tearDown(self):
        for key, value in self._saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def cache_key(self, source, **kwargs):
        return _build_cache_key(
            source,
            kwargs.get('release', False),
            kwargs.get('debug', False),
            kwargs.get('checked', True),
            kwargs.get('include_dir', []),
            kwargs.get('lib_dir', []),
            kwargs.get('link', []),
        )

    def test_dependency_files_are_unique_and_sorted(self):
        rng = random.Random(NSEED)
        for case in range(MAX_CASES):
            with tempfile.TemporaryDirectory(
                    prefix='vanta_cache_order_') as root:
                n = rng.randrange(2, 7)
                # A family of unrelated modules plus one entry. Using dotted
                # package names deliberately exercises lexicographic ordering.
                files = {}
                for i in range(n):
                    name = 'module_%02d.vnt' % i
                    files[name] = 'func value%d() -> i32:\n    return %d\n' % (
                        i, i)
                main_name = 'z_entry.vnt'
                dependencies = rng.sample(
                    ['module_%02d.vnt' % i for i in range(n)],
                    rng.randrange(0, n + 1))
                imports = ''.join('import "%s"\n' % name
                                  for name in dependencies)
                files[main_name] = imports + (
                    'func main() -> void:\n    return\n')
                entry = os.path.join(root, main_name)
                for name, content in files.items():
                    write(os.path.join(root, name), content)

                found = _dependency_files_for_cache(entry)
                self.assertTrue(found, 'empty dependency graph for case %d' % case)
                self.assertEqual(found, sorted(set(found)),
                                 'not canonical order at case %d' % case)
                # The set is exactly the imported closure (plus toolchain, which
                # is deterministic and contains the source directory's own files
                # already present in every key).  Imported user dependencies
                # must be included.
                for dep in dependencies:
                    self.assertIn(
                        os.path.normcase(os.path.realpath(
                            os.path.join(root, dep))), found,
                        '%s missing at case %d' % (dep, case))

    def test_source_and_unreachable_participants_are_sorted_together(self):
        rng = random.Random(NSEED ^ 0x9E3779B9)
        for case in range(MAX_CASES):
            with tempfile.TemporaryDirectory(
                    prefix='vanta_cache_sort_') as root:
                # Base graph intentionally import-spectrum varied.
                importable = []
                for i in range(rng.randrange(2, 5)):
                    name = 'dep_%02d.vnt' % i
                    importable.append(name)
                    write(os.path.join(root, name),
                          'func dep%d() -> i32:\n    return %d\n' % (i, i))
                entry_name = 'entry.vnt'
                selected = sorted(
                    rng.sample(importable, rng.randrange(0, len(importable) + 1)))
                ordered_one = ''.join(
                    'import "%s"\n' % name for name in selected)
                ordered_two = ''.join(
                    'import "%s"\n' % name
                    for name in reversed(selected))
                write(os.path.join(root, entry_name), ordered_one + (
                    'func main() -> void:\n    return\n'))
                first_files = tuple(_dependency_files_for_cache(
                    os.path.join(root, entry_name)))
                write(os.path.join(root, entry_name), ordered_two + (
                    'func main() -> void:\n    return\n'))
                second_files = tuple(_dependency_files_for_cache(
                    os.path.join(root, entry_name)))
                self.assertEqual(
                    first_files, second_files,
                    'import order changed dependency discovery at case %d'
                    % case)

    def test_unrelated_files_do_not_invalidate_cache_key(self):
        rng = random.Random(0xC0FFEE + (NSEED ^ 0x13579BDF))
        for case in range(MAX_CASES):
            with tempfile.TemporaryDirectory(
                    prefix='vanta_cache_unrelated_') as root:
                write(os.path.join(root, 'entry.vnt'),
                      'func main() -> void:\n    return\n')
                key_before = self.cache_key(os.path.join(root, 'entry.vnt'))
                # Sprinkle unrelated files throughout the project. They must
                # never become part of the dependency set, nor the hash.
                for i in range(rng.randrange(3, 9)):
                    rel = os.path.join(
                        root if rng.randrange(2) else os.path.join(
                            root, 'later%d' % rng.randrange(4)),
                        'noise_%03d.vnt' % (i,))
                    write(rel, 'func accidental() -> i32:\n    return %d\n' % i)
                key_after = self.cache_key(os.path.join(root, 'entry.vnt'))
                self.assertEqual(
                    key_before, key_after,
                    'unrelated file invalidated cache at case %d' % case)

    def test_unrelated_mutation_does_not_change_hash_across_variants(self):
        rng = random.Random(0xABCD1234)
        for case in range(MAX_CASES):
            with tempfile.TemporaryDirectory(
                    prefix='vanta_cache_mutate_') as root:
                entry = os.path.join(root, 'entry.vnt')
                unrelated = os.path.join(root, 'other.vnt')

                write(entry, 'func main() -> void:\n    return\n')
                write(unrelated, 'func helper() -> i32:\n    return 1\n')
                key_before = self.cache_key(entry)
                # mutate unrelated file many times
                for mutation in range(5):
                    write(unrelated, (
                        'func helper() -> i32:\n    return %d\n'
                        % (mutation * 97 + 1)))
                    key_after = self.cache_key(entry)
                    self.assertEqual(
                        key_before, key_after,
                        'unrelated mutation %d changed hash at case %d'
                        % (mutation, case))

    def test_missing_import_does_not_scan_neighbourhood(self):
        rng = random.Random(0x0F1EA0)
        for case in range(MAX_CASES):
            with tempfile.TemporaryDirectory(
                    prefix='vanta_cache_missing_') as root:
                entry = os.path.join(root, 'entry.vnt')
                unrelated = os.path.join(
                    root, 'not_an_import_%d.vnt' % case)
                write(entry, (
                    'import "missing_%d.vnt"\n'
                    'func main() -> void:\n    return\n') % case)
                # Make the "missing" name a directory boundary hazard.
                os.makedirs(os.path.join(root, 'missing_%d.vnt' % case),
                            exist_ok=True)
                before = _dependency_files_for_cache(entry)
                write(unrelated, 'this must be irrelevant')
                after = _dependency_files_for_cache(entry)
                self.assertEqual(before, after,
                                 'missing import scanned unrelated file')
                self.assertNotIn(
                    os.path.normcase(os.path.realpath(unrelated)), after,
                    'unrelated file appeared in missing-import cache graph')

    def test_imported_dependency_reliably_invalidates_key(self):
        root, files = self._make_import_project()
        entry = os.path.join(root, 'entry.vnt')
        imported = os.path.join(root, 'imported.vnt')
        before = self.cache_key(entry)
        write(imported, 'func imported() -> i32:\n    return 2\n')
        after = self.cache_key(entry)
        self.assertNotEqual(before, after,
                            'changed import did not invalidate key')

    def test_pruning_retains_one_valid_entry_after_failed_promotion(self):
        os.environ['VANTA_CACHE_MAX_MB'] = '1'
        os.environ['VANTA_CACHE_MAX_AGE_DAYS'] = '0'
        with tempfile.TemporaryDirectory(
                prefix='vanta_cache_prune_') as root:
            source = os.path.join(root, 'entry.vnt')
            write(source, 'func main() -> void:\n    return\n')
            cache_root = _build_cache_root(source)
            os.makedirs(cache_root, exist_ok=True)
            now = time.time()
            entries = [
                ('old', 2 * 1024 * 1024, now - 100),
                ('middle', 2 * 1024 * 1024, now - 50),
                ('newest', 2 * 1024 * 1024, now - 1),
            ]
            for name, size, mtime in entries:
                path = os.path.join(cache_root, name)
                os.makedirs(path, exist_ok=True)
                exe = os.path.join(
                    path, 'prog.exe' if os.name == 'nt' else 'prog')
                with open(exe, 'wb') as f:
                    f.write(b'x' * size)
                os.utime(path, (mtime, mtime))
            # A failed promotion leaves a directory with no executable and a
            # scratch artifact. It must not be treated as a valid active
            # entry and must not cause all valid entries to be dropped.
            failed = os.path.join(cache_root, 'failed-promotion')
            os.makedirs(failed, exist_ok=True)
            with open(os.path.join(
                    failed, '.scratch_partial'),
                      'wb') as f:
                f.write(b'nobody')
            before = [
                name for name, _, _ in entries if os.path.isfile(
                    os.path.join(cache_root, name,
                                 'prog.exe' if os.name == 'nt' else 'prog'))]
            self.assertGreater(len(before), 1)

            _prune_build_cache_root(source)

            valid_after = []
            for name in os.listdir(cache_root):
                candidate = os.path.join(cache_root, name)
                if not os.path.isdir(candidate):
                    continue
                exe = os.path.join(
                    candidate, 'prog.exe' if os.name == 'nt' else 'prog')
                if os.path.isfile(exe):
                    valid_after.append(name)
            self.assertGreaterEqual(
                len(valid_after), 1,
                'pruning removed every valid active cache entry')
            self.assertIn('newest', valid_after,
                          'pruning did not retain the newest active entry')

    def _make_import_project(self):
        root = tempfile.mkdtemp(prefix='vanta_cache_import_')
        imported = os.path.join(root, 'imported.vnt')
        entry = os.path.join(root, 'entry.vnt')
        write(imported, 'func imported() -> i32:\n    return 1\n')
        write(entry, (
            'import "imported.vnt"\n'
            'func main() -> void:\n    print_i32(imported())\n'))
        return root, [imported, entry]


if __name__ == '__main__':
    unittest.main()
