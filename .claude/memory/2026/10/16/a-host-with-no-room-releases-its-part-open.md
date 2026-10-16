---
name: a-host-with-no-room-releases-its-part-open
description: a Slurm host with no headroom (first submit) or held on an Assoc/QOS limit past the stall bound released its claim as `released: inconclusive (exit 3)`, which forgeclaim.assess reads DONE, so the sha never got a verdict; no-room is now NoRoom (a NotSubmitted subclass) and releases with the RETRYABLE prefix, OPEN to every host
created: 2026-10-16
---
# A host with no room releases its part open (2026-10-16)

## Cause
`forgerun._release_reason` mapped every `NotSubmitted` to `release_reason(INCONCLUSIVE)`. The two
no-room sites added by lane/acct-headroom (`hpc.run` first round with `plan.room == 0`;
`SlurmCluster.gather` on `held_by_a_limit`) raised plain `NotSubmitted`, so a fact about the HOST was
posted as a result about the sha. `forgeclaim.assess` reads any non-pending post not starting with
`producer.RETRYABLE` as DONE: the part was never claimed again.

## Fix
- `hpc.run.NoRoom(NotSubmitted)` raised at both sites; the learned ask (`learned.record_ask`) is still
  recorded first, so this host does not re-admit the part at the same size.
- `_release_reason`: `NoRoom` -> `released: unreachable -- this host had no room: <why>` (the existing
  RETRYABLE mechanism, the same one a box refusal uses). Other `NotSubmitted` stay inconclusive.
- Test: `test_a_host_with_no_room_releases_the_part_open_never_inconclusive`; control
  `test_a_failed_build_is_released_inconclusive_naming_its_log`.

## Re-opening a part already wrongly marked inconclusive
No new mechanism: post an `error` status on the sha in the part's context whose description starts with
`released: unreachable` (`forge status post <sha> --context <part ctx> --state error --description
"released: unreachable -- re-opened: no-room release misread as inconclusive"`, or the same through
`forgestatus.status_post`). `assess` reads only the LAST post, so the part is OPEN on the next tick.
