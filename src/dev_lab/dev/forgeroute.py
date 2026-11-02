"""FAILURE ROUTING: a run record's reds, grouped by AREA, each area kept in ONE open forge issue.

An area is a source region with one long-lived issue. The repo declares its areas ONCE, as data, in
``[tool.dev_lab.areas]`` of its pyproject -- read AT THE COMMIT the record ran, like the need
vocabulary (:mod:`lab_commons.hpc.needsets`)::

    [tool.dev_lab.areas]
    default = "triage"                       # where a red no glob claims goes; absent -> "unowned"
    jmag = ["src/pkg/adapters/jmag/**", "tests/**/jmag/**"]

A test id is matched by its FILE (the part before ``::``) against the globs in declaration order; the
first area that matches owns it. ``**`` spans directories, ``*`` and ``?`` stay inside one.

THE ISSUE IS FOUND BY ITS TITLE, ``area:<name>``, among the OPEN issues, so routing the same record
twice writes nothing the second time.

WHAT A ROW MEANS, derived rather than accumulated: ``- [ ] `<id>` (<part>) <outcome>`` says "the latest
record of <part> -- the part that NOW selects <id> -- reported <id> red". A part is a need-set and every
id belongs to exactly one (:mod:`dev_lab.dev.platformparts`), and every record names the owner of
EVERY collected id: its own test cell, or its entry in ``handed`` naming the part it is handed to. So the body is a
pure function of the latest record per part, and routing a record of part P (:func:`render`):

* REPLACES P's rows with P's reds in this record -- a row of P the record no longer reports red is gone;
* keeps another part Q's row only while this record says Q still selects that id. A row keyed by a part
  no record hands anything to (a retired part or platform name), or an id another part now selects, or
  an id no longer collected, disappears -- nothing will ever run it again under that key.

There is no ticked row: a green id has no row. An area with no ``- [ ]`` row left is CLOSED by
``forge tidy`` (``green_areas``, :func:`still_red` is the one test both read); routing only writes the body.
Every open ``area:*`` issue is re-rendered on each record, so an area the record has no red in still loses
the rows it disowns.

AN INCONCLUSIVE RECORD IS ROUTED. Its part is never posted (:func:`dev_lab.dev.platformparts.part_of`),
but each id it DID report red is a real red, so it is a row. The ids that gave no answer (a RETRYABLE
cell: never reported, lost, killed) are not reds of their own: they become ONE ``no answer`` row per area, counting them
and naming the first few -- the latest record says nothing about them, and that is itself the fact. A
record covering no id is no evidence at all and routes nothing. Unowned reds land in the default area, so
a red is never dropped.

OWNERS are data too, in ``[tool.dev_lab.forge.owners]``: a key is an area name or a branch glob
(matched against the record's ``branch``), its value a list of gitea usernames. Every owner whose key
matches the area or the branch is @-mentioned in a ``cc`` line closing the body; no table, no mentions.
"""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any, Final

import lab_commons.launch as _door
from lab_commons.hpc.records import cells_of, read_record
from lab_commons.hpc.testcells import conclude
from lab_commons.log import emit

from dev_lab.dev.family import declared_table
from dev_lab.dev.forge import _GIT, _GIT_TIMEOUT_S, Transport, forge_transport
from dev_lab.dev.forgefailure import ForgeCallFailed
from dev_lab.dev.forgepulls import issues
from dev_lab.dev.forgework import Client, Issue, client_for

__all__ = [
    'DEFAULT_AREA',
    'Routed',
    'area_of',
    'covers_any',
    'find_open',
    'group',
    'main',
    'owners_of',
    'pyproject_at',
    'read_areas',
    'read_owners',
    'reconcile',
    'render',
    'route',
    'still_red',
    'title_of',
]

#: The area an unmatched red lands in when the repo names none.
DEFAULT_AREA: Final = 'unowned'
_ROW: Final = re.compile(r'^- \[( |x)\] `([^`]+)`(.*)$', re.MULTILINE)
_OPEN: Final = re.compile(r'^- \[ \] `', re.MULTILINE)
_TAG: Final = re.compile(r' \(([^)\s]+)\) ')
_NAMED: Final = 5
_REASON_CHARS: Final = 200
_USER: Final = re.compile(r'[A-Za-z0-9](?:[A-Za-z0-9._-]{0,38}[A-Za-z0-9])?\Z')


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
    raw = declared_table(tomllib.loads(text), 'areas', {})
    default = raw.get('default', DEFAULT_AREA)
    if not isinstance(default, str) or not default:
        msg = f'[tool.dev_lab.areas] default = {default!r}: the default area is a non-empty name'
        raise ValueError(msg)
    areas = []
    for name, globs in raw.items():
        if name == 'default':
            continue
        if not isinstance(globs, list) or not globs or not all(isinstance(g, str) and g for g in globs):
            msg = f'[tool.dev_lab.areas] {name} = {globs!r}: an area is a non-empty list of path globs'
            raise ValueError(msg)
        areas.append((name, tuple(_glob(g) for g in globs)))
    return tuple(areas), default


def read_owners(text: str) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """``((area or branch glob, usernames), ...)`` from pyproject *text*; a malformed name is refused."""
    raw = declared_table(tomllib.loads(text), 'forge', {}).get('owners', {})
    owners = []
    for key, names in raw.items():
        if not isinstance(names, list) or not all(isinstance(n, str) and _USER.match(n) for n in names):
            msg = (
                f'[tool.dev_lab.forge.owners] {key} = {names!r}: owners are a list of gitea usernames'
                ' (letters, digits, "._-", no leading "@") -- write e.g. ["alice", "bob.k"]'
            )
            raise ValueError(msg)
        owners.append((key, tuple(names)))
    return tuple(owners)


def owners_of(area: str, branch: str, owners: Sequence[tuple[str, Sequence[str]]]) -> tuple[str, ...]:
    """The usernames whose key matches *area* or *branch*, in declaration order, each once."""
    found = (n for key, names in owners if key == area or fnmatchcase(branch, key) for n in names)
    return tuple(dict.fromkeys(found))


def area_of(node: str, areas: Sequence[tuple[str, Sequence[re.Pattern[str]]]], default: str) -> str:
    """The first declared area whose glob matches *node*'s file, else *default*."""
    path = node.split('::', 1)[0].replace('\\', '/')
    return next((name for name, globs in areas if any(g.match(path) for g in globs)), default)


def group(
    record: Mapping[str, Any], areas: Sequence[tuple[str, Sequence[re.Pattern[str]]]], default: str
) -> dict[str, dict[str, str]]:
    """``{area: {row key: row text after the key}}`` -- *record*'s own rows; an area with none is absent.

    A reported red is one row per id; the ids that gave no answer are ONE row per area.
    """
    part = str(record['platform'])
    grouped: dict[str, dict[str, str]] = {}
    unrun: dict[str, list[str]] = {}
    for node, one in sorted(cells_of(dict(record)).items()):
        area = area_of(node, areas, default)
        if one.red:
            why = _reason(one.why)
            grouped.setdefault(area, {})[node] = f' ({part}) {one.word()}' + (f' -- {why}' if why else '')
        elif one.met is None:
            unrun.setdefault(area, []).append(node)
    for area, nodes in unrun.items():
        named = ', '.join(nodes[:_NAMED]) + (', ...' if len(nodes) > _NAMED else '')
        grouped.setdefault(area, {})[_unrun_key(part)] = f' ({part}) {len(nodes)} test(s) -- {named}'
    return grouped


def _unrun_key(part: str) -> str:
    return f'{part}: no answer'


def covers_any(record: Mapping[str, Any]) -> bool:
    """Whether *record* covers any id at all -- a record covering none is no evidence and routes nothing."""
    return bool(record['cells'])


def still_red(body: str) -> bool:
    """Whether an area body holds a ``- [ ]`` row -- the one test routing writes and ``forge tidy`` closes by."""
    return _OPEN.search(body) is not None


def title_of(area: str) -> str:
    """The title an area's issue is found by."""
    return f'area:{area}'


_AREA_TITLE: Final = re.compile(re.escape(title_of('')) + r'(\S+)\Z')


def _reason(text: str) -> str:
    first = (text or '').strip().splitlines()[0] if (text or '').strip() else ''
    return first[:_REASON_CHARS]


def render(previous: str, mine: Mapping[str, str], record: Mapping[str, Any], commit_url: str) -> str:
    """The area body after *record*: *mine* (its :func:`group` rows here) and the rows it says still stand.

    A row of another part stands only while *record* says that part selects its id (module docstring).
    """
    part, cells = str(record['platform']), cells_of(dict(record))
    owner = {**{node: str(other) for node, other in record.get('handed', {}).items()}, **dict.fromkeys(cells, part)}
    current = set(owner.values())
    rows = {}
    for mark, node, rest in _ROW.findall(previous):
        tagged = _TAG.match(rest)
        other = tagged[1] if tagged else ''
        if mark == ' ' and other and other != part:
            stands = owner.get(node) == other or (node == _unrun_key(other) and other in current)
            if stands:
                rows[node] = rest
    rows.update(mine)
    verdict = conclude(cells.values(), record.get('flaky', ())).name
    head = (
        f'Last routed: part `{part}` at [{record["sha"][:12]}]({commit_url}) (req `{record["req"]}`), {verdict}.'
        ' A row is a red of the latest record of the part that now selects it.'
    )
    lines = [f'- [ ] `{node}`{rest}' for node, rest in sorted(rows.items())]
    return '\n'.join([head, '', *lines]) + '\n'


@dataclass(frozen=True)
class Routed:
    """What routing did to one area: ``created``, ``updated``, ``closed`` or ``unchanged``."""

    area: str
    action: str
    number: int | None


def find_open(client: Client, title: str) -> Issue | None:
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
    done = _door.run(
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
    """Re-render every open area issue and every area *record* has a row in; see the module docstring.

    Nothing is closed here: an issue left with no red row is ``forge tidy``'s (``green_areas``).
    """
    if not covers_any(record):
        return ()
    areas, default = read_areas(areas_text)
    owners = read_owners(areas_text)
    forge = client.forge
    commit_url = f'https://{forge.host}/{forge.owner}/{forge.repo}/commit/{record["sha"]}'
    open_numbers: dict[str, int] = {}  # the OLDEST open issue per area title, off one listing
    for raw in issues(client, state='open'):
        if found := _AREA_TITLE.match(str(raw.get('title', ''))):
            open_numbers[found[1]] = min(raw['number'], open_numbers.get(found[1], raw['number']))
    mine = group(record, areas, default)
    done = []
    for area in sorted(mine.keys() | open_numbers.keys()):
        title = title_of(area)
        names = owners_of(area, record.get('branch', ''), owners)
        cc = '\ncc ' + ' '.join(f'@{n}' for n in names) + '\n' if names else ''
        number = open_numbers.get(area)
        if number is None:
            body = render('', mine[area], record, commit_url) + cc
            done.append(Routed(area, 'created', client.issue_create(title, body).number))
            continue
        previous = _unstamped(client.issue_view(number).body)
        body = render(previous, mine.get(area, {}), record, commit_url) + cc
        if _ROW.findall(body) != _ROW.findall(previous):
            client.issue_edit(number, body)
            done.append(Routed(area, 'updated', number))
        else:
            done.append(Routed(area, 'unchanged', number))
    return tuple(done)


def reconcile(client: Client, prefix: str, wanted: Mapping[str, str]) -> tuple[Routed, ...]:
    """ONE open issue per title in *wanted* (each starting *prefix*), its body kept current; the rest closed.

    The same found-by-title rule :func:`route` keeps an area in, so N hosts deriving the same rows write
    one issue: the first ``created``, a changed body ``updated``, an unchanged one ``unchanged``, and an
    open ``<prefix>*`` issue no row wants any more ``closed``.
    """
    done = []
    for title, body in sorted(wanted.items()):
        found = find_open(client, title)
        if found is None:
            done.append(Routed(title, 'created', client.issue_create(title, body).number))
        elif _unstamped(found.body).strip() != body.strip():
            client.issue_edit(found.number, body)
            done.append(Routed(title, 'updated', found.number))
        else:
            done.append(Routed(title, 'unchanged', found.number))
    for raw in issues(client, state='open'):
        title = raw.get('title', '')
        if title.startswith(prefix) and title not in wanted and not raw.get('pull_request'):
            client.issue_close(raw['number'])
            done.append(Routed(title, 'closed', raw['number']))
    return tuple(done)


def main(
    argv: Sequence[str] | None = None,
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    transport: Transport = forge_transport,
) -> int:
    """``python -m dev_lab.dev.forge route <record.json.gz>``; exit 1 on a forge failure, 2 on a refusal."""
    parser = argparse.ArgumentParser(prog='dev_lab.dev.forge route', description='route reds to area issues')
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
