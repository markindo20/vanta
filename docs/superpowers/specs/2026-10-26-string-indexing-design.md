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
natural comparison is `s[i] == "a"`. The result owns its byte, and every access
is bounds-checked.

## Goals

- `s[i]` where `s: str` and `i` is an `i32`-compatible expression evaluates to
  a `str` holding exactly the byte at offset `i`.
- Indexing is safe by default: out-of-range and negative indices abort with
  `vanta: string index I out of bounds (length N) at line L`.
- The result is a one-byte string that owns its byte; each access copies
  exactly one byte, never the whole buffer.
- A result stays usable after the original `str` value goes out of scope.
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
  refcounted (`rep_ != nullptr`). A result must be independently valid.
- A `Str` is NUL-terminated: `print_str`, `str_to_i32`/`str_to_f32`, and
  `extern` C calls read to the terminator. A view into the middle of a buffer
  would expose the suffix, so an indexed byte must own a NUL-terminated copy.
- The runtime header is standalone C++17 with no exceptions; failures print to
  stderr and exit, like `at_checked` and `list_at_checked`.
- The parser already produces `A.Index`, so the grammar does not change.
- Existing diagnostics and generated C++ for other index kinds must not change.

## Approaches considered

1. **`s[i]` returns a checked one-byte `str`.** A checked helper types the index
   as `str` and codegen calls it. *(Chosen.)* Gives the desired syntax and safe
   reads; each access copies one byte.
2. **`s.at(i)` only, no bracket syntax.** Consistent with the checked-access
   spelling used for lists and pointers, but leaves `s[i]` failing and does not
   provide the requested affordance.
3. **`s[i]` unchecked, `s.at(i)` checked.** Mirrors list semantics exactly, but
   turns a typo into undefined behavior or a silent NUL rather than a loud
   abort, for no meaningful speed benefit.

Approach 1 was chosen because it provides `s[i] == "a"` directly and keeps
reads safe.

## Decisions

**Syntax and type.** `s[i]` has type `str`. The index is checked with the same
`_coerce_value(..., I32, ..., "index")` path every other index uses, so numeric
literals work and non-numeric indexes produce the existing index diagnostic.

**Bounds rule.** Always checked. Negative indices are out of range. Indexing an
empty string always aborts. The abort text is:

```
vanta: string index I out of bounds (length N) at line L
```

**Representation.** The result owns its byte. The helper returns
`Str::copy(s.c_str() + index, 1)`, which allocates a two-byte buffer (the byte
and its terminator). A zero-copy interior view was rejected during
implementation: `Str` is NUL-terminated, so `print_str(s[0])` would print the
rest of the source, `str_to_i32(s[0])` would parse the suffix, and an `extern`
call taking a `str` would see text past the indexed byte.

**Runtime helper.** Add `inline Str str_at_checked(Str s, int32_t index, int32_t
line)` next to `str_sub`. It aborts on `index < 0 || index >= s.size()`, then
returns `Str::copy(s.c_str() + index, 1)`.

**Assignment.** `_check_assign` rejects a string element target with
`cannot assign to a string element; str is immutable`, before the generic
`invalid assignment target` path. This covers compound assignment if it lowers
to the same target shape.

**Codegen.** `A.Index` whose object type is `STR` emits
`vanta::str_at_checked(<obj>, <index>, <line>)`. `_lvalue` raises a clear
internal error for a `str` index rather than emitting invalid C++.

## Files touched

- `runtime/vanta_runtime.hpp` — `str_at_checked`.
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
    print_bool(s[1] == "a")      # true
    let joined = str_concat(s[0], s[1])
    print_str(joined)            # Va
    let tail = str_concat("ab", "cd")[1]
    print_str(tail)              # b — the byte outlives the temporary
```

`s[5]` on `"Vanta"` does not return `""`; it aborts with the bounds message.

## What is left to the builder

- Exact placement of the checker branch and helper names, following surrounding
  style.
- Test names and fixture layout, matching the existing suites.
- Whether the changelog entry lists the feature alone or together with the
  pending v1.7.0 signal/LSP work at release time.

## Rollout

No version bump in this change. The behavior is additive: programs that index a
`str` previously failed to compile, so nothing that compiles today changes
meaning.
