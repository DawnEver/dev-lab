# Four repos install this one, and none of them can see this history

`lab-commons` is the leaf: motronics-studio, wdg-lab and optimi-lab import it, and nothing here
imports them. Every constraint below follows from that one fact.

- **A consumer inherits every runtime dependency**, including the ones it never uses. A new entry
  in `[project].dependencies` is a decision typed into the named set in
  `tests/test_arch_dependencies.py`, not a line that appears. Heavier or optional machinery ships
  behind an extra and an opt-in subpackage, as `lab_commons.dev` and `lab_commons.em` do.
- **An upper bound here is a resolver constraint imposed on four trees.** A floor states what this
  code needs; a ceiling is somebody's bad afternoon, inherited. Fix the incompatibility, or pin it
  in the consumer that actually has the problem.
- **Importing the top level must not drag in a tier it did not ask for.** `lab_commons.dev` and
  `lab_commons.em` are opt-in IMPORTS, pinned against a fresh interpreter by
  `tests/test_dev_gate.py` — a convenience re-export at the top level would silently repeal that.
- **`__all__` is the contract, and there is no second place a consumer learns it was wrong.**
  A public module declares its surface, and every declared name resolves.
- **No `_legacy`/`_compat` alias, no deprecation shim, no dual entry point.** A caller that is not
  made to move does not move; two spellings of one idea then drift in four trees at once. The
  rename breaks, deliberately, at a point somebody chooses — and the consumers move WITH it.
- **A behaviour a consumer's guard rests on is load-bearing even when it is private.**
  `_detect_repo_root` is imported by name across the family: change what it returns and four
  architecture suites change verdict, so the change is a breaking one whatever its underscore says.

Cites, from the shared registry: `LATEST-DEPENDENCIES`, `PUBLIC-SURFACE-DECLARED`,
`FIX-THE-CAUSE`, `NO-LAZY-IMPORT`.
