# Retirement

Two mechanisms handle code that is no longer current, and they are different kinds of thing. The ARCHIVE is a
place that keeps old code to read; the RETIRED REGISTRY is a rule that keeps a dead spelling from coming back.
When you delete a name, register it with its replacement in the same commit; when you keep a migrated repo's
code for reference, put it in the archive. In prose, name the replacement, never the retired spelling.

## The two, side by side

| | the archive | the retired registry |
|---|---|---|
| what it is | a PLACE: archived source from migrated repos | a RULE: spellings that must not reappear |
| status | read-only; never deleted without approval | live data, read on every architecture run |
| scanned | no, by construction | it IS the scan's input |
| answers | "what did the old implementation do?" | "has a dead spelling come back?" |

- The registry cannot live in the archive: the scan does not reach the archive, so its entries would stop being
  consulted and the rule would become prose nothing checks.
- The two never overlap: the archive holds files, the registry holds strings.

## Deciding which

- Code from a migrated repo, kept for reference: the archive.
- A spelling, symbol, environment variable, identifier or config key that must not reappear: the registry, with
  its replacement and its reason, in the same commit as the deletion (`RETIRED-NAMES-REGISTERED`).
- A deletion that is a POLICY also needs a retired-PATH row, so a branch cut before the deletion reds instead of
  merging the files back ([alignment](alignment.md#stage-5-the-guards-only-the-merged-tree-can-run)).
- Something merely discouraged, or still used somewhere: neither. An entry is a hard no.

## A retired spelling survives longest in prose

- Comments, docstrings and pages explaining a retirement are where an old name comes back. Name the
  REPLACEMENT and point at the registry for the thing replaced; prefer naming the SHAPE of a thing over an
  example of it, since an example is a spelling waiting to be retired.

## A registry split into siblings

- **Discover the siblings by glob**, or assert each contributes an entry. A whole built by hand-summing each
  sibling's entries can import a sibling, exclude it from the scan, and forget to add its entries: those
  spellings are then neither registered nor scanned for, while the registry reports success.
- Self-exclusion is necessary (each sibling contains its own spellings) and is the half everyone pins; the
  concatenation is the half to pin too.
