---
name: plan-one-source-of-truth-for-the-family-config-layer
description: A content-level census of the four repos' config layer and the R0-R6 refactor it implies under one premise - lab_commons is the single source of truth and no backward compatibility is owed. The finding that reorders the plan is that the kit selects 12 ruff rule groups against the consumers' identical 58, so every stage that moves code INTO lab-commons would move it into a weaker standard; but the relation is NOT a subset in either direction, because the consumers globally ignore 8 codes the kit enforces.
metadata:
  type: project
created: 2026-09-17
accessed: 2026-09-17
---

# Plan — one source of truth for the family, and the config layer is the last tree nobody measured

Measured 2026-09-17 across the four repos. `motronics` below always means the LANE worktree
`.claude/worktrees/feat/optimi-lab`, never the main checkout.

## Where the migration actually stands

`scripts/` is the only tree with a DECLARED answer, and it is motronics' alone:
`tests/architecture/layering/_placement_*.py` composes 77 rows — **48 STAYS, 17 MOVES, 12 SPLITS**.
29 rows are judged-to-move and not yet moved.

CLOSED 2026-09-17 (R0): both labs now have one too.

    wdg-lab      31 rows — 14 STAYS,  5 MOVES, 12 SPLITS   (8 scripts + 21 modules + its own 2)
    optimi-lab   23 rows —  9 STAYS,  6 MOVES,  8 SPLITS   (3 scripts + 18 modules + its own 2)

Both landed independently on motronics' two bars — binder ceiling 50 own lines, density bar 3.0% —
each BOUNDED in its own tree rather than copied: wdg-lab's ceiling must exceed 49 and fall below
55, optimi-lab's exceed 43 and fall below 67; density above 1.41% / at-or-below 4.79% in wdg-lab,
above 0.65% / at-or-below 3.06% in optimi-lab. The second interval is tight and says so.

A NUMBER IN DISPUTE: the roster agent reported motronics' PLACEMENT as 71 rows (44/13/14). Composed
live from the six partitions in the LANE worktree at HEAD it reads 77 (48 STAYS, 17 MOVES, 12
SPLITS), reproduced twice. The likeliest explanation is the same one that bit the engine comparison
today — reading `D:\MingyangBao\motronics-studio` (the main checkout, `integrate/main`, which has
older placement data) instead of the lane. NOT RESOLVED; whoever picks this up should say which
tree they read before quoting either number.

`lab_commons.dev` publishes 30 public modules. CONSUMPTION, and my first number was wrong: I
grepped for the string `lab_commons.dev.<name>`, which counts prose and docstrings, and got 28
(wdg-lab) / 33 (optimi-lab, motronics). Measured by DIRECT IMPORT across `scripts/`, `tests/` and
`src/`: **wdg-lab 17, optimi-lab 16.** The import reading is the one to trust — a module named in a
comment is not consumed. Neither lab imports `ab_bench netverb selfbuild shadow_build testfacts
content envkey logref verdict reports units quantity_values devdocs`.

The five that were asked about, each ANSWERED rather than counted:

* `netverb` — SUBJECT PRESENT, no mechanism. `scripts/pull_all.py` drives clone/pull with a 120 s
  timeout and ZERO retries; `wdg-lab-update.sh` exits on its first failed fetch. SPLITS.
* `shadow_build` / `selfbuild` — SUBJECT PRESENT, hand-rolled. `scripts/build_rust.py` runs
  `maturin develop --release` into the shared venv, the exact mutation `shadow_build` removes.
* `testfacts` — SUBJECT PRESENT, hand-rolled and WEAKER: `test_skips_are_a_named_set.py` reads a
  test file's declarations with a REGEX where `testfacts` reads the AST.
* `ab_bench` — correctly ABSENT. No file in either tree times, interleaves or reports a median.
  That statement is the row; a module with no subject is not a gap.

## THE FINDING THAT REVERSES THE ARROW

CORRECTED 2026-09-17 by the census in `tests/_config_census_rows.py`. The first reading of this
called the relation a subset. **It is not a subset in either direction**, and that matters to R1.

    lab-commons   E W F I UP B SIM RUF  +  ARG001 PLC0415 PLW0603 TRY301     12 selectors
    wdg-lab / optimi-lab / motronics    BYTE-IDENTICAL, 58 selectors each
                                        (pairwise symmetric difference EMPTY)
                                        ignore lists agree on 62 of 63/62/66

* 8 of the kit's 12 are whole groups the consumers also take.
* The other 4 are single codes inside consumer groups `ARG PLC PLW TRY`, ignored by NO consumer —
  so on those four the consumers are at least as strict.
* **50 selector groups** the consumers lint and the kit does not: `D ANN S PTH PT N TRY PLR` ...
* **Counter-direction, exactly 8 codes**: inside the 8 shared groups every consumer GLOBALLY
  IGNORES `B018 B904 E501 RUF012 RUF043 SIM108 SIM113 UP017`, which lab-commons enforces.

Scalars are identical across the three consumers (`line-length 120`, `py313`, `unsafe-fixes`,
`quote-style single`, `preview false`); lab-commons is `py312` with no ignore list at all.

**The repo that SHIPS code to the other three is blind to 50 groups its consumers lint.** That is
the part that is backwards, and it is why reversing it is R1: every later stage moves code INTO
lab-commons, and code arriving in a tree blind to 50 groups is how the blindness persists. But the
rule cannot be written as "the consumer's select is a superset of the kit's" — that is FALSE today
in the 8-code direction, and a rule that is false on arrival teaches people to weaken it.

Two more in the same class:

* `lab-commons` has **no `.pre-commit-config.yaml`** while all three consumers do. This is the same
  finding one layer out: the repo that ships `dev.hook_install`, `dev.hooks`, `dev.hook_adoption`
  and `dev.githooks` runs NONE of it on itself and has no commit-time enforcement at all.
* `motronics` carries BOTH `ruff.toml` and `[tool.ruff]`. MEASURED via `ruff check --show-settings`:
  `ruff.toml` wins outright, and the loser holds exactly one key, `extend = "ruff.toml"`, naming the
  winner. So it is **DEAD, NOT LYING** — deleting it changes nothing, but leaving it invites the
  next reader to edit the file ruff never reads.

Installed git hooks, measured 2026-09-17 by resolving the hooks dir THROUGH git (a first hand
reading with `ls .git/hooks` from the wrong directory reported zero everywhere and was refused by
the census reader): lab-commons `()`, wdg-lab `(pre-commit, pre-push)`, optimi-lab `(pre-commit,)`,
motronics `(commit-msg, pre-commit, pre-push)`. `dev.hook_install`'s docstring claim of zero
everywhere is now HISTORICAL and needs updating. What is still unwired is a STAGE, not a repo: both
labs declare `commitizen`, whose stage is `commit-msg`, and neither has a `commit-msg` hook — so
the one non-whitelist hook optimi-lab declares is the one part of its config nothing executes.

## What the config layer actually shares, measured by CONTENT

Line counts are not evidence; these are set intersections.

    artefact        lab-commons  wdg-lab  optimi-lab  motronics
    pyproject.toml      69         344       225        299
    .gitignore          10         103        73        150
    ruff.toml          absent     absent    absent      123
    Makefile            30         130       113         81
    .pre-commit        absent       98        72        128
    docs-src/dev        13           1         1         14

`.gitignore`, pairwise overlap among the three consumers: wdg/opt 27, wdg/motr 33, opt/motr 16.
Present in ALL THREE:

    **/.env  **/__pycache__  **/log/*.log  **/log/*.log.error  **/temp/**  *.c
    *.egg-info  *.spec  .coverage*  .mypy_cache  .pytest_cache  .ruff_cache  .venv*  uv.lock

`.pre-commit-config.yaml` hook ids in ALL THREE: `check-added-large-files check-ast
check-case-conflict check-json check-merge-conflict check-toml commitizen debug-statements
end-of-file-fixer mixed-line-ending trailing-whitespace` — eleven stock hooks, hand-maintained
three times.

`Makefile` targets: `lint`, `test`, `fmt` in all four; `clean install install-dev test-parallel
verify` in three. The repo-shaped remainder is small and NAMED: `build-rust* test-femm typecheck`
(motronics), `serve schema install-web pull docs` (wdg-lab), `purity adoption` (optimi-lab).

**Every one of these is a shared base plus a named delta. None is a coin-flip.**

## `uv.lock` IS IGNORED IN ALL THREE CONSUMERS, AND THAT IS THE ROOT

It appears in the all-three intersection above. So the fact that one declaration —
`lab-commons @ git+https://github.com/DawnEver/lab-commons.git`, no ref, in all three — resolved to
dev26 / dev34 / dev34 on one box today is not an oversight anyone forgot. It is the direct
consequence of a rule the family wrote down: never commit the lockfile.

Measured consequence, same day: lab-commons moved dev26 -> dev40 in one session; a consumer's
`agent_guard` import vanished under an agent mid-task; two agents read the same repo and reported
opposite pins, each correctly. **Nothing in any repo determines which lab-commons a fresh checkout
gets**, so an integrator on another box cannot attribute a single red.

### THE MECHANISM — and the first diagnosis in this file was WRONG

wdg-lab reverted to dev26 THREE times on 2026-09-17, twice after being explicitly upgraded. It was
read as contention between agents twice, and then written up here as uv re-resolving `make
install-dev` from its cache. **Both readings are wrong.** Measured:

    wdg-lab/uv.lock:  name = "lab-commons"
                      version = "0.2.2.dev26+gba3bf6dee"

**There IS a lockfile. It pins dev26 — the exact version the repo kept returning to — and it is
UNTRACKED, so nothing in git shows it and no review ever saw it.** `uv run` performs an implicit
sync against it before running anything, and the pre-commit `bump-version` hook and the
`generate-changelog` hook both go through `uv run`. So every commit and every push reinstalled the
kit at the lock's version. That is why the reverts clustered around commits rather than around
anyone running `make install-dev`, which nobody did.

THE SENTENCE WORTH KEEPING: **"not in git" is not "not there."** `.gitignore` made the lockfile
invisible, not absent. What the family actually has today is a pin that cannot be seen, cannot be
reviewed, and does not move when a commit moves — which is strictly worse than either a committed
lockfile or no lockfile at all, and it is the state that produced every symptom in this section.

The fix is `uv run --no-sync` in both hooks, so a hook runs the environment it was given instead of
silently rebuilding one. `--refresh-package`, proposed here earlier, was aimed at a mechanism that
was not the cause; it is not wrong, but it is not this.

## The refactor, first principles

The premise: `lab_commons` is the SINGLE SOURCE OF TRUTH, and no backward compatibility is owed —
no `_legacy` shims, no dual config paths, no deprecation window. A consumer either reads the family
artefact or DECLARES its delta; there is no third state.

The ordering principle: **a declaration before a move.** Every stage below produces a roster that
can red before anything is relocated, because a migration with no roster cannot tell an
intentional local copy from an unmigrated one — which is exactly the state the two labs are in now.

### R0 — make the two unmeasured trees measured  (DONE 2026-09-17)

Landed: wdg-lab `6d7a6c8b`, optimi-lab `f69f22e`, lab-commons config census `2048b37`.
Declaration only; no file moved.

What the rosters proved beyond their own rows — similarity is EVIDENCE, not a verdict:

    test_no_allow_entry_names_a_denied_shape.py   88.9% identical, ZERO repo nouns   -> clean MOVES
    test_the_dependency_door_is_wired.py          91.5% identical, 6 lines name the
                                                  repo's own port                    -> SPLITS
    test_the_public_surface_is_declared.py        89% DIFFERENT                       -> STAYS both

The last row is the counter-evidence that makes the other two mean something: a shared FILENAME is
not shared code, and a census that only ever finds MOVES is measuring its own expectation.

The guard corrected its author on first run, which is the part worth keeping: wdg-lab's
repo-noun property refused three MOVES rows over the English word "slot" and over prose naming the
repo. Property 3 now reads CODE with docstrings and comments blanked while property 2 keeps reading
prose, and the asymmetry is pinned by its own test on live rows. One row survived the refusal
correctly — `test_memory_lives_under_a_date.py` really does hold `src/wdg_lab/...` paths as data —
and moved to SPLITS.

Debt carried honestly: 5 `BELOW_THE_BAR` rows in wdg-lab, 4 in optimi-lab, each strict-xfailed with
its measurement, date and the seam it owes. SPLITS answers the SAME bar as STAYS, with a planted
control proving the SPLITS arm cannot be deleted. One self-row in optimi-lab predicted 0.00% and
XPASSED at 3.90% — recorded WITH the caveat that all six hits are planted-control fixtures rather
than real assertions about the repo.

### R1 — reverse the ruff arrow, and state the rule the measurement actually supports

`lab_commons` adopts the consumers' 58-selector set as its own floor and fixes what that reds.
That set is byte-identical in all three consumers, so it is not a negotiation — it is already the
family's answer, held three times.

The rule that follows is NOT "the consumer's select is a superset of the kit's": the 8-code
counter-direction makes that false on arrival. The measured relation is two separate facts, and
each gets its own arm:

* **the kit's select covers every group any consumer selects** — the blindness, closed by adoption;
* **a code the kit enforces may not be globally ignored by a consumer** — today `B018 B904 E501
  RUF012 RUF043 SIM108 SIM113 UP017` violate this, so the arm ships with those eight as a NAMED
  waiver set with a ceiling, not as a silent exception. A ratchet has two sides: the waiver set may
  only shrink, and it reds if it grows.

Eight rows, each with a reason, is the deliverable — deciding per code whether the kit should stop
enforcing it or the consumers should stop ignoring it. Both answers are legitimate; neither is
"lower the count".

This is R1 and not a tidy-up at the end because every later stage moves code INTO lab-commons.

### R2 — the config seam, one artefact at a time

For each of `.gitignore`, `.pre-commit-config.yaml`, `Makefile`, `[tool.ruff]`:
`lab_commons.dev` owns the BASE as data plus a renderer; each consumer declares only its named
delta; a test re-renders and asserts the file on disk equals base+delta. A hand edit to the
rendered file reds rather than drifting. The eleven stock pre-commit hooks and the fourteen
all-three gitignore lines are the first base; `build-rust*`, `serve`, `purity` are deltas and stay
deltas.

The seam is the same one `dep.py` already uses: the mechanism is the family's, the two or three
answers that are not derivable from there are the repo's, and the repo states them.

### R3 — delete motronics' dead `[tool.ruff]` block  (MEASURED, one line)

`ruff check --show-settings` names `ruff.toml` as the settings path; the `pyproject.toml` block
holds only `extend = "ruff.toml"`. It is dead rather than lying, so this is a deletion with no
migration behind it — but it must happen before R2 rewrites either file, or R2's renderer has two
places to write and one of them is a trap.

### R4 — the 29 declared-but-unmoved motronics rows

17 MOVES and 12 SPLITS, executed against the two-phase split rule: a SPLIT whose family half is NEW
cannot land in one lane — write in lab-commons, push, reinstall through the dependency door,
re-point. Take `scripts/hooks/*.sh` first: four MOVES in one mechanism, and `with-retry.sh` is
already being borrowed cross-repo today (wdg-lab has no copy and reaches into motronics' tree for
it), which is the seam arguing for itself.

### R5 — wdg-lab's five unconsumed modules

`ab_bench netverb selfbuild shadow_build testfacts`. For each: does wdg-lab have the SUBJECT? Where
it does, adopt and delete the local equivalent. Where it does not, record `declared_absent` with
the reason — the shape `agent_guard` already uses for GIT-NETWORK-VERB and RAW-PROCESS-KILL.
`netverb` is the known live one: `pull_all.py` calls git directly and `wdg-lab-update.sh` exits on
the first failed fetch.

### R6 — DISSOLVED: `docs-src/dev` 13/1/1/14 is not a gap

Measured, and it refutes the line-count reading that produced this stage. Both labs' single page is
a 30-line POINTER TABLE into `lab-commons/docs-src/dev/`, generated by
`lab_commons.dev.devdocs.pointer_table` and listing 12 family pages — the MOVES already executed
2026-09-16. motronics' 14 shares nine filenames with the kit's 13, every one already a pointer plus
a local delta (`the-three-participants.md` is 6 lines against 38 upstream); the five with no
upstream twin (`gate.md testing.md integration.md user-flow.md compute-resources.md`) are the gate
runner, the case library and the vendor engines, which are motronics facts.

Labs = MOVES, motronics = SPLITS, **both already executed**. Nothing to do. Kept as a numbered
stage so the 13/1/1 asymmetry is not re-opened by the next reader who sees only the line counts.

## THE DECISION, ANSWERED — and it moves the fix rather than removing it

**USER RULING 2026-09-17: `uv.lock` stays OUT of git.** Not a lockfile, and not a `rev=`/`tag=` pin
on the requirement either. "The latest from that URL" is the family's deliberate declaration.

CORRECTED after the ruling: the ruling is about what GIT holds, and the defect was never about
that. An untracked `uv.lock` pinning dev26 exists on disk in wdg-lab and `uv run` syncs against it
(see the mechanism section above). So "no lockfile in git" was being read as "no lockfile", and the
repo has been running against an invisible pin all along.

The repair therefore has two halves, and only the first is about the ruling:

* **Keep the lockfile out of git — and stop letting an invisible one decide.** `uv run --no-sync`
  wherever a hook or script runs the project, so a hook uses the environment it was handed instead
  of silently rebuilding one from a file nobody reviewed.
* **Make the install doors deliver what the declaration says.** `--refresh-package lab-commons`
  (or `-P`, which implies it). This was proposed as THE fix earlier in this file and it is not —
  it addresses a real second-order gap, not the cause. NOT a global `--refresh`: a fix wider than
  its cause is how the next reader loses the reason.

The asymmetry this also explains: motronics never reverted because its verdict path does not run
through `uv run` against a stale lock the way wdg-lab's hooks do, and because `dep_sync.py` already
passes `--upgrade-package`. wdg-lab's `scripts/dep.py` escapes for a THIRD reason — it shells to
`pip`, which re-clones a direct-URL requirement rather than treating it as satisfied. Three doors,
three different behaviours on the identical requirement string, **and the reverting one is the one
that runs automatically on every commit.** That is why "read the command text" was not a
measurement here, and why this file recorded the wrong cause twice before measuring the lock.

The section below is kept as the record of the question and of what it cost to answer it.

## THE QUESTION AS IT STOOD BEFORE THE RULING

`uv.lock` is ignored by family rule. Reversing it is what makes a checkout reproducible on the
integrator's box; keeping it is what keeps a fast-moving kit from costing a bump commit per hop.

R0-R6 are all sound under EITHER choice, so none of them is blocked on it. But R4 and R5 both
re-point consumers at kit versions, and until the lock question is answered **the version a
consumer ends up on is a property of the box, not of the commit** — so the integrator on another
workstation will not be able to attribute any red those stages produce.

The `make install-dev` mechanism above raises the cost of "keep it unpinned" past a preference: it
is not that a checkout MIGHT drift, it is that the repo's own install target reverts the kit
deterministically, three times measured in one day. Any fix short of pinning has to explain why
that command should keep resolving from cache.

ANSWERED. R4 is unblocked: once every install door refreshes the kit, the version a consumer runs
is determined by the declaration plus the clock rather than by the box's cache, which is what R4's
evidence needs in order to travel. It is a weaker guarantee than a lockfile — two boxes installing
at different times still differ — so R4's reports must quote the kit version they measured against,
and a red that cannot be reproduced upstream is to be re-measured at a stated version rather than
attributed.

## Floors for whoever picks this up

* motronics `scripts/` roster: 77 rows, 48/17/12, read from the LANE at HEAD — say which tree you
  read. wdg-lab 31 rows (14/5/12), optimi-lab 23 rows (9/6/8). If a later reading shows fewer rows
  than files, the completeness arm has been weakened.
* Consumption by IMPORT, not by grep: wdg-lab 17, optimi-lab 16, of 30 published modules.
* All-three `.gitignore` intersection: 14 lines. All-three pre-commit ids: 11.
* `lab_commons.dev` public modules: 30.

* ruff select: 12 selectors in the kit against 58 in each consumer, the consumers' sets
  BYTE-IDENTICAL (pairwise symmetric difference empty). 50 groups the kit is blind to; 8 codes the
  consumers globally ignore and the kit enforces. R1 is done when the first number is 0 and the
  second is a named, shrinking waiver set.
* Config census: 24 rows (4 repos x 6 artefacts) = 4 STAYS, 2 MOVES, 18 SPLITS.
* Installed git hooks: lab-commons 0, wdg-lab 2, optimi-lab 1, motronics 3. A later reading of zero
  everywhere means the hooks dir was resolved by path rather than through git.
