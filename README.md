# lab-commons

Project-agnostic shared infrastructure for the motronics-studio / optimi-lab / wdg-lab
family of labs. Extracted because the same utils layer had drifted into **six
near-identical, silently-diverging copies** across those repos (see
`finding-shared-lab-infra-extraction.md` in motronics-studio's memory).

## The two-tier rule

**Tier 1 — agnostic core (always available, this package's default install).** Contains
no concept from any single project's domain. Test: could a lab doing something
unrelated (chemistry, finance) use it unchanged? If a symbol names a *specific* solver,
a winding, an optimizer, or a vendor tool, it does not belong here.

**Tier 2 — shared-domain modules (optional import).** Vocabulary that is not
project-specific but IS common across this family of EM/motor labs — `lab_commons.em`,
the EM quantity types/constants. A separate, clearly-named, opt-in module — importing
tier 1 never drags tier 2 along; `lab_commons.em` needs no extra dependency to install
(pint is already a tier-1 dep), the "optional" is about IMPORT, not install. See the
source repo's `plan-lab-commons-standalone.md` for the full plan.

## What's here (v1)

- `lab_commons.log` — a named, `propagate=False` stdlib logger factory plus
  `log` / `log_decorator` / `timer` free-function helpers.
- `lab_commons.paths` — app-agnostic path resolution and per-run output directories.
  Home-root precedence per app: `<APP>_HOME` env -> auto-detected source checkout ->
  platformdirs. Everything is parameterized by `app_name`; nothing is hardcoded to any
  one project.
- `lab_commons.structured` — structlog/JSON structured output layered on the SAME named
  logger `log.py` produces (purely additive, v1 stays unchanged), secret redaction by
  field-KEY pattern (license keys / tokens / fingerprints / secrets / passwords are
  hashed, never logged in the clear), and a two-phase `bootstrap()` -> `bind_run_dir()`
  transport (console-only before the run directory is known, then a JSONL file sink).
- `lab_commons.file_io` — TOML read/write (`read_toml`, `save_toml`), plus filesystem
  presence helpers (`check_path`, `list_files_in_dir`).
- `lab_commons.exceptions` — the generic subset of exception classes/decorators
  (`ParameterException`, `QuantityException`, `deprecated`, `not_implemented`).
  Project-specific exceptions (a vendor-solver name, an error-code catalog) stay in
  each consumer's own tree.
- `lab_commons.units` (**tier 1**) — the generic pint <-> pydantic `Annotated` machinery:
  `ureg` / `Q_`, `PydanticQuantity`, `get_quantity_type()`, `BaseModel_with_q`. No EM
  vocabulary; importing this module never imports `lab_commons.em`.
- `lab_commons.em` (**tier 2, opt-in**) — the family-shared EM/physical quantity
  vocabulary built on `lab_commons.units`: every `*Type = NewType(...)` (`LengthType`,
  `TorqueType`, `AngleSpeedType`, ...) and every `Q_*` constant (`Q_0mm`, `Q_360deg`,
  `Q_0Nm`, ...), plus `Cartesian2DPoint`/`Polar2DPoint`, `Q_list2array`,
  `array2list_2Dpoint`, `is_equal_2DPoint`, and `CONSTANTS` (`vacuum_permeability`).
  Import explicitly: `from lab_commons.em import TorqueType`.

- `lab_commons.proc` (**tier 1**) — what a BOX is doing: `system_memory()` (the one home for
  `GlobalMemoryStatusEx` / `/proc/meminfo`), `working_set_bytes(pid)`, `pid_alive(pid)`,
  `process_tree(pid)` and `kill_process_tree(pid)`. stdlib `ctypes` only, never `psutil` — an
  optional dependency makes a ceiling that silently stops being enforced on some machines, which
  is worse than no ceiling because it is believed. Unreadable is always distinct from zero.
- `lab_commons.resources` (**tier 1**) — the box-resource broker built on it: resource
  DIMENSIONS as data (`seats`/`box_seats`/`memory`/`cpu` enforced; `wallclock`/`disk`/`gpu` carrying
  the shape
  with nothing able to check them), each naming its SCOPE — a pool's own stock, or one the whole
  BOX contends for, which is what makes "one at a time, everywhere" a property of the mechanism
  rather than of a shared pool NAME. A `CapacityRegistry` that models a per-box MEASUREMENT and an
  everywhere-identical
  STRUCTURAL constant as different kinds, cross-process reservation by record file, and a CEILING
  on the running job. A job DECLARES its cost rather than requesting a slot. A seat file is created
  WITH its record (`os.link` on a staged one) so a peer never reads a taken seat as free. An
  UNMEASURED box is
  neither refused nor permissively guessed: it gets the conservative value (serialise, minimum
  width, a floor that is a share of TOTAL) and the fact travels in the RETURN VALUE —
  `Grant.basis` / `Grant.conservative` / `Grant.is_fully_declared` — never in a log warning.
  A ceiling held at the conservative value and a ceiling nobody applied are DIFFERENT facts:
  `Grant.unbounded` is the second, so a demand on `disk` is never mistaken for a bound this
  package applied — and declaring a value for it does not change that, because a number nobody
  can read is not a ceiling.
  The reservation tracks the JOB, not the Python client, so a vendor process outliving its driver
  still holds its seat. It never evicts another party's run: the only route to a ceiling is
  through the grant that admitted the job.

## Adopting the shared agent deny rules

`lab_commons.dev.hooks` holds one row per UNIVERSAL denied command shape — a hand-written test
line, a bare `git push`, a stash, a force push, a `--no-verify` push, a raw process kill, a
worktree with no commit named. Each row states the hazard and **names its remedy**: a rule that
seals a road with no exit gets routed around rather than obeyed, so a rule whose remedy does not
exist in your repo is **not shipped to it at all**.

The statement is shared; the remedy is yours. Supply one per rule ID, exactly as
`lab_commons.dev.rules.Adoption` supplies a mechanism per rule ID:

```python
# <repo>/scripts/repo/write_deny_rules.py
from pathlib import Path
from lab_commons.dev.hooks import Remedy
from lab_commons.dev.hook_adoption import HookAdoption, render

VERIFY = Remedy(
    kind='verdict-entry-point',
    command='python -m lab_commons.dev.verify',
    allow=r'\blab_commons\.dev\.verify\b',
    path='src/lab_commons/dev/verify.py',  # resolved against YOUR tracked files
)
ADOPTION = HookAdoption(
    app_name='wdg-lab',
    remedies={'BARE-TEST-INVOCATION': VERIFY, 'PUSH-NO-VERIFY': VERIFY},
    declared_absent=frozenset({'GIT-NETWORK-VERB', 'RAW-PROCESS-KILL'}),  # no wrapper, no killer
)
Path('.claude/hooks/deny-rules.json').write_text(render(ADOPTION), encoding='utf-8')
```

Then commit that JSON, point a `PreToolUse` Bash matcher in `.claude/settings.json` at the deny
engine with the file as `argv[2]`, and have your suite call
`assert_shippable(ADOPTION, tracked_files(root))` plus a comparison of the committed file against
`render(ADOPTION)`, so the two halves cannot drift.

The ENGINE — the JavaScript that decides what a shell line will actually execute — is not shipped
from here: a hook is executed from the repo tree by the agent harness, not imported from a wheel.
motronics-studio's `.claude/hooks/deny-commands.js` is the reference implementation, and it reads
exactly the field names `render` emits (`name`, `pattern`, `matches`, `allow`, `reason`).

## The family's mechanism docs

`docs-src/dev/` is the one copy of the development MECHANISM every repo in this family shares —
how a verdict is produced, how lanes fan out, how a merge lands, what the box rations, how `main`
is protected. `.claude/rules/**` in each repo stays HARD CONSTRAINTS ONLY; the mechanics are here.

The test for what belongs here has the same shape as the noun test in `lab_commons.dev.rules`:
**does the document's SUBJECT change when you change repos?** The box, git, the forge and the
family's process are the family's; a repo's own domain stays home.

A consuming repo POINTS at these pages and never copies one. `lab_commons.dev.devdocs` ships the
table of contents as data, and `pointer_table(base)` renders the markdown table that repo puts in
its own dev index, so a page added or renamed here does not leave four hand-typed tables that
agree for a while. There is no rendered portal for this tree yet — the pages are read as markdown
from a checkout or from the forge — and that is stated rather than implied.

## Consumers

- **motronics-studio** — the origin of this code; re-points `core/utils/{config,logger}.py`
  at this package (see that repo's `plan-lab-commons-standalone.md` for the swap runbook).
- **optimi-lab**, **wdg-lab** (+ its forks) — planned, per the same plan doc.

## Installing (git-URL pin)

Not yet published to PyPI — pin by git URL + a REV (a tag or commit), never a bare
branch (an unpinned branch reintroduces exactly the drift this package exists to end):

```toml
dependencies = [
    "lab-commons @ git+https://github.com/DawnEver/lab-commons.git@<tag-or-commit>",
]
```

## Anti-drift guard

Each consumer is expected to carry a test that reds if a local re-implementation of a
lab-commons module reappears in its own tree (a re-fork), per this repo's origin plan
("a check the code must consult", not a policy nobody reads).
