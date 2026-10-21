# Vanta roadmap

Vanta ships in milestones: every release lands compiler work, game-kit work,
tests, and documentation together, and nothing ships undocumented or
untested. This file is a candidate backlog, not a promise — priorities move
as the games show what actually hurts.

Current release: **v0.30.0** ([changelog](CHANGELOG.md)). The language's
present limits are listed at the end of the [README](README.md#status); this
file turns those limits into work. Within each section the small,
high-leverage items come first; relative size is noted.

## Landed in v0.30.0

Module boundaries landed. A file can start with `module name`; its
declarations are private unless marked `pub`. `import "file.vnt"` brings a
module's public names into the importing file, while
`import "file.vnt" as alias` uses qualified names such as `alias.func(...)`,
`alias.Type(...)`, and `alias.Enum.Member`. Module-less files keep the
original flat, all-public import behaviour, so the game kit and every existing
program compile unchanged. The resolver rejects private access, ambiguous
unqualified imports, duplicate module names, and private types exposed by
public declarations. `examples/modules_demo/` is the worked example.

## Next: language (candidate v0.31.0)

1. **Error handling with `Option`/`Result` — medium.** A library-shaped
   alternative to sentinel values, built on payload enums now that module
   boundaries make a standard library practical.
2. **Module follow-ups — medium.** Per-field visibility, nested modules, and
   a package/search-path story are deliberately out of v0.30.0. They become
   worth doing when a library wants to hide struct representation or when
   path-only imports become painful.

## Kit and examples

- Breakout polish landed in v0.27.0: three walls, P/Space pause, a best score
  persisted in `breakout.score`, and `sound_load_gain` for per-sound volume.
  The pong and strike frozen runs stay untouched; breakout's frozen run now
  records the three-wall clear.
- `examples/enums_advanced.vnt` exercises explicit member values, payload
  enums, struct/str payloads, wildcard bindings, equality, and `enum_to_i32`;
  its output is frozen in the integration suite.
- `examples/modules_demo/` exercises declared modules, `pub`, a private
  helper, qualified and unqualified imports, module constants, and a payload
  enum crossing a module boundary; its output is frozen in the integration
  suite.
- Keep the asset pipeline honest: `examples/assets/gen_assets.py` generates
  every image and sound the examples use; new examples add generators, never
  binaries from elsewhere.

## Tooling and documentation

- Distribution is live: `vanta-lang` is on PyPI and the release workflow
  publishes each version tag through Trusted Publishing, attaching the wheel
  and sdist to the GitHub release too. Homebrew, Scoop, and winget formulas
  are follow-ups.
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
