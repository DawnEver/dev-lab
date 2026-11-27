---
name: family-python-and-windows-merge-condition
description: User rulings 2026-11-27 closing dev-lab #1045 -- one family Python (3.14) declared once in dev-lab and followed by every venv, CI sync and manifest; Windows a merge condition by family default
created: 2026-11-27
---

# One family Python, and Windows gates the merge (2026-11-27, dev-lab #1045)

## Ruling 1: one interpreter, declared in dev-lab

User ruling 2026-11-27 (translated): "unify on 3.14, declared in dev-lab".

Measured before: dev-lab and document-lab declared only `requires-python = ">=3.12"` (ruff `py312`); every local
venv was 3.15.2 because uv picks the newest installed interpreter; CI ran Ubuntu's system 3.14.4, Homebrew's 3.15 on
macOS and 3.13 or older on Windows (a `NameError` on a TYPE_CHECKING-only annotation that 3.14's deferred annotations
would not raise). Nothing declared the family's interpreter, so every host chose its own.

Decision:

- The ONE declaration is `dev_lab.dev.pythontoolchain.VERSION` (`"3.14"`), beside the family Rust toolchain
  (`rusttoolchain.CHANNEL`). Everything else derives from it: `REQUIRES_PYTHON`, `RUFF_TARGET`, `SYNC_FLAGS`,
  `hpcaccount.spec.DEFAULT_PYTHON`, and `ci_base.toml`'s `@python@` placeholder.
- `requires-python = ">=3.14,<3.15"`. The ceiling is the ruling itself (one minor), not a resolver accident: with a
  floor alone uv picked 3.15 locally and on macOS. With the ceiling, every plain `uv sync`/`uv run` in a family tree
  selects 3.14 and a lock resolves only cp314 wheels (uv writes the lock header as `==3.14.*`). Moving the family is
  one edit to `VERSION`, then a relock, a re-render and a rebootstrap per repo.
- The manifest keys are RENDERED by the one door (`python -m dev_lab.dev.famfiles` runs `pythontoolchain render`,
  the `pyproject.toml` row's renderer) and judged by `pythontoolchain.drift`; consumers run
  `famtests.pythontoolchain.assert_the_family_python`. `target-version` left the measured-disagreement record
  (`RUFF_TARGET_VERSIONS`, retired): one owner per key.
- Every rendered CI `uv sync` carries `--python 3.14 --managed-python`: a uv-managed interpreter on every runner,
  never the runner's own.
- `dep --bootstrap` builds on the target's `requires-python`: it now rebuilds an environment whose interpreter the
  target refuses (every 3.15 venv), fetches a missing interpreter through the network door
  (`uv python install`, retried by netverb) or refuses naming that door, and a sync or relock under an unfit env
  is refused naming `--bootstrap` (ENV-FITS-ITS-PROJECT) instead of failing at uv.

## Ruling 2: Windows is a merge condition (the other half of #1045)

User ruling 2026-11-27: merge-ready requires `tests/windows` (and `tests/base@windows` where rendered) as it requires
`tests/base`; macOS stays a later-tested part. Supersedes, for the OS parts only, the 2026-11-10 ruling that every
part but base's rows is a hand part.

Decision: a family declaration with a repo override -- `[tool.dev_lab.integrator] merge_systems`, defaulting to
`lanepolicy.FAMILY_MERGE_SYSTEMS = ("windows",)`. `forgemergewaits.gates` says which parts gate: `base` always, a
`base@<os>` row and an `<os>` part when the OS is declared; a resource's part (`gpu`, `femm+windows`) and an
undeclared OS's (`base@macos`) are hand parts, named, never waited on. A repo declaring `merge_systems = []` gates
on base alone. Red-on-record applies to every gating part alike.
