# Contributing

The runnable path from a fresh clone to a merged change. Every command below
runs from the repo root and is what CI does.

## Prerequisites

| Tool | Needed for | Pin |
|---|---|---|
| [uv](https://github.com/astral-sh/uv) | every Python command (`make setup`, `make test`, `make lint`) | `>=0.12` (`tools/pyproject.toml [tool.uv]`) |
| .NET SDK 8 | `make build` and the C# mod only | `8.0.400` (`global.json`) |
| bun 1.4.0 | viewer and webmod build/lint | `1.4.0` (CI); the lint scripts install tsc, oxlint and vnu at the pins in `scripts/toolchain-versions.env` |
| shellcheck, yamllint | `make lint-shell`, `make lint-yaml` | any recent release |

Python is not installed system-wide: uv manages the interpreter and the
`tools/.venv` environment. The game install (Steam, 7 Days to Die) is only
needed for `make build` and anything that installs into the game directory; CI
deliberately does not build the mod, because the C# references the proprietary
game assemblies.

## Bootstrap

```bash
make setup   # uv sync --locked in tools/, then report the game dir and dotnet
make help    # every target with a one-line description
make info    # resolved paths plus the uv and dotnet versions in effect
```

`make setup` warns instead of failing when the game is missing, so a
game-less machine still reaches the Python and viewer gates.

## Edit loop

```bash
make test-one T=tests/test_coords.py                    # one file
make test-one T=tests/test_coords.py::test_wrap_x       # one node
make test-one T="-k wrap"                                # one -k expression
make test-fast                                           # the quick subset
make test                                                # the full suite (what CI runs)
```

`T` paths are relative to `tools/`, because pytest runs from there. A new test
goes in `tools/tests/test_<area>.py` and drives the public entry point
(`realearth.cli`, a shipped module, or a script) rather than a helper.

## Before you push

```bash
make check
```

That is the pre-push gate and it mirrors the `tools` job of
`.github/workflows/ci.yml` step for step: shellcheck, yamllint, the artifact
backup/restore drill, the full pytest suite, ruff + black + mypy, and the
viewer, webmod and HTML gates. It adds `make build`, which needs the game
installed. On a machine without the game, run `make check NO_GAME_BUILD=1`,
which drops the one step CI cannot run either.

CI additionally runs a coverage pass over the `test-fast` list and republishes
the badge; nothing to do for a normal change.

## Regenerating what a build produces

| Path | Command |
|---|---|
| `data/samples/*` | `make demo` |
| `worlds/*` | `make bake` |
| `viewer/data/*` | `make viewer` |
| `viewer/js/*` | `make viewer-build` |
| `webmod/build/*` | `make webmod` |
| `dist/*` | `make package` |

None of it is committed (see `.gitignore`). The lockfiles are: change
`tools/pyproject.toml` and run `uv lock` in `tools/`, or change
`scripts/toolchain-versions.env` and re-lock `scripts/js-toolchain.lock` as
that file's header describes. `--locked` is on every make target, so a
dependency change that skips the re-lock fails loudly instead of silently
re-resolving.

## C# changes

`Source/RealEarth` targets net48 and references the game assemblies, so it only
compiles against an installed 7DTD build. `BuildGuard` pins the sha256 of the
reviewed `Assembly-CSharp.dll`; a new game build fails closed until the
allowlist is re-reviewed (see `docs/GAME_VERSION.md`). Never patch a game DLL
on disk: the YDim height expand is a runtime Harmony transpiler.

## Pull requests

Branch off `main` with a `feat/`, `fix/`, `refactor/`, `docs/`, `test/` or
`chore/` prefix. Keep Python changes deterministic and cover coordinate,
wrapping, height and tile-format behavior with tests. Third-party geodata needs
its license documented in `ATTRIBUTION.md`. `CHANGELOG.md` gets an `## [Unreleased]`
entry when a change is visible to server admins or pack builders; the release
gate requires a dated `## [x.y.z]` heading before a tag, and the shipped version
in `ModInfo.xml` must match `tools/realearth/__init__.py`.
