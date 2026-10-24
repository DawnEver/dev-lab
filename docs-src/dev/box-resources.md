# Box resources

One machine rations CPU, memory and tool seats across every repo, worktree and session on it through ONE
ledger in an installed package (`lab_commons.box`). Every run declares what it will use and how long it may
take; it is admitted only when the MEASURED room holds it, and it runs inside a kernel limit sized to that claim.

## The five rules

1. **A run declares its demand.** Cores, memory, a wall and named tool seats (`box.Demand`); no field has a
   default, because a default is a number nobody chose.
2. **Supply is measured (D3).** A run fits when the one rule (`compute.admission.admit`) admits its demand on
   the box's room (`box.supply.room`): cores idle and memory available NOW, less what every held claim has not
   taken yet (declared minus in use), less the machine file's `[reserve]` margins (`cpu_margin`, default 1
   core; `mem_margin`, default 0.10 of its memory) -- never more than the box's size less every declaration.
   An editor, a vendor GUI or another user's session counts because the OS counts it. Tool seats are declared:
   `[capabilities.<name>] seats`, 1 when undeclared.
3. **The claim is the limit.** `box.run` runs the process tree inside a Windows Job Object or a Linux
   systemd scope (on Slurm, the allocation or an RSS watchdog): killed past its memory or wall, so a claim is
   never exceeded and never idle-but-held. Where nothing can enforce, the run is refused.
4. **A waiter holds nothing.** It waits at most its own queue ceiling, then is refused naming the dimension
   short and every holder with its deadline. No room is held for a waiter, lent or preempted (user ruling
   2026-10-14); priority is ordering only (`compute.priority`).
5. **Backfill by reservation is the one ordering rule** (`box.order`). A contending ticket's earliest start is
   the first moment -- now, or a held claim's deadline -- at which the room, every claim ending by then
   released, admits it. A later ticket that fits now is admitted iff, held to its own deadline, it delays no
   earlier contending ticket's earliest start; so a ticket waits at most until the claims held when it arrived
   end. That start is computed, never booked: nothing is set aside, which is why rule 4 holds. A holder is
   never ordered behind a waiter (the 2026-10-19 deadlock): its ticket is admitted as soon as it fits. A
   ticket wanting nothing an earlier one wants is never ordered behind it.

## Who claims

- `python -m dev_lab.dev.verify -- <paths>` runs its pytest step in the box at the selection's declared
  claim; `--lock-wait "<duration>"` is its queue ceiling.
- `forge serve` admits a part against what the ledger can still admit, and runs its producer in the box at
  exactly that demand ([forge](forge.md#admission)); the producer's own verify does not claim again.
- Anything else: `python -m lab_commons.box run --cpu N --mem-gb G --wall S --queue-s Q --key K --outcome P -- argv`.
  The exit code is the child's own; how the BOX ended it -- the `Outcome` (`exit`, `memory`, `wall`) or a
  refusal when nothing ran -- is the record at `P`, read back with `lab_commons.box.read_ended`. No record
  after the process exited means the box itself crashed. A sentinel exit code would misread a child that
  chose the same number, so none exists.

## Not in scope

- Cross-machine arbitration. The ledger is per machine, because the machine is the thing that crashes; across
  machines, the forge schedules ([the forge](forge.md#scheduling)).
