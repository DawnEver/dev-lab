---
name: the-local-overlay-reads-repos-and-must-fold-into-the-key
description: Implementing the local-sibling overlay corrected two points of its plan -- the path comes from the machine file's existing [repos] record before family_root, and the key fold is necessary because envkey hashes name==version only; steps 1-2 landed.
corrects: .claude/memory/2026/11/05/PLAN-a-local-sibling-is-a-declared-overlay-on-the-locked-environment.md
metadata:
  type: project
created: 2026-11-05
accessed: 2026-11-05
---

> Redacted 2026-11-09: site markers removed (public repo).

# The local overlay reads `[repos]` and must fold into the key

Corrects the 2026-11-05 PLAN in three places, found while implementing it.

- **The machine table is `[dep] local`, not `[dev_lab.dep] local`.** It is read through
  `lab_commons.config.section('dep')`, like the existing bare tables `[repos]` and `[sync]`.
- **The path is not only derived.** The machine file already records where a checkout lives: `[repos] NAME = "<path>"`,
  read by `escapes.allowed_roots`. The overlay uses that entry when present, else `family_root(root) / NAME`.
- **The key fold is necessary, not cosmetic.** `lab_commons.envkey` hashes `name==version`, and an editable checkout at
  the locked commit reports the locked version. Without the fold, adding or removing an overlay moves no key and retires
  no anchor. `dep` folds the stamp (`dev-lab-local.json` in the venv) into the key `_change` compares. Folding it into
  `env_manifest` itself, so a gate's key differs too, is a lab-commons follow-up; the forge runs locked environments only.

## State
- Steps 1-2 done: `_dep_local.py`, `dep --local`, the overlay leg inside the seat (`_change(then=...)`), the key fold,
  and the fan-out doc. `tests/test_dev_dep_local.py` and the dep suites, 70 pass.
- Open: the `env_manifest` fold (lab-commons), and the the private consumer guide switching `uv pip install -e` to `dep --local`.
