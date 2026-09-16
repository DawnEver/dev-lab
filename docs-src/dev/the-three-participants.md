# The three participants — the human, the dev agents, the coordinator

- Every repo in this family is worked the same way, and it is genuinely three participants: a human, several dev agents working concurrently, and one coordinator agent that absorbs their work.
- The branch layers those three produce are on [branch layers](branch-layers.md); the verdict they all cite is on [the verdict model](verdict-model.md).

## Who does what

- **The human** sets goals, reviews, adjusts, and accepts; a task is DONE only when ITS OWN tests pass, never when an agent says so.
- **The human is the ACCEPTOR of the heavy tier, not its runner** — the agent runs it and records what it said. This was written as "the runner is the human" until 2026-09-07, and that phrasing was read as "an agent may not run heavy": measured on the 2026-09-06/07 integration session, an agent went most of a day without running the tier that gates `main` while believing it was forbidden to.
- **A dev agent** plans in a tracked file, implements on its own branch under TDD (one feature per commit, the commit being the state-file boundary), gates its own tree, pushes, and reports SHAs, measured verification and files touched.
- **The coordinator agent** takes a lane whose tip has moved, pulls that work into its OWN integration worktree, re-gates the combination, repairs the shared pins, and advances `main` on a heavy PASS.
- **Readiness is REF MOVEMENT, not a message.** Given "push each green commit" and "one commit completes one feature", the tip of a lane branch is integration-ready by construction; detection is listing the remote's lane refs and then asking `git cherry` which of their commits the integration branch does not hold, whose plus lines ARE the merge list. A chat notification is a PRIORITY HINT and may never be the trigger, because a trigger living only in chat contradicts "origin is the only shared medium".
- The dev agents keep working while the coordinator integrates, so divergence is expected and deliberately unbounded — absorbing it is the coordinator's job, not a failure state.

## The four facts everything else follows from

1. **The verdict is not the feedback loop.** A measurement answers "where am I" and runs dirty; a verdict answers "may this land" and needs a tree it can name.
2. **A branch is the unit of parallel work** — environments, shared hazards and landing are on [fan-out](fanout.md).
3. **The box has shared resources and at least one of them is locked** — two CPU-saturating runs cannot proceed at once; see [box resources](box-resources.md).
4. **The file is the truth, not the agent's memory.** Every commit lands its state/memory file, and every "merged" claim is answered by `git merge-base --is-ancestor` or `git cherry`, saying which one answered.

## Contention — the cases that actually occur

| situation | what the architecture does |
|---|---|
| two agents touch disjoint files | both gate and land; each verdict is about its own tree |
| two agents touch the same file | git detects it exactly at merge; the loser rebases. No pre-emptive lock |
| two agents each move a shared ratchet pin by one | both merge cleanly and the merged number is wrong with neither at fault; the coordinator re-measures it on the merged tree |
| a human edits while an agent gates | allowed; the cost is load, and load is the named worker-death trigger. Never compare two configurations from one run each |
| a human and an agent both want the box | one lock, first holder wins, the other is REFUSED and told who holds it |
| a participant dies | the lock releases to the OS; a missing run log means "not finished", never "not started" |
| the box is shared | count orphans before quoting any timing; a busy-box timing is not a property of the file |

## What keeps the picture honest

- A verdict names its tree and its environment, so a stale or cross-environment verdict cannot be quoted.
- A skipped test is green and a tier nobody runs rots, so the heavy tier has no flag to be unset and no wall to hide behind — and because it blocks no push, the only thing that makes it run is an agent choosing to run it.
- No hook or guard knows the integration branch's prefix, so the coordinator's discipline is exactly the re-gate and nothing enforces it for them.
