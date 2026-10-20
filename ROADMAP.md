# Vanta roadmap

Vanta ships in milestones: every release lands compiler work, game-kit work,
tests, and documentation together, and nothing ships undocumented or
untested. This file is a candidate backlog, not a promise — priorities move
as the games show what actually hurts.

Current release: **v0.25.0** ([changelog](CHANGELOG.md)). The language's
present limits are listed at the end of the [README](README.md#status); this
file turns those limits into work. Within each section the small,
high-leverage items come first; relative size is noted.

## Next: breakout polish (candidate v0.26.0)

The fourth game, `strike.vnt`, landed in v0.24.0 with `gamekit/collide.vnt`,
so the kit now covers the core loop, animation, text, audio, controllers, and
collision. The next kit step is the breakout polish pass: levels, pause,
score persistence, and per-sound gain by scaling PCM at load. The language
items below remain larger designs; checked pointer access landed in v0.25.0,
so string ownership is the next language item if a language milestone is
preferred.

## Language

1. **String ownership — large.** `str` comes from a fixed 64 KiB pool that is
   never freed, and `str_pool_reset()` invalidates everything built from it.
   Arena-backed or length-carrying strings would remove the global footgun;
   this touches the runtime, the type checker, and every string builtin.
2. **Enums with explicit values and associated data — large.** Enums are
   named constants with `==` and `match`; explicit member values are the
   smaller half, and associated data would extend `match` exhaustiveness.
   Design carefully — the current plainness is a feature.

## Kit and examples

- Breakout polish: levels, pause, score persistence, and per-sound gain by
  scaling PCM at load. The fourth game, `strike.vnt`, landed in v0.24.0
  with `gamekit/collide.vnt`; keep the pong and strike frozen runs untouched,
  and revise breakout's frozen run only when a polish item deliberately
  changes that game.
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
