---
name: a-doors-exit-status-is-read-before-the-next-step
description: Toolchain lessons of 2026-11-13 -- a piped door hid its failure, a text pipe broke a credential line, and four doors refused or skipped where they should not (#494, #496).
metadata:
  type: project
---

# A door's exit status is read before the next step (2026-11-13)

Six toolchain lessons from one recovery day. No hosts, accounts or secrets here.

| # | what happened | the lesson / the fix |
|---|---|---|
| 1 | A door's output piped through `\| tail` reported the tail's exit status, so a failed door read as success -- three times in one day, each followed by a dependent step that ran on nothing. | Read the door's OWN status before any dependent step: `set -o pipefail`, or `${PIPESTATUS[0]}`, or no pipe. |
| 2 | On Windows a text-mode subprocess pipe turned a staged credential line's LF into CRLF; git's credential store then matched no host and every network verb was refused. | Credential lines cross a pipe as BYTES: `devcredential.local_shell` sends bytes (#494). |
| 3 | `pr ready` was refused by a dirty-tree check, though marking a PR ready is a forge API call that reads no working tree. | A check guards only the step it protects (#496). |
| 4 | Whole-tree commit hooks ran on a merge commit: they refused debt the upstream side brought in and rewrote upstream files. | A merge commit's hooks judge the merge, not upstream's tree (#496). |
| 5 | `planrun` resumed a plan by its digest alone and skipped a re-mint the changed inputs required. | Resume keys on everything the step reads, not the plan digest only (#496). |
| 6 | Two delete guards contradicted each other for an approved worktree: one demanded the discard the other refused. | `branchset --discard` is the one approved path; the guards agree (#496). |

Follow-up the same day: the callers of the forgemerge split (#493) gained planted controls -- the wave sweep
reads its waits from `forgemergewaits` (`tests/test_ops_wave_sweep.py`).
