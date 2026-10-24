---
name: SUMMARY-2026-10
description: dev-lab's October 2026 -- the repo is born from lab-commons' dev package (cut-over 1614022); its Plans section is the one catalogue of every plan, handoff and decision log of the month.
metadata:
  type: summary
created: 2026-10-23
accessed: 2026-10-23
---

# October 2026

## Month

dev-lab split out of lab-commons with history kept (P2 of the toolchain plan; cut-over merge 1614022 on
lab-commons, relock 2235c51 here). The three memory files below exist byte-identical in both repos because
of that history; dev-lab OWNS them (their subject is dev mechanics), lab-commons only references them.

## Plans

### merge-audit-built-not-published
- status: partial
- source: .claude/memory/2026/10/07/HANDOFF-merge-audit-built-not-published-and-the-fcc-jmag-test-plan.md
- evidence: src/dev_lab/dev/mergeaudit.py, famtests/localadmission.py on integrate/main; MERGE-DEVIATIONS-NAMED adopted (motronics rem/integration.md cites it as enforced)
- remaining: acceptance triage of 15f0f1e4c9 (21 LOST / 88 CONFLICTED) not on record; blind spots: module-level pin data, helper/fixture changes, delta tests not forced into the integration selection
- decisions: extend the fingerprint to module-level assignments under test_roots?

### a-short-robust-toolchain
- status: partial
- source: .claude/memory/2026/10/21/PLAN-a-short-robust-toolchain.md
- evidence: P2 done (1614022, 2235c51; scope narrowed by DECISIONS row 22: only `dev` moved); P3 done (rows 17: motronics 07fb72c140, lab-commons b3dbbae); P5 partial (NEWEST-HEAD-ONLY, SCARCE-PARTS-BY-REACH fbb99cf, oldest-first e2711a4, data-only waits 0022b69); P6 partial (TRACKED-CITES-NO-EPHEMERAL row)
- remaining: P0 baseline logs and metrics; P1 one-session-one-PR refusal and PR landing list; P4 ai-lab review engine (findings reader move, one key source, method pinned by version); P5 `forge try`, reservations, owner notice, OS-as-resource markers, box hold guard on every fan-out; P6 builder-only deck cache, rule catch records and 30-day review, derived hand registries
- decisions: none open beyond the DECISIONS log below

### integrator-autonomous-day-2026-10-22
- status: open
- source: .claude/memory/2026/10/22/DECISIONS-integrator-autonomous-day.md
- evidence: 32 rows taken under the 10-22 grant, each with its reversal; rows 3/18 superseded by 24, 11 by 16, 4 by 14, 12 by 15
- remaining: user after-the-fact review of all rows; motronics: lazy forgeunit import that raises with dev-lab absent (row 22); narrow motronics carry reads `"*"` (row 31); stuck inconclusive heads such as 67d955f (row 28)
- decisions: row 8 relax PUBLISH-IS-THE-LOCAL-REF for a detached Break-Glass push?; row 13 install the post-commit shim into the forge host's shared hooks?; FORGE-ROLE (row 27) not found under that ID in src -- confirm where it landed
