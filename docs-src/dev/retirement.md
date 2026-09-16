# Retirement — an archive and a registry are a PLACE and a RULE, not two answers

- There are two mechanisms for code that is no longer current, and the recurring question is why the retired-entry registry does not simply live in the archive.
- They are not the same KIND of thing: **one is a PLACE, the other is a RULE, and putting the rule in the place would disable it.**
- **The archive remembers the CODE. The registry enforces the ABSENCE.** An archive cannot enforce anything, and a rule kept in an archive is not a rule.

## The two, side by side

| | the archive | the retired-entry registry |
|---|---|---|
| what it is | a PLACE — archived source from migrated repos | a RULE — spellings that must not reappear |
| status | READ-ONLY; never deleted without approval | LIVE DATA, read on every architecture run |
| is it scanned | **NO** — outside the retirement scan's reach, by construction and by intent | it IS the scan's input |
| what it answers | "what did the old implementation do?" | "has a dead spelling come back?" |
| failure if removed | lost reference material | a retired spelling silently returns |

## Why the registry cannot move into the archive

- The scan walks the live trees; the archive falls outside them deliberately, since it is read-only.
- Moving the registry there would put the scan's own INPUT beyond the scan's REACH, so the entries would stop being consulted and the test would stop failing when a retired spelling returned.
- What remained would be **prose that nothing checks** — the declaration-that-lies shape, in its purest form.

## The failure mode that a split registry invites

- A registry large enough to be split into siblings needs two things pinned, and it is easy to pin only one.
- **Self-exclusion is necessary**: every sibling contains every one of its own entries' spellings by construction, so the scan must exclude it or each entry would match itself. That exclusion set gets pinned, because forgetting it reds immediately.
- **The CONCATENATION is the half nobody pins.** If the whole is built by hand-summing each sibling's entries, this sequence is possible and nothing catches it: add a sibling with its entries; import it and add it to the exclusion set, which passes; forget to add its entries to the whole.
- **The result is worse than never registering the entries**: those spellings are now excluded from the scan AND never scanned for, so the registry reports success while covering less than it claims.
- A ratchet has two sides — a capability that disappears, or a waiver nothing uses, is as wrong as its opposite. Here one side is pinned and the other is not.
- The fix is small: DISCOVER the siblings by glob so the whole cannot omit one, or assert that every sibling contributes at least one entry to it.

## This page tripped the mechanism it describes

- Its first version enumerated the archive's subtrees BY NAME, and one of those names is itself a RETIRED SPELLING with a registered replacement.
- The scan failed on this file — **the document explaining the registry resurrected an entry in it.**
- That is the best available evidence both that the scan works and that **prose is exactly where a dead spelling comes back**, which is why the subtrees above are described rather than enumerated.
- The general rule that follows: **name the REPLACEMENT and point at the registry for the thing replaced.** The registry is the one place the old spelling may appear. Prefer naming the SHAPE of a thing over naming an example of it — an example is a spelling waiting to be retired.

## The rule, for future decisions

- Code from a MIGRATED REPO, kept for reference goes to the archive. Never scanned, never deleted without approval.
- A spelling, symbol, environment variable, identifier or config key that must NOT REAPPEAR goes to the registry, with its REPLACEMENT and its reason, **in the same commit as the deletion**.
- Something merely discouraged, or still in use somewhere, goes to **neither**. An entry is a hard NO; if it needs an exception, it is not retired yet.
- **The two never overlap: the archive holds files, the registry holds strings.**
- A deletion that is a POLICY rather than a cleanup needs a retired-PATH row as well, so a branch cut before the deletion reds instead of merging the files back in — see [alignment](alignment.md) Stage 5.
