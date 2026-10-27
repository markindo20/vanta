# Module Follow-Ups Design (Documentation-First)

**Status:** draft, awaiting approval
**Date:** 2026-10-30
**Size:** small/medium increment

## Current reality vs backlog label

The published list refers to "module follow-ups" as if they remain significant, but repository inspection shows that:
- per-field visibility is already implemented and enforced,
- nested dotted modules already resolve,
- VANTA_PATH search-path and dotted filesystem resolution already works,
- `pub` structs/functions/consts already honor selective sharing.

What remains undocumented and uneven is:
- method-level visibility in classes/components/systems (methods are always public now),
- package-level manifest exports and path resolution guarantees,
- path aliases (`foo/bar.vnt` needing `--include-dir`),
- transitive import and private re-export tests beyond current tests.

## Goal

Make module and visibility behavior clearly documented and add a modest utility set before generic unscoped features.

### In scope

1. Document module/visibility semantics in `docs/LANGUAGE_REFERENCE.md` and `README.md`.
2. Add `pub` to methods (`pub func foo`), consistent with fields.
3. Add module reflection: allow a module to mark imports reachable only within implementation (`@export` already behaves metadata-only).
4. Keep default behavior unchanged where `pub` is absent.

### Non-goals
1. New package bundles (`vanta pm pack`).
2. Full generic modules.
3. Major compiler disk layout changes.
4. Registry distribution changes (separate milestone).

### Constraints
- Preserve backward compatibility with legacy module-less files.
- Keep external/vanta run behavior.
- Keep diagnostics messages concrete.
- No behavior changes just for status reasons.

### Implementation strategy
- Allow method pub parsing (parser already supports? add detection).
- Enforce method privacy in `TypeChecker.check_class_method` wiring.
- Add tests:
  - private method rejected as unknown except inside own module
  - public method visible
  - module import search-path ordering still deterministic.
- docs/tutorials examples.

### Audit questions
- Does `pub` keyword already parse on methods in tests? inspect.
- If not, parser syntax gap only.
- Should method visibility default to `pub` to avoid regressions? Current whole-class customs may expect public methods. Keep default `pub` or `private`? Existing tests likely public, changing default may fail. Use default public unless explicit private syntax introduced, or `pub` explicit before method only newly restricts. Prefer backward-compatible default public.
- Fine.

### Acceptance
- Existing tests remain.
- New LSP and codegen doc. No feature lockouts.

Do you approve this?