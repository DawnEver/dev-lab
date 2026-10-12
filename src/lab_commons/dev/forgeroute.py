"""FAILURE ROUTING: a run record's reds, grouped by AREA, each area kept in ONE open forge issue.

An area is a source region with one long-lived issue. The repo declares its areas ONCE, as data, in
``[tool.lab_commons.areas]`` of its pyproject -- read AT THE COMMIT the record ran, like the platform
table (:mod:`lab_commons.hpc.platforms`)::

    [tool.lab_commons.areas]
    default = "triage"                       # where a red no glob claims goes; absent -> "unowned"
    jmag = ["src/pkg/adapters/jmag/**", "tests/**/jmag/**"]

A test id is matched by its FILE (the part before ``::``) against the globs in declaration order; the
first area that matches owns it. ``**`` spans directories, ``*`` and ``?`` stay inside one.

THE ISSUE IS FOUND BY ITS TITLE, ``area:<name>``, among the OPEN issues, so routing the same record
twice writes nothing the second time. Its body is the area's current list: a red id is ``- [ ]``, an id
listed earlier that THIS record ran green is ticked ``- [x]``, and an id this record did not run is left
as it was (another platform's red is not green here). When no ``- [ ]`` row remains the issue is
closed with a comment naming the sha. Unowned reds land in the default area, so a red is never dropped.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from lab_commons.dev.forge import _GIT, _GIT_TIMEOUT_S, Transport, https_transport
from lab_commons.dev.forgepulls import issues
from lab_commons.dev.forgework import Client, ForgeCallFailed, Issue, client_for
from lab_commons.hpc.records import read_record
from lab_commons.log import emit

__all__ = [
    'DEFAULT_AREA',
    'RED',
    'Routed',
    'area_of',
    'group',
    'main',
    'pyproject_at',
    'read_areas',
    'render',
    'route',
    'title_of',
]

#: The area an unmatched red lands in when the repo names none.
DEFAULT_AREA: Final = 'unowned'
#: The outcomes routed as red; everything else that ran counts as green.
RED: Final = frozenset({'failed', 'error', 'lost', 'missing'})
_GREEN: Final = frozenset({'passed', 'xfailed', 'skipped'})
_ROW: Final = re.compile(r'^- \[( |x)\] `([^`]+)`(.*)$', re.MULTILINE)
_REASON_CHARS: Final = 200


def _glob(pattern: str) -> re.Pattern[str]:
    out, index = [], 0
    while index < len(pattern):
        if pattern.startswith('**/', index):
            out.append('(?:.*/)?')
            index += 3
        elif pattern.startswith('**', index):
            out.append('.*')
            index += 2
        else:
            char = pattern[index]
            out.append({'*': '[^/]*', '?': '[^/]'}.get(char, re.escape(char)))
            index += 1
    return re.compile(''.join(out) + r'\Z')


def read_areas(text: str) -> tuple[tuple[tuple[str, tuple[re.Pattern[str], ...]], ...], str]:
    """``(((area, globs), ...), default)`` from pyproject *text*; a malformed entry is refused."""
    raw = tomllib.loads(text).get('tool', {}).get('lab_commons', {}).get('areas', {})
    default = raw.get('default', DEFAULT_AREA)
    if not isinstance(default, str) or not default:
        msg = f'[tool.lab_commons.areas] default = {default!r}: the default area is a non-empty name'
        raise ValueError(msg)
    areas = []
    for name, globs in raw.items():
        if name == 'default':
            continue
        if not isinstance(globs, list) or not globs or not all(isinstance(g, str) and g for g in globs):
            msg = f'[tool.lab_commons.areas] {name} = {globs!r}: an area is a non-empty list of path globs'
            raise ValueError(msg)
        areas.append((name, tuple(_glob(g) for g in globs)))
    return tuple(areas), default


def area_of(node: str, areas: Sequence[tuple[str, Sequence[re.Pattern[str]]]], default: str) -> str:
    """The first declared area whose glob matches *node*'s file, else *default*."""
    path = node.split('::', 1)[0].replace('\\', '/')
    return next((name for name, globs in areas if any(g.match(path) for g in globs)), default)


def group(
    outcomes: Mapping[str, str], areas: Sequence[tuple[str, Sequence[re.Pattern[str]]]], default: str
) -> dict[str, tuple[set[str], set[str]]]:
    """``{area: (red ids, green ids)}`` of one record; an area with neither is absent."""
    grouped: dict[str, tuple[set[str], set[str]]] = {}
    for node, outcome in outcomes.items():
        if outcome in RED or outcome in _GREEN:
            reds, greens = grouped.setdefault(area_of(node, areas, default), (set(), set()))
            (reds if outcome in RED else greens).add(node)
    return grouped


def title_of(area: str) -> str:
    """The title an area's issue is found by."""
    return f'area:{area}'


def _reason(text: str) -> str:
    first = (text or '').strip().splitlines()[0] if (text or '').strip() else ''
    return first[:_REASON_CHARS]


def render(
    previous: str, reds: set[str], greens: set[str], record: Mapping[str, Any], commit_url: str
) -> tuple[str, bool]:
    """The area body after *record*, and whether any red row remains open."""
    rows: dict[str, tuple[bool, str]] = {}
    for mark, node, rest in _ROW.findall(previous):
        rows[node] = (mark == 'x', rest)
    reasons = record.get('reasons', {})
    for node in greens & rows.keys():
        rows[node] = (True, rows[node][1])
    for node in reds:
        why = _reason(reasons.get(node, ''))
        rows[node] = (False, f' ({record["platform"]}) {record["outcomes"][node]}' + (f' -- {why}' if why else ''))
    head = f'Last routed: run `{record["platform"]}` at [{record["sha"][:12]}]({commit_url}) (req `{record["req"]}`).'
    lines = [f'- [{"x" if done else " "}] `{node}`{rest}' for node, (done, rest) in sorted(rows.items())]
    return '\n'.join([head, '', *lines]) + '\n', any(not done for done, _ in rows.values())


@dataclass(frozen=True)
class Routed:
    """What routing did to one area: ``created``, ``updated``, ``closed`` or ``unchanged``."""

    area: str
    action: str
    number: int | None


def _find(client: Client, title: str) -> Issue | None:
    """The OLDEST open issue titled *title*, read off the plain listing.

    A pull is one whose ``pull_request`` is SET: gitea sends ``"pull_request": null`` on every issue,
    so testing the key's presence discarded every match and each route opened a duplicate
    (#2432-#2436 beside #2427-#2431, 2026-10-11). Never ``q=`` either: gitea answers it from a search
    indexer that can lag a fresh issue. Every page is read so a duplicate never shadows the original.
    """
    numbers = [raw['number'] for raw in issues(client, state='open') if raw.get('title') == title]
    return client.issue_view(min(numbers)) if numbers else None


def pyproject_at(root: Path, sha: str) -> str:
    """*root*'s pyproject as commit *sha* holds it; an unreadable commit is refused."""
    done = subprocess.run(
        [_GIT, '-C', str(root), 'show', f'{sha}:pyproject.toml'],
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        timeout=_GIT_TIMEOUT_S,
        check=False,
    )
    if done.returncode != 0:
        msg = f'cannot read pyproject.toml at {sha} in {root}: fetch the commit the record ran ({done.stderr.strip()})'
        raise ValueError(msg)
    return done.stdout


def _unstamped(body: str) -> str:
    first, _, rest = body.partition('\n')
    return rest.lstrip('\n') if first.startswith('[') and first.endswith(']') else body


def route(client: Client, record: Mapping[str, Any], areas_text: str) -> tuple[Routed, ...]:
    """Bring every area *record* touched up to date on the forge; see the module docstring."""
    areas, default = read_areas(areas_text)
    forge = client.forge
    commit_url = f'https://{forge.host}/{forge.owner}/{forge.repo}/commit/{record["sha"]}'
    done = []
    for area, (reds, greens) in sorted(group(record['outcomes'], areas, default).items()):
        title = title_of(area)
        found = _find(client, title)
        if found is None:
            if reds:
                body, _ = render('', reds, greens, record, commit_url)
                done.append(Routed(area, 'created', client.issue_create(title, body).number))
            continue
        previous = _unstamped(found.body)
        body, still_red = render(previous, reds, greens, record, commit_url)
        if not still_red:
            client.issue_edit(found.number, body)
            client.issue_comment(found.number, f'green at {record["sha"]} on `{record["platform"]}`: closing')
            client.issue_close(found.number)
            done.append(Routed(area, 'closed', found.number))
        elif _ROW.findall(body) != _ROW.findall(previous):
            client.issue_edit(found.number, body)
            done.append(Routed(area, 'updated', found.number))
        else:
            done.append(Routed(area, 'unchanged', found.number))
    return tuple(done)


def main(
    argv: Sequence[str] | None = None,
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    transport: Transport = https_transport,
) -> int:
    """``python -m lab_commons.dev.forge route <record.json.gz>``; exit 1 on a forge failure, 2 on a refusal."""
    parser = argparse.ArgumentParser(prog='lab_commons.dev.forge route', description='route reds to area issues')
    parser.add_argument('record', type=Path)
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    root = Path.cwd() if cwd is None else cwd
    record = read_record(args.record)
    try:
        areas_text = pyproject_at(root, record['sha'])
        routed = route(client_for(root, env=env, transport=transport), record, areas_text)
    except ForgeCallFailed as failed:
        emit(f'[forge] {failed}', err=True)
        emit(failed.report.attempts[-1].output, err=True)
        return 1
    except ValueError as exc:
        emit(f'[forge] {exc}', err=True)
        return 2
    for one in routed:
        emit(f'{title_of(one.area)} {one.action}' + (f' #{one.number}' if one.number else ''))
    return 0
