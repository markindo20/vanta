# String indexing — design

**Status:** approved approach, awaiting sign-off
**Date:** 2026-10-26
**Size:** small change (one feature, ~200–300 LoC plus tests and docs)

## Intent

Vanta's `str` is immutable, byte-oriented, and already supports `str_len` and
`str_sub`, but the language rejects `s[i]` with `cannot index a value of type
str`. Reading a single byte is a constant need when parsing text, walking a
font's glyph table, and writing little scanners in game code.

This change makes `s[i]` work for a `str` and yield a one-byte `str`, so the
natural comparison is `s[i] == "a"`. The result is a zero-copy view into the
original buffer, and every access is bounds-checked.

## Goals

- `s[i]` where `s: str` and `i` is an `i32`-compatible expression evaluates to
  a `str` holding exactly the byte at offset `i`.
- Indexing is safe by default: out-of-range and negative indices abort with
  `vanta: string index I out of bounds (length N) at line L`.
- The result shares storage with the original string; a loop over characters
  performs no allocation and does not copy the buffer.
- A view keeps the source buffer alive after the original `str` value goes out
  of scope.
- Indexing composes: `s[0]`, `s[i][0]`, `str_concat(a, b)[0]`, and a call
  result are all valid.

## Non-goals

- Slicing (`s[a:b]`). `str_sub(s, start, n)` already exists; slice syntax needs
  its own parser and semantics design.
- UTF-8 character indexing. `s[i]` is the byte at offset `i`, matching
  `str_len` and `str_sub`. Indexing a multi-byte character yields its first
  byte, which may print as an invalid standalone sequence; the docs say so.
- Mutating a string element. `str` is immutable; `s[i] = "x"` is a compile
  error.
- Changes to list, array, or pointer indexing semantics.

## Anti-goals

- An unchecked `[]` variant with a separate `.at()` spelling. A raw read past a
  literal is undefined behavior, and strings cannot be mutated, so there is no
  performance-sensitive write case that would justify two spellings.
- Character-count-based indexing that disagrees with `str_len`.

## Constraints

- `str` literals are static views (`rep_ == nullptr`); runtime strings are
  refcounted (`rep_ != nullptr`). A view must handle both.
- The runtime header is standalone C++17 with no exceptions; failures print to
  stderr and exit, like `at_checked` and `list_at_checked`.
- The parser already produces `A.Index`, so the grammar does not change.
- Existing diagnostics and generated C++ for other index kinds must not change.

## Approaches considered

1. **`s[i]` returns a checked one-byte `str` view.** Runtime view constructor
   plus a checked helper; checker types the index as `str`; codegen calls the
   helper. *(Chosen.)* Gives the desired syntax and safe reads with no
   per-character allocation.
2. **`s.at(i)` only, no bracket syntax.** Consistent with the checked-access
   spelling used for lists and pointers, but leaves `s[i]` failing and does not
   provide the requested affordance.
3. **`s[i]` unchecked, `s.at(i)` checked.** Mirrors list semantics exactly, but
   turns a typo into undefined behavior or a silent NUL rather than a loud
   abort, for no meaningful speed benefit.

Approach 1 was chosen because it provides `s[i] == "a"` directly, keeps reads
safe, and the zero-copy view removes the only cost that made the unchecked
variant tempting.

## Decisions

**Syntax and type.** `s[i]` has type `str`. The index is checked with the same
`_coerce_value(..., I32, ..., "index")` path every other index uses, so numeric
literals work and non-numeric indexes produce the existing index diagnostic.

**Bounds rule.** Always checked. Negative indices are out of range. Indexing an
empty string always aborts. The abort text is:

```
vanta: string index I out of bounds (length N) at line L
```

**View representation.** Add `static Str view(const Str& base, int32_t start,
int32_t len)` to `Str`. It sets `data_ = base.data_ + start`, `len_ = len`, and
`rep_ = base.rep_`, incrementing the refcount when `rep_` is present. The
existing destructor then frees the buffer only when the last view and owner are
gone. Preconditions (`0 <= start`, `len >= 0`, `start + len <= base.size()`)
are guaranteed by the checked helper.

**Runtime helper.** Add `inline Str str_at_checked(Str s, int32_t index, int32_t
line)` next to `str_sub`. It aborts on `index < 0 || index >= s.size()`, then
returns `Str::view(s, index, 1)`.

**Assignment.** `_check_assign` rejects a string element target with
`cannot assign to a string element; str is immutable`, before the generic
`invalid assignment target` path. This covers compound assignment if it lowers
to the same target shape.

**Codegen.** `A.Index` whose object type is `STR` emits
`vanta::str_at_checked(<obj>, <index>, <line>)`. `_lvalue` raises a clear
internal error for a `str` index rather than emitting invalid C++.

## Files touched

- `runtime/vanta_runtime.hpp` — `Str::view`, `str_at_checked`.
- `compiler/type_checker.py` — accept `STR` in `A.Index`, reject assignment to
  an element.
- `compiler/codegen_cpp.py` — emit the helper for `STR`; guard `_lvalue`.
- `tests/test_type_checker.py` — indexing type, index type errors, immutable
  element.
- `tests/test_codegen.py` — helper emitted; no raw `[]` on `Str`.
- `tests/test_integration.py` — run programs covering first/last byte, empty
  string, out-of-range, negative index, composed indexing, and a view outliving
  its source.
- `docs/LANGUAGE_REFERENCE.md` — replace both "no string indexing" statements
  with the byte-level rule and a runnable example.
- `README.md` — remove string indexing from the status gap list.
- `CHANGELOG.md` — add an `## Unreleased` section with the feature entry (the
  pending v1.7.0 items can accumulate there).
- `ROADMAP.md` — note string indexing landed.

## Testing

Verification is the existing suite plus the new cases above. The full
`python -m unittest discover -s tests` run is the release gate; the changed
areas are also run directly (`tests.test_type_checker`, `tests.test_codegen`,
`tests.test_integration`).

Program-level cases:

```vanta
func main() -> void:
    let s = "Vanta"
    print_str(s[0])              # V
    print_str(s[4])              # a
    print_bool(s[0] == "V")      # true
    print_bool(s[5] == "")       # false — indexing past the end aborts, does not yield ""
    let joined = str_concat(s[0], s[1])
    print_str(joined)            # Va
    let tail = str_concat("ab", "cd")[1]
    print_str(tail)              # b — the view keeps the temporary alive
```

## What is left to the builder

- Exact placement of the checker branch and helper names, following surrounding
  style.
- Whether `Str::view` is public or a private factory used by the helper (the
  helper is a free function, so it must be public).
- Test names and fixture layout, matching the existing suites.
- Whether the changelog entry lists the feature alone or together with the
  pending v1.7.0 signal/LSP work at release time.

## Rollout

No version bump in this change. The behavior is additive: programs that index a
`str` previously failed to compile, so nothing that compiles today changes
meaning.
