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
- **Git:** a regular clone source, optionally followed by a ref fragment:

  ```sh
  vanta pm add https://example.com/foo.git#tag=v1
  vanta pm add https://example.com/foo.git#ref=main
  ```

  `git clone` is used without an implicit depth, the requested tag or branch
  is checked out when provided, and the resulting `HEAD` commit is recorded in
  `vanta.lock`. `git+https://...#tag=...` URLs are also accepted.
- **Registry:** `vanta pm add foo@1.2.3` — resolves through `VANTA_REGISTRY`,
  which may be a directory base (`<base>/<name>/<ver>/`) or an HTTP base
  (`<base>/<name>/<ver>/source.tar.gz`). A bare name `foo` resolves to
  `latest`. Requires `VANTA_REGISTRY` to be set.

## Lockfile and reproducibility

`vanta.lock` records `source`, `path`, `commit`, and `sha256` for each
installed dependency. `source` is the manifest-level identity, including a
Git ref as `...#tag=...` or `...#ref=...`; `commit` is the locked revision for
Git checkout; `sha256` is a deterministic digest of the whole vendored package
tree.

Install behavior:
- If an installed package has a recorded commit and its Git `HEAD` differs,
  install removes and re-fetches that package at the locked commit.
- If `sha256` is present and the vendored tree differs, `pm check` fails and
  install reports a checksum mismatch.
- If the manifest endpoint, Git tag, or ref changes while the lockfile still
  points at the old source, install rejects it as source drift rather than
  silently producing a different package.
- An already-present vendor directory is left untouched when no commit or
  checksum migration is required.
- `pm check` validates presence, source identity where possible, Git commit,
  and tree digest.
- `pm lock` regenerates lock rows. It records an installed HEAD or
  already-known commit, plus the current vendored-tree digest.
- A lock row with no `commit` or `sha256` is tolerated for compatibility with
  older `vanta.lock` files; `pm check` passes and `pm install` records values
  on the next fetch.

Digest and checkout determinism:
- The tree digest covers files and contents only; VCS bookkeeping (`.git`
  directories) is excluded, so re-fetching the same pinned commit is
  byte-identical across machines.
- Git fetches force `core.autocrlf=false` on clone and checkout, so vendored
  files keep LF endings no matter the local Git policy.
- A successful install keeps the source identity the lock already records;
  it refreshes `commit`/`sha256` but does not rewrite `registry:name@version`
  into the manifest's version-only form.

## Unsupported and incomplete features

- No signed registry; HTTP and local directory registry modes are simple
  tar/archive and file copies under `VANTA_REGISTRY`.
- No automatic conflict resolution beyond `setdefault`; the first dependency
  spec for a name wins when manifests are merged.
- Gem-style version ranges and a separate package index format are not
  available; registry dependencies are `name@version`.
- Git credentials are supplied by the invoking `git` command and environment.
- `pm remove` clears only the named targets. It does not automatically remove
  formerly required transitive packages from the root manifest.
- Converting a manual vendored-tree change back to a clean package requires
  deleting the directory and rerunning `pm install`.

## Backward compatibility and deprecation

`vanta get <source>` still works and is unchanged, but it is superseded by
`vanta pm add <source>`. Prefer `vanta pm add` going forward; `vanta get` is
kept for compatibility and may be removed in a future release. Migrate by
running `vanta pm init`, then `vanta pm add <source>` for each dependency
you previously passed to `vanta get`.
