---
name: recorded-stage-identities-first-tests-are-not-a-green-source-fix
description: Tests-only checkpoint for issue582's legal-whitespace identity loss and exact structured-stage evidence, preserving existing text-log and lifecycle guards.
metadata:
  type: project
---

## Subject and source boundary

Root handed exclusive write ownership of this separate dev-lab clone at clean
7bf5ff864264561657a821503249d53716307125, own envb6d93e25006dfa0c. The existing
997 stop/lifecycle and 7a41 default work remain present. No source, environment,
resource policy, codec, timeout, worker setting or original assertion is changed
by this tests-only checkpoint.

The observed issue582 failure is NOT retrospectively called PASS: the ae03
Actions43695441263 run had25 actual assertion failures and71 passes, while the
canonical result refused with25 versus11 named failures. reports._FAILED_NODE
uses a non-whitespace token where pytest permits whitespace inside identities.
Live identities already exist in the canonical CellRecorder/Record data.

## Proposed public evidence contract under test

- read_pytest accepts explicit cells and flaky facts. None remains the real
  independent log-only method; an explicitly empty live mapping must never
  fall back to parsing printed names.
- read_stages accepts positional (cells, flaky) facts for each (text, exit)
  stage, with exact length checking. Each real process/stage keeps the existing
  recorder format; the reader unions the actual parallel/serial directories.
- Canonical TestCell.red and testcells.conclude own semantic decisions. Text
  independently witnesses counts, collection, interruption, errors, skips and
  exit. New inputs do not erase original truncation or skip guards.
- Complete accounted count must match actual stage cell population. Green
  cells cannot overrule a red terminal summary, and missing/corrupt/truncated/
  extra/flaky records cannot manufacture a live PASS.

New tests include a real run_verify/pytest parallel+serial example with four
failing whitespace/delimiter/bracket IDs, and a real non-strict XPASS whose
pytest process exits zero. Pure controls use real CellRecorder records and
canonical TestCells, not a second classifier. They distinguish None from empty
evidence, retain exact25 identities, check expected rejections, retryable cells,
non-strict/strict XPASS, unmarked skips, printed-name spoofing, original text
guards, stage cardinality and cross-stage disagreement. Reader controls cover
stage-directory union and rejection of mixed or unknown layouts.

## Qualification and next action

These new tests are NOT RUN and NOT GREEN at this checkpoint. A missing new
keyword is not itself the historical issue's proof: the real public verifier
example reproduces the existing identity failure without requiring new report
keywords. The full affected qualification scope remains:
tests/test_dev_verify.py, tests/test_dev_serialpass.py,
tests/test_dev_test_outcomes.py, and tests/test_dev_logdistil.py.

Root will normally publish the fixed tests-only SHA and use its already
qualified focused Actions measurement door. This worker does not push,
dispatch Actions, open/ready a PR, start external review or override local
admission. Actual RED/GREEN must come from complete formal execution; a local
never-admit is INCOMPLETE and provides no RED credit. After real RED, the live
caller must read the real stage facts and existing fake-positive tee fixtures
must emit actual CellRecorder data without weakening their original assertions.
