# dev-lab

The development system of the lab family: the forge (verdicts per sha, PR merges, the integration
branch), the git and agent hooks, the gate and `verify`, lane and worktree mechanics, and the
census/refusal tables they enforce. It is a tool a repo DEVELOPS with, never a library its
production code imports.

Split from lab-commons on 2026-10-22 at lab-commons `8c401f0` with history kept. lab-commons stays the
project-agnostic RUNTIME (logging, paths, config, units, viz, and the execution packages `box`,
`compute`, `hpc`, `supervise`); dev-lab depends on it, never the other way round.

## Installing

A consumer declares it beside lab-commons, as one bare git URL that its `uv.lock` pins:

```toml
[dependency-groups]
dev = ["dev-lab @ git+https://github.com/DawnEver/dev-lab.git"]
```

Its own environment is built through the dependency door, never a bare installer:

```
<python> -m dev_lab.dev.dep --bootstrap <checkout>
```

## Using it

Every entry point is a module of `dev_lab.dev`, for example:

| Command | What it does |
|---|---|
| `python -m dev_lab.dev.verify -- <paths>` | the measure door: the tests you touched, no verdict |
| `python -m dev_lab.dev.forge queue` | where each sha stands on the forge |
| `python -m dev_lab.dev.forge sync` | take the integration branch into your lane |
| `python -m dev_lab.dev.hook_install --install` | install the declared git hooks |
| `python -m dev_lab.dev.netverb -- git <verb> ...` | a network git verb with retries and a diagnosis |

A repo configures it in its `pyproject.toml` under `[tool.lab_commons.*]`; the table names are
unchanged by the split, so consumer manifests need no edit for it.

The mechanism pages are under `docs-src/dev/` (`docs-src/dev/index.md` first).
