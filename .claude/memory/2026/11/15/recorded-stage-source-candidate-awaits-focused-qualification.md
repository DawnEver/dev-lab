---
name: recorded-stage-source-candidate-awaits-focused-qualification
description: Issue582 source candidate consumes canonical stage cells without parsing live whitespace IDs; real hosted RED exists but the fixed full scope is not yet qualified.
metadata:
  type: project
---

## Actual RED, not a relabelled receipt

Tests-only 6f5157d925c68d498f099cc06c6dd9df4a14ed26 was normally published
by root. Focused Actions run43707074179/job132790343892 ran all four complete
owners: tests/test_dev_verify.py, tests/test_dev_serialpass.py,
tests/test_dev_test_outcomes.py and tests/test_dev_logdistil.py.
Raw pytest reported 35 failed and145 passed in19.60s. These actual assertion
failures establish counterexamples, including legal whitespace failure IDs and
non-strict XPASS. The canonical receipt remained INCONCLUSIVE/exit3 because the
existing identity parser also misread the outer failing run; it is not called a
canonical FAIL or PASS. Root saved receipt/stdout/verify artifacts under
output/logs/26/11/15/integration/recorded-failure-tests-red-6f5157d9.

## One decision owner, independent witnesses

Live verify uses the existing CellRecorder/Record codec in parallel and serial
subdirectories. The reader unions only that declared layout; unknown, nested,
mixed, corrupt or retired evidence is refused. Executed and recorded stages
must match. Exact identities and misses come from TestCell.red and the combined
decision from canonical conclude/merged, not another pytest classifier.
Skip identities project the reason kinds already recorded by judged().

Explicit cells=None/stage_cells=None preserve the existing pure text-log
method. Explicit empty live evidence never falls back to it. Text remains an
independent summary-total, collected-count, exit, interruption, error, marker
and skip-allowance witness. Accounted tests must equal the stage cell count;
deselected items are not recorded outcomes. Summary failed/XPASS counts cannot
be overruled by green records. Existing stop/lifecycle, scope, skip ceilings,
stale declarations and original assertions remain.

Passing process doubles now write actual CellRecorder records, rather than
pretending a summary or an empty JSON object is evidence. Persistence still
proves live writes are outside the checkout, land beside the log and disappear
from the temporary location. Additional four real whitespace-skip controls and
an unexecuted-stage negative are new coverage, not previously executed REDs.

## Qualification boundary

One normal local full-four-file verify attempt used unchanged admission and
envb6d93e25006dfa0c. Session1120 / own verifier PID28760 (runtime21444) ended
without admission: log output/logs/26/11/15/verify/verify-20261115T112248Z.log,
1GB requested/0 free, foreign holders47228 and41364. No test ran. This is
INCOMPLETE, not RED or GREEN; those holders were not touched. Source was frozen
until terminal. Subsequent stage-binding and documentation refinements are
also unqualified. Static Ruff/check and formatting passed before the last
narrow missing-directory expression adjustment; normal commit hooks will
check the complete candidate. No environment, budget, timeout, worker count,
codec, dependency or scientific bar changed. No push or review was dispatched
by this worker. Root must run the same four complete owners through its normal
focused Actions door before calling this fix GREEN or DONE.
