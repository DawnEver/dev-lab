# Testing discipline

How tests are classified and recorded. Mark slow or live-engine tests heavy (by path or marker), record a known
failure as an `xfail` carrying its residual, and run one test session per box at a time. Which tier runs what,
and who runs it, is on [the verdict model](verdict-model.md).

## The lightweight / heavy partition

- **Tiers select by MARKER, never by an opt-in flag.** A group that needs a flag to run is a group nobody runs,
  and a skip reads green.
- **The heavy partition is declared data**: a test is heavy by PATH or by an explicit marker, and a collection
  hook makes the classification visible to `-m`. A test in a heavy subtree that drives nothing heavy is carved
  back out by name.
- Live vendor tools run only in the heavy tier.
- Which PLATFORM runs a test is a separate declaration, `[tool.lab_commons.platforms]`
  ([HPC clusters](hpc.md#platform-parts)).

## xfail, never skip

- A known-failing combination is an `xfail` with the MEASURED residual in its reason.
- Strict when it is stable-but-off, so an unexpected pass reds and forces the entry out; non-strict when it
  depends on the operating point.
- A skip is only for a genuinely missing environment or a capability that cannot run, never to hide a
  correctness failure.
- **The xfail list is the distance to done; its terminal state is empty.**
- A repo declares the skips it allows as a NAMED SET, two-sided: an undeclared skip reds, and a declared skip
  that is gone reds too (`lab_commons.dev.reports`).

## One file, one module object

- A script tree that is not a package is loaded by its tests from a path. **Every loader uses one
  `sys.modules` key per file**, the bare name the script itself resolves under; two keys are two module
  objects, and a patch applied to one is invisible to the other. Pin it by identity.

## One test session per box

- The hazard is the SESSION, not the tier: a serial run is not "small". Every run holds the box's CPU seat
  (`lab_commons.dev.cpuseat`); a second request waits a bounded time, attaches to an identical run, or is
  refused naming the holder.
- Independent vendor tools may run concurrently where a repo has measured that they can; the per-vendor
  grouping bounds memory, not the box.
- A full suite runs once per sha, on a producer ([the forge](forge.md)); you run a targeted measure.
