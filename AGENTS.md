# dev-lab

The development system of the lab family: the forge, the hooks, the gate and `verify`, lane and worktree mechanics.

## How a change lands

The family flow, stated once in [the integration branch](docs-src/dev/integration.md):

- Cut `pr/<topic>` from `origin/integrate/main`, measure what you touched, commit, push, open a pull request.
- A producer claims the pushed head and posts `tests/<part>`; the FORGE merges the PR once every part
  stands PASS, the head merges cleanly and the merge passes the audit.
- `main` moves only by `integrate promote <sha>` on a full PASS.

The mechanisms are documented in `docs-src/dev/`; this repo declares its names in `pyproject.toml`.
