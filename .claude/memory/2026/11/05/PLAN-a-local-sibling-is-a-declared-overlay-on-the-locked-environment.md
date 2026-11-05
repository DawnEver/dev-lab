---
name: PLAN-a-local-sibling-is-a-declared-overlay-on-the-locked-environment
description: A consumer's environment is the lock by default; a family sibling checked out beside it is used instead only when declared, per machine or per run, and only through dep -- which installs it as an editable overlay after the frozen sync, says so on every sync, and drops it when the declaration goes.
metadata:
  type: project
created: 2026-11-05
accessed: 2026-11-05
---

# PLAN: a local sibling is a declared overlay on the locked environment (user directive 2026-11-05)

Directive: an environment uses the LOCK by default. A local checkout of a family sibling replaces its
locked version only when needed, and that choice is RECORDED, not remembered.

## What exists (surveyed 2026-11-05) and why none of it is this

| fact | where it lives | why it is not the answer |
|---|---|---|
| where the family's checkouts sit | `worktreeplace.family_root` (the main checkout's parent) | names the place; installs nothing. REUSED: it resolves a sibling's path |
| a product composing an engine from a tree | `[tool.dev_lab.components]` + `_dep_components` stamps | COMMITTED and shared: it pins every checkout of the product. A consumer retired it (2026-10-21) because no sibling must change in the same commit. REUSED: its tree stamp |
| the one door that moves an environment | `dep` (`_change`: the seat, the census, anchor retirement) | the right door; it only knows the lock and components |
| a consumer's dev recipe | motronics `pyproject.toml` comment: `uv pip install -e ../<repo>` | a bare install outside the door: refused for agents, unrecorded, and silently undone by the next frozen sync |

## The design

1. **The declaration.** Two sources, merged, one name each:
   - the machine file, `[dev_lab.dep] local = ["lab-commons", ...]` in `lab_commons.config` (per machine, never committed -- the
     "no machine-local path in a manifest" ruling holds);
   - `dep --local NAME` (repeatable), for one run.
   A name is a distribution in the target's `uv.lock`; anything else is refused by name. The path is DERIVED,
   `family_root(root) / NAME`, never declared; a missing checkout, or one whose `pyproject` names another
   distribution, is refused naming the fix.
2. **The overlay.** After the frozen sync succeeds, inside the SAME seat (`_change`), `dep` runs
   `uv pip install --python <prefix python> --no-deps -e <path>` per declared sibling. `--no-deps`: the lock
   still decides every transitive version; a sibling that needs a newer peer is a relock, not an overlay.
3. **The default is the lock, by construction.** The frozen sync already reinstalls every locked source,
   so a sync with nothing declared IS the revert: no `--unlocal`, no state to clean.
4. **Visible.** Every sync prints `LOCAL OVERLAY: <name> -> <path> @ <HEAD>[+dirty]`, and the overlay set is
   folded into `env_key`, so a measurement taken on an overlaid environment can never cite the locked one
   (anchors retire exactly as on any other move).
5. **Stamped.** The overlay's tree is recorded with the components stamp (`_dep_components._tree`), so a
   moved sibling with a native build is reinstalled on the next sync, the 2026-10-19 incident's rule.

## Not in scope

- Verdicts: the forge runs locked environments only; an overlay is a local measurement aid.
- Lock moves: `--upgrade-package` / `--lock-upgrade` stay the way a sibling change reaches everybody.

## Steps (each test-first, one green commit)

1. `local_overlays(root, cli_names)`: merge, validate, derive paths -- pure, with planted refusals
   (unknown name, missing checkout, wrong distribution).
2. The overlay leg in `main` after a green sync, in the seat; the banner; `env_key` folding.
3. The stamp; then the consumer doc: motronics' installation guide replaces the `uv pip install -e` recipe
   with `dep --local`.

## State
- 2026-11-05: plan written; no code yet.
