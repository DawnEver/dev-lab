# Principles -- family policy, rendered from dev_lab.dev.principles; edit there

- **First principles** (`first-principles`): Derive from the actual system and current needs, not habit or precedent;
  state shaping assumptions.
- **Discard historical baggage** (`no-historical-baggage`): Remove obsolete structures, duplicates and dead paths no
  current need uses -- never a capability.
- **Occam's razor** (`occams-razor`): Simplest design that fully meets the need; nothing for hypothetical needs; it
  removes dead paths and duplicates, never a capability.
- **Single source of truth** (`single-source-of-truth`): Each fact lives in one place; everything else is derived from
  it.
- **Layered decoupling** (`layered-decoupling`): Depend one way through narrow interfaces; never into internals or
  upward.
- **Names match what they do** (`names-match-behaviour`): A name says what the thing does now.
- **No backward compatibility** (`no-backward-compatibility`): No shims, aliases or dual paths for old callers; callers
  move with the change.
- **Progressive disclosure** (`progressive-disclosure`): An entry point states what is needed first and points to
  detail; no duplication across levels.
- **Keep every valuable parameter and option** (`keep-valuable-options`): Generality is a requirement: keep every
  parameter and option a real case uses or plausibly needs. Matching a reference or vendor ADDS a selectable option,
  declared by the case or config that needs it; it never replaces or deletes the alternative. Numerical method choices
  (quadrature, time scheme, averaging window, coefficient evaluation) are options, and "no current caller" is not
  grounds to delete a numerically meaningful one.
