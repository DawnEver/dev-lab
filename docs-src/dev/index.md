# Development mechanism

How the family's repositories are developed: who writes code, who proves it, and how it reaches `main`.

- Authors edit in a worktree, measure only what they touched, commit and push. Nobody runs a full suite to push.
- The forge holds every verdict: `forge serve` hosts claim a pushed sha and post its `tests/<part>` parts.
- `integrate/main` coordinates; `main` moves only by `integrate promote`, when every part is a full PASS.
- `.claude/rules/**` in each repo holds hard constraints only and is read on every turn; these pages hold the
  mechanism and are read when you do the thing.
- New here, or arriving from the old local-gate model: read [Migrating a workstation](migrate.md) first.

## The pages

| page | what it covers |
|---|---|
| [Onboarding a repo](./onboarding.md) | Every declaration a new repo supplies, in one call and one table |
| [Migrating a workstation](./migrate.md) | Start here if you used to run the gate before a push: what to stop, and the five commands that replace it |
| [The three participants](./the-three-participants.md) | Who does what: the human, the authors, the producers, the forge and the steward |
| [The verdict model](./verdict-model.md) | What a verdict is, the tiers, and which destination needs which forge parts |
| [Testing discipline](./testing-discipline.md) | The lightweight/heavy partition, xfail never skip, one test session per box |
| [Branch layers](./branch-layers.md) | Trunk, integration and child branches: what each proves and the one verb that moves it |
| [Alignment](./alignment.md) | How every branch keeps shared bookkeeping out of merge conflicts |
| [Fan-out](./fanout.md) | Parallel work in worktrees: environments, subagent bases, measuring, landing |
| [The shared checkout](./shared-checkout.md) | What breaks when several parties write one checkout, and the habits that prevent it |
| [Killed runs and orphans](./orphans.md) | What survives a stopped run, why a lock judges liveness, and how to reap |
| [Box resources](./box-resources.md) | What one workstation rations, and the broker every run declares its cost to |
| [The forge](./forge.md) | Parts, claims, `forge serve`, scheduling and `forge queue`: how a sha gets its verdict |
| [The integration branch](./integration.md) | The path of one change, the roles, the integration tick, `forge sync`, `integrate promote`, the merge audit |
| [Components](./components.md) | A product mounts its engines as submodules: the table, the derived-file check, the bump loop |
| [Issues](./issues.md) | An issue is intent; its state is derived from refs and parts; claims and priority are labels and comments |
| [HPC clusters](./hpc.md) | A cluster is one more `forge serve` host: grants, the one-line deploy, runs, records |
| [Artefacts](./artefacts.md) | A run's declared outputs: the store, its layout and its retention |
| [Retirement](./retirement.md) | The archive keeps old code, the registry keeps a dead spelling dead |
| [The docs pipeline](./docs-pipeline.md) | The three properties a docs builder holds, and why a skipped sub-site is announced |
| [Translations](./translations.md) | How a `<stem>.zh.md` beside its `<stem>.md` passes the CJK guard, and the non-ASCII goal |
| [Worktrees stay inside](./worktrees.md) | Every checkout lives under `<repo>/.claude/worktrees/<name>` |
| [One branch per session](./branch-set.md) | The declared branch set, merge-or-delete, and the push-time check |
| [Auto mode runs the doors](./auto-doors.md) | Local cleanup and run stops are checked doors both clients allow unprompted |
| [Refusals](./refusals.md) | Every deny refusal is a clause, a door and a pointer; the full text of each row |
| [Project files](./project-files.md) | Every project file is rendered from a family base plus a delta, or owned by the repo; hooks and CI are TOML |

## How a consuming repo uses these pages

- These pages exist once, here. A consuming repo's dev index renders the table above with
  `lab_commons.dev.devdocs.pointer_table(base)`, where `base` is its path to this directory.
- A local page under the same name holds only that repo's delta and links the family page in its first lines
  (`lab_commons.dev.famtests.devdocs`).
- The test for where a page belongs: does its subject change when you change repos? The box, git, the forge
  and the process are the family's; a repo's domain stays home.
