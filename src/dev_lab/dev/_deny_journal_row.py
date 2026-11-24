"""The TRACKED-CITES-NO-EPHEMERAL deny row -- pure DATA, its pattern a prefilter and its judge a Python module.

THE INCIDENT, dev-lab#419: a task-journal append through the journal's door (then rem's, now
``python -m dev_lab.dev.task log``) cited a git-ignored path; the commit-time check then refused a line the
append-only journal forbade repairing. So the call is judged BEFORE it appends. Whether a cited path is ignored is
the repo's own answer (``git check-ignore``, the tracked set, the declared stray roots), which no regex reads:
``asks`` hands the decision to :mod:`dev_lab.dev.journaldoor` only after this pattern matched, so the common shell
call spawns no interpreter. The verbs are declared here, once.
"""

from __future__ import annotations

from typing import Final

#: The journal verbs: the ones whose words the task door (:mod:`dev_lab.dev.task`) appends to ``JOURNAL.md``.
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
    # A superset of what the judge appends: the task door followed by a journal verb, quoted or not, anywhere on the
    # executed line (a `bash -c` script or an interpreter's heredoc included; a sink's heredoc body is data).
    'pattern': rf'dev_lab\.dev\.task["\']?\s+["\']?(?:{_VERBS})(?![\w-])',
    'matches': 'line',
    'asks': 'dev_lab.dev.journaldoor',
    'hazard': 'a task journal line is append-only: a cite of an ignored path written now is refused at commit and '
    'never repairable.',
    'remedy': f'No door: {REMEDY}.',
    'needs': None,
    'refuses': (
        'python -m dev_lab.dev.task log "swept output/logs/x.log" --task t',
        'python -m "dev_lab.dev.task" decide --task t "use A over B"',
        "python -m dev_lab.dev.task 'open-item' --task t 'read output/x'",
        'cd x && python -m dev_lab.dev.task close-item O1 "done" ; echo y',
        'python -m dev_lab.dev.task handoff --task t "see output/x"',
    ),
    'permits': (
        'python -m dev_lab.dev.task list',
        'python -m dev_lab.dev.task open t "goal"',
        'python -m dev_lab.dev.task logs --task t',
        'git commit -m "dev_lab.dev.task list output/x"',
        'python -m dev_lab.dev.taskledger log "output/x"',
    ),
}
