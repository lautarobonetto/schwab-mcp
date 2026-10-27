# Release and maintenance of the distribution package

How to package `schwab-mcp` to deliver it to recipients who do **not**
work with the repo. The audience of this guide is the project
**maintainer**; recipients use the English manuals that travel inside
the package (`docs/release/`).

## The command

```sh
uv run schwab-mcp-release build [--allow-dirty] [--output-dir DIR]
```

| Argument | Default | What it does |
|-----------|---------|----------|
| `--allow-dirty` | off | Allows building with uncommitted changes; the manifest records `build_dirty: true` |
| `--output-dir` | `dist/` | Destination of the archive and its checksum |

The tooling lives in `src/schwab_mcp_release/` and is **not** included
in the delivered wheel (`packages = ["schwab_mcp"]` in
`pyproject.toml`).

## What it produces

In `dist/`, exactly two files:

- `schwab-mcp-<version>.zip` — the distribution package.
- `schwab-mcp-<version>.zip.sha256` — outer checksum
  (`<sha256>  schwab-mcp-<version>.zip`).

The archive wraps everything under `schwab-mcp-<version>/` and contains:
the runtime wheel (only the `schwab_mcp` package), the package
`README.md`, the 4 manuals in `manuals/`, `install.sh`, `manifest.json`
and `SHA256SUMS`. The stdout output is a stable contract (tests):

```text
BUILD schwab-mcp <version>
WHEEL  schwab_mcp-<version>-py3-none-any.whl
ARCHIVE members=<n> bytes=<size>
CHECKS completeness=PASS exclusion=PASS secrets=PASS
OUT    dist/schwab-mcp-<version>.zip
OUT    dist/schwab-mcp-<version>.zip.sha256
OK     build complete in <s>s
```

## Included checks (the build fails loudly)

Before emitting anything, the command verifies the final archive:

1. **Completeness** — all allowlist members present and non-empty, with
   no extra entries (`MISSING: …` / `UNEXPECTED: …`).
2. **Development material** — no `tests/`, `specs/`, `plans/`, `.git*`,
   `__pycache__/`, `*.egg-info/`, editable source or dev configs,
   including inside the wheel (`DEV-MATERIAL: …`).
3. **Secrets** — neither `.env`/`*.pem`/`*token*db*`/`*secret*`/
   `*credential*` files nor content shaped like a credential
   (`SECRET: …`, file name only — the content is never printed).

Exit codes: `0` ok · `1` validation (names the member) · `2` dirty tree
without `--allow-dirty` · `3` build prerequisite (missing toolchain or
source). On failure, no valid archive or checksum is left behind.

## Delivery workflow

1. Clean commit and green suite (`uv run pytest`).
2. `uv run schwab-mcp-release build`
3. Send **both** files (`zip` + `zip.sha256`) to the recipient.
4. The recipient follows `docs/release/` (verify checksum →
   `./install.sh` → `schwab-mcp auth` → connect AI client).

Recipient upgrades are a re-installation from a new archive:
`~/.schwab-mcp/tokens.db` sits outside the installation and is
automatically preserved.

## Reproducibility

Same version + same inputs ⇒ byte-identical archive (FR-011). The build
normalizes timestamps (archive members and wheel members via
`SOURCE_DATE_EPOCH`) and fixes the member order; two consecutive builds
must yield the same `shasum -a 256` of the zip.

## Validation history

**2026-10-26** (quickstart of `specs/009-mcp-release-packaging/`):

| Scenario | Result |
|-----------|-----------|
| 1 — full build | OK — stdout contract, exit 0, < 60 s |
| 2 — full and clean contents | OK — exactly 9 entries, correct manifest, checksums verify |
| 3 — checks fail loudly | OK — `MISSING:`/`SECRET:` with exit 1, no checksum (covered by tests + manual validation) |
| 4 — dirty tree guard | OK — exit 2 + message; `--allow-dirty` records `build_dirty: true` |
| 5 — reproducibility | OK — identical digest across separate builds |
| 6 — recipient install (package only) | OK steps 1–2 (checksum → `install.sh` → `schwab-mcp --help` with version, `HOME` intact). Steps 3–4 (auth + AI client) require the recipient's Schwab credentials — not executable by the maintainer |
| 7 — upgrade preserves credentials | OK — validated by tests (`test_install_script.py`); tokens outside the installation |
| 8 — full suite | OK — green, 0 skipped |