---
name: three-ways-a-box-or-a-run-stopped-producing
description: G admitted no box part for ~20 h (whole-box ask, then a pre-boot NUL claim record), and an Ada run hung forever after one OOM grew its ask past the quota
created: 2026-10-14
---
# Three ways a box or a run stopped producing (2026-10-14)

| incident | cause | fix |
|---|---|---|
| G: `dev_checkout`/`node` parts "G lacking cpu", starved 11 h+ | an unmeasured box part asked cpu = every core (32) against a supply of ~30 (the desktop) | a box part asks 1 core + its memory, holds what it measured (ed62c03) |
| G still "lacking cpu" after that | a hard crash (Kernel-Power 41, 10-13 22:05) left `lab-commons-cpu.claim.*.json` as 254 NUL bytes; unreadable = held, no cpu declared = whole box | an unreadable record older than the last boot is debris (`liveness.predates_boot`, e7beefe/612a714) |
| Ada: a downstream run bc53de614c `pending ... running 1/5` for hours | item OOM at 62.7 GB; the retry compounded killed-peak x2 with round oom x2 -> 366.8 GB > the 360 GB `uon-free` ceiling; `make_plan` refused, serve alarmed and waited forever | the ask is capped at the grantable ceiling, an OOM item is bisected to a lone test failed by id, an unplaceable round settles as `error` (00ea657) |

- The OOM test: the downstream `_weighted_by_row_bars` built two dense live x live squares (466c8917ab); fixed in
  downstream 517abc94ab. A test that hogs memory must come back as THAT test's red, never as a hung part.
- G's CPU itself is unstable (0x1E bugchecks incl. `c0000096`, WHEA TLB errors): turbo disabled
  (PERFBOOSTMODE 0) on 10-14. Crashes leave NUL records -- the pre-boot rule is what makes them harmless.
- Merges today redded on rules I did not run locally (module size band, suppressions, reflection, subprocess
  encoding): run every `tests/test_arch_*.py` before an integrate merge.
- Next: one box manager (`lab_commons.box`), user ruling 2026-10-14 "A 删除": reservations/leases, lending
  and preemption are deleted -- a claim exists only for a running process, is its kernel limit, and has a deadline.
