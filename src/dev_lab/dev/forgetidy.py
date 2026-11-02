"""``forge tidy``: remove the issues and machine comments the collaboration loop has finished with.

EVERY RULE IS ON, in every repo the forge serves (user ruling 2026-10-15: issues must never rot); a repo
only TUNES them, once, as data in its pyproject -- absent, the defaults below apply::

    [tool.dev_lab.forge.issue_hygiene]
    host_duplicates = true         # DELETE every machine-made `forge hosts` issue but the OLDEST (the one home)
    green_areas = true             # close an open `area:<name>` issue with no `- [ ]` red row left
    request_max_age_days = 14      # close an open request issue (`forge:request`) older than this
    work_max_idle_days = 14        # close an open WORK issue not updated for longer than this

A WORK issue is one no machinery keeps: not a hosts issue, not an ``area:`` issue, not a request, not an
alarm kept as an issue (``<kind>: ...``, :data:`dev_lab.dev.forgealarm.ISSUE_KINDS`), and carrying no
hidden marker. A comment, a claim or an edit updates it, so only an issue nobody touched goes.

A RETIRED MARKER IS ALWAYS DELETED, with no knob: a comment on an open issue carrying a hidden marker whose
kind no :class:`~dev_lab.dev.forgepulls.Marker` member names was written by a writer that no longer
exists, and nothing else will ever update or remove it.

Each rule reads the ONE listing of every issue (:func:`dev_lab.dev.forgepulls.issues`), so
a partial or failed read removes nothing. A hosts duplicate is useless, so it is DELETED (user ruling
2026-10-13) -- but only one :mod:`~dev_lab.dev.forgehosts` opened (its marker or its origin text in
the body), never one a human wrote under that title; a token without delete rights closes it instead and
says so. Every other issue is only ever CLOSED, and a closed issue reopens to undo. The numbers, the outcome
and the reason for each are said in ONE comment on the hosts home issue (found by a hidden marker and edited
in place, :func:`dev_lab.dev.forgepulls.comment_upsert`), never one comment per closed issue.
``--dry-run`` prints the plan and writes nothing. ``forge serve`` runs it on every host every tick
(:mod:`dev_lab.dev.forgeserve`): a pass is idempotent, so no host owns it.
"""

from __future__ import annotations

import argparse
import dataclasses
import sys
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Final

from lab_commons.compute.model import Schedule
from lab_commons.log import emit

from dev_lab.dev.family import declared_table
from dev_lab.dev.forgealarm import ISSUE_KINDS
from dev_lab.dev.forgeclaim import forge_now
from dev_lab.dev.forgefailure import ForgeCallFailed
from dev_lab.dev.forgehosts import HOSTS_MARKER, HOSTS_ORIGIN, is_hosts
from dev_lab.dev.forgepulls import ListingIncomplete, Marker, comment_list, comment_upsert, forget_issue, marker_kinds
from dev_lab.dev.forgepulls import issues as list_issues
from dev_lab.dev.forgeroute import still_red, title_of
from dev_lab.dev.forgework import Client, Comment, client_for

__all__ = ['Closing', 'Hygiene', 'apply', 'load_hygiene', 'main', 'plan', 'retired_markers', 'tidy']

_AREA_PREFIX: Final = title_of('')
_MACHINE_PREFIXES: Final = (_AREA_PREFIX, *(f'{kind}: ' for kind in ISSUE_KINDS))
_LIVE_KINDS: Final = frozenset(str(kind) for kind in Marker)


@dataclass(frozen=True)
class Hygiene:
    """What ``forge tidy`` removes; every rule is on, a repo only tunes it."""

    host_duplicates: bool = True
    green_areas: bool = True
    request_max_age_days: float = 14
    work_max_idle_days: float = 14
    request_label: str = Schedule.request_label


@dataclass(frozen=True)
class Closing:
    """One issue to close or delete -- or, with *comment*, one comment on it to delete -- and why."""

    number: int
    title: str
    why: str
    delete: bool = False
    comment: int | None = None

    @property
    def verb(self) -> str:
        """``delete comment <id> on``, ``delete`` or ``close``."""
        if self.comment is not None:
            return f'delete comment {self.comment} on'
        return 'delete' if self.delete else 'close'


def load_hygiene(root: Path) -> Hygiene:
    """*root*'s ``[tool.dev_lab.forge.issue_hygiene]`` over the defaults; an unknown key is refused by name."""
    manifest = root / 'pyproject.toml'
    if not manifest.is_file():
        return Hygiene()
    with manifest.open('rb') as handle:
        table = declared_table(tomllib.load(handle), 'forge', {})
    declared = table.get('issue_hygiene', {})
    known = {field.name for field in dataclasses.fields(Hygiene)}
    unknown = sorted(set(declared) - known)
    if unknown:
        where = f'[tool.dev_lab.forge.issue_hygiene] in {manifest}'
        msg = f'{where} has unknown key(s) {unknown}; the keys are {sorted(known)}'
        raise ValueError(msg)
    return Hygiene(**declared)


def _labels(raw: Mapping[str, Any]) -> set[str]:
    return {str(label['name']) for label in raw.get('labels') or ()}


def _machine_hosts(raw: Mapping[str, Any]) -> bool:
    """A hosts issue :mod:`~dev_lab.dev.forgehosts` opened -- never one a human wrote under that title."""
    body = raw.get('body') or ''
    return is_hosts(raw) and (HOSTS_MARKER in body or HOSTS_ORIGIN in body)


def _work(raw: Mapping[str, Any], hygiene: Hygiene) -> bool:
    """Whether *raw* is a work issue: one no machinery keeps (module docstring)."""
    kept = is_hosts(raw) or raw['title'].startswith(_MACHINE_PREFIXES) or hygiene.request_label in _labels(raw)
    return not kept and not marker_kinds(raw.get('body') or '')


def retired_markers(number: int, title: str, comments: Sequence[Comment]) -> list[Closing]:
    """A comment deletion for each of *comments* carrying a marker kind no :class:`Marker` member names."""
    found = []
    for comment in comments:
        retired = sorted(set(marker_kinds(comment.body)) - _LIVE_KINDS)
        if retired:
            why = f'machine comment of retired marker kind {", ".join(retired)}'
            found.append(Closing(number, title, why, comment=comment.id))
    return found


def plan(
    issues: Sequence[Mapping[str, Any]],
    hygiene: Hygiene,
    now: datetime,
    comments: Mapping[int, Sequence[Comment]] | None = None,
) -> tuple[Closing, ...]:
    """What *hygiene* removes, lowest number first; *issues* is the full listing in every state.

    *comments* are the open issues' comments, by number. A machine-made hosts duplicate is DELETED, open
    or closed (user ruling 2026-10-13: useless issues go outright); a retired-marker comment is DELETED;
    every other issue is only ever closed, and only while open.
    """
    comments = comments or {}
    hosts = sorted(raw['number'] for raw in issues if is_hosts(raw))
    closing: list[Closing] = []
    for raw in sorted(issues, key=lambda raw: raw['number']):
        number, title, body = raw['number'], raw['title'], raw.get('body') or ''
        if hygiene.host_duplicates and _machine_hosts(raw) and number != hosts[0]:
            closing.append(
                Closing(number, title, f'duplicate host-card issue; #{hosts[0]} is the one home', delete=True)
            )
            continue
        if raw['state'] != 'open':
            continue
        closing += retired_markers(number, title, comments.get(number, ()))
        age = now - datetime.fromisoformat(raw['created_at'])
        idle = now - datetime.fromisoformat(raw.get('updated_at') or raw['created_at'])
        if hygiene.green_areas and title.startswith(_AREA_PREFIX) and not still_red(body):
            closing.append(Closing(number, title, 'area issue with no red row left'))
        elif hygiene.request_label in _labels(raw) and age > timedelta(days=hygiene.request_max_age_days):
            closing.append(
                Closing(number, title, f'request open {age.days} d, past {hygiene.request_max_age_days:g} d')
            )
        elif _work(raw, hygiene) and idle > timedelta(days=hygiene.work_max_idle_days):
            closing.append(
                Closing(number, title, f'work issue idle {idle.days} d, past {hygiene.work_max_idle_days:g} d')
            )
    return tuple(closing)


def _remove(client: Client, one: Closing, state: str) -> str:
    """Delete or close *one*; a delete the forge refuses (no admin right) falls back to closing, said."""
    if one.comment is not None:
        client.call('DELETE', f'{client.repo}/issues/comments/{one.comment}')
        return 'comment deleted'
    if one.delete:
        try:
            client.call('DELETE', f'{client.repo}/issues/{one.number}')  # gitea: repository admin rights
        except ForgeCallFailed as refused:
            if not refused.report.attempts or refused.report.attempts[-1].retryable:
                raise
            if state == 'open':
                client.issue_close(one.number)
            return f'delete refused ({refused.report.attempts[-1].returncode}), closed instead'
        forget_issue(client, one.number)
        return 'deleted'
    client.issue_close(one.number)
    return 'closed'


def apply(client: Client, issues: Sequence[Mapping[str, Any]], closing: Sequence[Closing], stamp: str) -> list[str]:
    """Remove every *closing* issue or comment, then say so once on the hosts home issue; one line per outcome."""
    states = {raw['number']: raw['state'] for raw in issues}
    done = [(one, _remove(client, one, states[one.number])) for one in closing]
    rows = [f'- #{one.number} `{one.title}`: {outcome} -- {one.why}' for one, outcome in done]
    lines = [f'#{one.number}: {outcome}' for one, outcome in done]
    hosts = sorted(raw['number'] for raw in issues if is_hosts(raw))
    if not hosts:
        return [*lines, 'no hosts issue to say it on']
    text = '\n'.join([f'**forge tidy** at {stamp} (a closed issue reopens to undo):', '', *rows])
    action, _ = comment_upsert(client, hosts[0], kind=Marker.TIDY, text=text)
    return [*lines, f'summary {action} on #{hosts[0]}']


def tidy(client: Client, hygiene: Hygiene, *, dry_run: bool = False) -> list[str]:
    """One pass: the plan as lines, applied unless *dry_run*."""
    issues = list_issues(client, state='all')
    now = forge_now(client)
    commented = [raw['number'] for raw in issues if raw['state'] == 'open' and raw.get('comments')]
    closing = plan(issues, hygiene, now, {number: comment_list(client, number) for number in commented})
    lines = [f'{"would " if dry_run else ""}{one.verb} #{one.number} {one.title!r}: {one.why}' for one in closing]
    if closing and not dry_run:
        lines += apply(client, issues, closing, now.isoformat(timespec='seconds'))
    return lines or ['nothing to close']


def main(argv: Sequence[str] | None = None, *, cwd: Path | None = None) -> int:
    """``forge tidy [--dry-run]``: exit 1 when the forge or the declaration fails."""
    parser = argparse.ArgumentParser(prog='dev_lab.dev.forge tidy', description=__doc__.splitlines()[0])
    parser.add_argument('--dry-run', action='store_true', help='print what would be removed; write nothing')
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    root = Path.cwd() if cwd is None else cwd
    try:
        lines = tidy(client_for(root), load_hygiene(root), dry_run=args.dry_run)
    except (ForgeCallFailed, ListingIncomplete, OSError, ValueError) as failed:
        emit(f'[tidy] {failed}', err=True)
        return 1
    for line in lines:
        emit(f'[tidy] {line}')
    return 0
