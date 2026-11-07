"""THE ARTEFACT STORE -- a run's DECLARED outputs, packed once and kept behind the record's manifest.

NOTHING TRAVELS BY DEFAULT (user rulings 2026-10-11). A request declares ``outputs = [...]`` -- globs or
named files relative to the run's work tree; only those are packed (:mod:`dev_lab.dev.artefactpack`), a
declared output that matched nothing fails the run loudly (:class:`MissingOutput`), and an undeclared
file is never uploaded. The verdict itself still travels as the run record, with each archive's member
index beside its Ref (:mod:`dev_lab.dev.artefactindex`).

ONE INTERFACE, THREE BACKENDS (:class:`ArtefactStore`): ``put(run_id, path) -> Ref``, ``get(ref, dest)``,
``list(older_than)``, ``delete(ref)``. ``forge`` keeps an archive as a records-home attachment
(<= :data:`ATTACHMENT_LIMIT_MB`); ``rclone`` any rclone remote, by shelling out with argv lists;
``folder`` a local path (:mod:`dev_lab.dev.artefactfolder`). A :class:`Ref` IS the manifest entry the record carries --
``{backend, ref, bytes, sha256}`` -- and :meth:`get` refuses bytes whose sha256 differs.

CONFIG IS DATA. The writer side is the repo's ``[tool.lab_commons.artefacts]`` (:class:`Config`): an
archive at or under ``threshold_mb`` goes to the forge, a larger one to ``backend``/``remote``; the
output and member-index budgets are declared there too, never defaulted. :func:`query_members` reads a
record's index under that policy without touching an archive. The reader side maps the same store to
a local path in the MACHINE config (``[artefacts] folder``, :func:`reader`) -- a synced mirror of the
remote, read, never written.

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
import re
import tomllib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from lab_commons.config import config_path, section
from lab_commons.hpc.rclone import probe
from lab_commons.hpc.records import read_record

from dev_lab.dev.artefactfolder import FolderStore
from dev_lab.dev.artefactindex import MemberFact, catalogue, select_members
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
    OutputBudgetRefused,
    RcloneStore,
    Ref,
    check_key,
    check_rclone_config,
    object_key,
    parsed_run_id,
    run_id,
    run_time,
)
from dev_lab.dev.forgefailure import ForgeCallFailed
from dev_lab.dev.forgepulls import pages, pulls_off
from dev_lab.dev.forgework import Client, is_pull, pull_of

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
    'ForgeStore',
    'MissingOutput',
    'OutputBudgetRefused',
    'RcloneStore',
    'Ref',
    'check_key',
    'check_rclone_config',
    'clean',
    'config_from',
    'large_store',
    'load_config',
    'object_key',
    'pinned',
    'query_members',
    'reader',
    'remote_problem',
    'resolve',
    'run_id',
    'store_for',
]

_BACKENDS: Final = (FORGE, RCLONE, FOLDER)
_SHA_TOKEN: Final = re.compile(r'\b[0-9a-f]{12,40}\b')
_TABLE: Final = 'tool.lab_commons.artefacts'


# --- config, selection, reading -------------------------------------------------------------------


@dataclass(frozen=True)
class Config:
    """``[tool.lab_commons.artefacts]``: where archives above *threshold_mb* go, and how long they stay."""

    backend: str = FORGE
    remote: str = ''
    threshold_mb: int = ATTACHMENT_LIMIT_MB
    retain_days: int = 3
    cap_gb: float = 0.0  # 0: no cap
    expanded_output_max_entries: int | None = None
    expanded_output_max_bytes: int | None = None
    member_index_max_members: int | None = None
    member_index_max_bytes: int | None = None
    member_index_max_path_bytes: int | None = None
    record_max_compressed_bytes: int | None = None
    record_max_decompressed_bytes: int | None = None

    @property
    def cap_bytes(self) -> int:
        """The cap in bytes; 0 when uncapped."""
        return int(self.cap_gb * 1024 * MB)


def load_config(root: Path) -> Config:
    """The repo's table, validated; no table is :class:`Config` (forge only)."""
    pyproject = root / 'pyproject.toml'
    return config_from(pyproject.read_text(encoding='utf-8') if pyproject.is_file() else '', str(pyproject))


def config_from(text: str, where: str) -> Config:
    """The table of the manifest *text* (read from *where*, named in a refusal), validated; none is forge only."""
    raw = tomllib.loads(text)
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
        msg = f'{where} [{_TABLE}]: {"; ".join(problems)}'
        raise ArtefactRefused(msg)
    budgets = _budget_problems(config)
    if budgets:
        msg = f'{where} [{_TABLE}]: {"; ".join(budgets)}'
        raise OutputBudgetRefused(msg)
    return config


def _budget_problems(config: Config) -> list[str]:
    """The output budgets *config* declares wrongly: a bool is never an integer budget."""
    expanded = {
        'expanded_output_max_entries': config.expanded_output_max_entries,
        'expanded_output_max_bytes': config.expanded_output_max_bytes,
    }
    bounded = {
        'member_index_max_members': config.member_index_max_members,
        'member_index_max_bytes': config.member_index_max_bytes,
        'member_index_max_path_bytes': config.member_index_max_path_bytes,
        'record_max_compressed_bytes': config.record_max_compressed_bytes,
        'record_max_decompressed_bytes': config.record_max_decompressed_bytes,
    }
    found = [
        f'{name} must be a nonnegative integer or omitted'
        for name, value in expanded.items()
        if value is not None and (type(value) is not int or value < 0)
    ]
    positive = [name for name, value in bounded.items() if value is not None and (type(value) is not int or value < 1)]
    return found + ([f'{positive} must be positive integers or omitted'] if positive else [])


def query_members(
    root: Path,
    record_path: Path,
    ref: Ref,
    paths: Sequence[str],
    *,
    case_sensitive: bool,
    expected_sha256: str | None = None,
) -> tuple[MemberFact, ...]:
    """The members *paths* select from *ref*'s index in the record at *record_path*, under *root*'s policy.

    The policy is read once from the trusted repo root BEFORE the record is opened, and every one of its
    seven budgets must be declared -- an omission is refused, never filled with a default. Only the
    bounded record is read (:func:`lab_commons.hpc.records.read_record`, which keeps its own
    ``RecordRefused``); no store or archive is touched, so the answer is a declaration, not verified
    archive contents.
    """
    config = load_config(root)
    record_budget = (config.record_max_compressed_bytes, config.record_max_decompressed_bytes)
    index = (config.member_index_max_members, config.member_index_max_bytes, config.member_index_max_path_bytes)
    selection = (config.expanded_output_max_entries, config.expanded_output_max_bytes)
    compressed, expanded = record_budget
    members, index_bytes, path_bytes = index
    entries, selected_bytes = selection
    if (
        compressed is None
        or expanded is None
        or members is None
        or index_bytes is None
        or path_bytes is None
        or entries is None
        or selected_bytes is None
    ):
        msg = f'a catalogue query requires explicit record, index and selection budget policy in [{_TABLE}]'
        raise OutputBudgetRefused(msg)
    record = read_record(
        record_path, max_compressed_bytes=compressed, max_decompressed_bytes=expanded, expected_sha256=expected_sha256
    )
    facts = catalogue(record, ref, max_members=members, max_index_bytes=index_bytes, max_path_bytes=path_bytes)
    return select_members(
        facts,
        paths,
        max_entries=entries,
        max_bytes=selected_bytes,
        max_path_bytes=path_bytes,
        case_sensitive=case_sensitive,
    )


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
