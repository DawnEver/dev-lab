# Project files

Rule `PROJECT-FILES-HAVE-ONE-SOURCE` (statement in `lab_commons.dev.rules`). User ruling, 2026-10-03: every project-level file the four repos repeat has ONE source of truth in lab-commons.

## The shape

- **One list.** `lab_commons.dev.famfiles.PROJECT_FILES` names every project-level file the family knows, each either MANAGED (the row names the mechanism) or REPO-OWNED (the row names the reason). A repo adds its own files to an `owned_here` mapping, each with a reason. A tracked file in neither is refused.
- **One engine.** The mechanisms the rows name already existed one file at a time and are reused, not paralleled: `lab_commons.dev.famconfig` renders a whole file from a BASE plus the repo's declared `Delta` (`RENDERED` = byte equality, `REQUIRED` = base lines present); `_famconfig_sections` does the same for a config TABLE inside a file somebody else owns (`pyproject.toml`, `ruff.toml`); `agent_guard` / `hook_adoption` install and render the agent hook files.
- **One command.** `python -m lab_commons.dev.famfiles --deltas <the repo's DELTAS module> [--check]` re-renders every RENDERED artefact the repo declares and reports the REQUIRED ones (not written: a Makefile's recipes are the repo's own). `--check` writes nothing and exits 1 if anything would change.
- **One check.** `lab_commons.dev.famtests.famfiles`:
  - `assert_every_project_file_is_accounted_for(root=, owned_here=)` -- the list is complete for this repo; an `owned_here` entry restating a family row, carrying no reason, or naming an untracked file is refused.
  - `assert_every_managed_file_is_rendered(root=, deltas=, repo=, rerender_hint=)` -- every famconfig base is declared, no delta restates a base line (`delta_problems`), every file on disk is base plus delta. It composes the `famtests.configrender` bodies.

## Inventory, measured 2026-10-03

Repos: LC = lab-commons, MS = consumer-a, OL = consumer-c, WL = consumer-b (the aliases the rest of this kit uses).

| file | LC | MS | OL | WL | shared vs own | family mechanism |
|---|---|---|---|---|---|---|
| `.gitignore` | yes | yes | yes | yes | 14-pattern consumer core + 9 mandated lines; deltas 1 / ~140 / ~25 / ~65 | `famconfig` RENDERED -- MS, OL, WL already stamped; LC adopted 2026-10-03 |
| `.pre-commit-config.yaml` | yes | yes | yes | yes | 12-id hook core | `famconfig` RENDERED, all four stamped |
| `Makefile` | yes | yes | yes | yes | 9 target headers + the `verify` recipe; no other shared recipe | `famconfig` REQUIRED, all four |
| `.gitattributes` | yes | yes | -- | -- | no shared line; one family reason (`*.sh text eol=lf`, the shipped bash payloads) | `famconfig` RENDERED, NEW 2026-10-03; LC adopted |
| `ruff.toml` / `[tool.ruff*]` | pyproject | `ruff.toml` | pyproject | pyproject | select set and shared ignores | section bases `[tool.ruff]`, `[tool.ruff.lint]`, `[tool.ruff.format]` |
| `pyproject.toml` | yes | yes | yes | yes | `[project]` and `[tool.pytest.ini_options]` keys shared; the rest per repo | section bases; `build-system`, `commitizen`, `coverage`, `hatch`, `pyright`, `lab_commons`, `optional-dependencies` declined with the measurement in `PYPROJECT_DECLINED` |
| `.claude/settings.json` | -- | yes | yes | yes | the PreToolUse hook wiring + derived allow rows | `agent_guard.wire_settings`, `allow_adoption` |
| `.claude/hooks/deny-commands.js` | -- | yes | yes | yes | byte-identical engine | `agent_guard` install |
| `.claude/hooks/deny-rules.json` | -- | yes | yes | yes | the deny registry, minus rules whose remedy a repo lacks | `hook_adoption.render` |
| `.github/workflows/python-verify.yml` | yes | -- | -- | -- | THE family CI definition | hosted in LC, called by every repo |
| `.github/workflows/ci.yml` | yes | -- | yes | -- | a thin caller | calls LC's reusable workflow; checks are `make verify` |
| `docs-src/dev/index.md` pointer table | yes | yes | yes | yes | the family page table | `devdocs.pointer_table`, asserted by `famtests.devdocs` |
| always-loaded rule pages | yes | yes | yes | yes | rule statements | `lab_commons.dev.rules` IDs, `famtests.rulespages` |
| `LICENSE` | MIT | -- | Apache-2.0 | LGPL-3.0 | nothing | REPO-OWNED: the licence is the repo's decision |
| `README.md` | yes | yes | yes | yes | nothing | REPO-OWNED: subject is the repo |
| `AGENTS.md` | -- | yes | -- | yes | nothing | REPO-OWNED: architecture; shared rules are cited by ID |
| `CLAUDE.md` | -- | yes | -- | yes | a pointer to AGENTS.md, spelled two ways | REPO-OWNED for now; candidate for a REQUIRED base (`@AGENTS.md`) once LC and OL carry an AGENTS.md |
| `CHANGELOG.md` | -- | -- | -- | yes | nothing | REPO-OWNED |
| `.editorconfig` | -- | -- | -- | -- | none exists anywhere | nothing to unify |
| `dependencies.observed.toml` | -- | yes | -- | -- | one repo | MS `owned_here` |
| `.python-version`, `.rgignore`, `Cargo.toml` | -- | -- | -- | yes | one repo | WL `owned_here` |

## Adopting it in a repo

1. Keep the repo's `DELTAS` module where it is (`tests/_famconfig_delta.py` in LC, `tests/architecture/ratchets/_famconfig.py` in consumer-a, `tests/architecture/_famconfig.py` in consumer-b and consumer-c) and add a `Delta` for every base the kit publishes -- the completeness arm refuses a missing one.
2. Remove from each delta every line the base now holds (a restatement is refused at render time).
3. `python -m lab_commons.dev.famfiles --deltas <that module>`; commit the rendered files.
4. One test file calling both `famtests.famfiles` bodies, with `owned_here` naming the repo's own files and why.

## The interpreter spelling

One owner: `lab_commons.dev.venvpath` (`VENV_LAYOUTS`, `VENV_INTERPRETER_GLOB`, `INTERPRETER_ALLOW_ENTRY`). Rendered from it:

- the `permissions.allow` row `Bash(.venv/*/python* *)` -- `allow_adoption.derived_entries` puts it in every repo's allow block, so the settings check every consumer already runs refuses a block without it;
- the deny row `BARE-INTERPRETER` (`_deny_interpreter_row`): it refuses `uv run ...`, `uvx`, and a bare `python`/`python3`/`py`, including behind wrappers and heredocs (the engine unwraps `uv run` and the row fires on either position). The refusal names `.venv/Scripts/python.exe` / `.venv/bin/python`, and for a worktree with no `.venv` the main checkout's. `python -m pytest` stays with `BARE-TEST-INVOCATION`: one shape, one row;
- a repo whose user-facing CLI runs through `uv run` (consumer-a: `uv run <cli>`) opens exactly that with its own `Remedy.allow` for `BARE-INTERPRETER` -- a per-repo delta, never a hole in the base row.
