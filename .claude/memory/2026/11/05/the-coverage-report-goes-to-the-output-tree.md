---
name: the-coverage-report-goes-to-the-output-tree
description: verify's coverage report and data file go to <[tool.dev_lab.parts] output>/<yy>/<mm>/<dd>/coverage/, resolved by datedlog.output_dir; an undeclared output root is refused, not defaulted.
metadata:
  type: project
created: 2026-11-05
accessed: 2026-11-05
---

> Redacted 2026-11-09: site markers removed (public repo).

# The coverage report goes to the output tree (user ruling 2026-11-05)

Supersedes the COVERAGE line of `one-test-kit-and-an-in-repo-commit-message-check.md`.

- Family rule: everything a program produces and can regenerate goes to `output/logs/<yy>/<mm>/<dd>/<kind>/`.
  `<log stem>.coverage.md` and `<log stem>.coverage` now go to kind `coverage/` (its own kind, as the ruling
  named it; the shared stem ties it to its run log).
- ONE resolver: `dev_lab.dev.datedlog.declared_output(root)` reads `[tool.dev_lab.parts] output`, and
  `output_dir(root, kind)` is today's dated dir under it (built on `dated_log`).
- NO DEFAULT ROOT: an undeclared `output` raises `UndeclaredOutput` naming the key. Every family repo
  (dev-lab, lab-commons, ai-lab, numerics-lab, the private consumer repo) already declares `output = "output/logs"`,
  so a default would be dead code that hands an undeclared repo another repo's answer (datedlog's own rule).
- `platformparts.cluster_part` still reads `output` itself, at a COMMIT (not the working tree); that is a
  different question and stays there.
