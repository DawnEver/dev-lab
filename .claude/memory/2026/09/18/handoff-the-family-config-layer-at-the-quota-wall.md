---
created: 2026-09-18
accessed: 2026-09-18
---

# Handoff — the family config layer at the quota wall

Written 2026-09-18 01:10 local, weekly quota nearly spent. A 4h one-shot reminder is scheduled
(session-only; it dies with the session, so this file is the durable half).

Plan: `.claude/memory/2026/09/17/plan-one-source-of-truth-for-the-family-config-layer.md`, stage R4.

## State of the four repos

| repo | HEAD | pushed |
|---|---|---|
| lab-commons | `a177ba6` + one live agent | yes |
| wdg-lab | `7329b1c1`, then `cc8d8c11` | `7329b1c1` pushed; `cc8d8c11` NOT |
| optimi-lab | `aab4074` pushed, then `4c5b1cd` | `4c5b1cd` NOT |
| motronics lane `feat/optimi-lab` | `cb810816e` + live agent | push in flight at write time |

NEVER `D:\MingyangBao\motronics-studio` itself.

## THE FINDING THAT CHANGES THE PRIOR

The standing prior — the roster OVER-reports, three tranches declared 17 MOVES and measured 7 — did
NOT reproduce in the labs. Neither lab holds a stale MOVES row; optimi-lab has ZERO. The error is
the opposite one and it is in the INSTRUMENT:

**`supersede.imported_kit_modules(package='lab_commons.dev')` resolves
`from lab_commons.dev.famtests import allowguard` to the segment at depth 2 — `'famtests'` — while
`supersede.kit_modules` publishes the same module under the bare stem `'allowguard'`. The two
halves spell one module two ways, so the IMPORT detector cannot corroborate ANY sub-package
adoption.** Twelve rows across both labs grade `NAMED_ONLY` and every one is fully adopted:
`allowguard agentguard hookinstall configrender rulespages visibility`, six modules, two labs.

**FIXED UPSTREAM, lab-commons `1aa2738` on `main`, NOT PUSHED.** Two lanes reached this
independently -- one measured it from the labs' rosters, one from the kit -- and converged on the
same six modules. The kit lane took it: `imported_kit_modules` now reaches TWO segments below the
package.

**The bound is the interesting part and must not be widened.** Reading EVERY segment would let a
one-level-short `lab_commons` resolve `bounded` inside `lab_commons.dev.bounded` and silently
retire `_refuse_mismatch` -- a repair that switches off the guard it repairs. That plant passes
unchanged; keep it.

The re-measured row is `PARTIAL`, not `SUPERSEDED`, and for the opposite reason to before: it was
PARTIAL because a local mechanism had not left, it is PARTIAL now because what remains is optimi's
own half of a FINISHED split. `covered` is EMPTY -- after the move the file shares zero names with
its superseder, which is a sharper restatement of why surface overlap is a RULER and never a
detector. New round-trip arm: what `kit_modules` PUBLISHES, `imported_kit_modules` must NAME, with
a `NESTED_FLOOR = 3` because the defect is reachable only through a sub-package.

CONSEQUENCE FOR THE NEXT WINDOW: the labs pinned those 12 rows as a NAMED SET so they RED when the
kit is fixed. The kit is fixed. **Push `1aa2738`, reinstall in both labs, and expect that set to
red -- that is the ratchet working, not a regression.** Re-take the set to empty in the same change.

This is the second measured `NAMED_ONLY` false positive (the first was `scripts/gate/runner.py`)
and the first STRUCTURAL one. Fix is one line in `imported_kit_modules` — emit the full sub-path,
or both tokens. It is pinned as a NAMED SET in both labs' new
`test_the_roster_is_re_read_against_the_kit.py`, so it reds when the kit is fixed.

## THE NEXT TRANCHE IS UPSTREAM, NOT IN THE LABS

Every remaining SPLITS row in both labs is blocked on lab-commons. Four family halves, each with
two consumers already waiting:

1. `famtests.rostercensus` — the roster-vs-kit assertion body, written twice by hand already
2. dated-memory READERS beside `datedlog` — `datedlog` publishes `date_parts`/`dated_log`, which
   CONSTRUCT a dated path; the rows need `entries` / `undated` / `date_disagreements` / `silent`,
   which nobody publishes. Adjacent subject, not the same one.
3. a floor helper for `bind_floor` / `assert_floor`
4. a `placement` module — no kit module owns placement at all

## INVENTORY, caused by the `rulespages` adoption, one red per lab

Both in `test_the_rules_pages_are_a_ratchet.py`, both refused by each repo's OWN guards:
- wdg-lab: the suppression scanner reads a PROSE LINE ABOUT `noqa` as a `noqa`.
- optimi-lab: a count pin named `CEILING` without the `_CEILING` suffix its ratchet requires.

## optimi-lab `.claude/settings.json` — RESOLVED, and how it nearly unresolved itself

The user ruled 2026-09-18: add the block. Added, one row —
`Bash(./.venv/Scripts/python.exe -m lab_commons.dev.verify *)` — and the `strict=True` xfail on
`test_no_allow_entry_names_a_command_the_engine_refuses` removed in the same change, which is what
the mark's own reason instructed.

**A concurrent agent then `git restore`d the settings half**, believing the permission machinery had
written it, and correctly declined to touch the test half because it could not attribute it. That
left the two halves inconsistent — xfail gone, row absent, `VacuousAllowScan` red. Re-applied.

The shape worth keeping: **a two-file change made by two parties is a torn write, and the party who
can only see one half will revert the half it can see.** The agent's restraint on the half it could
not attribute is what kept this cheap.

**UNCOMMITTED AND UNVERIFIED at hand-off.** Both halves sit in optimi-lab's working tree; the
verify run was queued behind the box CPU lock (the lane's push was holding it) and never
returned, so nothing was committed on an unread verdict. FIRST ACTION NEXT WINDOW: re-run
`./.venv/Scripts/python.exe -m lab_commons.dev.verify tests/architecture/test_no_allow_entry_names_a_denied_shape.py`
in optimi-lab, and commit the two files together or not at all -- the torn write above is
exactly what splitting them produces.

## RETRACTED: `verify` DOES refuse a held box. The defect was in my instrument.

This file previously carried a finding -- committed in `27ab0a1` and again in `9a9e422` -- that a
`verify` run which times out waiting for the box lock exits 0 with zero tests and no VERDICT line,
"measured twice at 361s and 843s". **It is false and is retracted here rather than quietly edited.**

Measured directly, with the box genuinely held by a live `gate/runner.py`:

    $ python -m lab_commons.dev.verify --lock-wait-s 0 <a test file>
    EXIT=2
    stderr: verify: inconclusive -- this box is held and nothing was measured.
            Held by: gate/runner.py gate push=320190 [client:40936] since 2026-09-18T01:58:45.
            Wait for it, or stop that holder, then re-run; --lock-wait-s raises or drops
            the 0s ceiling on the wait.

`verify.py` catches `Exhausted`, prints the holder and the remedy, and returns
`EXIT_CODES[Outcome.INCONCLUSIVE]` = 2. Its own `--help` epilog documents the code. `gate` and
`verify` AGREE; there was never a disagreement between two entry points.

### What actually produced the false reading, because that is the reusable part

Both "measurements" were commands the harness moved to the background at its own 120s limit. I then
read two things that were not what I took them for:

1. **The exit code was the BACKGROUNDED WRAPPER's, not the runner's.** The line `[exited with code
   0]` in the task output belongs to the harness.
2. **The capture held stdout only.** The `waiting Ns for the box` progress lines go to stdout; the
   refusal goes to **stderr**. So the one line that would have refuted me was the one line not in
   the file I was reading.

Two reads, same instrument, same blind spot -- which is why repeating it produced agreement rather
than a correction. **A measurement repeated through the same instrument is one measurement.** The
disproof cost one command, took eleven seconds, and separated the two streams and the two exit
codes; I should have run it before writing the finding down, let alone before pushing it twice.

The irony is on the record deliberately: the claim was that a failure had presented as a benign
state, and it was produced by exactly that -- a harness's success code presenting as the runner's.

### What survives

The family of three is now a family of two, and both are still real and still measured:
a stray newline that turned a resolved push base into a silent fall-through to the trunk, and a
failed pre-commit hook that destroyed staged work and left `git status` clean. Both were found by
driving the thing rather than reading it, which is the same method that just refuted the third.

## THE MOTRONICS LANE, and two findings of the same family as the one above

Lane `feat/optimi-lab`, four commits, **NOT pushed and correctly so** -- its pre-push gate could not
acquire the box and answered INCONCLUSIVE. `a5c9d3c31` (the shared-venv guard test), `0c5eb3110`
(`_dated.py` -> `dev.datedlog`), `68f161358` (a 4th call site), `a4de78caa` (`base.py` ->
`dev.gatebase`). `tree_state.py` -> `dev.treedirt` is designed and deliberately NOT started:
`runner.py` is size-ratcheted and the `tests/architecture/gate` tier is over the 300s wall as one
selection, so it needs many sub-selections and the box was never free.

### A PORT SILENTLY WIDENED A BASE, and only running the contract found it

`lab_commons.dev.checkout.git_out` returns `stdout` VERBATIM where the local `_git_out` returned
`stdout.strip()`. The resolved `@{push}` carried a trailing newline, was therefore not a ref git
would admit, silently stopped being a candidate, and every hand-run gate FELL THROUGH TO THE TRUNK
-- **the widest possible base wearing the shape of a working resolution.** Nothing red. Caught by
`test_the_push_target_is_the_base_between_hook_runs`, which drives the contract rather than reading
it.

This is the `LAB_CZ_BASE_REF` lesson arriving through a different door: last time a guessed default
resolved to nothing and reported the lane clean; this time a stray newline did. **The failure mode
of a base is not an error, it is a wider base.**

### A FAILED PRE-COMMIT RUN DESTROYS STAGED WORK, and the tree looks clean afterwards

The ruff hook failed; pre-commit's stash/restore left the working tree **clean at HEAD** with three
files of finished work gone and `git status` showing nothing. Recovered from
`C:\Users\ezxmb14\.cache\pre-commit\patch1789689677-17872`.

**It also produced a false MEASUREMENT**: density was re-read on the silently-reverted file and
returned `own=20`, which is the ORIGINAL file's number. A measurement taken after a silent revert
measures the thing you were replacing.

RULE: **run `ruff check` and `ruff format` BEFORE `git commit` here.** A hook failure in this
configuration is destructive, not merely a refusal. And if a tree is unexpectedly clean, look in
the pre-commit patch cache before concluding anything.

Worth naming once: **twice this window a failure presented as a benign state** -- a stray newline as
a resolved base, a destroyed stash as a clean tree. In each case the reader's normal instrument said
nothing was wrong. A third candidate was claimed and RETRACTED above; it turned out to be this same
shape in the instrument I was measuring WITH, which is the more useful version of the lesson.

### Also confirmed
`scripts/gate/envkey.py` does not exist. The docs-registry row
`agent_swarm.environment -> scripts/gate/envkey.py` names a path with no file, which is why
`test_no_prose_names_a_retired_package` fires on it. Real, small, unassigned.
