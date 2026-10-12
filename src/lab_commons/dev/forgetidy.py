"""``forge tidy``: close the issues the collaboration loop has finished with -- CLOSE, never delete.

The repo declares what may be closed, ONCE, as data in its pyproject; absent, nothing is closed::

    [tool.lab_commons.forge.issue_hygiene]
    host_duplicates = true         # every `forge hosts` issue but the OLDEST (the one home)
    green_areas = true             # an open `area:<name>` issue with no `- [ ]` red row left
    request_max_age_days = 14      # an open request issue (`forge:request`) older than this

Each rule reads the ONE listing of every issue (:meth:`~lab_commons.dev.forgework.Client.issues`), so
a partial or failed read closes nothing. Closing is reversible; the closed numbers and the reason for
each are said in ONE comment on the hosts home issue (found by a hidden marker and edited in place,
:func:`lab_commons.dev.forgepulls.comment_upsert`), never one comment per closed issue. ``--dry-run``
prints the plan and writes nothing. The integration tick (:mod:`lab_commons.dev.forgeintegration`)
runs it after reporting on the child branches.
"""

from __future__ import annotations

import argparse
import dataclasses
import re
import sys
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Final

from lab_commons.dev.forgeclaim import forge_now
from lab_commons.dev.forgehosts import is_hosts
from lab_commons.dev.forgepulls import comment_upsert
from lab_commons.dev.forgeroute import title_of
from lab_commons.dev.forgeschedule import Schedule
from lab_commons.dev.forgework import Client, ForgeCallFailed, ListingIncomplete, client_for
from lab_commons.log import emit

__all__ = ['SUBJECT', 'Closing', 'Hygiene', 'apply', 'load_hygiene', 'main', 'plan', 'tidy']

#: The hidden-marker subject of the one summary comment.
SUBJECT: Final = 'tidy'

_OPEN_RED: Final = re.compile(r'^- \[ \] `', re.MULTILINE)
_AREA_PREFIX: Final = title_of('')


@dataclass(frozen=True)
class Hygiene:
    """What ``forge tidy`` may close; every rule is off until declared."""

    host_duplicates: bool = False
    green_areas: bool = False
    request_max_age_days: float | None = None
    request_label: str = Schedule.request_label

    @property
    def any(self) -> bool:
        """Whether any rule is on."""
        return self.host_duplicates or self.green_areas or self.request_max_age_days is not None


@dataclass(frozen=True)
class Closing:
    """One issue to close, and why."""

    number: int
    title: str
    why: str


def load_hygiene(root: Path) -> Hygiene:
    """*root*'s ``[tool.lab_commons.forge.issue_hygiene]``; an unknown key is refused by name."""
    manifest = root / 'pyproject.toml'
    if not manifest.is_file():
        return Hygiene()
    with manifest.open('rb') as handle:
        table = tomllib.load(handle).get('tool', {}).get('lab_commons', {}).get('forge', {})
    declared = table.get('issue_hygiene', {})
    known = {field.name for field in dataclasses.fields(Hygiene)}
    unknown = sorted(set(declared) - known)
    if unknown:
        where = f'[tool.lab_commons.forge.issue_hygiene] in {manifest}'
        msg = f'{where} has unknown key(s) {unknown}; the keys are {sorted(known)}'
        raise ValueError(msg)
    return Hygiene(**declared)


def _labels(raw: Mapping[str, Any]) -> set[str]:
    return {str(label['name']) for label in raw.get('labels') or ()}


def plan(issues: Sequence[Mapping[str, Any]], hygiene: Hygiene, now: datetime) -> tuple[Closing, ...]:
    """The OPEN issues *hygiene* closes, lowest number first; *issues* is the full listing in every state."""
    hosts = sorted(raw['number'] for raw in issues if is_hosts(raw))
    closing: list[Closing] = []
    for raw in sorted(issues, key=lambda raw: raw['number']):
        if raw['state'] != 'open':
            continue
        number, title, body = raw['number'], raw['title'], raw.get('body') or ''
        if hygiene.host_duplicates and is_hosts(raw) and number != hosts[0]:
            closing.append(Closing(number, title, f'duplicate host-card issue; #{hosts[0]} is the one home'))
        elif hygiene.green_areas and title.startswith(_AREA_PREFIX) and not _OPEN_RED.search(body):
            closing.append(Closing(number, title, 'area issue with no red row left'))
        elif hygiene.request_max_age_days is not None and hygiene.request_label in _labels(raw):
            age = now - datetime.fromisoformat(raw['created_at'])
            if age > timedelta(days=hygiene.request_max_age_days):
                closing.append(
                    Closing(number, title, f'request open {age.days} d, past {hygiene.request_max_age_days:g} d')
                )
    return tuple(closing)


def _summary(closed: Sequence[Closing], stamp: str) -> str:
    rows = [f'- #{one.number} `{one.title}`: {one.why}' for one in closed]
    return '\n'.join([f'**forge tidy** closed {len(closed)} issue(s) at {stamp} (reopen any to undo):', '', *rows])


def apply(client: Client, issues: Sequence[Mapping[str, Any]], closing: Sequence[Closing], stamp: str) -> str:
    """Close every *closing* issue, then say so once on the hosts home issue; the summary's action."""
    for one in closing:
        client.issue_close(one.number)
    hosts = sorted(raw['number'] for raw in issues if is_hosts(raw))
    if not closing or not hosts:
        return 'nothing to say' if not closing else 'no hosts issue to say it on'
    action, _ = comment_upsert(client, hosts[0], subject=SUBJECT, text=_summary(closing, stamp))
    return f'summary {action} on #{hosts[0]}'


def tidy(client: Client, hygiene: Hygiene, *, dry_run: bool = False) -> list[str]:
    """One pass: the plan as lines, applied unless *dry_run*; nothing is read or written with no rule on."""
    if not hygiene.any:
        return []
    issues = client.issues(state='all')
    now = forge_now(client)
    closing = plan(issues, hygiene, now)
    lines = [f'{"would close" if dry_run else "close"} #{one.number} {one.title!r}: {one.why}' for one in closing]
    if not dry_run:
        lines.append(apply(client, issues, closing, now.isoformat(timespec='seconds')))
    return lines or ['nothing to close']


def main(argv: Sequence[str] | None = None, *, cwd: Path | None = None) -> int:
    """``forge tidy [--dry-run]``: exit 1 when the forge or the declaration fails."""
    parser = argparse.ArgumentParser(prog='lab_commons.dev.forge tidy', description=__doc__.splitlines()[0])
    parser.add_argument('--dry-run', action='store_true', help='print what would be closed; write nothing')
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    root = Path.cwd() if cwd is None else cwd
    try:
        lines = tidy(client_for(root), load_hygiene(root), dry_run=args.dry_run)
    except (ForgeCallFailed, ListingIncomplete, OSError, ValueError) as failed:
        emit(f'[tidy] {failed}', err=True)
        return 1
    for line in lines or ['no issue_hygiene rule declared']:
        emit(f'[tidy] {line}')
    return 0
