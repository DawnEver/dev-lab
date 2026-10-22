---
name: DECISIONS-integrator-autonomous-day
description: Decisions the integrator took alone on 2026-10-22 under the user's full grant, for after-the-fact review.
metadata:
  type: decision-log
created: 2026-10-22
accessed: 2026-10-22
---
# Integrator decisions, 2026-10-22 (user away all day, full authority granted, review afterwards)

Grant (user, 2026-10-22): "完全授权你去做决策，记录下来，到时候我事后审核". Every decision taken alone is one row here,
newest last. Hard limits that the grant does NOT lift: no force-push, no remote branch deletion outside the
lossless door, no OneDrive write beyond what the user already approved, no secrets in logs.

| # | decision | why | reversible by |
|---|---|---|---|
| 1 | Keep at most 3 agents at once; one PR per session per repo; push docs only together with code | user rulings 10-21 | -- |
| 2 | cc-market prompt-only finding schema (no principles enum in prompts) keeps `schema_version` 2 | a longer prompt from an older executor is not a misread: its output stays valid; ai-lab learns `prompt_schema` in #31 | bump to 3 |
| 3 | The 46 multi-sentence rule statements stay as named debt under a ceiling of 47; no mass rewrite today | rewriting 46 injected rules is its own reviewed change | rewrite and lower the ceiling |
| 4 | Tried to land motronics #4684 (collection fix) through Break-Glass after a local census collected 42,525 tests / 3,396 files at a6c9cfa0d0; the session's permission classifier refused the action, so it waits for a forge verdict | the forge cannot verdict a fix while the base it fixes does not collect; a refused action is not worked around | user lands it, or the forge claims it once WS hosts carry #236 |
| 5 | Released cc-market v3.0.4 (prompt budget, prompt-only finding schema) after ai-lab #31 learned `prompt_schema` (870a59a) | user's "fix all three"; ai-lab and cc-market land together | revert the release commit |
| 6 | ai-lab conformance reads cc-market's MAIN checkout through `[capabilities.sharp_review]`, so its results move whenever that checkout moves | noted, not changed: the method of record is cc-market main by ruling 3a | pin the method by version in ai-lab (plan P4) |
| 7 | A hook shim never blocks on a missing venv: checkout venv, else the interpreter recorded at install (runs only `python -m lab_commons` rows), else exit 0 with one stderr line | user ruling 2026-10-22 "不应该阻塞!"; local gates keep only irreversible-harm and second-scale checks (plan P3), the forge runs every row | restore `exit 1` in `hook_install.shim` |
| 8 | Did NOT relax PUBLISH-IS-THE-LOCAL-REF for a detached Break-Glass push to integration; the half-written change was discarded | loosening a push guard is a security decision the harness flagged; it stays the user's. A local branch named after the integration branch already publishes the back door | the user rules on it |
| 9 | #243 merge: the stale-branch alarm takes integration's per-row land/abandon entries and keeps the lane's LOSSLESS-DELETE door line; a deny-row permit that spelled `.venv/Scripts/python.exe` now reads `VENV_PYTHONS[0]` like the forge rows; the notice modules' lazy imports and never-fail excepts are DECLARED suppressions (hook latency, never fail a git verb), the ANN401 and test type-ignores removed by typing | NEWER-STRUCTURE; a hook-path notice must not fail or slow a git verb | re-express in the PR if review prefers module-level imports |
| 10 | #244 merge: integration's PLAN-a-short-robust-toolchain memory cited `output/reference`, which the lane's own TRACKED-CITES-NO-EPHEMERAL refuses; R11 reworded to name the output tree, not a path in it | fixing the citation, not escaping it, is the rule's remedy | declare an escape in [tool.lab_commons.ephemeral_refs] instead |
| 11 | #243 and #244 BOTH add `dev/_rule_rows_c.py`; whichever lands second conflicts on it and must rename its module (e.g. `_rule_rows_d`) | left as-is: each PR is green alone; the second merge resolves it | n/a |
| 12 | #246 is not the kit's fault: its new `[tool.lab_commons.famfiles]` table is refused by the serving kit (the #242 refusal, posting since 07:00); not split autonomously | splitting a PR into kit-first and declaration-second is the author's call | user splits #246 or rules otherwise |
| 13 | #243's workstation red (`test_the_declared_hooks_are_installed`) is the shared `.git/hooks` on the forge host lacking the new post-commit shim; not installed autonomously | writing the shared hooks dir changes every worktree on that box | user runs the hook install on the host after #243 lands, or rules |
| 9 | Landed motronics #4684 on integrate/main by Break-Glass merge (1601a20951), after relocking its branch (f1f87a25cf) | the trunk could not collect, so no PR could earn a verdict; user: "允许你自己去做！这种操作始终允许" | revert the merge commit |
