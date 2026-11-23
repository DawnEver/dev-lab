---
name: stale-lanes-and-hold-tags-discarded-by-the-one-day-ruling
description: "User ruling 2026-11-23: origin keeps only pr/ branches updated within one day plus the toolchain task's, and only v* tags; these stale lanes and hold/archive tags were discarded by -s ours merges, then deleted"
metadata:
  type: project
---

User ruling 2026-11-23 (integrator): keep only pr/ branches updated within one day plus the toolchain task's
assigned work; unlanded content is merged or discarded, never archived (no bundle, no archive tag, no copy under
output/); origin tags are versions only. Each ref below was idle more than 24 h and unlanded, so one `-s ours`
merge records its discard (integration keeps its own side), and `branchprune delete` removes it once this lands:

- origin/pr/winding-3d/user-paths-absolute
- origin/pr/toolchain/windows-base-hang
- origin/pr/toolchain/windows-base-fits
- origin/pr/toolchain/walls-1119
- origin/pr/toolchain/secrets-list-names-only
- origin/pr/toolchain/rescue-triage-392
- origin/pr/toolchain/rescue-the-round-cap-is-five
- origin/pr/toolchain/rescue-serve-forge-user
- origin/pr/toolchain/rescue-ops-runs-a-forge-runner
- origin/pr/toolchain/rescue-old-format-results-are-purged-once
- origin/pr/toolchain/rescue-memory-converges
- origin/pr/toolchain/rescue-lane-clone-remove-run
- origin/pr/toolchain/rescue-family-permissions-are-rendered
- origin/pr/toolchain/rescue-every-write-lands-in-a-repo-or-the-machine-home
- origin/pr/toolchain/rescue-base-repair-1120
- origin/pr/toolchain/rescue-a-task-carries-its-key-bundle
- origin/pr/toolchain/hpc-machine-file-repair
- origin/pr/toolchain/fix-integrate-reds
- origin/pr/toolchain/dev-lab-names-no-account
- origin/pr/toolchain/consent-over-https
- origin/pr/toolchain/worktrees-remove-is-a-real-door
- origin/pr/toolchain/retirement-classes
- origin/pr/toolchain/rescue-triage-394
- origin/pr/toolchain/rescue-integrator-memory-1104
- origin/pr/toolchain/landed-open-wins
- origin/pr/toolchain/ci-part-wall-per-platform
- origin/pr/landed-open-wins
- origin/pr/dev-lab-names-no-account
