"""MONTHLY-PLANS-CARRIED -- no half-done plan is lost when a month turns over.

THE DEFECT. Plans, handoffs and decision logs are dated entries under a DAY, so a reader in a new month
reaches last month's open work only by remembering it exists. A plan that nobody re-reads is a plan
that silently closed.

THE SHAPE. One entry per month sits at month depth, ``YYYY/MM/SUMMARY-YYYY-MM.md`` (the one exception
:func:`~dev_lab.dev.famtests._datedmemory_readings.is_month_summary` admits to MEMORY-SHAPE), and its
``## Plans`` section is the catalogue: one ``### <slug>`` per plan, with ``- status:`` one of
:data:`STATUSES` and ``- evidence:`` (shas, the newer plan's name). A plan is owned by the repo its file
lives in; another repo only references it.

THE CHECK IS A TREE INVARIANT, not a commit-history walk: every month at or after ``since`` that holds an
entry must carry its summary, and each summary must list every slug the PREVIOUS summary left open or
partial. Held on every tree, it refuses the first memory commit of a new month that lacks the carried
summary -- the event the rule is about -- without reading history. ``since`` is the repo's adoption
month, a keyword with no default: months before it predate the rule and carry nothing.

A CLOSE NAMES ITS EVIDENCE: ``done`` or ``superseded`` with an empty ``evidence`` is refused, in any
month, so a catalogue cannot drop an entry by relabelling it.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Final, NamedTuple

from dev_lab.dev.famtests._datedmemory_readings import DATE_DEPTH

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    'CLOSED',
    'STATUSES',
    'Plan',
    'assert_every_month_carries_its_plans',
    'assert_the_reader_still_convicts',
    'month_problems',
    'plans',
]

#: A plan leaves the catalogue only through one of these, and only with evidence.
CLOSED: Final = frozenset({'done', 'superseded'})
STATUSES: Final = CLOSED | {'partial', 'open'}

_SECTION: Final = re.compile(r'^## Plans[ \t]*$(.*?)(?=^## |\Z)', re.MULTILINE | re.DOTALL)
_ENTRY: Final = re.compile(r'^### (\S+)[ \t]*$', re.MULTILINE)
_FIELD: Final = re.compile(r'^- (status|evidence):[ \t]*(.*?)[ \t]*$', re.MULTILINE)
_DAY: Final = re.compile(r'\d{4}/\d{2}/\d{2}')


class Plan(NamedTuple):
    """One catalogue entry: its status and the evidence that closes it."""

    status: str
    evidence: str


def plans(text: str) -> tuple[dict[str, Plan], list[str]]:
    """The ``## Plans`` catalogue of one summary, and every malformed entry in it -- pure."""
    found = _SECTION.search(text)
    if found is None:
        return {}, ['carries no `## Plans` section']
    body = found.group(1)
    heads = list(_ENTRY.finditer(body))
    out: dict[str, Plan] = {}
    problems: list[str] = []
    for head, after in zip(heads, [*heads[1:], None], strict=True):
        slug = head.group(1)
        fields = dict(_FIELD.findall(body[head.end() : after.start() if after else len(body)]))
        status, evidence = fields.get('status', ''), fields.get('evidence', '')
        if status not in STATUSES:
            problems.append(f'plan {slug} has status {status!r}, not one of {sorted(STATUSES)}')
        elif status in CLOSED and not evidence:
            problems.append(f'plan {slug} is {status} without naming its evidence')
        out[slug] = Plan(status, evidence)
    return out, problems


def _months(tree: Path) -> list[str]:
    """Every ``YYYY/MM`` under *tree* that holds at least one dated markdown entry, oldest first."""
    parts = (path.relative_to(tree).parts for path in tree.glob('*/*/*/**/*.md'))
    return sorted({'/'.join(p[:2]) for p in parts if len(p) > DATE_DEPTH and _DAY.fullmatch('/'.join(p[:3]))})


def month_problems(tree: Path, *, since: str) -> list[str]:
    """Every month at or after *since* (``YYYY/MM``) missing its summary or dropping a carried plan."""
    problems: list[str] = []
    previous: tuple[str, dict[str, Plan]] | None = None
    for month in _months(tree):
        if month < since:
            continue
        year, mm = month.split('/')
        name = f'{month}/SUMMARY-{year}-{mm}.md'
        summary = tree / name
        if not summary.is_file():
            problems.append(f'{name} is missing: {month} holds entries but no plan catalogue')
            continue
        current, malformed = plans(summary.read_text(encoding='utf-8'))
        problems.extend(f'{name}: {p}' for p in malformed)
        if previous is not None:
            prior_name, prior = previous
            dropped = sorted(s for s, p in prior.items() if p.status not in CLOSED and s not in current)
            problems.extend(f'{name} drops plan {s}, still {prior[s].status} in {prior_name}' for s in dropped)
        previous = (name, current)
    return problems


def assert_every_month_carries_its_plans(tree: Path, *, since: str) -> None:
    """THE VERDICT over a repo's memory tree."""
    problems = month_problems(tree, since=since)
    if problems:
        msg = 'MONTHLY-PLANS-CARRIED refuses:\n  ' + '\n  '.join(problems)
        raise AssertionError(msg)


_HEAD: Final = '---\nname: s\ndescription: d\n---\n\n## Month\n\nx\n\n## Plans\n\n'


def assert_the_reader_still_convicts(tmp_path: Path) -> None:
    """THE PLANTED CONTROL: one clean carry and each refusal, through the real reader."""

    def plant(relative: str, body: str) -> None:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding='utf-8')

    for day in ('2026/09/01', '2026/10/01', '2026/11/01', '2026/12/01'):
        plant(f'{day}/entry.md', '---\nname: e\ndescription: d\n---\n')
    plant('2026/08/01/entry.md', '---\nname: e\ndescription: d\n---\n')  # before `since`: never read
    plant(
        '2026/09/SUMMARY-2026-09.md',
        _HEAD + '### kept\n- status: open\n\n### lost\n- status: partial\n\n'
        '### shut\n- status: done\n- evidence: abc1234\n',
    )
    plant('2026/10/SUMMARY-2026-10.md', _HEAD + '### kept\n- status: done\n\n### extra\n- status: wip\n')
    plant('2026/11/SUMMARY-2026-11.md', '---\nname: s\ndescription: d\n---\n\n## Month\n')
    problems = month_problems(tmp_path, since='2026/09')
    expected = [
        '2026/10/SUMMARY-2026-10.md: plan kept is done without naming its evidence',
        "2026/10/SUMMARY-2026-10.md: plan extra has status 'wip', not one of ['done', 'open', 'partial', 'superseded']",
        '2026/10/SUMMARY-2026-10.md drops plan lost, still partial in 2026/09/SUMMARY-2026-09.md',
        '2026/11/SUMMARY-2026-11.md: carries no `## Plans` section',
        '2026/11/SUMMARY-2026-11.md drops plan extra, still wip in 2026/10/SUMMARY-2026-10.md',
        '2026/12/SUMMARY-2026-12.md is missing: 2026/12 holds entries but no plan catalogue',
    ]
    if problems != expected:
        msg = f'the planted tree must read {len(expected)} refusals, read {problems}'
        raise AssertionError(msg)
