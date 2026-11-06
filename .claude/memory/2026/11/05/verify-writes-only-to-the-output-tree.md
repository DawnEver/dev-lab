---
name: verify-writes-only-to-the-output-tree
description: .verify/ is retired family-wide; verify's run log and records go to <output>/<yy>/<mm>/<dd>/verify/, the durations ledger to .../durations/ (read across every day), coverage stays in .../coverage/.
metadata:
  type: project
created: 2026-11-05
accessed: 2026-11-05
---

# Verify writes only to the output tree; .verify/ is gone (user ruling 2026-11-05: "迁到 output，删掉 .verify/")

- What `.verify/` held (inventory at retirement): `verify-<ts>.log` (the run log a VERDICT cites by content hash),
  `verify-<ts>.outcome.json` (the box's ended record), `verify-<ts>.outcomes/` (per-worker cell records),
  `verify-<ts>.serial-seen` + `.serial-seen.json` (serial-stage marker and its box record), `verify-<ts>.coverage`
  and `.coverage.md` (moved by the coverage commit), and `durations[-gwN].json` (the durations ledger).
- Now: the log and every per-run record beside it -> kind `verify/`
  (`verifysteps.LOG_KIND`); the ledger -> kind `durations/` (`durations.LEDGER_KIND`); coverage keeps its own
  kind `coverage/` as ruled first (its stem ties it to the log; nesting would make one kind mean two things).
  All through `datedlog.output_dir`; an undeclared `[tool.dev_lab.parts] output` is refused.
- THE ONE CROSS-RUN READER is the durations ledger: `durations.read` now globs every dated `durations/` dir under
  the declared output and merges newest-wins (at_ns), so yesterday's readings still count. No dual path: nothing
  reads `.verify/` any more. VERDICT `log=` is a content hash and the run cache stores the log's absolute path,
  so neither spelled `.verify/`.
- Removed: the `.verify/` line of `.gitignore` and of `_famconfig_rows.GITIGNORE_FAMILY_LINES` (consumers' rendered
  `.gitignore` drops it on their next render), the Makefile `clean` entry, and the prose.
- Stale `.verify/` dirs on disk at the time (to delete after merge, not by the agent): dev-lab worktrees
  dep-local, one-test-kit, uv-freshened; lab-commons worktree one-toml-writer.
