---
name: batched-checks-retain-string-exit-semantics-and-name-the-task-protocol
description: Resolves both nonblocking findings from the actual PR218 review with planted RED controls and 106 lightweight passing tests.
metadata:
  type: project
---
# Review findings are repaired, not hidden

PR218 review round one at 9516a0d2d069 passed with two nonblocking findings.
The first identified int(SystemExit.code) raising ValueError on a textual exit;
the second identified an unnamed external task-format protocol and an unhelpful
generic refusal. Both are actual boundary defects, irrespective of severity.

New controls measured two failures and three passes before the product fixes:
a textual exit raised ValueError, and the manual-task refusal named no protocol.
The initial verification also correctly reported test formatting/annotations;
those were corrected, not suppressed.

check_file now preserves numeric exit codes, maps None to success and prints a
textual exit to stderr with failure status, like Python's ordinary exit behavior.
Its finally block still restores argv and excepthook. A textual refusal therefore
returns to the existing ordered batch loop instead of terminating it unexpectedly.

The memory classifier names rem 2.2.0 scripts/task-engine.js handleAdd/handleMark
as the format authority. A failed dated-manual operation now names that protocol
and the supported append/checkbox remedy while retaining the immutable-memory
refusal. No classifier acceptance condition or exemption was expanded.

The final focused owner verification measured 106 passed in 136.52 seconds,
including both complete behavior files, shell-hook tests, launch-door and module
inventory checks, and the provenance declaration check. Ruff and formatting also
passed. This is a local lightweight measurement, not a substitute for the next
head's actual Linux/Windows/review/security forge results.
