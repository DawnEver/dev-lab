---
name: no-commit-message-exemptions-history-is-what-was-published
description: No repo may add a commit-message prefix and LAB_CZ_EXEMPT is gone; a commit is judged once, when first published, so existing off-format commits stand and new ones are refused.
metadata:
  type: project
created: 2026-11-05
accessed: 2026-11-05
---

> Translated 2026-11-12: CJK rendered as faithful English (NO-CJK-IN-TRACKED-SOURCE).

# No commit-message exemptions; history is what was published (user rulings 2026-11-05)

Supersedes the `allowed_prefixes` paragraph of `one-test-kit-and-an-in-repo-commit-message-check.md`.

- RULING 1: "rem( / data( style prefixes must not be let through; writing such a commit is a violation."
  `[tool.dev_lab.commit_msg] allowed_prefixes` and `declared_prefixes()` are removed; a pyproject still
  declaring it widens nothing (test: `rem(`/`data(`/`wip` refused through `main`). `DEFAULT_PREFIXES` is only
  what git writes: Merge, Revert, fixup!, squash!, amend! (`Pull request` dropped: no family flow writes it,
  the forge merges as `chore(merge): ...`). `LAB_CZ_EXEMPT` is removed from `cz-push-range.sh`.
- RULING 2: "Existing prefixes such as rem( and data( may be exempted! Avoid affecting history too deeply!" (translated) -- EXISTING ones stand, NEW ones are
  refused, with no name or sha list. "Existing" = PUBLISHED: `commitmsg --published REV` (repeatable, passed to
  `git log <range> --not REV...`). A commit is judged once, when first published.
- TWO MODES of `cz-push-range.sh`: pre-push (no argument) excludes LAB_CZ_BASE_REF AND `--remotes`, so an old
  commit already pushed on another branch never blocks a later push; `--merge-decision` (forgemerge) excludes the
  base only, because a PR's own commits are on the remote by then and would otherwise never be judged.
- The reason the holes existed (a published off-format commit made every later push unpushable) is answered by
  the published-exclusion, not by an exemption.
