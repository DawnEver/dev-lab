---
name: an-area-row-is-a-red-of-the-part-that-now-selects-it
description: area:<name> issue rows are derived from the latest record per part, not accumulated; retired-part rows vanish, inconclusive records are routed, tidy closes
created: 2026-10-15
---
# An area row is a red of the part that NOW selects it (2026-10-15)

## The defect

Area issues accumulated rows and only a run of the SAME part could tick them. Three ways they froze:

- rows tagged with a part name that no longer exists (a platform name from before need-set parts): no run of
  that part will ever happen, so the rows stood forever;
- rows for tests that moved to another part by a marker (a `node` test, tagged with its old part): the part
  that now runs them reports them, the part they are tagged with never sees them;
- an INCONCLUSIVE cluster record raised `PartRefusal` before routing, so a head that is never conclusive
  froze every area issue it touched.

## The rule (`lab_commons.dev.forgeroute`)

A row `- [ ] `<id>` (<part>) <outcome>` says: the latest record of the part that now selects `<id>` reported
it red. Every record names the owner of EVERY collected id (its own outcome, or `not-covered` + `handed`),
so routing a record of part P:

- REPLACES P's rows with P's reds in this record;
- keeps another part Q's row only while this record says Q selects that id (or, for Q's `never reported`
  row, while Q is still a part some id is handed to). Retired names, moved ids, uncollected ids drop out.

No ticked rows: a green id has no row. Every open `area:*` issue is re-rendered on each record (one listing),
so an area the record has no red in still sheds disowned rows. Routing NEVER closes: `forge tidy`
`green_areas` does, through the one predicate `forgeroute.still_red`.

INCONCLUSIVE: `forgerun` now routes at the GATHERED phase, before the part is posted (and refused). Its
reported reds (`failed`/`error`) are rows; its `lost`/`missing` ids are ONE `<part>: never reported` row per
area, counted and the first five named. A record covering no id routes nothing.

## Assumption

Records carry no branch; all routed records feed the same `area:*` issues and the newest record of a part
wins. That is right while the forge produces parts for one integration line; per-branch issues would need
the ref in the title.

`RED` lost `lost`/`missing` (now `platformparts.UNRUN`, made public with `NOT_COVERED`; `localpart` reads
that one constant instead of its own copy).
