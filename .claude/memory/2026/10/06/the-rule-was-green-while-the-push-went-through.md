---
name: the-rule-was-green-while-the-push-went-through
description: A session pushed seven lane branches to origin while ONE-BRANCH-PER-SESSION was green, because every enforcement point the rule had ran AFTER the push. The push-time hook, what pre-commit actually hands it on stdin and in the environment, why a deletion must pass, and the three floors one module moved.
metadata:
  type: project
created: 2026-10-06
accessed: 2026-10-06
---

# The rule was green while the push went through

`320422c`, released as `v0.3.0`.

## The defect was not the rule. It was WHEN the rule was read

ONE-BRANCH-PER-SESSION has been declared since 2026-10-04, with a census
(`lab_commons.dev.branchset`), famtests every consumer runs, and a registry row. MEASURED 2026-10-05
and 10-06: a session pushed **seven** `work/sdm*` lane branches to origin, and every guard naming
that exact hazard was GREEN throughout, because none of them had run yet. A verdict that arrives
after the operation it judges is a report, not a guard. `lab_commons.dev.branchset_push` is the same
rule read at the one moment the answer still matters.

## The refspec arrives through two doors, and which one is a MEASUREMENT

Git's `pre-push` writes `<local ref> <local sha> <remote ref> <remote sha>` on **stdin**, one line
per ref. pre-commit CONSUMES that stdin to compute its diff range -- the family's own
`branch-push-only.sh` had recorded this since 2026-08-13 -- so a hook written to read stdin only
would judge nothing under the wiring all four repos actually use. Re-measured on a real bare origin,
both ways:

| wiring | stdin | environment |
|---|---|---|
| raw `.git/hooks/pre-push` | the refspec, every ref | no `PRE_COMMIT_*` at all |
| through pre-commit | **EOF** | `PRE_COMMIT_REMOTE_BRANCH=refs/heads/<b>`, `PRE_COMMIT_LOCAL_BRANCH=HEAD` |

So stdin is read first and the environment is the fallback. Reading the environment FIRST would pass
the door that needs it and silently judge one ref of a multi-ref push at the other.

## Two more measurements that decided the code

* **pre-commit runs NO hook at all for a delete-only push.** Measured twice: the probe logged the
  branch push and logged nothing for the deletion. So a deletion passes there by not being asked.
  A RAW hook IS asked, and the deletion is recognisable -- `local_ref=(delete)` and an all-zero
  `local_sha`.
* **A deletion must pass EITHER WAY**, and this is a design constraint rather than a courtesy: the
  census's own message tells a human `git push origin --delete <b>`, so a push guard that refused
  deletions would refuse the remedy for the debt it exists to report.

## The handshake, which is a change to shared machinery

`run_hook` now exports `LAB_PYTHON=sys.executable`. A bash hook cannot recover `sys.executable`, and
the shipped script needs an interpreter that can import this very package; resolving one from `PATH`
would let an ImportError be reported as a policy refusal -- the misattribution `with-venv.sh` and
`git-env-repair.sh` were each written about. The name is defined once, in `githooks.PYTHON_ENV`,
because the dispatcher that sets it and the script that reads it must not spell it twice.

## Three floors moved, each TIGHTENED, and each by its own arm's documented arithmetic

Landing one module and one test file is enough to red three floors in this repo, and every one of
them said so rather than absorbing it -- which is what they are for. The repairs all reduce slack:

| pin | before | after | the reading |
|---|---|---|---|
| `test_famtests_venvspelling.FILE_FLOOR` | 151 | **152** | 192 kit modules, 41 clear against a 40 margin |
| `test_famtests_countpins.CONSTANT_FLOOR` | 361 | **366** | 456 constants, 95 clear against a 90 headroom (the ~80% of 456 is 365, still one past) |
| `test_dev_githook_scripts` HOOKS pin | 2 names | **3 names** | a NAMED set, so the arrival is legible |

The count-pin reading is ALL module-level constants in `tests/`, so a new test file's five named
constants are what moved it -- worth knowing before writing a test that names five things.

## What a consumer has to do, and what is deliberately absent

Wire the hook in the `pre-push` stage, before the gate, so an undeclared ref is refused in
milliseconds instead of after a multi-hour verdict:

```yaml
      - id: branchset-push
        entry: lab-with-venv
        args: ['lab_commons.dev.githooks', 'branchset-push']
        stages: [pre-push]
```

No bypass exists: no flag, no environment variable, no `--force` spelling. A checkout that declares
no branch set is REFUSED (exit 2) rather than passed, because a guard that cannot judge must not
read as a guard that acquitted -- the incident's own shape, one layer down.
