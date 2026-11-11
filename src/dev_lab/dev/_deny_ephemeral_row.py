"""The TRACKED-CITES-NO-EPHEMERAL door row -- pure DATA, judged only when the journal line cites an ephemeral path.

Issue #419: a line rem's ``task.js`` appends to a TRACKED journal that cites a git-ignored path is refused by the
pre-commit scan, and the journal is append-only, so the line can never be committed or repaired. This row refuses
the COMMAND before the line exists. ``when: 'cites-ephemeral'``: the engine matches the pattern as for any row, and
only then asks ``python -m dev_lab.dev.ephemeralrefs --door`` (the command on stdin, in the target checkout), which
judges the text after the verb with the scan's own :func:`dev_lab.dev.ephemeralrefs.judge`.
"""

from __future__ import annotations

__all__ = ['JOURNAL_CITES_EPHEMERAL', 'JOURNAL_VERBS']

#: rem's ``task.js`` verbs that append to a tracked journal; everything after the verb is the line.
JOURNAL_VERBS = r'\btask\.js["\']?\s+(?:log|decide|open-item|close-item|handoff)\b'

JOURNAL_CITES_EPHEMERAL: dict[str, object] = {
    'id': 'TRACKED-CITES-NO-EPHEMERAL',
    'pattern': JOURNAL_VERBS,
    'matches': 'argument',
    'when': 'cites-ephemeral',
    'hazard': 'the line lands in a tracked append-only journal, where an ignored-path cite blocks every commit '
    'and no edit may repair it.',
    'remedy': 'Re-issue the line citing a tracked source, a <placeholder> shape, or the memory entry that holds '
    'the finding -- never a path under an ignored root or scratch/.',
    'needs': None,
    'refuses': (
        'node .claude/plugins/rem/scripts/task.js log "see output/logs/26/11/11/run/a.md"',
        'node "C:/p/rem/scripts/task.js" decide "D1: per scratch/x.py"',
        'node task.js open-item "O1"',
        'node task.js close-item "O1"',
        'node task.js handoff "next"',
    ),
    'permits': (
        'node task.js show',
        'node task.js list',
        'cat task.js',
        'node task.js status --json',
    ),
}
