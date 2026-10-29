---
name: forge-waits-answered-bounded-and-seen
description: The long forge queue waits of 2026-10-25 classified; a box now answers a never-fitting part, protects a waiting part's earliest start and tells it on waits/<part>; the Ada wall over-ask is lab-commons' and open.
created: 2026-10-25
metadata:
  type: project
---

# Forge waits: answered, bounded and seen

## The waits of 2026-10-25, classified

| class | what | count | answer |
|---|---|---|---|
| (a) no live host can ever fit | none measured: host-A's size is 30.1 GB after its reserve, the 12.4 GB base part fits it | 0 | `forgewait.nowhere` now refuses such a part on its commit at once, naming the remedy |
| (b)+(c) fits, host busy, smaller claims keep passing | consumer-c milestone `base` on host-A, `lacking mem_gb (12.4 asked, 0 free)` for hours; G read 0.21-0.8 GB free all day beside interactive verify claims | 1 | the claim pass protects its earliest start (`Box.delays`, the ledger's backfill rule) and posts `waits/base` past `request_unadmitted_hours` |
| (d) host liveness | 12 dev-lab PRs `no host provides workstation` (13 reported), host-A's only serve busy, its card STALE | 12 | dev-lab #135 |
| (e) Ada idle-core waits | user4 last 36 h: 1149 tasks, shortq p90 wait 1.27 h even at a <=1 h limit; defq tasks asked a median 45.2 h wall and used a median 0.27 h (p90 10 % of the limit) | 92 defq tasks over 12 h | lab-commons `hpc/gather.py:102`, open, below |

The G case is NOT (a): `Capacity.read()` on host-A is 31 cores / 30.14 GB. What starved it was ordering -- a part
refused for room never took a ledger ticket, so every interactive verify and every smaller part was admitted
past it; `lab_commons.box.order` only protects TICKETS.

## What changed (dev-lab, pr/queue-waits-bounded-and-visible)

- `forgewait.py`: `Box` (size, ledger claims, one OS reading per pass), `Outlook` (never / earliest start +
  the claims ending first / `inf` = used outside the ledger), `nowhere` (no live card serving its needs is
  large enough; an unsized or big live card waits), `tell` (pending `waits/<part>`, once per waited hour per
  host, `success` once claimed; never a `tests/` context).
- `forgetake.ClaimPass`: a refused part's blocked line carries its outlook; a lower-ranked admitted part that
  would delay a protected start waits `queued behind <key>`; claims taken in the pass count as held.
- `forgetick.tick(box=, cards=)`, `forgerounds.box_now`, `forgeserve(boxed=)`, `HostCard.size` (a box's
  size after its reserve; `{}` is unstated and never refuses).
- `forgeproduce.box_claim` and the outlook share `forgewait.claim_vector`.

## Open

- A forge part still holds no LEDGER ticket between passes, so an interactive verify started between two
  ticks still passes it; protecting it there needs a non-blocking ticket in `lab_commons.box.ledger`
  (lab-commons PR #413's one-path design is where it belongs).
- `request_unadmitted_hours` now bounds parts too; its name says requests. Rename in lab-commons' Schedule.
- Ada over-ask: `gather.py:102` sets `state['min_minutes'] = 2 * planned['minutes']` after ANY timeout, for
  every later band of the run, and it compounds round over round (one hung test: 1.4 h -> 45 h walls on defq,
  preferred for the longest ceiling). `Measured.killed` already prices the interrupted id; the global floor
  should go or apply only to the timed-out items.
- Aging: proven within a scored tier (`test_aging_brings_an_old_waiter_to_the_front_...`); `served_first`
  tiers and a host's `[priority]` stay strict by ruling, so a flood of priority work can still precede.
