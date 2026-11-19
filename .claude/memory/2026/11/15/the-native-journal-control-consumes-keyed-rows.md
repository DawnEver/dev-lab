---
name: the-native-journal-control-consumes-keyed-rows
description: Tests-only correction consumes the real journal mapping after complete hosted identity replay
metadata:
  type: project
---

# The native journal control consumes keyed rows

Stage: tests-only correction after a real complete hosted replay; corrected source NOT_RUN.

Actions 43720960506 measured exact b92f8f54a6d655e9540d3245c1422ebd0797400d over all sixteen complete owners: canonical FAIL/exit 1, 1 failed / 265 passed in 13.04 seconds, environment e29a74da8f4dcf3a. Receipts remain under output/logs/26/11/15/integration/native-session-candidate-b92. The 265 actual passes include the built-wheel/imported-package/installed-companion smoke; they are real observations of that exact source, not qualification of this follow-up.

The only failure is a newly introduced test API error. Public sessionprs.rows(session) returns dict[str, Row], by its declared signature and implementation, not an iterable of Row objects or a tuple with a refusal reason. Iterating the dictionary and asking each string key for .number raised AttributeError after record_opened had already successfully returned a Row. Production must not grow a compatibility result shape to accommodate this incorrect test.

Only that new control is corrected: exact one-item items() destructuring proves cardinality, the canonical forge/number key, equality with the actual returned Row, complete forge/number/branch/sha identity, and absence under another native session. No production source, lock, catalog, original test assertion or authorization boundary changes. Full sixteen-owner exact-SHA hosted replay is still required; no local RAM-wall retry and no push occur here.
