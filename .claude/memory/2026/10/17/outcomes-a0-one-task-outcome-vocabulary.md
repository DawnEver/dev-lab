---
name: outcomes-a0-one-task-outcome-vocabulary
description: Track A item A0 of <consumer> PLAN-engines-and-one-outcome-vocabulary landed on lane/outcomes-a0 -- `lab_commons.outcomes` (stdlib only): Family/Status/Evidence, Reason/Cost/Cell, Identity, Expectation, JSONL reader, Record, Conclusion; A1 (producers, forge format) deliberately not started
created: 2026-10-17
---
# `lab_commons.outcomes` -- A0 (2026-10-17)

Spec: <consumer> `.claude/memory/2026/10/17/PLAN-engines-and-one-outcome-vocabulary.md`, II.3 and Part IV A0.1-A0.8.

## Decisions taken where the spec was silent
- `Cell.evidence` defaults to OBSERVED; `Cost` fields `None` = unknown, never zero; a value is int/float (not bool), NaN refused, inf allowed.
- `Identity.of(subject, context)`: inactive = the `INACTIVE` sentinel (dropped); `None` is a VALUE and is kept. `1` != `1.0` != `True`. NaN/inf and non-string keys refused.
- `Expectation.met_by`: NOT_APPLICABLE meets every expectation (answers no question); RETRYABLE returns None. `Conclusion.over` therefore: any DECIDED mismatch -> FAIL even beside a RETRYABLE.
- Record idempotence: an outcome equal to the identity's CURRENT cell writes nothing; other kinds dedupe against any equal earlier event. Finality refuses any differing later outcome (DECIDED or RETRYABLE) after a DECIDED one.
- Record is ONE WRITER PER FILE; views come from open + own appends. A torn tail is truncated before the next append, else it would become a torn MIDDLE line.
- JSONL reader: an unterminated tail is torn even if it parses (writer writes line+newline together).
- Event lines carry `schema: 1`; `_UPGRADES` is consulted before `UnknownSchema` (FORMATS-UPGRADE-ON-READ).

## Pre-existing reds on origin/integrate/main b940d48 (not this lane)
`test_arch_module_size_alarm` (forgerun.py, hpc/deploy.py over band; _rule_rows.py grew) and
`test_arch_suppressions_are_a_named_set` (undeclared PLC0415 in box/demand.py).

## Next
A1 (pytest/hpc/verdict/forge producers onto it) is a coordinated cutover; not started.
