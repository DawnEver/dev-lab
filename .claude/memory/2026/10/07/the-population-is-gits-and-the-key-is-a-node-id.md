---
name: the-population-is-gits-and-the-key-is-a-node-id
description: Two defects that made a verdict unreproducible from its own tree hash — `collectscope.local_modules` derived the local import names from a filesystem walk, so gitignored debris masked a missing distribution (consumer-b's recorded `bokeh` residue silently vanished on a box where a retired module had left a `__pycache__` behind), and `allowed_skips` keyed on `path:line`, so an inserted comment invalidated a pin. The population is now `git ls-files -co --exclude-standard` and the key is a pytest node ID, read through `--no-fold-skipped` because `-rs` folds the skip summary into a line that carries a LINE NUMBER and no node id. A third arm was written for `allowed_skips` at the same time: a declaration whose subject left the tree is refused with no run at all.
metadata:
  type: project
created: 2026-10-07
accessed: 2026-10-07
---

# The population is git's and the key is a node id

Two mechanisms in `lab_commons.dev`, both measured, both reachable from four repos, and both with
the same failure: **a verdict that cannot be reproduced from its own `tree=` hash.**

## D1 — `local_modules` walked the filesystem, so the box answered for the checkout

`collectscope.local_modules` collected every directory name and `.py` stem under the root, skipping a
hand-maintained `SKIP_DIRS = {'.claude', '.git', '.venv', '__pycache__', 'attic', 'node_modules',
'target'}`. That set cannot predict every ignored directory a box leaves lying around: `htmlcov/`,
`output/`, `.verify/`, `.pytest_cache/`, `.ruff_cache/`, `lib/`, `docs/` are all absent from it.

MEASURED 2026-10-07, `git ls-files -co --exclude-standard` against the walk, per repo:

| repo | walk | git | walk-only IDENTIFIERS |
|---|---|---|---|
| lab-commons | 386 | 382 | 6 |
| consumer-c | 107 | 93 | 12 |
| consumer-b | 493 | 360 | 45 |
| consumer-a | 8679 | 7128 | 240 |

The walk-only names are ordinary import names — `bokeh`, `lib`, `wdg`, `cache`, `design`, `verify`,
`output`, `dist`, `local`, `reports`, `stationary`, `magnet`.

**THE HARM IS A FALSE NEGATIVE, NOT A WIDER SET.** `resolve` reads a local name as SUPPLIED, so a
name that exists only as debris MASKS a distribution the selection really does strand. The module's
own docstring argued the derivation erred "in the safe direction"; that argument is true of the REACH
answer and false of the census one.

The reproduction is exact and it is not a hypothetical: `consumer-b` records
`unresolved={'annotated_types', 'bokeh', 'pydantic_core'}`, and on this box the live census answered
`{'annotated_types', 'pydantic_core'}` — because `src/<pkg>/viz/backend/bokeh/` survived its own
retirement commit holding nothing but a `__pycache__/`. A directory git knows nothing about, on a
box that had run things, and the row could not be reproduced.

**AND THE WALK IS NOT THE ONLY ONE THAT WOULD HAVE BEEN WRONG, WHICH IS WHY THE FIX IS A SOURCE AND
NOT A LONGER LIST.** `.pytest_cache/v/cache/`, `lib/` (a gitignored sibling clone) and
`output/logs/26/09/14/design/3Ph-48/wdg/` each supplied `cache`, `lib`, `design` and `wdg` the same
way. Adding those seven names to `SKIP_DIRS` fixes today and predicts nothing about tomorrow.

`SKIP_DIRS` is DELETED rather than kept as a filter over git's listing. `-c` plus `-o` minus the
ignore rules already IS "the files this checkout holds", and an extra hand-maintained set on top of
it would be a second source of truth for the same question. A root that is not in a git work tree
now raises `NotACheckout` instead of returning the empty set: empty is not a smaller answer, it is
the OPPOSITE one — every local name falls through to `UNRESOLVED`.

## D2 — `allowed_skips` keyed on a line number and the lines move

`reports._skip_shortfall` matched `path:line` prefixes against what `-rs` printed. MEASURED in
consumer-b: a five-line comment inserted into a test file moved a skip from `:101` to `:106` and
silently invalidated a pin that had just been re-measured by hand; the repo's own list read **18 rows
in one checkout, 20 in a second and 21 in a third**, and the main checkout carried measurably stale
pins, so every verify there read INCONCLUSIVE.

**THE BRIEF OFFERED A NODE ID OR A "CAUSE", AND THE CAUSE IS NOT AVAILABLE IN A STABLE FORM.**
Read out of the installed pytest, `show_skipped_folded` and `show_skipped_unfolded` are the only two
skip summaries there are, and neither prints a MARKER NAME — the only cause-carrying text is the
REASON, which is free prose. Measured in consumer-b's own skip helper, the reason is
`f'lib/ (<the sibling library>) is not checked out: {folder}'` — a BOX-DEPENDENT path inside the key, which is
the defect being fixed arriving by a new road. `pytest.importorskip` synthesises its reason from the
ImportError text, which varies the same way.

**THE NODE ID IS REACHABLE, AND THE KIT'S OWN DOCSTRING SAID IT WAS NOT.** The docstring asserted
"there is no node id in it to match, because several parametrisations of one test share a line". That
is true of the FOLDED form. `_pytest.terminal.pytest_addoption` declares `--no-fold-skipped`,
`dest='fold_skipped'`, **`default=True`**; setting it False selects `show_skipped_unfolded`, whose
line is `SKIPPED <node id> - <reason>` — one line per skip, node id first. `PYTEST_ARGS` now carries
it, and `tests/test_dev_logdistil.py` pins the line a LIVE pytest prints rather than a hand-written
one, so a future pytest that folds again reds instead of silently re-keying every consumer's
allowance to a line number.

The key is still a PREFIX, so a declaration chooses its precision: a module path covers every test in
it and a full node id pins one.

## The arm that was missing, and it is the reason the key change is worth more than it looks

`_skip_shortfall`'s stale side needs a COMPLETE suite census — a selected invocation never checks it
— so between runs nothing refused an entry whose subject had left. The sibling is consumer-b's own
`test_every_conditional_cost_declaration_names_a_module_that_is_marked`, whose docstring names
`allowed_skips` beside `COST_IS_CONDITIONAL` and says a declaration whose subject left must leave
with it. A LOCATION can never be checked without a run; a NODE ID can.
`reports.stale_declarations` resolves each entry against the tree — the module must exist under the
root, and every `::` part must be a `def`/`class` in it — and `run_verify` refuses before the box is
held, on a selected invocation too.

## What a consumer has to do

- **D1: nothing.** Every repo's census re-measures identically except consumer-b's, and there the
  reading moves to what its row already records.
- **D2: consumer-b's 21 rows must move from `path:line` to a node id, and no test code changes.**
  MEASURED over all four repos: those 21 are every one of them refused by `stale_declarations`
  immediately, before any step launches — a `path:line` entry names no file, so under the node-id key
  it names nothing. That is deliberate and it is the better failure: the refusal lists all 21 by name
  rather than making the repo wait twenty minutes for a run whose real skips come back mixed with
  them. The other three repos declare nothing and are untouched.
  Truncating each row at the colon is mechanical and immediately matches (a module path is a prefix
  of every node id in it), at the cost of per-test discrimination; the refusal for an undeclared skip
  PRINTS the node ids, so tightening is a copy and paste. One row cannot be truncated:
  `tests/_winding_lib.py` is not collected (`python_files` is the default `test_*.py`), so that entry
  becomes the node ids of the tests the skip actually reports at — MEASURED by AST: the helper
  `_winding()` in `test_twisting_sides.py` is called by 4 tests, `_load_paths()` in
  `test_terminal_pattern.py` by 6, `_require_layout()` in `test_terminal_pattern_cli.py` by 3, and
  the module-level `require_lib()` in `test_winding_from_toml.py` reports at that module.
- pytest must be >= 9 on every box, measured from four locks: 9.0.2 (consumer-b), 9.1.1 (the other
  three). A pytest without `--no-fold-skipped` exits 4, which `read_pytest` already names as misuse
  — loud, not silent.
