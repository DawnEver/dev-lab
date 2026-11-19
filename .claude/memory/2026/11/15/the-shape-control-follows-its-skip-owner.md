---
name: the-shape-control-follows-its-skip-owner
description: Complete-owner evidence exposes one missed shape-control consumer and a separate summary-marker ambiguity
metadata:
  type: project
---

# The shape control follows its skip owner

Stage: tests-only consumer correction after actual complete-owner execution; corrected candidate NOT_RUN.

Actions 43727443801 measured exact 96f00d892e53ef7abf0418a717268031275c6cfa over 73 complete owners. Raw pytest was 1 failed / 1,085 passed in 70.40 seconds, environment e29a74da8f4dcf3a. The canonical result is INCONCLUSIVE/exit 3, NOT canonical FAIL or PASS. Receipt and complete raw output remain under output/logs/26/11/15/integration/architecture-run-43727443801. The observed passes include the unchanged functional/lifecycle controls, but this run does not qualify the whole candidate.

The sole raw failure is test_dev_logdistil::TestTheShapeSetIsARatchet::test_the_representatives_are_exactly_the_shapes_the_parser_consults. Its actual source census still read only reports.py and pytestout.py, omitting skipallowance.py after the policy relocation. The _SKIPPED recognizer still exists exactly in the new canonical policy owner and is consumed by report evidence; the representative is not obsolete. The test now reads all three real owners. It retains the exact PARSE_SHAPES representatives, floor 12, headroom 4, exact set equality and every distillation/refusal control. No production alias or duplicate recognizer is restored, and no number changes to conceal the omitted member.

The canonical INCONCLUSIVE has a separate concrete cause. stdout says the run was truncated by reported '+ Timeout +' and pytest stayed silent. In verify.log, the failure-body occurrences at lines 51/58 are behind the pytest E prefix and are correctly excluded by pytestout._marker_is_the_runs_own. The short-summary continuation at line 83 is an unindented assertion repr containing that representative literal. The current classifier excludes whitespace/E prefixes but treats this continuation as the run's own timeout marker; reports then supplies truncation to Proof, which correctly refuses settlement under that supplied evidence. This is not a missing or whitespace-corrupted structured record identity.

No marker classifier, completeness gate or verdict logic changes in this checkpoint. A separate exact-runtime negative control should plant a genuine multiline pytest short summary containing marker literals while retaining all real timeout/worker/collection-banner positives. That source-boundary issue belongs with DawnEver/dev-lab#599 and must not be hidden by labeling raw failure output as a canonical result.

Ruff/diff checks are static only. Root must replay the same complete 73 owners on the fixed SHA; no local resource override, pytest retry, push or assertion weakening occurs here.
