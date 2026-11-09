---
name: one-test-kit-and-an-in-repo-commit-message-check
description: dev-lab[test] is the family's one test kit; commitizen gave way to dev_lab.dev.commitmsg, rtoml to tomlkit, pytest-mock to unittest.mock; verify writes a coverage report.
metadata:
  type: project
created: 2026-11-05
accessed: 2026-11-05
---

> Redacted 2026-11-09: site markers removed (public repo).

# One test kit, an in-repo commit-message check, a coverage report (user rulings 2026-11-05)

- THE KIT: base install pytest, pytest-xdist, pytest-cov, ruff (the verify door runs all four); `test` extra adds
  pytest-timeout, hypothesis, pyright, pdoc. Not in it: maturin (repo build tool), pytest-mock. A consumer
  declares `dev-lab[test]` and drops its own copies -- each consumer's own PR, not this one.
- COMMITIZEN DROPPED: `dev_lab.dev.commitmsg` owns `type(scope)!: subject` (commitizen's cz_conventional_commits
  schema, types build bump chore ci docs feat fix perf refactor revert style test), the default prefixes
  (Merge, Revert, Pull request, fixup!, squash!, amend!) and the empty-message abort. A repo EXTENDS the prefixes
  with `[tool.dev_lab.commit_msg] allowed_prefixes` -- the private consumer repo's `[tool.commitizen] allowed_prefixes`
  (merge, wip, rem(, record(, data() is no longer read and must move there. The base commit-msg row is now
  `conventional-commit`; `cz-push-range` and its `LAB_CZ_*` env keep their names (consumer rows name them).
- The push-range and forge-merge tests used to plant a fake commitizen that refused only `data(`; they now run
  the REAL checker. That surfaced a vacuous control: the merge test's off-format arm passed because the worktree
  had no venv, not because the message was judged -- the refusal now must quote the subject.
- TOML: tomlkit writes (dep_observe), stdlib tomllib reads. rtoml stays in the resolution through
  lab-commons[io]; jinja2 through pdoc.
- COVERAGE: every verify pytest step writes `.verify/<log stem>.coverage.md` and prints the TOTAL; never a gate.
