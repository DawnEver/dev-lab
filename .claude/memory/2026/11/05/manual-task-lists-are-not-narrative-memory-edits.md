---
name: manual-task-lists-are-not-narrative-memory-edits
description: Recognize rem's dedicated manual task-list operations without exempting manual.md or mutable narrative memory.
metadata:
  type: project
created: 2026-11-05
---

# Manual task lists are not narrative memory edits

Human authorizes autonomous owner fixes; the coordinator requested this separate follow-up to `6114144957ab8453e388fe305e651f7b5f7791ab`, without changing other lanes or publishing. Read-only consumer index inspection proved the refused change only appended MANUAL-20261105-695 and its module to the existing dedicated task list. `memoryadds.py` treated all modified memory paths as immutable narrative entries except volatile-field stripping, so the official rem operation could not commit.

Prior art is rem 2.2's `scripts/task-engine.js` handleAdd/handleRemove and `skills/todo/SKILL.md`: manual.md has dated producer frontmatter, task/check state, MANUAL ID, severity, summary/date and module; tasks append, close and reopen in place. This fix recognizes that format in both old and new content. The relative path must be dated `.claude/memory/YYYY/MM/DD/manual.md` (including a scoped prefix), with a real calendar date matching the exact frontmatter, each unique task ID and row date. No generic filename exemption exists.

Only a suffix of new tasks and checkbox changes on retained tasks are allowed. Existing task identity, full summary/severity/date, module and order remain unchanged. Both open and checked appended tasks are valid: official add followed by mark closed before committing must remain composable, rather than inventing an open-only capability restriction. Both versions must consist exclusively of the dedicated frontmatter and task/module pairs; prose cannot turn into a mutable task list. Arbitrary narrative, rewritten summaries/modules/severity, deleted/reordered tasks, duplicate IDs, mismatched dates, changed metadata and task-shaped content in another filename all remain refused. Deletion/move rules and immutable narrative rules are unchanged; sharp-review is outside this narrow correction.

TDD: original classifier produced 3 real-Git RED failures for append/close/reopen, with 37 other cases passing. Final own tooling measure `tests/test_dev_memoryadds.py` is 45/45 GREEN in 210.26 s, tree `sha256:d3a0958c1ccafca6`, log `sha256:66f065882f8c1160bdc0def5e4f1a8139f67fac7ca6cbd2e9072d35ef0fb4db5@17`. Controls cover staged and pushed changes, checked-new add/close composition, scoped/CRLF content and planted bypasses; existing narrative, merged-entry, migration and upstream-resolution tests remain. Ruff check and format pass. No root edits, credentials/config changes, solver/heavy runs or push occurred. Root owns publication and consumer adoption.
