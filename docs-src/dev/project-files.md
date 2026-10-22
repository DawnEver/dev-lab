# Project files

Every project-level file a repo tracks (ignore and attribute files, the Makefile, hook and lint configuration,
agent hook wiring, CI) is either RENDERED from a family base plus the repo's delta, or OWNED by the repo with a
written reason (`PROJECT-FILES-HAVE-ONE-SOURCE`). Every configuration is TOML; a file a third party forces into
another format is rendered from TOML and never parsed back. To change one, edit its base or the repo's delta and
re-render; never hand-edit a rendered file.

## The shape

- **One list.** `dev_lab.dev.famfiles.PROJECT_FILES` names every project-level file the family knows, each
  MANAGED (the row names its mechanism) or REPO-OWNED (the row names its reason). A repo adds its own files to
  an `owned_here` mapping, each with a reason. A tracked file in neither is refused.
- **One engine.** `dev_lab.dev.famconfig` renders a whole file from a BASE plus the repo's `Delta`
  (`RENDERED` = byte equality, `REQUIRED` = base lines present); `_famconfig_sections` does the same for a table
  inside a file somebody else owns (`pyproject.toml`, `ruff.toml`); `agent_guard` and `hook_adoption` install
  and render the agent hook files.
- **One command.** `python -m dev_lab.dev.famfiles --deltas <the repo's DELTAS module> [--check]` re-renders
  every RENDERED artefact and reports the REQUIRED ones. `--check` writes nothing and exits 1 on any change.
- **One check.** `dev_lab.dev.famtests.famfiles`:
  `assert_every_project_file_is_accounted_for(root=, owned_here=)` and
  `assert_every_managed_file_is_rendered(root=, deltas=, repo=, rerender_hint=)`.

## Git hooks and CI workflows are TOML

- **Hooks are declared, not rendered.** The family base is `dev_lab/dev/githooks/base.toml`; a repo adds or
  narrows rows under `[[tool.lab_commons.hooks.<stage>]]` in `pyproject.toml` (the same `id` merges key by key,
  a new `id` appends). Keys: `id`, `run` (argv; a leading `python` is the repo venv's interpreter),
  `files`/`exclude` (regexes over repo paths), `pass_files`, `always_run`, `env`, and `refs` (pre-push only).
  Stages: `pre-commit`, `commit-msg`, `pre-push`. `uv`/`uvx` as `run[0]` is refused.
- **One runner**: `python -m dev_lab.dev.githooks run <stage> [git args]`. At commit it selects among the
  STAGED paths and fails a hook that rewrites the working tree; at commit-msg it appends the message file; at
  pre-push it reads git's ref lines once and pipes the matching ones to every hook. No hook runs a test suite.
- **One install**: `python -m dev_lab.dev.hook_install --install --repo .` writes one shim per declared stage
  into the directory git consults; the shim finds the checkout's venv and runs the runner. A worktree may point
  `core.hooksPath` at its own directory with `git config --worktree`. The `hooks-installed` verify step reports a
  missing, stale or foreign shim.
- **CI workflows**: the base is `dev_lab/dev/ci_base.toml`; a repo opts in with
  `[tool.lab_commons.ci."<file>.yml"]` (deep-merged over the base) or declares its own.
  `python -m dev_lab.dev.ciworkflows render` writes `.github/workflows/*.yml` as stamped JSON (JSON is YAML);
  `check` refuses a hand edit or an undeclared workflow, naming the render command.

## The files

| file | how it is kept |
|---|---|
| `.gitignore` | `famconfig` RENDERED: the family core plus mandated lines, plus the repo's delta |
| `.gitattributes` | `famconfig` RENDERED |
| `Makefile` | `famconfig` REQUIRED: the shared target headers and the `verify` recipe; other recipes are the repo's |
| git hooks | `[tool.lab_commons.hooks]` over `githooks/base.toml`, run by `dev_lab.dev.githooks` |
| `.github/workflows/*.yml` | `ciworkflows` RENDERED from `[tool.lab_commons.ci]` over `ci_base.toml` |
| `ruff.toml` / `[tool.ruff*]` | section bases `[tool.ruff]`, `[tool.ruff.lint]`, `[tool.ruff.format]` |
| `pyproject.toml` | section bases for `[project]` and `[tool.pytest.ini_options]`; the rest declined in `PYPROJECT_DECLINED` |
| `.claude/settings.json` | `agent_guard.wire_settings` and `allow_adoption` |
| `.claude/hooks/deny-commands.js`, `deny-rules.json` | `agent_guard` install and `hook_adoption.render` |
| `docs-src/dev/index.md` pointer table | `devdocs.pointer_table`, asserted by `famtests.devdocs` |
| always-loaded rule pages | rule IDs from `dev_lab.dev.rules`, `famtests.rulespages` |
| `LICENSE`, `README.md`, `AGENTS.md`, `CLAUDE.md`, `CHANGELOG.md` | REPO-OWNED: their subject is the repo |

## Adopting it in a repo

1. Keep the repo's `DELTAS` module and add a `Delta` for every base the kit publishes; a missing one is refused.
2. Remove from each delta every line the base now holds; a restatement is refused at render time.
3. `python -m dev_lab.dev.famfiles --deltas <that module>`; commit the rendered files.
4. One test file calling both `famtests.famfiles` bodies, with `owned_here` naming the repo's own files and why.

## The interpreter spelling

One owner: `dev_lab.dev.venvpath` (`VENV_LAYOUTS`, `VENV_INTERPRETER_GLOB`, `INTERPRETER_ALLOW_ENTRY`).
Rendered from it: the allow row `Bash(.venv/*/python* *)`, and the deny row `BARE-INTERPRETER`, which refuses
`uv run`, `uvx` and a bare `python`/`python3`/`py` and names the venv interpreter instead. A repo whose
user-facing CLI runs through `uv run` opens exactly that with its own `Remedy.allow`.
