# Plan — one source of truth for the family, and the config layer is the last tree nobody measured

Measured 2026-09-17 across the four repos. `motronics` below always means the LANE worktree
`.claude/worktrees/feat/optimi-lab`, never the main checkout.

## Where the migration actually stands

`scripts/` is the only tree with a DECLARED answer, and it is motronics' alone:
`tests/architecture/layering/_placement_*.py` composes 77 rows — **48 STAYS, 17 MOVES, 12 SPLITS**.
29 rows are judged-to-move and not yet moved.

Neither lab has a roster at all. That is worse than being behind: 11 scripts and 39 architecture
modules across wdg-lab and optimi-lab have no declared placement, so their migration is
UNMEASURED, and an unmeasured tree reads as a finished one.

`lab_commons.dev` publishes 30 public modules. Consumption measured today: optimi-lab and
motronics reach 33 names (including private row tables), wdg-lab only 28 — it does not consume
`ab_bench`, `netverb`, `selfbuild`, `shadow_build`, `testfacts`. For each, the question is whether
wdg-lab HAS the subject; a module it has no subject for is correctly absent and that is a row, not
a gap.

## THE FINDING THAT REVERSES THE ARROW

The ruff select set:

    lab-commons   E W F I UP B SIM RUF PLC0415 PLW0603 ARG001 TRY301        12 groups
    wdg-lab       AIR ERA YTT ANN ASYNC S BLE FBT B A COM C4 ... TRY        ~57 groups
    optimi-lab    the same ~57, diverging only in `ignore`
    motronics     the same ~57, diverging only in `ignore`

**The repo that SHIPS code to the other three is linted least strictly of the four.** This is not
"not yet migrated". It is backwards: a shared kit's standard must be at least its consumers', or
every consumer inherits code its own gate would have refused. Nothing in the family enforces the
direction of that inequality today.

Two more in the same class:

* `lab-commons` has **no `.pre-commit-config.yaml`** while all three consumers do.
* `motronics` carries BOTH `ruff.toml` (123 lines) AND `[tool.ruff]` in `pyproject.toml`. One
  decision, two sources, so one of them is read by nobody — a declaration that lies, and which one
  loses must be MEASURED against ruff's precedence, not assumed.

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

Measured consequence, same day: lab-commons moved dev26 -> dev37 in one session; a consumer's
`agent_guard` import vanished under an agent mid-task; two agents read the same repo and reported
opposite pins, each correctly. **Nothing in any repo determines which lab-commons a fresh checkout
gets**, so an integrator on another box cannot attribute a single red.

## The refactor, first principles

The premise: `lab_commons` is the SINGLE SOURCE OF TRUTH, and no backward compatibility is owed —
no `_legacy` shims, no dual config paths, no deprecation window. A consumer either reads the family
artefact or DECLARES its delta; there is no third state.

The ordering principle: **a declaration before a move.** Every stage below produces a roster that
can red before anything is relocated, because a migration with no roster cannot tell an
intentional local copy from an unmigrated one — which is exactly the state the two labs are in now.

### R0 — make the two unmeasured trees measured (IN FLIGHT)

Placement rosters for wdg-lab's and optimi-lab's `scripts/` and `tests/architecture/`, on
motronics' shape: path key, STAYS/MOVES/SPLITS, and a REASON naming the deciding fact. Completeness
test so a new file cannot be silently unplaced; a floor so an empty scan is not green.
Plus a config-layer census in lab-commons covering the six artefacts above.

DECLARATION ONLY. No file moves in R0.

### R1 — reverse the ruff arrow

`lab_commons` adopts the consumers' ~57-group select as its own floor, and fixes what that reds.
Then the family rule becomes enforceable and is added as a row: **a consumer's select must be a
superset of the kit's.** The test lives in `lab_commons.dev.rules` and each consumer's adoption
arm asserts it, so the inequality cannot silently invert again.

This is R1 and not R3 because every later stage moves code INTO lab-commons, and code arriving in
a tree with a weaker standard is how the standard stays weak.

### R2 — the config seam, one artefact at a time

For each of `.gitignore`, `.pre-commit-config.yaml`, `Makefile`, `[tool.ruff]`:
`lab_commons.dev` owns the BASE as data plus a renderer; each consumer declares only its named
delta; a test re-renders and asserts the file on disk equals base+delta. A hand edit to the
rendered file reds rather than drifting. The eleven stock pre-commit hooks and the fourteen
all-three gitignore lines are the first base; `build-rust*`, `serve`, `purity` are deltas and stay
deltas.

The seam is the same one `dep.py` already uses: the mechanism is the family's, the two or three
answers that are not derivable from there are the repo's, and the repo states them.

### R3 — kill the second ruff source

Measure which of motronics' `ruff.toml` and `[tool.ruff]` ruff actually reads, move anything the
loser uniquely holds into the winner, delete the loser. One decision, one source. Falls out of R2
if R2 chooses `[tool.ruff]` as the family base.

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

### R6 — `docs-src/dev`, 13 / 1 / 1 / 14

The labs have one page each. Either their mechanics genuinely live elsewhere, or `rules/**` is
carrying mechanism that the width cap says belongs in `docs-src/dev/`. MEASURE before deciding;
this is the one stage whose direction is not yet established by evidence.

## THE ONE DECISION THAT IS NOT MINE

`uv.lock` is ignored by family rule. Reversing it is what makes a checkout reproducible on the
integrator's box; keeping it is what keeps a fast-moving kit from costing a bump commit per hop.

R0-R6 are all sound under EITHER choice, so none of them is blocked on it. But R4 and R5 both
re-point consumers at kit versions, and until the lock question is answered **the version a
consumer ends up on is a property of the box, not of the commit** — so the integrator on another
workstation will not be able to attribute any red those stages produce.

State the choice before R4 starts, or R4's evidence is not transferable off this box.

## Floors for whoever picks this up

* `scripts/` roster: 77 rows, 48/17/12. If a later reading shows fewer rows than files, the
  completeness arm has been weakened.
* All-three `.gitignore` intersection: 14 lines. All-three pre-commit ids: 11.
* `lab_commons.dev` public modules: 30.
* wdg-lab consumes 28; optimi-lab and motronics 33.
* ruff select: 12 groups in the kit against ~57 in each consumer. R1 is done when that inequality
  points the other way and a test says so.
