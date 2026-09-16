# Box resources — what one workstation rations, and the design that unified it

- STATUS: the GENERIC half is LANDED as `lab_commons.resources`, whose own docstring is the implementation record. This page is the DESIGN — the four defects measured in doing it by hand, and the four axes that answer them — because a module docstring explains what the code does and this explains why the previous seven mechanisms could not.
- Occasioned by a user report: a vendor engine exhausting RAM and taking the whole workstation down several times in one day, killing sessions and destroying in-flight work in other lanes.
- What happens after a run is killed is on [killed runs and orphans](orphans.md); the lock that serialises verdict runs is on [the verdict model](verdict-model.md).

## The inventory that provoked it, measured 2026-09-13

- Seven mechanisms enforced something independently — six in Python, one in shell. **They shared a discipline and almost no code.**

| | resource | quantity | scope | on an unmeasured box |
|---|---|---|---|---|
| a job-count gate | seats | integer | cross-process | REFUSES |
| the box lock | box CPU | boolean | cross-process | n/a |
| a memory-headroom wait | bytes | bytes plus a bounded wait | cross-process | REFUSES |
| the test-worker width | memory and cores | worker count | in-process | DEFAULTS to a proven width |
| a vendor pool size | memory and cores | worker count | in-process | DEFAULTS to cpu-only |
| a wall-clock family | wall-clock | seconds | mixed | mixed |

- The count gate and the memory wait were one pair. **The other mechanisms were mutually unaware of that pair and of each other.** A run holding the box lock with several workers each loading large heaps was invisible to the memory floor, and the floor was invisible to the width arithmetic — while both read the SAME operating-system call through two duplicated structure definitions in two trees.
- One sized off TOTAL memory where two others sized off AVAILABLE.

## The four defects, in the order they matter

### 1. Nothing observes a RUNNING job, and admission alone cannot prevent a box crash

- A headroom check reads box-global available memory ONCE, at admission. **A job admitted with headroom and then growing to fill the box is unobserved for its entire life.**
- No mechanism sampled a live process's working set and acted on it: one collected memory totals for a HUMAN to read, another sampled CPU seconds only to decide whether an aged session was idle enough to reap.
- Three independent reviews arrived here on the same day — this design, a resource inventory, and a review that called the floor "a declaration with a racy or absent enforcement point".
- **A gate that only admits POSTPONES the crash; it does not prevent it.**

### 1b. The slot recorded the wrong pid, and that is the crash mechanism

- The slot file wrote the CLIENT's process id. When a client gave up, its cleanup released the slot while the vendor process ran on for another hour and the census still showed six live engines.
- **The gate under-counted exactly the case it existed for** — a vendor process outliving its driver holds zero slots, so nothing believed it was still eating the box.

| the bookkeeping | what it tracked | what it should track |
|---|---|---|
| the concurrency slot | our client's lifetime | the vendor JOB |
| "the box is free" | our client exited | the PROCESS TABLE |

- **A proxy that is usually right is the hardest kind of wrong, because it earns trust before it fails.**

### 2. Count and memory guarded different seams for the same resource

- Memory gated at process creation. Count gated at job submission. Nothing gated the interval between them, so four processes could exist with the count entirely unconsumed, and then a fifth job be refused.

### 3. The tree disagreed with itself about the unmeasured box

- One mechanism refused and argued at length that a guess is worse than a refusal. One defaulted to a proven width. One defaulted to cpu-only and dropped the memory ceiling entirely, its own docstring naming that as the constraint disappearing.
- **Three positions, each argued. A general mechanism must pick one and re-argue the other two — not inherit all three.**

### 4. Whole resources sat outside every gate

- One vendor took no slot and no floor on any path; worse, asking for its limit RAISED, because the local declaration deliberately omitted it — so the guard was not unused but UNUSABLE.
- Others had wall-clock bounds and nothing else, including the one holding a real licence seat.
- Dev scripts driving live engines took neither the box lock nor any slot, so a human running one beside a verdict contended through no mechanism at all.

## The four axes the answer is built on

1. **Resource DIMENSIONS are registry DATA, not branches on a kind**, and each names its SCOPE — a pool's own stock, or one the whole BOX contends for. A pool is a key and a key is a string, so "one at a time, everywhere" is not a fact a shared pool NAME can carry; a box-scoped dimension is how it becomes one.
2. **A job DECLARES its cost; it does not request a slot.** Admission is a per-dimension headroom check against capacity minus what live peers claim, which is what lets four small jobs and two large ones be told apart — a count never can. And because a declaration that lies is the dominant defect, the broker MEASURES the actual peak against the declared estimate, so systematic under-declaration becomes a recorded ratio rather than a box crash.
3. **Exhaustion has THREE outcomes, not one**: a BOUNDED queue, a readable refusal naming the holder, and a CEILING ON THE RUNNING JOB. On the running ceiling one constraint is absolute — **never evict another party's run**, because a verdict in progress is someone's evidence. A job exceeding ITS OWN declared ceiling is a different matter and is the safety valve that keeps the box alive.
4. **A per-box MEASUREMENT and an everywhere-identical STRUCTURAL CONSTANT are different KINDS.** Measured: a vendor session type is exclusive because attaching to it ATTACHES rather than starting a clean instance, so the usable session count is effectively one while the declared concurrency says nothing about it — an export launched during a solve was handed the solve's session and died reporting success while writing no file. That exclusivity must NOT be declared per-box: it is identical on every machine, so declaring it as a measurement would make every export RAISE on a box that had not declared it.

## The unmeasured box: conservative PLUS forced visibility

- CONSERVATIVE means the direction that CANNOT crash the box — serialise, minimum width, one job, a floor that is a share of TOTAL. Never the permissive direction, and **never dropping a dimension entirely**: an unmeasured ceiling is a ceiling nobody measured, not an absent one.
- VISIBLE cannot be a log warning. A warning on an unchanged success return is the forbidden shape — the test is whether the CALLER can tell — so the un-measured fact travels in the RETURN VALUE, saying per dimension what the ceiling rested on.
- **A ceiling held at the conservative value and a ceiling nobody applied are DIFFERENT FACTS.** Collapsing them makes the conservative flag itself a declaration that lies.
- Capacities keep the discipline the first measured mechanism established: measured per workstation, written to an ignored local config carrying the date it was measured, no value and no hostname committed, and a copied limit refused by hostname mismatch.

## The constraint the unification had to reckon with first, and how it was resolved

- A dev tree that may not import production code means a mechanism in either tree is unreachable from the other, which is why one module RE-DERIVED another's reasoning and why two copies of the same system structure existed.
- **An INSTALLED package is importable from both** — and from every worktree on the box regardless of which revision each has checked out, which structurally closes the "a stale checkout silently weakens the box-global ceiling" hazard instead of closing it by policy.
- Around twenty worktrees can exist on one box, at least one checked out before any given gate landed. They contend for the same files deliberately: the whole point is that two lanes on one machine contend.

## Not in scope

- Cross-MACHINE arbitration, deliberately. Every mechanism here is per-box, and **the box is the thing that crashes.**
