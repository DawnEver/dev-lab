"""RUN RECORDS on the forge -- attachments, never refs, so they can be CLEANED (forge plan, data by lifetime).

WHERE A RECORD LIVES. A run record (``run-<sha>-<part>-<req>.json.gz``, :mod:`lab_commons.hpc.records`)
is evidence every workstation must be able to read, so it goes to the forge -- but not into git: a
per-sha ref piles up and slows every ref listing (user ruling 2026-10-09), and a blob in history can
never be removed. The forge's attachment store is the one channel that is both shared and deletable.
Every record of a repository is an attachment of ONE issue, titled :data:`RECORDS_TITLE` and kept
closed so it never sits in anybody's queue; a status's ``target_url`` points at its record.

CLEANUP IS DERIVED, NOT DECLARED PER RECORD (:func:`prune`). A record is kept while its sha is still
someone's business: the tip of any ``origin`` branch (a lane, the integration branch, the trunk), or
one of the newest ``--keep-trunk`` first-parent commits of the trunk. Everything else is deleted --
a sha nobody can push or cite any more needs no evidence on the server. A compute UNIT RESULT
(:mod:`dev_lab.dev.forgeunit`) shares the home and is a cache, not evidence: only the newest
``[retention] unit_results`` of them stay (:class:`dev_lab.dev.retentionplan.Policy`, the one policy).
``forge serve`` runs the prune on its tick, at most once per :data:`PRUNE_EVERY` (:func:`serve_prune`).

ONE STORE, TWO FORGES. Gitea keeps the records as attachments of the closed :data:`RECORDS_TITLE`
issue; GitHub, which has no issue attachments, keeps them as assets of ONE prerelease tagged
:data:`RECORDS_TAG`. Both answer an asset as ``{id, name, browser_download_url}``, so :func:`listing`,
:func:`attach` and :func:`prune` read the same for either, and a caller never branches on the forge.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import re
import sys
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Final, cast

import lab_commons.launch as _door
from lab_commons.config import config_path, section
from lab_commons.hpc.allocation import RECORD as ALLOCATION
from lab_commons.log import emit

from dev_lab.dev._forge_journal import Durable, Probe
from dev_lab.dev.forge import _GIT, _GIT_TIMEOUT_S, Transport, fetch_origin, https_transport
from dev_lab.dev.forgealarm import STORAGE, Alarm
from dev_lab.dev.forgework import GITHUB, Client, ForgeCallFailed, client_for
from dev_lab.dev.lanepolicy import load_policy

__all__ = [
    'DEFAULT_KEEP_TRUNK',
    'PRUNE_EVERY',
    'RECORDS_TAG',
    'RECORDS_TITLE',
    'UNIT_RESULT',
    'Attachment',
    'attach',
    'kept_shas',
    'listing',
    'main',
    'prune',
    'read_named',
    'records_issue',
    'records_release',
    'remove_named',
    'replace_named',
    'serve_prune',
    'sha_of',
]

#: The one issue every run record of a repository is attached to.
RECORDS_TITLE: Final = 'run records'

_RECORDS_BODY: Final = (
    'Run records (`run-<sha>-<part>-<req>.json.gz`) are attached here so each `tests/<part>` '
    'status can link its evidence without a ref or a git object. Pruned by '
    '`python -m dev_lab.dev.forge records prune`; nothing else belongs on this issue.'
)

#: The tag of the one GitHub release whose assets are the run records.
RECORDS_TAG: Final = 'run-records'

#: GitHub serves release-asset uploads from its own host.
_GITHUB_UPLOADS: Final = 'uploads.github.com'

#: How often ``forge serve`` prunes the records home: the one statement of the interval.
PRUNE_EVERY: Final = timedelta(hours=6)

#: How many first-parent trunk commits keep their records by default.
DEFAULT_KEEP_TRUNK: Final = 20

_RECORD_NAME: Final = re.compile(r'^run-(?P<sha>[0-9a-f]{40})-[a-z]+-[^/]+\.json\.gz$')
#: A compute unit result (:func:`dev_lab.dev.forgeunit.result_name`), whatever archive it was posted as.
UNIT_RESULT: Final = re.compile(r'^unit-(?P<unit>[0-9a-f]{64})-(?P<result>[0-9a-f]{64})\.tar\.[a-z]+$')
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


@dataclass(frozen=True)
class _Store:
    """Where the records live on this forge: the asset collection, and the path one asset is deleted at."""

    assets: str
    delete: str
    upload_host: str | None


def records_issue(client: Client, *, create: bool) -> int | None:
    """Gitea's home: the number of the :data:`RECORDS_TITLE` issue, created (and closed) when *create* and absent."""
    query = f'state=all&type=issues&q={RECORDS_TITLE.replace(" ", "+")}&limit=50'
    found = [raw for raw in client.call('GET', f'{client.repo}/issues?{query}') if raw.get('title') == RECORDS_TITLE]
    if found:
        return min(int(raw['number']) for raw in found)
    if not create:
        return None
    number = client.issue_create(RECORDS_TITLE, _RECORDS_BODY).number
    client.issue_close(number)
    return number


def records_release(client: Client, *, create: bool) -> int | None:
    """GitHub's home: the id of the :data:`RECORDS_TAG` prerelease, created when *create* and absent."""
    listed = client.call('GET', f'{client.repo}/releases?per_page=100')
    found = [int(raw['id']) for raw in listed if raw.get('tag_name') == RECORDS_TAG]
    if found:
        return min(found)
    if not create:
        return None
    body = {'tag_name': RECORDS_TAG, 'name': RECORDS_TITLE, 'body': _RECORDS_BODY, 'prerelease': True}
    return int(client.call('POST', f'{client.repo}/releases', body)['id'])


def _store(client: Client, *, create: bool) -> _Store | None:
    if client.backend is GITHUB:
        release = records_release(client, create=create)
        if release is None:
            return None
        return _Store(f'{client.repo}/releases/{release}/assets', f'{client.repo}/releases/assets/', _GITHUB_UPLOADS)
    number = records_issue(client, create=create)
    if number is None:
        return None
    return _Store(f'{client.repo}/issues/{number}/assets', f'{client.repo}/issues/{number}/assets/', None)


def listing(client: Client) -> tuple[Attachment, ...]:
    """Every run-record asset on the forge, oldest first; none when the records home does not exist yet."""
    store = _store(client, create=False)
    if store is None:
        return ()
    raw = client.call('GET', store.assets)
    return tuple(sorted((_attachment(item) for item in raw), key=lambda item: item.id))


def attach(client: Client, path: Path) -> Attachment:
    """Upload *path* to the records home; returns the attachment (its ``url`` is the status target).

    IDEMPOTENT BY NAME, AND A RESULT'S NAME IS ITS HASH (:func:`dev_lab.dev.forgeoutbox.content_name`): an
    asset already stored under *path*'s name is returned and nothing is sent, and the write's probe finds an
    upload whose answer was lost, so one upload is never stored twice.
    """
    store = cast('_Store', _store(client, create=True))  # create=True always yields a home
    held = next((raw for raw in client.call('GET', store.assets) if raw.get('name') == path.name), None)
    if held is not None:
        return _attachment(held)
    return _upload(client, store, path.name, path.read_bytes())


def _upload(client: Client, store: _Store, name: str, content: bytes) -> Attachment:
    target = f'{store.assets}?name={name}'
    durable = Durable(probe=Probe(store.assets, {'name': name}))
    if store.upload_host is not None:
        return _attachment(client.upload_raw(store.upload_host, target, content=content, durable=durable))
    return _attachment(client.upload(target, field='attachment', filename=name, content=content, durable=durable))


def read_named(client: Client, name: str) -> bytes | None:
    """The newest file stored under *name* on the records home; ``None`` when there is none."""
    held = [item for item in listing(client) if item.name == name]
    return client.download(held[-1].url) if held else None


def read_allocation(root: Path | None = None) -> bytes | None:
    """The allocation record on *root*'s forge (default: the working directory's) -- ``None`` when there is none.

    THE READER lab-commons loads (entry point :data:`lab_commons.hpc.allocation.READER`), so every submitter --
    a person's ``python -m lab_commons.hpc submit`` and the forge's own -- reads one record; the forge writes it
    (``python -m dev_lab.dev.hpchost allocate``).
    """
    return read_named(client_for(Path.cwd() if root is None else root), ALLOCATION)


def remove_named(client: Client, name: str) -> int:
    """Delete every file stored under *name*; how many went."""
    store = _store(client, create=False)
    if store is None:
        return 0
    held = [item for item in listing(client) if item.name == name]
    for item in held:
        client.call('DELETE', f'{store.delete}{item.id}')
    return len(held)


def replace_named(client: Client, name: str, content: bytes) -> Attachment:
    """Store *content* as the ONE file named *name*: an earlier one is deleted first -- a mutable record."""
    remove_named(client, name)
    return _upload(client, cast('_Store', _store(client, create=True)), name, content)


def _git(root: Path, *args: str) -> str:
    return _door.run(
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


def prune(client: Client, keep: Collection[str], *, unit_results: int, dry_run: bool = False) -> tuple[Attachment, ...]:
    """Delete every run record whose sha is not in *keep*, and every unit result but the newest *unit_results*.

    Returns what was (or, dry, would be) deleted, oldest first. Any other file on the home is never touched.
    """
    store = _store(client, create=False)
    if store is None:
        return ()
    found = listing(client)
    units = [item for item in found if UNIT_RESULT.match(item.name)]
    stale = {item.id for item in units[: max(len(units) - unit_results, 0)]}
    doomed = tuple(
        item for item in found if item.id in stale or ((sha := sha_of(item.name)) is not None and sha not in keep)
    )
    if not dry_run:
        for item in doomed:
            client.call('DELETE', f'{store.delete}{item.id}')
    return doomed


def _budget(table: Mapping[str, Any]) -> int:
    from dev_lab.dev.retentionplan import load_policy as retention  # noqa: PLC0415 -- it imports this module

    return retention(table).unit_results


def serve_prune(
    root: Path,
    client: Client,
    *,
    now: datetime,
    say: Callable[[str], None],
    alarm: Callable[[Alarm], object],
    stamp: Path | None = None,
    table: Mapping[str, Any] | None = None,
    trunk: str | None = None,
) -> tuple[Attachment, ...]:
    """The serve tick's step: :func:`prune` once per :data:`PRUNE_EVERY`, read from the already-fetched refs.

    *stamp* holds the last prune's time (per repo beside the machine file); a failure alarms and is retried
    next interval. The unit-result budget is ``[retention] unit_results``.
    """
    repo = client.forge.repo
    stamp = config_path().parent / f'forge-records-prune-{repo.replace("/", "-")}' if stamp is None else stamp
    try:
        if now - datetime.fromisoformat(stamp.read_text(encoding='utf-8').strip()) < PRUNE_EVERY:
            return ()
    except (OSError, ValueError):
        pass  # never pruned, or an unreadable stamp: prune now
    stamp.parent.mkdir(parents=True, exist_ok=True)
    stamp.write_text(now.isoformat(), encoding='utf-8')
    try:
        keep = kept_shas(root, trunk=trunk or load_policy(root).trunk, keep_trunk=DEFAULT_KEEP_TRUNK)
        doomed = prune(client, keep, unit_results=_budget(section('retention') if table is None else table))
    except (ForgeCallFailed, OSError, ValueError) as failed:
        alarm(Alarm(STORAGE, repo, 'the records prune failed', str(failed)))
        return ()
    for item in doomed:
        say(f'[records] deleted {item.name}')
    return doomed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='dev_lab.dev.forge records', description=__doc__.splitlines()[0])
    verbs = parser.add_subparsers(dest='verb', required=True)
    listed = verbs.add_parser('list', help='every run record attached on the forge')
    listed.add_argument('--json', action='store_true', help='print the attachments as JSON')
    pruned = verbs.add_parser(
        'prune', help='delete records whose sha is no live tip and no recent trunk commit, and unit results over budget'
    )
    pruned.add_argument('--keep-trunk', type=int, default=DEFAULT_KEEP_TRUNK, help='first-parent trunk commits kept')
    pruned.add_argument('--dry-run', action='store_true', help='name what would be deleted; delete nothing')
    for verb, says in (('get', 'print it; nothing when absent'), ('put', 'replace it with stdin'), ('rm', 'delete it')):
        named = verbs.add_parser(verb, help=f'one mutable named file on the records home: {says}')
        named.add_argument('name', help='the file name, e.g. hpc-allocation.json')
    return parser


def _named(client: Client, verb: str, name: str) -> None:
    """``get|put|rm <name>``: one mutable named file -- e.g. :data:`lab_commons.hpc.allocation.RECORD`."""
    if verb == 'get':
        held = read_named(client, name)
        if held is not None:
            emit(held.decode('utf-8'))
    elif verb == 'put':
        replace_named(client, name, sys.stdin.read().encode('utf-8'))
    else:
        remove_named(client, name)


def main(
    argv: Sequence[str] | None = None,
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    transport: Transport = https_transport,
    fetch: Callable[[Path], None] = fetch_origin,
) -> int:
    """``records list|prune|get|put|rm``; exit 1 with the forge's remedy when a call fails."""
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
        if args.verb in {'get', 'put', 'rm'}:
            _named(client, args.verb, args.name)
            return 0
        fetch(root)
        keep = kept_shas(root, trunk=load_policy(root).trunk, keep_trunk=args.keep_trunk)
        doomed = prune(client, keep, unit_results=_budget(section('retention')), dry_run=args.dry_run)
    except ForgeCallFailed as failed:
        emit(f'[forge] {failed}', err=True)
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
