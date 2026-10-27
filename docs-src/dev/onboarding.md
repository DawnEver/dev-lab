# Onboarding a repo

A new repo is configured ONCE, and the configuration is one statement rather than five later discoveries.

## The one call

```python
from pathlib import Path
from dev_lab.dev.famtests.onboarding import assert_repo_is_onboarded, assert_the_forge_takes_pull_requests
from dev_lab.dev.forgework import client_for

assert_repo_is_onboarded(root=Path(__file__).resolve().parents[2])
assert_the_forge_takes_pull_requests(client_for(Path.cwd()))
```

The first reads the tree and names every missing declaration at once; the second reads the forge, because
"Pull Requests are ON" is a repository SETTING and cannot live in a file.

## What a repo declares

| piece | the line | why |
|---|---|---|
| the trunk and its sessions | `[tool.dev_lab.branchset] trunk = 'main'`, `sessions = ['integrate/main']` | ONE-BRANCH-PER-SESSION: anything else is debt |
| the PR namespace | `ephemeral = ['pr/*']` | a PR head pushes with no declared session row |
| the flow's start | `[tool.dev_lab.integrator] pr_merges_since = "<sha>"` | INTEGRATION-TAKES-ONLY-FORGE-MERGES from that commit |
| the one producer | `[tool.lab_commons.tests] produce = ["-m", "dev_lab.dev.verify", "--part", "{part}"]` | a part nobody can produce is a sha nobody can merge |
| the hook rows | `[tool.dev_lab.hooks]` (an empty table is the whole declaration) | the family base rows run |
| the entry point for an agent | `AGENTS.md` (+ `CLAUDE.md` = `@AGENTS.md`) | it names [the integration branch](integration.md) by link and restates nothing |
| a committed lock | `uv.lock` | PIN + FRESHNESS: a verdict pins an environment to it |
| Pull Requests ON | the forge's repository settings | with the unit off, every `/pulls` call answers 404 and no PR can be opened |

## The order that matters

**Relock before you declare.** `pr_merges_since` is a key a pinned lab-commons must KNOW; a repo that
declares it before relocking makes its own tooling refuse its manifest (`unknown key(s) ['pr_merges_since']`).
The relock belongs in the same PR as the declaration.

## Then the two lines every consumer carries

```toml
[tool.dev_lab.branchset]
ephemeral = ['pr/*']

[tool.dev_lab.integrator]
pr_merges_since = "<the integrate/main sha the flow starts after>"
```

A repo that runs the call above has both, and a test of its own that fails the day either goes missing.
