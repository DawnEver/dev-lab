# Development mechanism — the family's half

- **The rule this section exists to hold.** `.claude/rules/**` in each repo is HARD CONSTRAINTS ONLY, read on every turn; MECHANISM — how a thing actually works, and what went wrong to make it work that way — lives here, and you read the page when you do the thing.
- **Why here rather than in each repo.** The universal rule STATEMENTS were unified into `lab_commons.dev.rules` on 2026-09-15, where each row carries its ID, its statement and the mechanism that refuses a violation. The MECHANISM DOCS were not, so the four repos cited rules by ID and had nothing that explained how the mechanism works. Three of them had no written mechanism at all while one held roughly 1,300 lines of it.
- **These pages are POINTED AT, never copied.** A consuming repo points at the slug from its dev index; a local page under the same name holds only that repo's DELTA and links this one in its first lines, which `lab_commons.dev.famtests.devdocs` asserts in the consumer's own suite. The page itself exists once, here. A "shared" document each repo copies is the fork the sharing was removing.
- **The test that put a page here, and it is the only one: does its SUBJECT change when you change repos?** The BOX, GIT, THE FORGE or THE FAMILY'S PROCESS is the family's. Motors, solvers, meshes and cases stay home. Delete every domain noun from a sentence: if it still constrains something, it is universal — the same noun test `lab_commons.dev.rules` applies to a rule statement.

## The pages

| page | what it covers |
|---|---|
| [The three participants](./the-three-participants.md) | Who does what: the human, the concurrent dev agents, the coordinator that absorbs their work |
| [The verdict model](./verdict-model.md) | What a verdict IS, why it starts INCONCLUSIVE, the three tiers and the destination each one gates |
| [Testing discipline](./testing-discipline.md) | The lightweight/heavy partition, xfail never skip, one test session at a time |
| [Branch layers](./branch-layers.md) | What a lane, an integration branch and `main` each PROVE, and why one cannot substitute for another |
| [Alignment](./alignment.md) | The framework every branch develops against so an integration conflicts on CODE, never on bookkeeping |
| [Fan-out](./fanout.md) | Parallel lanes in worktrees: environments, subagent bases, the shared hazards, landing |
| [The shared checkout](./shared-checkout.md) | Where a tool's correctness argument stops transferring when the checkout is not exclusive |
| [Killed runs and orphans](./orphans.md) | What survives a stopped run, why a lock does not time out, and the census a reaper needs |
| [Box resources](./box-resources.md) | What one workstation rations, the four defects measured in doing it by hand, and the broker shape |
| [The forge](./forge.md) | How `main` is protected on a self-hosted forge: the push whitelist, the status check, branch disposal |
| [Issues](./issues.md) | An issue is intent; todo/in-progress/ready/done are derived from origin refs and `lab/gate`, claims are comments |
| [The integrator](./integrator.md) | Woken or self-polling, one derived merge queue: the ready predicate over `lab/gate` and `lab/heavy` |
| [Retirement](./retirement.md) | An archive and a retired-spelling registry are a PLACE and a RULE, and why the rule cannot live in the place |
| [The docs pipeline](./docs-pipeline.md) | The three properties a docs builder must hold, and why an unbuilt sub-site is announced rather than silent |
| [Translations](./translations.md) | Why a `<stem>.zh.md` beside its `<stem>.md` escapes the CJK guard, and the non-ASCII goal |
| [Worktrees stay inside](./worktrees.md) | Every checkout lives under `<repo>/.claude/worktrees/<name>`: the deny row, the detector, the ignore line |
| [One branch per session](./branch-set.md) | One long-lived branch per session: the declared branch set, the census, and the merge-and-delete list |
| [Auto mode runs the doors](./auto-doors.md) | Local cleanup and own-run stops are checked doors both clients allow; pushes and remote deletes stay human |
| [Project files](./project-files.md) | Every project-level file is rendered from a family base plus a delta, or owned by the repo with a reason |

## Reading these from a consuming repo

- `lab_commons.dev.devdocs` is the DATA half: `PAGES` carries one row per page above, and `pointer_table()` renders the table a repo puts in its own dev index — so a pointer is generated from the page set rather than hand-copied and left to rot.
- **The table above is that same render, with the base `.`, and it used to be hand-typed.** Measured 2026-09-19: every title agreed and SIX of the then-twelve subjects had drifted from `PAGES`, so the origin page and the table every consumer renders described the same page differently and nothing noticed. All four dev indexes now hold one render of one registry, and `tests/test_the_dev_docs_tree_is_shared_by_reference.py` asserts each against a live `pointer_table(base)` call rather than against a stored copy.
- A repo's own `docs-src/dev/` keeps only what is about THAT repo, and says at the top which family page the rest went to.
- **A mechanism only one repo HAS is named as that repo's, in the page.** An instruction a reader's repo cannot follow is the declaration that lies, arriving through prose.
