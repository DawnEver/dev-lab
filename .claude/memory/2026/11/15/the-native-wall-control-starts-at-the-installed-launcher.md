---
name: the-native-wall-control-starts-at-the-installed-launcher
description: Tests-only correction separates the Claude adapter fixture error from actual native identity failures
metadata:
  type: project
---

# The native wall control starts at the installed launcher

Stage: tests-only correction after an actual hosted RED; NOT GREEN, with no production or lock change.

Actions run 43712496872 measured exact 346a4a337dbdf0719f23c4d7c7bd163be328111d over all ten complete selected owners. The canonical receipt is FAIL/exit 1, raw pytest 21 failed / 138 passed, environment b6d93e25006dfa0c. Its artifacts are retained under output/logs/26/11/15/integration/native-session-tests-red-346. These are executed counterexamples, unlike the earlier local request that never entered pytest. Native session module absence, Codex signed-role lookup, request subject, PR journaling, required task, wall attribution and both milestone guards supplied the actual identity failures.

One of those 21 failures is a fixture defect and must not be counted as a product identity counterexample. The NEW Node control invoked the Claude-specific TASKBIND_COMMAND after deliberately removing CLAUDE_PROJECT_DIR, so its shell expanded an absent project directory and failed to find /.claude/hooks/py.js. It never entered the launcher and proved nothing about fallback wall attribution. The prompt-binding adapter is a separate issue (#580); it is not changed into a generic working-directory shim here.

Only that new test now invokes the real installed launcher asset directly, through the existing normal node_path() and agent_wiring.LAUNCHER_REL, with the planted checkout as cwd and its genuine Codex field. The fixture still installs the actual launcher, constructs the same stale Python metadata and leaves both fake Claude variables absent. Its original assertions require the normal bootstrap remedy and the actual wall's Codex identity; none is deleted or weakened. The unused optional cwd extension to the shared _bind helper is removed, restoring that helper exactly to parent 72536605597dc9d2672113bceda6fb616dd171fb. A standard-library AST comparison finds every original function in this owner unchanged from that parent; only the newly introduced control changes.

The corrected control has NOT RUN at this checkpoint. Root will publish it and replay all ten complete owners through the supported exact-SHA hosted door, to reach the real Node wall counterexample before production implementation. No environment alias, role credential, task binding, consent-state write or machine reach edit was used. The leaf and cross-caller implementation remains pending actual RED and root approval.
