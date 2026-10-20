# Vanta roadmap

Vanta ships in milestones: every release lands compiler work, game-kit work,
tests, and documentation together, and nothing ships undocumented or
untested. This file is a candidate backlog, not a promise — priorities move
as the games show what actually hurts.

Current release: **v0.23.0** ([changelog](CHANGELOG.md)). The language's
present limits are listed at the end of the [README](README.md#status); this
file turns those limits into work. Within each section the small,
high-leverage items come first; relative size is noted.

## Next: a fourth worked game (candidate v0.24.0)

The three games cover the kit's core loop, and the recent milestones closed
the kit's animation/text gaps and the small language loose ends. The next kit
milestone is either a fourth small game (a shooter or a platformer built on
`anim.vnt`, `collide.vnt`, and `text.vnt`) or the breakout polish pass
(levels, pause, score persistence). The remaining language items below are
larger designs, so the kit is the natural next step.

## Language

1. **Checked pointer access — medium.** Arrays have opt-in `xs.at(i)`; raw
   pointers have only `ptr_cast` / `ptr_offset`. Needs a design for a checked
   accessor that does not sand off the escape hatches.
2. **String ownership — large.** `str` comes from a fixed 64 KiB pool that is
   never freed, and `str_pool_reset()` invalidates everything built from it.
   Arena-backed or length-carrying strings would remove the global footgun;
   this touches the runtime, the type checker, and every string builtin.
3. **Enums with explicit values and associated data — large.** Enums are
   named constants with `==` and `match`; explicit member values are the
   smaller half, and associated data would extend `match` exhaustiveness.
   Design carefully — the current plainness is a feature.

## Kit and examples

- A fourth worked game, or a polish pass on breakout (levels, pause, score
  persistence, per-sound gain by scaling PCM at load). With the two game-loop
  items landed, either is a fair next kit step.
- Keep the asset pipeline honest: `examples/assets/gen_assets.py` generates
  every image and sound the examples use; new examples add generators, never
  binaries from elsewhere.

## Tooling and documentation

- The VS Code extension (`editors/vscode/`) provides syntax highlighting
  only. A language server (diagnostics, hover, go-to-definition) is a
  substantial separate project and is not scheduled.
- Watch the `ubuntu-latest` runner migration to Ubuntu 26 (GitHub announced
  the change for the 2026-10-19 window): if the Linux job's SDL package
  install or tests change behaviour, pin the label or adapt the setup,
  verified with the usual full-suite run.
- Documentation keeps its rule: every snippet in the tutorial and reference
  is executed with its output frozen, and CI runs the real programs that the
  docs describe.

## Not scheduled

Garbage collection, closures, generics — each is a language-design project,
not a milestone. If one becomes necessary for a game, it graduates to the
sections above with a concrete motivating program.
