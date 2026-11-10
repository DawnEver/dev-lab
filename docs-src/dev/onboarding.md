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
| the PR namespace | nothing: `pr/*` is ephemeral by default (`branchset.FAMILY_EPHEMERAL`); declare `ephemeral` only to differ | a PR head pushes with no declared session row |
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

## Then the line every consumer carries

```toml
[tool.dev_lab.integrator]
pr_merges_since = "<the integrate/main sha the flow starts after>"
```

A repo that runs the call above has it, and a test of its own that fails the day it goes missing. A line that
restates a built-in default (`ephemeral = ['pr/*']`) is a second source: leave it out.

## The family side: a repo joins this machine's family

The tree being onboarded is half of joining; the other half is everything OUTSIDE the tree -- the forge's
rules and secrets, the checkout's place, the machine lists. Both verbs implement this checklist
(`dev_lab.dev.family.members`, whose docstring is the authority):

1. **One member list** -- the machine file's `[repos]` (name -> checkout path). What else lists repos derives
   from it (`forge secrets sync`'s targets) or is checked against it (`[serve] repos`).
2. **Cloned beside its siblings** -- the parent most members share.
3. **Onboarded** -- the call above, over the member's own tree.
4. **On its forge** -- Pull Requests on; the trunk and integration branches exist; protection as declared
   (`forge protect`); the review secret present (by name); no PR open past `OPEN_PR_DAYS`.

`python -m dev_lab.dev.family check` names every fact that is not so and exits 1 -- a member's files and manifest are
read from `origin/<integration>` after a fetch, never its working tree, and a member that cannot be fetched is
`unread`, never lacking (`dev_lab.dev.family.origin`); the serve tick runs the same
reading on the dev-lab checkout's tick and raises one `family` alarm per finding (`dev_lab.dev.family.watch`).
`python -m dev_lab.dev.family join <name> <url> [--secrets]` runs the steps in order -- clone, record the
member (first, so the watch sees a half-joined repo), onboarding, protection, the review secret from the
bundle on stdin -- and prints each `left:` step for the user.
