# The integrator — two ways to wake, one queue

- This page is how the integrator (the coordinator of [the three participants](the-three-participants.md)) finds work. What a lane, the integration branch and `main` each prove is on [branch layers](branch-layers.md); the statuses it reads are published as described on [the forge](forge.md), layer C.
- **User directive 2026-10-02: two work modes, one merge queue, one definition of "ready".** WOKEN: an event (a lane's `lab/gate` went green) wakes the integrator's session. SELF-POLLING: the integrator fetches every origin branch on a cadence and compares their `lab/gate` and `lab/heavy` statuses.
- **The modes differ only in WHAT STARTS a pass, never in what the pass computes.** Both run `git fetch --prune origin` through the retry wrapper, then `python -m lab_commons.dev.integrator queue [--json]`. A wake carries no readiness — it means "re-derive now" — which keeps the existing rule that a notification is a priority hint and origin is the only shared medium.

## The ready predicate

- Inputs: the remote-tracking refs (`refs/remotes/origin/*`, with each tip's committer time), `git cherry` of each tip against its target, and the LATEST status per context on each un-absorbed tip.
- A **lane** is an origin branch under a declared prefix. It is skipped when ABSORBED: `git cherry <origin/integration> <tip>` prints no `+` line, so a cherry-picked or rebased lane whose content is present is not re-queued (the ancestor test would say no).
- An un-absorbed lane is `merge` when its tip's latest `lab/gate` is `success`, `blocked` on `failure`, `waiting` otherwise (absent, `pending`, `error`). `gate_ready(state)` is the one spelling of that rule, and `forgeissue`'s `ready` state calls the same function.
- The **integration branch**, when its change is not on `main`, is `promote` on a `lab/heavy` `success`, `blocked` on `failure`, `heavy-needed` otherwise.
- Everything else (`main`, undeclared prefixes) is never queued.

## The queue

- **It lives nowhere. It is recomputed from origin every pass**, by `ready_lanes(refs, statuses, policy)` — a pure function over the inputs above. No file, no daemon state, no comment thread holds it, so there is nothing to go stale and nothing two modes can disagree on.
- **Idempotent by construction**: a duplicate wake, a wake lost in transit, and a wake racing a poll all print the same queue, because none of them is an input. A merged lane drops out on the next pass because `git cherry` now absorbs it.
- **Order**: oldest tip commit time first (the lane that finished first merges first), ties by branch name, so two passes over the same refs print byte-identical queues. The integrator merges the `merge` rows in that order, re-gates the combination, publishes `lab/gate` on the integration tip, then runs heavy when the row reads `heavy-needed`, and fast-forwards `main` on `promote`.

## Mode (a) — woken

- The observer is the bridge daemon's `observer.mjs` (per machine, in the user's Claude Code config tree, not in this family). It already fetches each observed repo, follows a pushed tip until `lab/gate`/`lab/heavy` appear, and posts the result into that session's Telegram Topic.
- **The wake is one more sink for the event it already detects.** When a `lab/gate` `success` lands on a lane tip, the observer also calls its host adapter's `inject(id, text)` for the session whose branch is the declared integration branch in that repo, with the text `integrator: wake <repo> <branch> <sha>`. The Claude adapter delivers that as a channel message, which starts a turn in the integrator's session; its handler is "fetch, then `queue`".
- **The adapter is documented, not shipped here.** The observer lives outside this family's repos and its inject path needs a live channel-connected session, which no test in this repo can stand up. What it needs: identify the integrator session by `branch == integration` (it already reads each session's branch), and coalesce — at most one wake per repo per poll.
- Inside Claude Code, a session that is not channel-connected is reachable by cross-session `SendMessage` from another agent; that is the fallback if the bridge is down, with the same one-line payload.

## Mode (b) — self-polling

- The integrator schedules itself (`/loop` or `ScheduleWakeup`). Each tick: fetch through the wrapper, `queue --json`, act on the first actionable row, reschedule.
- **Cadence: 10 minutes idle, immediate re-run after a pass that merged something.** A gate on the integration branch costs the whole lightweight suite (about 13 minutes measured on branch layers), so polling faster than a gate takes buys nothing.
- **Cost per tick**: one `git fetch` (one network round trip, refs only when nothing moved), one `git cherry` per declared ref (local), and one forge API call per UN-ABSORBED tip — absorbed lanes are never asked about. Ten open lanes is ten small GETs per tick.
- Woken and polling coexist: a wake simply brings the next tick forward. Polling is the floor that makes a lost wake harmless.

## Failure modes

| failure | what happens |
|---|---|
| stale status — the lane moved after its gate | the green is on the old sha; the new tip has no status and reads `waiting` until its own gate publishes |
| force-pushed lane | same as above: statuses are keyed on the sha, so a rewritten tip starts unjudged; nothing to detect |
| stale refs — the caller forgot to fetch | the tips are printed in every row, so the answer is visibly old; the module never fetches (network belongs to the retry wrapper) |
| forge unreachable | the `queue` call exits non-zero with the forge door's remedy; nothing is merged on a guess |
| seat contention — gate/heavy already holds the box | the pass waits on the box seat like any verdict; a wake arriving meanwhile is coalesced into the next pass, never queued twice |
| two integrators on one repo | not prevented here; the forge's push whitelist and the fast-forward-only `main` update make the loser's push fail, and it re-derives |
| a lane blocked on `failure` | listed under `held` with its tip; it is the lane's to fix, the integrator does not retry it |

## What a consumer declares

Only names, in its `pyproject.toml`; every key is optional and an unknown key is refused:

```toml
[tool.lab_commons.integrator]
lane_prefixes = ["feat/", "fix/"]   # which origin branches are lanes
integration = "integrate/main"      # the branch lanes merge into
main = "main"                       # the branch a heavy PASS promotes to
gate_context = "lab/gate"           # the lane verdict's status context
heavy_context = "lab/heavy"         # the integration verdict's status context
```

- The predicate, the order and the queue are the family's and are not configurable: a consumer that could redefine "ready" would be a second source of it.

## A merge names every test it lost or rewrote (`MERGE-DEVIATIONS-NAMED`)

- The tests ARE the feature inventory, so the one regression a gate cannot see is a resolution that deletes or rewrites the test that would have caught it. `lab_commons.dev.mergeaudit` computes, per test, what a clean three-way merge would hold, and reads git objects only.
- A deviation is `LOST` (expected, absent), `ALTERED` (a body or presence the clean merge would not hold) or `CONFLICTED` (both sides changed it differently). Each is named in the merge commit: `Merge-Audit: <KIND> <test> -- <reason>`. A clean merge needs no line; a line naming no real deviation is refused too.
- `ALTERED` passes on the merging agent's one-line reason and is audited afterwards (user ruling 2026-10-07).
- Push admission audits every merge reachable from HEAD and from no remote ref, on EVERY destination, over `test_roots` in `[tool.lab_commons.integrator]` (default `["tests"]`). Name the deviation before the first push: once a merge is on a remote, it is no longer re-audited.
- Integrate by MERGE only: a rebase resolves conflicts with no merge commit to audit.
- Not seen: a fixture or helper changed under an unchanged test body. It still runs under the gate.
