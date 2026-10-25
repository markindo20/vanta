# Packaging — vanta pm

`vanta pm` is Vanta's client-side package manager. It is the successor to
`vanta get` and works entirely without a central registry for v1.4.0.

## Manifest (`vanta.toml`)

A project root contains a `vanta.toml` with a `[package]` section and an
optional `[dependencies]` table:

```toml
[package]
name = "mygame"
version = "0.1.0"

[dependencies]
dep1 = "./local/dep"
dep2 = { git = "https://example.com/dep2.git" }
dep3 = { registry = "latest" }
```

Dependency values are either a plain source string (local path or git URL)
or an inline table with keys `git`, `path`, `src`, or `registry`.

## Lockfile (`vanta.lock`)

`vanta pm lock` writes `vanta.lock` with one `[packages.<name>]` table per
dependency, recording `source`, `path`, and `commit` so installs are
reproducible.

## Subcommands

| Command | Purpose |
|---------|---------|
| `vanta pm init [--name NAME]` | Create `vanta.toml` with a `[package]` section |
| `vanta pm add <source>... [--name NAME] [--dest DIR]` | Fetch and record dependencies |
| `vanta pm install [--dest DIR]` | Install manifest dependencies into `vendor/` |
| `vanta pm remove <name>...` | Drop dependencies and clean `vendor/` |
| `vanta pm list` | List dependencies from the manifest |
| `vanta pm lock` | Regenerate `vanta.lock` from the manifest |
| `vanta pm check` | Verify every manifest dependency is present in `vendor/` |

`--dest` defaults to `vendor`.

## Dependency sources

- **Local path:** `vanta pm add ./libs/foo` — copies the directory into
  `vendor/foo` via `shutil.copytree`.
- **Git:** `vanta pm add https://example.com/foo.git` — shallow-clones
  (`git clone --depth 1`) and records the resolved commit.
- **Registry:** `vanta pm add foo@1.2.3` — resolves through `VANTA_REGISTRY`,
  which may be a directory base (`<base>/<name>/<ver>/`) or an HTTP base
  (`<base>/<name>/<ver>/source.tar.gz`). A bare name `foo` resolves to
  `latest`. Requires `VANTA_REGISTRY` to be set.

## Transitive dependencies

When a dependency is added or installed, `vanta pm` reads that dependency's
own `vanta.toml` and merges its `[dependencies]` into the root manifest, so
the full transitive closure is available.

## Backward compatibility and deprecation

`vanta get <source>` still works and is unchanged, but it is superseded by
`vanta pm add <source>`. Prefer `vanta pm add` going forward; `vanta get` is
kept for compatibility and may be removed in a future release. Migrate by
running `vanta pm init`, then `vanta pm add <source>` for each dependency
you previously passed to `vanta get`.
