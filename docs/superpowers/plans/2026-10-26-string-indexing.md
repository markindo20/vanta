# String Indexing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `s[i]` on a `str` return a bounds-checked one-byte `str`, so `s[i] == "a"` works.

**Architecture:** The parser already emits `A.Index`; only its type is missing. The type checker types a `str` index as `str` and rejects element assignment. Codegen lowers the read to `vanta::str_at_checked`, and the runtime copies the byte into its own NUL-terminated buffer. No grammar or AST change.

**Tech Stack:** Python 3 compiler (`compiler/`), standalone C++17 runtime header (`runtime/vanta_runtime.hpp`), `unittest` suites.

**Spec:** `docs/superpowers/specs/2026-10-26-string-indexing-design.md`

## Global Constraints

- `s[i]` has type `str` and holds exactly the byte at offset `i`.
- Every access is bounds-checked. Negative indices and empty strings abort.
- Abort text is exactly `vanta: string index I out of bounds (length N) at line L`.
- The result is a one-byte string that owns its byte and stays valid after the source value goes out of scope.
- `s[i] = ...` is a compile error: `cannot assign to a string element; str is immutable`.
- Indexing is byte-based, consistent with `str_len` and `str_sub`; no UTF-8 character indexing.
- No slicing, no version bump, no change to list/array/pointer indexing.
- Never disable, skip, or weaken an existing test to get green.

## Review Focus

- Empty string indexed at `0`: aborts with length 0, never reads the buffer.
- Index equal to `str_len` or negative: aborts with the exact message and Vanta line.
- A one-byte result used after its source temporary is destroyed: it owns its byte.
- Multi-byte UTF-8 input: indexing walks bytes, so a two-byte character has two positions.
- A non-`i32` index (`s["a"]`): compile error, not a silent coercion.

---

### Task 1: Type-check `str` indexing

**Files:**
- Modify: `compiler/type_checker.py:1815-1827` (`A.Index` in `_check_expr`)
- Modify: `compiler/type_checker.py:1111-1120` (`_check_assign`)
- Test: `tests/test_type_checker.py` (after `test_ptr_void_cannot_be_indexed`, around line 1910)

**Interfaces:**
- Consumes: `STR` from `compiler.typesys` (already imported in the module).
- Produces: `A.Index` with `obj.type is STR` gets `expr.type = STR`; assignment to such an index raises `CheckError("cannot assign to a string element; str is immutable")`.

- [ ] **Step 1: Write the failing tests**

Add these four tests to `TypeCheckerTests`:

```python
    def test_str_index_yields_str(self):
        run("func f() -> void:\n"
            "    let s = \"Vanta\"\n"
            "    let c: str = s[0]\n")

    def test_str_index_must_be_i32(self):
        with self.assertRaises(CheckError):
            run("func f() -> void:\n"
                "    let s = \"Vanta\"\n"
                "    let c = s[\"a\"]\n")

    def test_str_element_assignment_rejected(self):
        with self.assertRaisesRegex(
                CheckError, "cannot assign to a string element"):
            run("func f() -> void:\n"
                "    mut s = \"Vanta\"\n"
                "    s[0] = \"W\"\n")

    def test_str_element_compound_assignment_rejected(self):
        with self.assertRaisesRegex(
                CheckError, "cannot assign to a string element"):
            run("func f() -> void:\n"
                "    mut s = \"Vanta\"\n"
                "    s[0] += \"W\"\n")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m unittest tests.test_type_checker.TypeCheckerTests.test_str_index_yields_str tests.test_type_checker.TypeCheckerTests.test_str_index_must_be_i32 tests.test_type_checker.TypeCheckerTests.test_str_element_assignment_rejected tests.test_type_checker.TypeCheckerTests.test_str_element_compound_assignment_rejected -v`

Expected: `test_str_index_yields_str` fails with `cannot index a value of type str`; the two assignment tests fail because the error is `invalid assignment target`; `test_str_index_must_be_i32` already passes (the index coercion runs before the object check).

- [ ] **Step 3: Accept `STR` in `_check_expr`**

In the `A.Index` branch, after the `ptr<void>` guard and before the `PtrType`/`ArrayType`/`ListType` branch, add:

```python
            if ot is STR:
                expr.type = STR
                return STR
```

- [ ] **Step 4: Reject element assignment in `_check_assign`**

Right after `tt = self._check_expr(a.target)` (before `_is_assignable`), add:

```python
        if (isinstance(a.target, A.Index)
                and self._check_expr(a.target.obj) is STR):
            raise CheckError(
                "cannot assign to a string element; str is immutable",
                self.filename, a.pos)
```

This checks the *object*, not the target type, so assigning a whole `str` into a `ptr<str>` slot (`p[0] = s`) stays legal.

- [ ] **Step 5: Run the type-checker suite**

Run: `python -m unittest tests.test_type_checker -v`

Expected: all tests pass, including the four new ones.

- [ ] **Step 6: Commit**

```bash
git add compiler/type_checker.py tests/test_type_checker.py docs/superpowers/specs/2026-10-26-string-indexing-design.md
git commit -m "feat: type-check str indexing as a byte"
```

---

### Task 2: Checked helper and codegen

**Files:**
- Modify: `runtime/vanta_runtime.hpp:1101-1109` (after `str_sub`, add `str_at_checked`)
- Modify: `compiler/codegen_cpp.py:1496-1499` (`A.Index` in `_expr`)
- Modify: `compiler/codegen_cpp.py:1383-1387` (`A.Index` in `_lvalue`)
- Test: `tests/test_codegen.py` (after `test_list_index_emit`, around line 566)
- Test: `tests/test_integration.py` (after `test_checked_index_out_of_bounds_read_fails_loudly`, around line 1349)

**Interfaces:**
- Consumes: `s[i]` typed `STR` by Task 1.
- Produces: `inline Str vanta::str_at_checked(Str s, int32_t index, int32_t line)`. Codegen emits `vanta::str_at_checked(<obj>, <index>, <line>)`.

- [ ] **Step 1: Write the failing codegen test**

```python
    def test_str_index_emit(self):
        cpp = gen("func main() -> void:\n"
                  "    let s = \"Vanta\"\n"
                  "    print_str(s[0])\n")
        self.assertIn('vanta::print_str(vanta::str_at_checked(v_s, 0, 3));', cpp)
```

- [ ] **Step 2: Write the failing integration tests**

```python
    def test_str_index_runtime(self):
        src = (
            "func main() -> void:\n"
            "    let s = \"Vanta\"\n"
            "    print_str(s[0])\n"
            "    print_str(s[4])\n"
            "    print_bool(s[0] == \"V\")\n"
            "    print_bool(s[1] == s[0])\n"
            "    print_i32(str_len(s))\n"
            "    let joined = str_concat(s[0], s[1])\n"
            "    print_str(joined)\n"
            "    print_str(s[0][0])\n"
            "    let tail = str_concat(\"ab\", \"cd\")[1]\n"
            "    print_str(tail)\n"
            "    let i = 1 + 2\n"
            "    print_str(s[i])\n"
        )
        tmp = tempfile.mkdtemp(prefix='vanta_stridx_')
        try:
            path = os.path.join(tmp, 'stridx.vnt')
            with open(path, 'w', encoding='utf-8') as f:
                f.write(src)
            self._build_and_run(path, ['V', 'a', 'true', 'false', '5',
                                       'Va', 'V', 'b', 't'])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_str_index_out_of_bounds_fails_loudly(self):
        src = (
            "func main() -> void:\n"
            "    let s = \"abc\"\n"
            "    let i = 2 + 1\n"
            "    print_str(s[i])\n"
        )
        tmp = tempfile.mkdtemp(prefix='vanta_stridx_oob_')
        try:
            path = os.path.join(tmp, 'oob.vnt')
            with open(path, 'w', encoding='utf-8') as f:
                f.write(src)
            self._build_and_run_expect_error(
                path,
                'vanta: string index 3 out of bounds (length 3) at line 4')
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_str_index_negative_fails_loudly(self):
        src = (
            "func main() -> void:\n"
            "    let s = \"abc\"\n"
            "    print_str(s[0 - 1])\n"
        )
        tmp = tempfile.mkdtemp(prefix='vanta_stridx_neg_')
        try:
            path = os.path.join(tmp, 'neg.vnt')
            with open(path, 'w', encoding='utf-8') as f:
                f.write(src)
            self._build_and_run_expect_error(
                path,
                'vanta: string index -1 out of bounds (length 3) at line 3')
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_str_index_empty_string_fails_loudly(self):
        src = (
            "func main() -> void:\n"
            "    let s = \"\"\n"
            "    print_str(s[0])\n"
        )
        tmp = tempfile.mkdtemp(prefix='vanta_stridx_empty_')
        try:
            path = os.path.join(tmp, 'empty.vnt')
            with open(path, 'w', encoding='utf-8') as f:
                f.write(src)
            self._build_and_run_expect_error(
                path,
                'vanta: string index 0 out of bounds (length 0) at line 3')
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_str_index_is_byte_based(self):
        tmp = tempfile.mkdtemp(prefix='vanta_stridx_bytes_')
        try:
            data = os.path.join(tmp, 'utf8.bin')
            with open(data, 'wb') as f:
                f.write(b'\xc3\xa9')  # "é" in UTF-8: two bytes
            src = (
                "func main() -> void:\n"
                f"    let s = file_read(\"{data.replace(chr(92), '/')}\")\n"
                "    print_i32(str_len(s))\n"
                "    print_bool(s[0] == s[1])\n"
            )
            path = os.path.join(tmp, 'bytes.vnt')
            with open(path, 'w', encoding='utf-8') as f:
                f.write(src)
            self._build_and_run(path, ['2', 'false'])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python -m unittest tests.test_codegen.CodegenTests.test_str_index_emit tests.test_integration.IntegrationTests.test_str_index_runtime -v`

Expected: codegen assertion fails because the output contains `v_s[0]`; the integration test fails to compile because `vanta::Str` has no `operator[]`.

- [ ] **Step 4: Add `str_at_checked` to the runtime**

Immediately after `str_sub`:

```cpp
// One byte with a checked index, copied into its own NUL-terminated buffer.
// A view into the middle of an existing string would leak its suffix into
// printf, strtol, and extern C calls, which all read to the terminator.
inline Str str_at_checked(Str s, int32_t index, int32_t line) {
    if (index < 0 || index >= s.size()) {
        std::fprintf(stderr,
                     "vanta: string index %d out of bounds (length %d) "
                     "at line %d\n",
                     (int)index, (int)s.size(), (int)line);
        std::exit(1);
    }
    return Str::copy(s.c_str() + index, 1);
}
```

- [ ] **Step 5: Lower the read in codegen**

In `_expr`, the `A.Index` branch becomes:

```python
        if isinstance(e, A.Index):
            obj_type = getattr(e.obj, 'type', None)
            if obj_type is STR:
                line = e.pos.line if e.pos else 0
                return (f'vanta::str_at_checked({self._expr(e.obj)}, '
                        f'{self._expr(e.index)}, {line})')
            if isinstance(obj_type, ListType):
                return f'{self._expr(e.obj)}.h->data[{self._expr(e.index)}]'
            return f'{self._expr(e.obj)}[{self._expr(e.index)}]'
```

- [ ] **Step 6: Guard `_lvalue`**

At the top of the `A.Index` branch in `_lvalue`:

```python
            if getattr(expr.obj, 'type', None) is STR:
                raise RuntimeError(
                    "cannot assign to a string element; str is immutable")
```

The checker rejects this first; the guard keeps a compiler bug from emitting invalid C++.

- [ ] **Step 7: Run the focused tests**

Run: `python -m unittest tests.test_codegen.CodegenTests.test_str_index_emit tests.test_integration.IntegrationTests.test_str_index_runtime tests.test_integration.IntegrationTests.test_str_index_out_of_bounds_fails_loudly tests.test_integration.IntegrationTests.test_str_index_negative_fails_loudly tests.test_integration.IntegrationTests.test_str_index_empty_string_fails_loudly tests.test_integration.IntegrationTests.test_str_index_is_byte_based -v`

Expected: all six pass.

- [ ] **Step 8: Run the affected suites**

Run: `python -m unittest tests.test_codegen tests.test_type_checker tests.test_integration -v`

Expected: all pass. If an unrelated integration test is skipped for a missing SDL2/compiler, confirm the skip existed before this change and leave it alone.

- [ ] **Step 9: Commit**

```bash
git add runtime/vanta_runtime.hpp compiler/codegen_cpp.py tests/test_codegen.py tests/test_integration.py docs/superpowers/specs/2026-10-26-string-indexing-design.md docs/superpowers/plans/2026-10-26-string-indexing.md
git commit -m "feat: index strings by byte with a checked one-byte copy"
```

---

### Task 3: Documentation and release notes

**Files:**
- Modify: `docs/LANGUAGE_REFERENCE.md:1215-1219` (Strings section)
- Modify: `docs/LANGUAGE_REFERENCE.md:1409` (Strings and ownership section)
- Modify: `README.md:355-358` (status gap list)
- Modify: `CHANGELOG.md:1-4` (add `## Unreleased`)
- Modify: `ROADMAP.md:48` (remaining queue note)

**Interfaces:**
- Consumes: the behavior verified in Tasks 1-2.
- Produces: no code.

- [ ] **Step 1: Replace the "no indexing" paragraph in the Strings section**

Replace the paragraph starting `There is no string indexing or slicing.` at line 1215 with:

````markdown
Indexing a `str` by byte yields a one-byte `str`:

```vanta
let s = "Vanta"
print_str(s[0])            # V
print_bool(s[1] == "a")    # true
```

`s[i]` is bounds-checked: a negative index, or an index at or past `str_len(s)`,
stops the program with `vanta: string index I out of bounds (length N) at line L`.
The result is a zero-copy view, so it stays valid after the source string goes
out of scope. Indices count **bytes**, not UTF-8 characters; a multi-byte
character occupies several positions. There is no slicing; use `str_sub`.
````

- [ ] **Step 2: Fix the second claim in the ownership section**

Replace line 1409 (`There is no string indexing or slicing.`) with:

```markdown
Indexing is byte-based and checked; see [Strings](#strings). There is no slicing.
```

- [ ] **Step 3: Update the README gap list**

Replace `there is still no string indexing or slicing` in the bullet at lines
355-358 with:

```markdown
   indexing is byte-based and bounds-checked (`s[i]` yields a one-byte `str`),
   and there is no slicing
```

- [ ] **Step 4: Add the changelog entry**

Insert after the intro line (`Notable changes to Vanta, newest first.`):

```markdown
## Unreleased

- **String indexing:** `s[i]` on a `str` yields a one-byte `str`. Reads are
  always bounds-checked — a negative or past-the-end index stops the program
  with `vanta: string index I out of bounds (length N) at line L` — and the
  result owns its byte, so it outlives the source value.
  Indexing is byte-based, consistent with `str_len`/`str_sub`; `s[i] = ...` is
  a compile error because `str` is immutable. Tests: N.
```

Replace `N` with the total reported by the full suite in Step 6.

- [ ] **Step 5: Note it on the roadmap**

Replace line 48 (`Remaining queue: ...`) with:

```markdown
Remaining queue: string indexing landed in v1.7.0 (unreleased): `s[i]` returns
a checked one-byte `str` and is byte-based like `str_len`. Next up:
struct/pointer/bool signal payloads and the remaining LSP `@export` affordances.
```

- [ ] **Step 6: Run the full suite and record the count**

Run: `python -m unittest discover -s tests` (allow up to 10 minutes; use a background run or a longer timeout if the shell's 120-second limit applies).

Expected: all tests pass. Put the reported total in the changelog entry.

- [ ] **Step 7: Commit**

```bash
git add docs/LANGUAGE_REFERENCE.md README.md CHANGELOG.md ROADMAP.md
git commit -m "docs: document byte-based string indexing"
```
