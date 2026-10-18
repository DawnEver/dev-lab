---
name: one-run-per-ref-and-part-in-flight
description: D6 implemented -- a coalesced ref (integration, feature classes) holds at most one run per part in flight across the fleet; the current tip waits "waiting behind <sha12> (in flight on <host>)", never cancelling it. Earlier tips are the tip's first-parent history (16), the same on every host.
created: 2026-10-17
---
# One run per (ref, part) in flight (2026-10-17)

- Incident: every pushed integrate/main tip was claimed separately -- Ada ezxmw9 held 7 shas of
  integrate/main at once, <user-b> another -- filling account memory so the newest tip was never admitted.
- Ruling (D6 of <consumer> DECISION-distributed-compute-final-architecture): never cancel a running
  part; newer pushes queue and the next tip is tested as one batch (per-test carry makes it cheap).
- Where: `forgecoalesce.behind` is the one rule (moved out of `forgeschedule`, which crossed the 300-line module band); `forgetake.ClaimPass._blocked` (claim) and
  `forgequeue.forge_queue` (display) both call it. `Schedule.coalesce` (default `integration`, `feature`)
  is the declared data; `branch` (lane/*) and `pr` heads are tested at every pushed sha.
- How in-flight is found with no new state: the claims already on the forge, read on the ref's EARLIER
  tips from `refs/remotes/origin/<ref>`'s reflog (newest first, at most 16), stopping at the first tip
  whose part is settled. Limitation: a tip pushed AND claimed between two of this host's fetches is not in
  its reflog; ticks are minutes and runs hours, so the window is small. A first-parent walk would close it
  at one status read per ancestor.
- `candidates` already named only the tip, so an earlier never-claimed sha is never claimed.
- Tests: `tests/test_dev_forgetick.py` -- the coalesced-tip/lane/settled planted controls on `behind`,
  only-newest-is-a-candidate, and a tick that claims nothing behind bob's run then claims once it settles.
  `_declare` now answers the replaced head's statuses `[]` (a real forge does; the fake 404s).
- Gap closed the same day (coordinator): the reflog was HOST-LOCAL state, blind to a tip pushed and
  claimed between two of this host's fetches. `_earlier_tips` is now `git rev-list --first-parent -n 16
  <tip>~1` -- history is one source of truth on every host; on integrate/main each first-parent commit is
  a merge, so the reads stay few. Test: `test_a_tip_another_host_claimed_that_this_host_never_fetched_
  still_blocks`. The fixture `_origin` answers `[]` for every commit's statuses (a real forge does).
