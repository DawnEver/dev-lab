"""The TRACKED-CITES-NO-EPHEMERAL deny row -- pure DATA, its pattern a prefilter and its judge a Python module.

THE INCIDENT, dev-lab#419: a task-journal append through rem's door (``task.js log``) cited a git-ignored path; the
commit-time check then refused a line the append-only journal forbade repairing. So the call is judged BEFORE it
appends. Whether a cited path is ignored is the repo's own answer (``git check-ignore``, the tracked set, the
declared stray roots), which no regex reads: ``asks`` hands the decision to :mod:`dev_lab.dev.journaldoor` only
after this pattern matched, so the common shell call spawns no interpreter. The verbs are declared here, once.
"""

from __future__ import annotations

from typing import Final

#: rem's journal verbs: the ones whose words ``task.js`` appends to ``JOURNAL.md`` (rem ``scripts/task.js``).
JOURNAL_VERBS: Final = frozenset({'log', 'decide', 'open-item', 'close-item', 'handoff'})

#: The one remedy, printed verbatim by the judge after its cites: the agent's last chance to change the line. The
#: exit is a rephrase, not a command, so the row declares it ``No door:`` (the shape every deny row discloses).
REMEDY: Final = (
    'rephrase the text before it is appended: cite a memory entry by name or the path as a <placeholder> shape '
    '(output/logs/<yy>/<mm>/<dd>/<kind>/) -- a written journal line is append-only, so this is the last point '
    'the agent can still change it'
)

_VERBS = '|'.join(sorted(JOURNAL_VERBS))

JOURNAL_CITES: dict[str, object] = {
    'id': 'TRACKED-CITES-NO-EPHEMERAL',
    # A superset of what the judge appends: rem's door followed by a journal verb, quoted or not, anywhere on the
    # executed line (a `bash -c` script or an interpreter's heredoc included; a sink's heredoc body is data).
    'pattern': rf'task\.js["\']?\s+["\']?(?:{_VERBS})(?![\w-])',
    'matches': 'line',
    'asks': 'dev_lab.dev.journaldoor',
    'hazard': 'a task journal line is append-only: a cite of an ignored path written now is refused at commit and '
    'never repairable.',
    'remedy': f'No door: {REMEDY}.',
    'needs': None,
    'refuses': (
        'node scripts/task.js log "swept output/logs/x.log" --task t',
        'node "scripts/task.js" decide --task t "use A" "over B"',
        "node rem/task.js 'open-item' --task t 'read output/x'",
        'cd x && node task.js close-item --task t "done" ; echo y',
        'node task.js handoff --task t "see output/x"',
    ),
    'permits': (
        'node scripts/task.js list --task t',
        'node scripts/task.js open --task t',
        'node scripts/task.js logs --task t',
        'git commit -m "task.js list output/x"',
        'node mytask.jsx log "output/x"',
    ),
}
