"""THE BACKUP ROLE: one tar out of the forge host, unpacked and kept on the backup host, copied off-site.

* ``ops backup export`` -- the forced command of the export account on the forge host: every declared dumper
  (:data:`DUMPERS`; ``gitea`` = ``gitea dump`` as the Gitea user, ``postgresql`` = ``pg_dump -Fc`` as the database
  user) writes one file into a private work directory, an EMPTY file is refused, and ONE tar of them goes to stdout.
  ``git_mirror`` = every ``mirrors`` repository on any forge, kept as ``git clone --mirror`` in ``mirror_cache`` and
  bundled per repo (``git bundle --all``), plus its pulls, reviews, statuses and issues as JSON when
  ``mirror_metadata`` is set (:func:`metadata`). A dumper is a function returning its files, so another forge or
  database is one more entry, never a new role.
* ``ops backup pull`` -- the backup host's timer: ssh with the dedicated key to the export account, unpack into
  ``<dest>/<UTC stamp>/`` (a partial directory until every file is there and non-empty), drop stamped backups older
  than ``retention_days``, then the optional off-site copy (:mod:`dev_lab.ops.offsite`).

Any refusal or failure is alerted through ``[alerts]`` by the door (:mod:`dev_lab.ops.__main__`).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tarfile
import tempfile
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, BinaryIO, Final

import lab_commons.launch as _door

from dev_lab.dev.forge import forge_of_url
from dev_lab.dev.forgepulls import pages
from dev_lab.dev.forgework import Client
from dev_lab.dev.netverb import run_network_verb
from dev_lab.ops.config import Backup, mirror_name

__all__ = ['DUMPERS', 'STAMP', 'BackupRefused', 'Dumper', 'export', 'git_mirror', 'metadata', 'pull']

#: The UTC stamp a backup directory is named by.
STAMP: Final = '%Y%m%dT%H%M%SZ'
_STAMPED: Final = re.compile(r'^\d{8}T\d{6}Z$')
_SSH: Final = shutil.which('ssh') or 'ssh'
_RUNUSER: Final = shutil.which('runuser') or 'runuser'
_GIT: Final = shutil.which('git') or 'git'

Dumper = Callable[[Backup, Path], Sequence[Path]]
Metadata = Callable[[str, str], Mapping[str, Any]]
Fetch = Callable[[Backup, Path], None]


class BackupRefused(RuntimeError):
    """The backup was refused or failed; the message names what and why."""


def _checked(argv: list[str], **kwargs: object) -> None:
    done = _door.run(argv, check=False, timeout=6 * 3600, **kwargs)
    if done.returncode != 0:
        msg = f'{argv[0]} ... {argv[-1]} exited {done.returncode}'
        raise BackupRefused(msg)


def _gitea(role: Backup, tmp: Path) -> Sequence[Path]:
    """``gitea dump`` (repositories, data, app.ini and its SQL) as the Gitea user."""
    target = tmp / 'gitea-dump.zip'
    shutil.chown(tmp, user=role.gitea_user)
    _checked([_RUNUSER, '-u', role.gitea_user, '--', role.gitea_binary, 'dump', '-c', role.gitea_config,
              '--skip-log', '--tempdir', str(tmp), '-f', str(target)],
             cwd=role.gitea_workdir or None, stdout=subprocess.DEVNULL)  # fmt: skip
    return (target,)


def _postgresql(role: Backup, tmp: Path) -> Sequence[Path]:
    """``pg_dump -Fc`` of the declared database as the database user."""
    target = tmp / f'{role.pg_database}.pgdump'
    with target.open('wb') as out:
        _checked([_RUNUSER, '-u', role.pg_user, '--', 'pg_dump', '-Fc', role.pg_database], stdout=out)
    return (target,)


def metadata(client: Client) -> Mapping[str, Any]:
    """Every pull (with its reviews and its head's statuses) and every issue of *client*'s repository, as JSON."""
    pulls = [
        dict(pull)
        | {
            'reviews': pages(client, f'{client.repo}/pulls/{pull["number"]}/reviews', {}),
            'statuses': pages(client, f'{client.repo}/commits/{pull["head"]["sha"]}/statuses', {}),
        }
        for pull in pages(client, f'{client.repo}/pulls', {'state': 'all'})
    ]
    return {'pulls': pulls, 'issues': pages(client, f'{client.repo}/issues', {'state': 'all'})}


def _api_metadata(url: str, token: str) -> Mapping[str, Any]:
    """:func:`metadata` of *url* through the forge's API, presenting *token* (anonymous when empty)."""
    return metadata(Client(forge_of_url(url), token))


def git_mirror(*, meta: Metadata = _api_metadata) -> Dumper:
    """The ``git_mirror`` dumper; *meta* reads one repository's metadata from its URL and read token."""

    def dump(role: Backup, tmp: Path) -> Sequence[Path]:
        cache = Path(role.mirror_cache)
        cache.mkdir(parents=True, exist_ok=True)
        files: list[Path] = []
        for url in role.mirrors:
            name = mirror_name(url)
            mirror = cache / f'{name}.git'
            fetch = [_GIT, '-C', str(mirror), 'remote', 'update', '--prune']
            if not mirror.is_dir():
                fetch = [_GIT, 'clone', '--quiet', '--mirror', url, str(mirror)]
            report = run_network_verb(fetch, timeout=6 * 3600)
            if not report.ok:
                msg = f'git ... {url} exited {report.returncode}: {report.remedy}'
                raise BackupRefused(msg)
            bundle = tmp / f'{name}.bundle'
            _checked([_GIT, '-C', str(mirror), 'bundle', 'create', '--quiet', str(bundle), '--all'],
                     stdout=subprocess.DEVNULL)  # fmt: skip
            files.append(bundle)
            if role.mirror_metadata:
                token_file = role.mirror_tokens.get(name.split('_', 1)[0], '')
                token = Path(token_file).read_text(encoding='utf-8').strip() if token_file else ''
                meta_file = tmp / f'{name}.meta.json'
                meta_file.write_text(json.dumps(meta(url, token), indent=1, sort_keys=True), encoding='utf-8')
                files.append(meta_file)
        return files

    return dump


#: The dumpers a config may name in ``dumpers``.
DUMPERS: Final[Mapping[str, Dumper]] = {'gitea': _gitea, 'postgresql': _postgresql, 'git_mirror': git_mirror()}


def export(role: Backup, out: BinaryIO, *, dumpers: Mapping[str, Dumper] = DUMPERS) -> list[str]:
    """Run every declared dumper and write ONE tar of their files to *out*; returns the member names.

    Raises:
        BackupRefused: an unknown dumper, a dumper that failed, or one that left an empty file -- before any byte
            is written to *out*.

    """
    if unknown := [name for name in role.dumpers if name not in dumpers]:
        msg = f'unknown dumper(s) {unknown}; known: {sorted(dumpers)}'
        raise BackupRefused(msg)
    with tempfile.TemporaryDirectory(dir=role.tmp or None, prefix='ops-export-') as work:
        files = [path for name in role.dumpers for path in dumpers[name](role, Path(work))]
        if empty := [path.name for path in files if not path.is_file() or path.stat().st_size == 0]:
            msg = f'empty dump(s) {empty}: nothing is exported'
            raise BackupRefused(msg)
        with tarfile.open(fileobj=out, mode='w|') as archive:
            for path in files:
                archive.add(path, arcname=path.name)
    return [path.name for path in files]


def _fetch(role: Backup, target: Path) -> None:
    """The export's tar over ssh (the account's forced command ignores the command line) into *target*."""
    with target.open('wb') as out:
        _checked([_SSH, '-T', '-i', role.identity, '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
                  role.source], stdout=out)  # fmt: skip


def _retain(dest: Path, now: datetime, days: int) -> None:
    for path in dest.iterdir():
        if path.is_dir() and _STAMPED.match(path.name):
            taken = datetime.strptime(path.name, STAMP).replace(tzinfo=UTC)
            if now - taken > timedelta(days=days):
                shutil.rmtree(path)


def _unpack(role: Backup, partial: Path, fetch: Fetch) -> None:
    """Fetch the stream into *partial* and unpack it there; refuse no file or an empty one."""
    stream = partial / '.stream.tar'
    fetch(role, stream)
    with tarfile.open(stream) as archive:
        archive.extractall(partial, filter='data')
    stream.unlink()
    files = list(partial.iterdir())
    if not files or any(path.stat().st_size == 0 for path in files):
        msg = f'empty backup stream or file from {role.source}: {sorted(p.name for p in files)}'
        raise BackupRefused(msg)


def pull(role: Backup, now: datetime, *, fetch: Fetch = _fetch) -> Path:
    """Fetch, unpack and keep one backup as ``<dest>/<stamp>``, then apply retention; returns the directory.

    Raises:
        BackupRefused: the fetch failed, or the stream held no file or an empty one (nothing is kept).

    """
    dest = Path(role.dest)
    dest.mkdir(parents=True, exist_ok=True)
    stamp = now.strftime(STAMP)
    partial = dest / f'.partial-{stamp}'
    partial.mkdir()
    try:
        _unpack(role, partial, fetch)
        kept = partial.rename(dest / stamp)
    except (OSError, tarfile.TarError) as failed:
        shutil.rmtree(partial, ignore_errors=True)
        msg = f'backup pull failed: {type(failed).__name__}: {failed}'
        raise BackupRefused(msg) from failed
    except BackupRefused:
        shutil.rmtree(partial, ignore_errors=True)
        raise
    _retain(dest, now, role.retention_days)
    return kept
