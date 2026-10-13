# Box resources

One workstation rations CPU, memory and vendor seats across every repo and worktree on it. A job declares what
it will cost, and one broker in an installed package (`lab_commons.resources`) admits it against what live peers
already claim; the box's CPU seat (`lab_commons.dev.cpuseat`) serialises INTERACTIVE test sessions (a `forge serve`
producer takes none: serve admits it, [forge](forge.md#admission)). Declare a job's cost,
measure the box's capacities once, and never evict another party's run.

## The four axes

1. **Resource dimensions are registry data**, each with a SCOPE: a pool's own stock, or one the whole box
   contends for. "One at a time, everywhere" is a box-scoped dimension, not a pool name.
2. **A job declares its cost; it does not request a slot.** Admission is a per-dimension headroom check against
   capacity minus what live peers claim, so four small jobs and two large ones are told apart. The broker
   measures the actual peak against the declaration, so under-declaration becomes a recorded ratio rather than
   a crash.
3. **Exhaustion has three outcomes**: a bounded queue, a readable refusal naming the holder, and a ceiling on
   the running job. Never evict another party's run; a job exceeding its OWN declared ceiling is stopped.
4. **A per-box measurement and a structural constant are different kinds.** A vendor session that ATTACHES
   rather than starting a clean instance is exclusive on every machine; declaring that per box would make every
   undeclared box refuse.

## What the broker must watch

- **A running job, not only an admission.** A job admitted with headroom and then growing to fill the box is
  invisible to an admission-only gate, which postpones the crash rather than preventing it.
- **The vendor process, not the client.** A slot keyed on the client's pid is released when the client gives up
  while the vendor job runs on; track the process table.
- **Every seam of one resource**: process creation and job submission must consume the same budget.
- **Every resource**: a vendor with no slot, or a dev script driving a live engine outside every gate, contends
  through no mechanism at all.

## The unmeasured box

- Conservative means the direction that cannot crash the box: serialise, minimum width, one job, a memory floor
  as a share of TOTAL. Never drop a dimension: an unmeasured ceiling is a ceiling nobody measured, not an
  absent one.
- The caller must be able to tell: the unmeasured fact travels in the return value, per dimension, never only
  in a log line. A conservative ceiling and a ceiling nobody applied are different facts.
- Capacities are measured per workstation, written to an ignored local config with the date measured; no value
  and no hostname is committed, and a copied limit is refused by hostname mismatch.

## Why it is an installed package

- An installed package is importable from the dev tree and the production tree alike, and from every worktree
  regardless of its revision, so a stale checkout cannot weaken the box-wide ceiling.

## Not in scope

- Cross-machine arbitration. Every mechanism here is per box, because the box is the thing that crashes;
  across machines, the forge schedules ([the forge](forge.md#scheduling)).
