---
name: HANDOFF-merge-audit-built-not-published-and-the-fcc-jmag-test-plan
description: MERGE-DEVIATIONS-NAMED is built and committed on lab-commons lane/merge-audit (not pushed, not consumed). What it does, the two user rulings it encodes, the publish order, the motronics wiring still owed, and the acceptance test on feat/field-circuit-coupling x feat/jmag-integration, with a measured baseline.
created: 2026-10-07
---

# HANDOFF: the merge audit is built, not published

## What the user asked for (2026-10-07)

Agents iterate fast and merges silently drop updates. Every merge must be checked ITEM BY ITEM for
feature regression, as part of the lab-commons dev workflow. First principles, single source of
truth, no backward compatibility.

## Design (decided)

- The tests ARE the feature inventory; no second list. The one regression a gate cannot see is a
  resolution that deletes or rewrites the test that would catch it.
- `lab_commons.dev.mergeaudit`: for merge M of O and T over base B, each test's expected body is
  git's three-way rule (O==B takes T, T==B takes O, equal changes take it, else none). M differing
  is a deviation: `LOST`, `ALTERED`, `CONFLICTED`. Identity is the test's NAME (survives a file
  split); a name defined twice anywhere is keyed `path::name`. Docstrings and comments are not
  fingerprinted. Reads git objects only -- no checkout, no execution.
- Each deviation is named in the merge commit: `Merge-Audit: <KIND> <test> -- <reason>`. Unnamed
  or over-named lines refuse. Octopus and criss-cross merges refuse (one lane at a time).
- User rulings 2026-10-07:
  - a LANE admits PASS/FAIL/INCONCLUSIVE (slow boxes cannot finish); the INTEGRATION branch admits
    PASS/FAIL only; the trunk a PASS;
  - `ALTERED` passes on the merging agent's one-line reason, audited afterwards.
- `lab_commons.dev.admission`: three destinations (`RESULTS` table); every push audits merges
  reachable from HEAD and from no remote. Integration branch and `test_roots` come from
  `[tool.lab_commons.integrator]` (single source; default `tests`).
- BREAKING: `admit`/`decide_fresh(destination=...)` replace `trunk=`; `LANE_RESULTS`/`TRUNK_RESULTS`
  are gone. Rule row `MERGE-DEVIATIONS-NAMED` added and adopted here.

## State

- lab-commons `lane/merge-audit` (worktree `.claude/worktrees/merge-audit`, own venv):
  `8572185` feat, `3ecc8c9` noqa -> named constant, plus this handoff. NOT PUSHED.
- Verify on `8572185`: 3085 passed, 3 failed. Two are NOT this increment and pre-date it:
  - `test_arch_text_subprocess_declares_encoding` names `tests/test_dev_branchset_push.py:216,231`;
  - `test_no_tracked_file_carries_private_markers` names
    `.claude/memory/2026/10/07/the-population-is-gits-and-the-key-is-a-node-id.md:27-29`.
  The third (an undeclared `noqa`) is fixed in `3ecc8c9`, its file re-measured PASS.
- motronics: NOTHING changed. `scripts/gate/prepush_gate.py` still calls `trunk=`, so it BREAKS the
  moment its venv syncs the new lab-commons. Publish and consume in the same sitting.

## Next, in order (awaiting the user's go on step 1-2)

1. Fix the two pre-existing reds (add `encoding=` at the two calls; genericise the home paths in
   that memory file), so lab-commons trunk can cite a PASS.
2. Merge `lane/merge-audit` into lab-commons `main`, push through the netverb door.
3. motronics, in a LANE worktree (main checkout has another editor):
   - `prepush_gate.py`: `destination=` from `PRE_COMMIT_REMOTE_BRANCH` via
     `admission.destination_of(remote_ref, load_policy(root))`; call `admission.merge_refusals(root,
     admission.unpublished_merges(root), policy.test_roots)` before citing a verdict;
   - `pyproject.toml`: `[tool.lab_commons.integrator]` with `integration = "integrate/main"` and
     `test_roots = ["tests"]`;
   - adopt `MERGE-DEVIATIONS-NAMED` in the adoption test;
   - `.claude/rules/workflow.md`: the "integrate/main INCLUDED ... INCONCLUSIVE" line is now false;
     `rem/integration.md`: NEWER-STRUCTURE's loss half is now enforced -- point at the rule ID.
4. Other consumers (optimi-lab, ...): adopt the rule, follow the API break.

## Acceptance test: feat/field-circuit-coupling x feat/jmag-integration

MEASURED 2026-10-07 with the lane's `mergeaudit.audit(root, sha, roots=('tests',))`:

| merge | what it is | deviations |
|---|---|---|
| `15f0f1e4c9` | fcc INTO jmag, "upstream's structure, our content re-expressed" | 127: 21 LOST, 18 ALTERED, 88 CONFLICTED |
| `8721a94eeb` | jmag tip INTO fcc | 1 CONFLICTED (`TestTheRefusals::test_a_drive_field_the_deck_cannot_carry_raises`) |

Test plan:
1. Triage `15f0f1e4c9`'s 21 LOST by hand: each is a moved-and-renamed test (fine, name it), a
   deliberate retirement (fine, name it), or a REAL REGRESSION -- the thing this exists to catch.
   Record the split; it is the first evidence of whether past merges lost features.
2. Read 10 of the 88 CONFLICTED: if most are both-sides-reformatted noise, consider a narrower
   fingerprint (e.g. normalising string literals is NOT acceptable -- they are assertions); if most
   are real choices, the count is the honest cost of that merge.
3. Live round trip on the current tips (fcc `868c18eb5e`, jmag `8721a94eeb`): in a scratch worktree
   merge one into the other, push to a throwaway branch NAME the branchset allows (or run
   `python -m lab_commons.dev.admission` with `--remote-ref` directly, which pushes nothing), and
   confirm: unnamed deviation -> refused naming each; trailers added -> admitted; a bogus trailer ->
   refused; pushing to `integrate/main` with an INCONCLUSIVE verdict -> refused.

## Known blind spots (not bugs; decide later)

- A fixture/helper change under an unchanged test body (the gate still runs it).
- Module-level pin DATA (`_*_pins.py`, parametrize lists defined outside the function). The most
  practical gap in motronics; extend the fingerprint to module-level assignments under `test_roots`.
- A rebase resolves conflicts with no merge commit; force-push is hook-denied, merge-only is prose.
- The delta tests of both sides are not forced into the integration verdict's selection.
