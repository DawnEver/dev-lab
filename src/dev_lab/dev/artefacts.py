"""THE ARTEFACT STORE -- a run's DECLARED outputs, packed once and kept behind the record's manifest.

NOTHING TRAVELS BY DEFAULT (user rulings 2026-10-11). A request declares ``outputs = [...]`` -- globs or
named files relative to the run's work tree; only those are packed (:func:`collect`, :func:`pack`), a
declared output that matched nothing fails the run loudly (:class:`MissingOutput`), and an undeclared
file is never uploaded. The verdict itself still travels as the run record.

ONE INTERFACE, THREE BACKENDS (:class:`ArtefactStore`): ``put(run_id, path) -> Ref``, ``get(ref, dest)``,
``list(older_than)``, ``delete(ref)``. ``forge`` keeps an archive as a records-home attachment
(<= :data:`ATTACHMENT_LIMIT_MB`); ``rclone`` any rclone remote, by shelling out with argv lists;
``folder`` a local path. A :class:`Ref` IS the manifest entry the record carries --
``{backend, ref, bytes, sha256}`` -- and :meth:`get` refuses bytes whose sha256 differs.

CONFIG IS DATA. The writer side is the repo's ``[tool.lab_commons.artefacts]`` (:class:`Config`): an
archive at or under ``threshold_mb`` goes to the forge, a larger one to ``backend``/``remote``. The
reader side maps the same store to a local path in the MACHINE config (``[artefacts] folder``,
:func:`reader`) -- a synced mirror of the remote, read, never written.

CLOUD-DRIVE-SHAPED LAYOUT. ``<repo>/<yyyy>/<mm>/<dd>/<run-id>.tar.gz`` plus ``<run-id>.manifest.json``,
``run-id = <sha12>-<platform>-<account>-<utcstamp>``: one archive per run (a synced drive pays per FILE),
short ASCII names checked against OneDrive's forbidden characters, trailing dot/space and its path limit
(:func:`check_key`). WRITE-ONCE: an object is never rewritten -- a different object under an existing
key is refused; the same bytes again is the object already landed (a resumed tick), not a write.

ONE SHARED LIBRARY, MANY WRITERS (user ruling 2026-10-13). Several cluster accounts, each with its own
rclone identity, write the same store; ``<account>`` in the run id is the cluster account that wrote it
(the claim owner's). EACH WRITER CLEANS ONLY ITS OWN (:func:`clean`): of the runs carrying its account,
whole runs in day folders older than ``retain_days`` go, unless a ``keep`` label on an issue or pull
request pins their sha (:func:`pinned`); then its oldest first until its own share is under ``cap_gb``;
emptied folders are removed. A writer whose remote is unusable says so (:func:`remote_problem`) and
claims no part whose declared outputs could need it.

CREDENTIALS. The rclone config is never in a repo, never logged, and must be mode 600
(:func:`check_rclone_config`); no argv here carries a secret.
"""

from __future__ import annotations

import dataclasses
import json
import os
import re
import shutil
import tarfile
import tomllib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Final

from lab_commons.config import config_path, section
from dev_lab.dev.artefactstores import (
    ARCHIVE,
    ATTACHMENT_LIMIT_MB,
    FOLDER,
    FORGE,
    MANIFEST,
    MB,
    RCLONE,
    ArtefactRefused,
    ArtefactStore,
    ForgeStore,
    MissingOutput,
    RcloneStore,
    Ref,
    check_key,
    check_rclone_config,
    landed_already,
    object_key,
    parsed_run_id,
    ref_of,
    run_id,
    run_time,
    scratch_dir,
    sorted_refs,
    verified_copy,
)
from dev_lab.dev.forgepulls import pages, pulls_off
from dev_lab.dev.forgework import Client, ForgeCallFailed, is_pull, pull_of
from lab_commons.hpc.rclone import probe

__all__ = [
    'ARCHIVE',
    'ATTACHMENT_LIMIT_MB',
    'FOLDER',
    'FORGE',
    'MANIFEST',
    'RCLONE',
    'ArtefactRefused',
    'ArtefactStore',
    'Config',
    'FolderStore',
    'ForgeStore',
    'MissingOutput',
    'RcloneStore',
    'Ref',
    'check_key',
    'check_rclone_config',
    'clean',
    'collect',
    'large_store',
    'load_config',
    'object_key',
    'pack',
    'pinned',
    'reader',
    'remote_problem',
    'resolve',
    'run_id',
    'store_for',
    'unpack',
]

_BACKENDS: Final = (FORGE, RCLONE, FOLDER)
_SHA_TOKEN: Final = re.compile(r'\b[0-9a-f]{12,40}\b')
_TABLE: Final = 'tool.lab_commons.artefacts'


def collect(tree: Path, outputs: Sequence[str]) -> list[Path]:
    """The files *outputs* name under *tree*, sorted; every declaration must match at least one file."""
    found: set[Path] = set()
    missing = []
    for pattern in outputs:
        pure = PurePosixPath(pattern)
        if pure.is_absolute() or '..' in pure.parts or ':' in pattern or '\\' in pattern:
            msg = f'declared output {pattern!r} must be a relative path or glob inside the work tree'
            raise ArtefactRefused(msg)
        matched = [path for path in tree.glob(pattern) if path.is_file()]
        if not matched:
            missing.append(pattern)
        found.update(matched)
    if missing:
        msg = f'{", ".join(missing)} matched nothing in {tree}'  # names first: a status description is short
        raise MissingOutput(msg)
    return sorted(found)


def pack(tree: Path, files: Sequence[Path], dest: Path) -> Path:
    """One gzip tar of *files* (named relative to *tree*) at *dest* -- stdlib only, so no host needs a tool."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(dest, mode='w:gz') as tar:
        for path in files:
            tar.add(path, arcname=path.relative_to(tree).as_posix(), recursive=False)
    return dest


def unpack(archive: Path, dest: Path) -> Path:
    """The inverse of :func:`pack`: every member of *archive* under *dest* (a member leaving it is refused)."""
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, mode='r:gz') as tar:
        tar.extractall(dest, filter='data')
    return dest


@dataclass(frozen=True)
class FolderStore:
    """A local directory; *root* holds ``<repo>/...`` exactly as the remote does (a reader's synced mirror)."""

    root: Path
    repo: str
    backend: str = FOLDER

    def _stored(self, key: str) -> Ref | None:
        manifest = self.root / key.removesuffix(ARCHIVE)
        path = manifest.with_name(manifest.name + MANIFEST)
        return Ref.of(json.loads(path.read_text(encoding='utf-8'))) if path.is_file() else None

    def put(self, ident: str, path: Path) -> Ref:
        """Write-once: an existing key with other content is refused (module docstring)."""
        base = object_key(self.repo, ident)
        new = ref_of(self.backend, base + ARCHIVE, path)
        check_key(base + MANIFEST)
        landed = landed_already(self._stored(new.key), new)
        if landed is not None:
            return landed
        target = self.root / new.key
        target.parent.mkdir(parents=True, exist_ok=True)
        for name, write in ((target, lambda dst: shutil.copyfile(path, dst)),
                            (target.with_name(ident + MANIFEST),
                             lambda dst: dst.write_text(json.dumps(new.manifest()), encoding='utf-8'))):  # fmt: skip
            partial = name.with_name(name.name + '.partial')
            write(partial)
            try:
                os.link(partial, name)  # fails rather than overwrite
            finally:
                partial.unlink()
        return new

    def get(self, ref: Ref, dest: Path) -> Path:
        """Copy out and verify."""
        scratch = scratch_dir()
        try:
            fetched = scratch / 'fetched'
            shutil.copyfile(self.root / ref.key, fetched)
            return verified_copy(ref, fetched, dest)
        finally:
            shutil.rmtree(scratch, ignore_errors=True)

    def list(self, older_than: datetime | None) -> tuple[Ref, ...]:
        """Every manifest under ``<root>/<repo>``."""
        base = self.root / self.repo
        found = [Ref.of(json.loads(p.read_text(encoding='utf-8'))) for p in base.rglob(f'*{MANIFEST}')]
        return sorted_refs(found if base.is_dir() else [], older_than)

    def delete(self, ref: Ref) -> None:
        """Delete both objects, then each emptied parent up to the repo folder."""
        archive = self.root / ref.key
        archive.with_name(ref.run_id + MANIFEST).unlink(missing_ok=True)
        archive.unlink(missing_ok=True)
        top = self.root / self.repo
        parent = archive.parent
        while parent != top and top in parent.parents and not any(parent.iterdir()):
            parent.rmdir()
            parent = parent.parent


# --- rclone ---------------------------------------------------------------------------------------


# --- config, selection, reading -------------------------------------------------------------------


@dataclass(frozen=True)
class Config:
    """``[tool.lab_commons.artefacts]``: where archives above *threshold_mb* go, and how long they stay."""

    backend: str = FORGE
    remote: str = ''
    threshold_mb: int = ATTACHMENT_LIMIT_MB
    retain_days: int = 3
    cap_gb: float = 0.0  # 0: no cap

    @property
    def cap_bytes(self) -> int:
        """The cap in bytes; 0 when uncapped."""
        return int(self.cap_gb * 1024 * MB)


def load_config(root: Path) -> Config:
    """The repo's table, validated; no table is :class:`Config` (forge only)."""
    pyproject = root / 'pyproject.toml'
    raw = tomllib.loads(pyproject.read_text(encoding='utf-8')) if pyproject.is_file() else {}
    table = raw.get('tool', {}).get('lab_commons', {}).get('artefacts', {})
    known = {field.name for field in dataclasses.fields(Config)}
    problems = [f'unknown key {key!r}' for key in sorted(set(table) - known)]
    try:
        config = Config(**{key: value for key, value in table.items() if key in known})
    except TypeError as bad:
        problems.append(str(bad))
        config = Config()
    if config.backend not in _BACKENDS:
        problems.append(f'backend = {config.backend!r} is not one of {_BACKENDS}')
    if config.backend != FORGE and not config.remote:
        problems.append(f'backend = "{config.backend}" needs remote = "<rclone remote:path or folder>"')
    if not 0 < config.threshold_mb <= ATTACHMENT_LIMIT_MB:
        problems.append(f'threshold_mb must be in (0, {ATTACHMENT_LIMIT_MB}] (the forge attachment limit)')
    if config.retain_days < 1 or config.cap_gb < 0:
        problems.append('retain_days must be >= 1 and cap_gb >= 0')
    if problems:
        msg = f'{pyproject} [{_TABLE}]: {"; ".join(problems)}'
        raise ArtefactRefused(msg)
    return config


def large_store(config: Config, repo: str) -> ArtefactStore | None:
    """The configured backend for archives over the threshold; ``None`` when the forge is the only one."""
    if config.backend == RCLONE:
        return RcloneStore(config.remote, repo)
    if config.backend == FOLDER:
        return FolderStore(Path(config.remote).expanduser(), repo)
    return None


def remote_problem(root: Path, *, rclone: Sequence[str] = ('rclone',)) -> str:
    """Why this host cannot write the repo's rclone store, ``''`` when it can or none is configured.

    A cheap READ-ONLY probe of the remote's root (:func:`lab_commons.hpc.rclone.probe`).
    """
    try:
        config = load_config(root)
    except ArtefactRefused as bad:
        return str(bad)
    return probe(config.remote, rclone=rclone) if config.backend == RCLONE else ''


def store_for(config: Config, client: Client, repo: str, *, size: int) -> ArtefactStore:
    """The forge for an archive of *size* at or under the threshold, else the configured large backend."""
    if size <= config.threshold_mb * MB:
        return ForgeStore(client)
    large = large_store(config, repo)
    if large is None:
        msg = (
            f'an archive of {size} bytes is over the forge threshold of {config.threshold_mb} MB and '
            f'[{_TABLE}] names no backend for it: set backend = "rclone" and remote = "<remote:path>"'
        )
        raise ArtefactRefused(msg)
    return large


def reader(repo: str) -> FolderStore:
    """The local mirror of the large store on this machine (``[artefacts] folder`` in its config); read-only use."""
    folder = section('artefacts').get('folder')
    if not isinstance(folder, str) or not folder:
        msg = f'{config_path()}: set [artefacts] folder = "<local mirror of the artefact remote>" to read artefacts'
        raise ArtefactRefused(msg)
    return FolderStore(Path(folder).expanduser(), repo)


def resolve(entry: dict[str, Any], dest: Path, *, client: Client, repo: str) -> Path:
    """Fetch the archive a record's manifest *entry* names, through the store -- never a hard-coded path."""
    ref = Ref.of(entry)
    store: ArtefactStore = ForgeStore(client) if ref.backend == FORGE else reader(repo)
    return store.get(ref, dest)


_NOT_FOUND: Final = 404


# --- cleanup --------------------------------------------------------------------------------------


def pinned(client: Client, *, say: Callable[[str], None]) -> frozenset[str]:
    """The sha12s a ``keep``-labelled issue or pull request names: shas in its body, and a PR's head.

    The labelled set is read through the one paged listing and told apart by the one
    :func:`~dev_lab.dev.forgework.is_pull` -- gitea's ``"pull_request": null`` marks a plain issue.
    A ``/pulls/N`` read answered 404 (pull requests switched off, or no such pull) skips that number
    with a named reason -- its body still pins; any other refusal (401, 403, 5xx) raises.
    """
    found: set[str] = set()
    for item in pages(client, f'{client.repo}/issues', {'state': 'all', 'labels': 'keep'}):
        found.update(token[:12] for token in _SHA_TOKEN.findall(item.get('body') or ''))
        if not is_pull(item):
            continue
        try:
            head = pull_of(client.call('GET', f'{client.repo}/pulls/{item["number"]}')).head_sha
        except ForgeCallFailed as failed:
            status = failed.report.attempts[-1].returncode if failed.report.attempts else 0
            if status != _NOT_FOUND:  # an auth or server refusal is not about this number: it stays an alarm
                raise
            why = 'HTTP 404, pull requests are off' if pulls_off(client, failed) else f'HTTP 404: {failed}'
            say(f'[artefacts] keep #{item["number"]} pins by its body only: its pull read was refused ({why})')
            continue
        found.update([head[:12]] if head else [])
    return frozenset(found)


def clean(
    store: ArtefactStore, *, account: str, now: datetime, retain_days: int, cap_bytes: int, pinned: frozenset[str]
) -> tuple[Ref, ...]:
    """Delete *account*'s old runs, then its oldest until its share is under *cap_bytes*; nobody else's.

    Of *account*'s runs only: those older than *retain_days* go, then oldest first until its share is
    under *cap_bytes* (0: no cap); pins stay, and every other writer's run is never touched.
    """
    refs = [ref for ref in store.list(None) if parsed_run_id(ref.run_id)['account'] == account]
    cutoff = now.astimezone(UTC).date().toordinal() - retain_days
    held = [ref for ref in refs if parsed_run_id(ref.run_id)['sha'] in pinned]
    doomed = [ref for ref in refs if ref not in held and run_time(ref.run_id).date().toordinal() < cutoff]
    left = [ref for ref in refs if ref not in doomed]
    total = sum(ref.bytes for ref in left)
    for ref in left:  # oldest first
        if not cap_bytes or total <= cap_bytes:
            break
        if ref not in held:
            doomed.append(ref)
            total -= ref.bytes
    for ref in doomed:
        store.delete(ref)
    return tuple(doomed)
