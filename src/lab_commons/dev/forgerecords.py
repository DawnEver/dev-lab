"""RUN RECORDS on the forge -- attachments, never refs, so they can be CLEANED (forge plan, data by lifetime).

WHERE A RECORD LIVES. A run record (``run-<sha>-<platform>-<req>.json.gz``, :mod:`lab_commons.hpc.records`)
is evidence every workstation must be able to read, so it goes to the forge -- but not into git: a
per-sha ref piles up and slows every ref listing (user ruling 2026-10-09), and a blob in history can
never be removed. The forge's attachment store is the one channel that is both shared and deletable.
Every record of a repository is an attachment of ONE issue, titled :data:`RECORDS_TITLE` and kept
closed so it never sits in anybody's queue; a status's ``target_url`` points at its record.

CLEANUP IS DERIVED, NOT DECLARED PER RECORD (:func:`prune`). A record is kept while its sha is still
someone's business: the tip of any ``origin`` branch (a lane, the integration branch, the trunk), or
one of the newest ``--keep-trunk`` first-parent commits of the trunk. Everything else is deleted --
a sha nobody can push or cite any more needs no evidence on the server.

GITEA ONLY. The attachment API used here is Gitea's; GitHub is a read-only mirror for this family and
holds no records, so asking it is refused by name rather than sent somewhere it cannot land.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import re
import subprocess
import sys
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from lab_commons.dev.forge import _GIT, _GIT_TIMEOUT_S, Transport, fetch_origin, https_transport
from lab_commons.dev.forgework import GITHUB, Client, ForgeCallFailed, client_for
from lab_commons.dev.integrator import load_policy
from lab_commons.log import emit

__all__ = [
    'DEFAULT_KEEP_TRUNK',
    'RECORDS_TITLE',
    'Attachment',
    'attach',
    'kept_shas',
    'listing',
    'main',
    'prune',
    'records_issue',
    'sha_of',
]

#: The one issue every run record of a repository is attached to.
RECORDS_TITLE: Final = 'run records'

_RECORDS_BODY: Final = (
    'Run records (`run-<sha>-<platform>-<req>.json.gz`) are attached here so each `tests/<platform>` '
    'status can link its evidence without a ref or a git object. Pruned by '
    '`python -m lab_commons.dev.forge records prune`; nothing else belongs on this issue.'
)

#: How many first-parent trunk commits keep their records by default.
DEFAULT_KEEP_TRUNK: Final = 20

_RECORD_NAME: Final = re.compile(r'^run-(?P<sha>[0-9a-f]{40})-[a-z]+-[^/]+\.json\.gz$')
_TRACKING: Final = 'refs/remotes/origin/'


@dataclass(frozen=True)
class Attachment:
    """One attached file: its forge id, its name and where it downloads from."""

    id: int
    name: str
    url: str


def _attachment(raw: Mapping[str, Any]) -> Attachment:
    return Attachment(int(raw['id']), raw['name'], raw.get('browser_download_url') or '')


def sha_of(name: str) -> str | None:
    """The sha a record's file name carries, or ``None`` for a file that is not a run record."""
    found = _RECORD_NAME.match(name)
    return found['sha'] if found else None


def _gitea_only(client: Client) -> None:
    if client.backend is GITHUB:
        msg = 'run records live on the gitea forge; this origin is GitHub, which holds none'
        raise ValueError(msg)


def records_issue(client: Client, *, create: bool) -> int | None:
    """The number of the :data:`RECORDS_TITLE` issue, created (and closed) when *create* and absent."""
    _gitea_only(client)
    query = f'state=all&type=issues&q={RECORDS_TITLE.replace(" ", "+")}&limit=50'
    found = [raw for raw in client.call('GET', f'{client.repo}/issues?{query}') if raw.get('title') == RECORDS_TITLE]
    if found:
        return min(int(raw['number']) for raw in found)
    if not create:
        return None
    number = client.issue_create(RECORDS_TITLE, _RECORDS_BODY).number
    client.issue_close(number)
    return number


def listing(client: Client) -> tuple[Attachment, ...]:
    """Every attachment on the records issue, oldest first; none when the issue does not exist yet."""
    number = records_issue(client, create=False)
    if number is None:
        return ()
    raw = client.call('GET', f'{client.repo}/issues/{number}/assets')
    return tuple(sorted((_attachment(item) for item in raw), key=lambda item: item.id))


def attach(client: Client, path: Path) -> Attachment:
    """Upload *path* to the records issue; returns the attachment (its ``url`` is the status target).

    A retry after a lost response first looks for an attachment of the same name, so one upload is
    never stored twice.
    """
    number = records_issue(client, create=True)
    assets = f'{client.repo}/issues/{number}/assets'

    def landed() -> Any:  # noqa: ANN401 -- JSON
        return next((raw for raw in client.call('GET', assets) if raw.get('name') == path.name), None)

    raw = client.upload(
        f'{assets}?name={path.name}', field='attachment', filename=path.name, content=path.read_bytes(), landed=landed
    )
    return _attachment(raw)


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        [_GIT, '-C', str(root), *args],
        capture_output=True,
        text=True,
        encoding='utf-8',
        check=True,
        timeout=_GIT_TIMEOUT_S,
    ).stdout


def kept_shas(root: Path, *, trunk: str, keep_trunk: int) -> frozenset[str]:
    """Every ``origin`` branch tip, plus the newest *keep_trunk* first-parent commits of ``origin/<trunk>``.

    Read from the remote-tracking refs, so the caller fetches first; nothing here touches the network.
    """
    tips = _git(root, 'for-each-ref', '--format=%(objectname)', _TRACKING).split()
    trunk_ref = f'{_TRACKING}{trunk}'
    known = _git(root, 'for-each-ref', '--format=%(refname)', trunk_ref).split()
    history = _git(root, 'rev-list', '--first-parent', f'-{keep_trunk}', trunk_ref).split() if known else []
    return frozenset(tips) | frozenset(history)


def prune(client: Client, keep: Collection[str], *, dry_run: bool = False) -> tuple[Attachment, ...]:
    """Delete every run record whose sha is not in *keep*; returns what was (or, dry, would be) deleted.

    A file on the records issue that is not a run record is never touched.
    """
    number = records_issue(client, create=False)
    if number is None:
        return ()
    doomed = tuple(item for item in listing(client) if (sha := sha_of(item.name)) is not None and sha not in keep)
    if not dry_run:
        for item in doomed:
            client.call('DELETE', f'{client.repo}/issues/{number}/assets/{item.id}')
    return doomed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='lab_commons.dev.forge records', description=__doc__.splitlines()[0])
    verbs = parser.add_subparsers(dest='verb', required=True)
    listed = verbs.add_parser('list', help='every run record attached on the forge')
    listed.add_argument('--json', action='store_true', help='print the attachments as JSON')
    pruned = verbs.add_parser('prune', help='delete records whose sha is no live tip and no recent trunk commit')
    pruned.add_argument('--keep-trunk', type=int, default=DEFAULT_KEEP_TRUNK, help='first-parent trunk commits kept')
    pruned.add_argument('--dry-run', action='store_true', help='name what would be deleted; delete nothing')
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    transport: Transport = https_transport,
    fetch: Callable[[Path], None] = fetch_origin,
) -> int:
    """``records list|prune``; exit 1 with the forge's remedy when a call fails."""
    args = _parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    root = Path.cwd() if cwd is None else cwd
    client = client_for(root, env=env, transport=transport)
    try:
        if args.verb == 'list':
            found = listing(client)
            if args.json:
                emit(json.dumps([dataclasses.asdict(item) for item in found], indent=2))
            for item in () if args.json else found:
                emit(f'{item.id}  {item.name}  {item.url}')
            return 0
        fetch(root)
        keep = kept_shas(root, trunk=load_policy(root).main, keep_trunk=args.keep_trunk)
        doomed = prune(client, keep, dry_run=args.dry_run)
    except ForgeCallFailed as failed:
        emit(f'[forge] {failed.report.remedy}', err=True)
        emit(failed.report.attempts[-1].output, err=True)
        return 1
    except (OSError, ValueError) as failed:
        emit(f'[records] {failed}', err=True)
        return 1
    verb = 'would delete' if args.dry_run else 'deleted'
    for item in doomed:
        emit(f'{verb} {item.name}')
    emit(f'[records] {verb} {len(doomed)} record(s); kept every record of {len(keep)} live sha(s)')
    return 0
