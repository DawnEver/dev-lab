---
name: DECISIONS-coordinator-1113-night
description: Coordinator decisions of the 2026-11-13 night under the user's full autonomy grant -- break-glass wave, size-alarm split, venvspelling floor, cc-market branches, deferred venv bootstrap, unenabled ops features, promote gate.
created: 2026-11-13
accessed: 2026-11-13
---
# Coordinator decisions, 2026-11-13 (night)

Made under the user's autonomy grant of 2026-11-13 night: the user would give no guidance for a full day, asked
the coordinator to iterate until every task is done, granted full authority to decide, and asked that each
decision be recorded for review afterwards. Each row names its source or principle.

| # | decision | source / principle |
|---|---|---|
| 1 | Opened the next break-glass wave (`20261113T224809Z`, 60 merges / 24 h) with the user's code; merges #536-#541 and lab-commons #174 went through it. Every such PR still gets the forge's run afterwards | break-glass is an UNTESTED merge, not a verdict (`VERDICTS-FROM-THE-FORGE`) |
| 2 | `forgerequest.py` was split by concept instead of pinned in the size alarm | `no-historical-baggage`: a pin waives the check it pins |
| 3 | venvspelling floor re-measured 479 -> 503; margin 40 unchanged | the code base grew; a floor is re-measured, never loosened (`RATCHET-TWO-SIDES`) |
| 4 | cc-market stays one-branch: #11 (into a stale `integrate/main`) closed, #12 into `main` merged, the stale `integrate/main` deleted after a lossless check | cc-market's own adoption decision; `MERGE-OR-DELETE` |
| 5 | The private consumer's main checkout was fast-forwarded; its venv bootstrap DEFERRED, because other sessions' runs (a forge watch stream, a reclaim run, a commit hook) held the venv | stopping another session's run needs the user. Gap (to design): a long-lived watcher can pin a venv forever |
| 6 | Host auto-upgrade (#534) and the status card (#539) are built but NOT enabled; enabling needs `[ops.upgrade] follow` / `[ops.status]` through a consented config apply | waits for the user's one code after dev-lab `main` is promoted (consent is the user's) |
| 7 | dev-lab `main` is promoted only after a green forge run on `integrate/main`, never from break-glass alone | `TRUNK-MOVES-BY-FAST-FORWARD`; break-glass carries no verdict |

Review: each row reverts independently; rows 5 and 6 are open until the user acts.
