---
name: native-session-controls-do-not-manufacture-a-claude-identity
description: Tests-first native Codex/Claude session identity controls preserve signed-role, task, milestone, PR and wall boundaries without a fake environment alias.
metadata:
  type: project
---

Issue 587 is an actual observed mechanism failure: native Codex thread metadata exists, but the hardcoded Claude session variable is absent; session-scoped mechanisms consequently see no agent. The supported verification-account deployment dry-run refused access, correctly. No role, credential, hook payload or environment alias was manufactured to get past it.

This tests-only checkpoint starts from 72536605597dc9d2672113bceda6fb616dd171fb in an independent own clone, officially bootstrapped at env9b06beb5bf7c74de. That parent's exact four-file hosted measurement passed 185 tests; this is not qualification of the new session controls. Production source and lock are unchanged.

New controls cover both native harnesses, absent/invalid/conflicting identity, auxiliary metadata that cannot substitute for a real thread, privacy of refusal diagnostics, actual PR journal recording, required/bound tasks, wall attribution, real signed-role and foreign-subject refusals, the role request's actual subject, and approved/unapproved milestone tags. A real stale-interpreter Node launcher must also retain Codex wall identity without a fake Claude session or project variable. The offline test fixture clears both harnesses before a test plants the identity it means; it does not weaken any runtime guard.

These controls are NOT RUN / NOT GREEN when introduced. The signed user credential remains mandatory after identity is recognized; no TTL, reach, task binding or verification privilege is relaxed. The separate LAB_SESSION worktree provenance is not a native harness identity. All original assertions remain; only the launcher fixture gains an explicit cwd so the native Codex case can use its actual working directory.

The normal local verify request selected ten complete owner files and ended INCOMPLETE: the real box never admitted its 1 GB request, so zero pytest items executed. Ruff check and format check passed. A qualified-name AST comparison of every original test function in the three extended test files reports no removed or altered test function; the new controls and fixture changes are not runtime proof. The next qualification door is an exact-SHA hosted focused measurement, not a resource override or another local retry against the same wall.

The fresh clone had not yet installed its declared family Git shims when the first tests-only checkpoint f1fe7d0a was created. Do not claim that commit exercised those hooks. Before any publication, the explicit official hook installer installed all six declared stages in this clone's own Git directory, and its read-only report verified every stage protected. This follow-up preserves the history rather than amending it; subsequent commits and publication use the actual installed doors.
