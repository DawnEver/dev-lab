# A rule is shared; the thing that refuses one is not

This repo AUTHORS the family's development rules (`lab_commons.dev.rules`). These are the
constraints that come with owning that file. Universal rules are not restated here — they are
cited by ID, and `tests/test_the_adoption_accounts_for_every_rule.py` is what makes the citation
a check.

- **A STATEMENT is universal; a MECHANISM is a path in ONE tree. Never conflate them.** A row in
  `_rule_rows.py` carries the statement plus the EXISTENCE PROOF that the rule is enforceable at
  all. It never grades another repo: an adopter supplies its own mechanisms through `Adoption`.
  Measured 2026-09-15 — when all 70 mechanisms were one repo's paths, lab-commons refused its own
  registry with 70 failures.
- **A row with no mechanism may not exist**, and a rule this repo cannot yet refuse goes in the
  ABSENT set BY NAME. Never an integer: a count cannot say which rule moved, and the honest-looking
  repair when it disagrees is to edit the digit.
- **A rule is added to `_rule_rows.py` only after the NOUN TEST**: delete every domain noun; if
  nothing constrains anything afterwards, the rule belongs to the repo that has that noun.
- **Rows are never deleted to make something pass.** A mechanism that has gone is repointed or
  restored — deleting the row is the one repair that turns a guarantee back into prose.
- **A rule ID is a handle, not a display name.** Renaming one is a breaking change to every
  adopter's rules page and its adoption test; rewording the STATEMENT is not.
- **This repo may not be the worst adopter of its own registry.** A gap closed here deletes its
  name from `_ABSENT` and lowers `_ABSENT_CEILING` in the same edit.

Cites, from the shared registry: `NAMED-SETS-NOT-COUNTS`, `ESCAPE-HATCH-CEILING`,
`DECLARATION-LIES`, `REGISTRY-OWNS-THE-DECISION`.
