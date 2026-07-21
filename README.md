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

**Tier 2 — shared-domain modules (future, optional import).** Vocabulary that is not
project-specific but IS common across this family of EM/motor labs (e.g. EM quantity
types/constants). A separate, clearly-named, opt-in module/extra — importing tier 1
never drags tier 2 along. Not yet populated; see the source repo's
`plan-lab-commons-standalone.md` for the full plan.

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
