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
