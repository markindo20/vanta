# Vanta roadmap

Vanta ships in milestones: every release lands compiler work, game-kit work,
tests, and documentation together, and nothing ships undocumented or
untested. This file is a candidate backlog, not a promise — priorities move
as the games show what actually hurts.

Current release: **v0.28.0** ([changelog](CHANGELOG.md)). The language's
present limits are listed at the end of the [README](README.md#status); this
file turns those limits into work. Within each section the small,
high-leverage items come first; relative size is noted.

## Next: language (candidate v0.29.0)

The installable release landed in v0.28.0: the runtime and game kit travel
inside the wheel, `vanta doctor` checks a machine, and tagging builds and
attaches the distribution. The next language item is enum extensions; checked
pointer access and automatic string ownership are already in.

1. **Enums with explicit values and associated data — large.** Enums are
   named constants with `==` and `match`; explicit member values are the
   smaller half, and associated data would extend `match` exhaustiveness.
   Design carefully — the current plainness is a feature.

## Kit and examples

- Breakout polish landed in v0.27.0: three walls, P/Space pause, a best score
  persisted in `breakout.score`, and `sound_load_gain` for per-sound volume.
  The pong and strike frozen runs stay untouched; breakout's frozen run now
  records the three-wall clear.
- Keep the asset pipeline honest: `examples/assets/gen_assets.py` generates
  every image and sound the examples use; new examples add generators, never
  binaries from elsewhere.

## Tooling and documentation

- Distribution is now wheel-based. The release workflow can publish to PyPI
  through Trusted Publishing once the project and the `pypi` environment are
  configured there and `PUBLISH_PYPI=true` is set; until then the wheel is
  attached to each GitHub release and installs with
  `pip install <release wheel URL>`. Homebrew, Scoop, and winget formulas are
  follow-ups.
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
