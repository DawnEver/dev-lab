# The participants

Every repo here is worked by a human, by agents writing code concurrently, and by one integrator session that
keeps the pipeline flowing; producer hosts prove it. A box may play several roles: capability decides, not
identity. Find your role below and do only what it says. Origin and the forge are the only shared media: a
chat message is a hint, never a trigger.

## The roles

| role | does | never |
|---|---|---|
| human | sets goals, reviews, accepts; decides forge settings and remote deletions | accepts "done" from an agent without its tests |
| author (any box, the weakest included) | cuts `pr/<topic>`, measures what it touched, commits, pushes, opens a PR | runs a full suite; merges another branch |
| producer (a box with capacity, or a cluster) | runs `forge serve`: claims a sha lacking its part, runs it, posts `tests/<part>` | produces a part it did not claim |
| forge | merges a PR whose every part stands PASS into integration, server side | merges a PR lacking a part |
| integrator | `forge integration`, `forge queue`, routes stuck PRs to their authors, `integrate promote` | hand merges; direct pushes to integration; runs tests |
| owner (per area) | fixes the reds in its `area:<name>` issue on its own PR | is interrupted by another area's reds |

- A **subagent** is an author that never publishes: it commits on its branch and hands the SHA back to its main
  session (`SUBAGENT-NO-PUSH`), which pushes the `pr/*` branch and opens the PR.
- A task is done when its own tests pass, never when an agent says so.

## One change, end to end

1. The author cuts `pr/<topic>` from `origin/integrate/main`, commits, and pushes. Seconds.
2. `forge sync` keeps that branch current with integration ([the integration branch](integration.md)).
3. A producer claims the pushed sha and posts its parts ([the forge](forge.md)).
4. `forge route` files the reds as `area:*` issues for their owners ([issues](issues.md)).
5. The forge merges the PR once its parts stand PASS, its head merges cleanly and its merge passes the audit.
6. When every part of an integration commit is a full PASS, `integrate promote` fast-forwards `main`.
7. A merged branch is deleted ([one branch per session](branch-set.md)).

Every arrow is a forge event, not someone remembering: push, missing status, claim, status, issue, fix, push.

## What follows from it

1. **The verdict is not the feedback loop.** A measurement runs dirty and answers "where am I"; a verdict is a
   fact about a sha and is produced once ([the verdict model](verdict-model.md)).
2. **A branch is the unit of parallel work** ([fan-out](fanout.md)).
3. **The box has shared resources, and the CPU is one of them** ([box resources](box-resources.md)).
4. **The file is the truth, not an agent's memory.** Every commit lands its state or memory file, and every
   "merged" claim is answered by `git merge-base --is-ancestor` or `git cherry`, saying which one answered.

## When participants collide

| situation | what happens |
|---|---|
| two authors touch disjoint files | both merge cleanly; the integration tip's parts judge the combination |
| two authors touch the same file | git detects it at merge; the later author resolves it on its own branch after `forge sync` |
| two authors each move a shared count by one | the merged number is wrong with neither at fault; [alignment](alignment.md) removes such counts |
| a human and an agent both want the box | one CPU seat; a measure waits briefly, then is refused naming the holder |
| a participant dies | its lock releases with its process; its claim lapses and is retaken |
