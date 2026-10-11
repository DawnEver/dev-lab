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

CLOUD-DRIVE-SHAPED LAYOUT. ``<repo>/<yyyy>/<mm>/<dd>/<run-id>.tar.zst`` plus ``<run-id>.manifest.json``,
``run-id = <sha12>-<platform>-<utcstamp>``: one archive per run (a synced drive pays per FILE), short
ASCII names checked against OneDrive's forbidden characters, trailing dot/space and its path limit
(:func:`check_key`). WRITE-ONCE: an object is never rewritten -- a different object under an existing
key is refused; the same bytes again is the object already landed (a resumed tick), not a write.

CLEANUP BY THE SINGLE WRITER (:func:`clean`): whole runs in day folders older than ``retain_days`` go,
unless a ``keep`` label on an issue or pull request pins their sha (:func:`pinned`); then oldest first
until the store is under ``cap_gb``; emptied folders are removed.

CREDENTIALS. The rclone config is never in a repo, never logged, and must be mode 600
(:func:`check_rclone_config`); no argv here carries a secret.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Final, Protocol

from lab_commons.config import config_path, section
from lab_commons.dev.forgerecords import Attachment, attach, listing, records_issue
from lab_commons.dev.forgework import GITHUB, Client, pull_of

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
    'resolve',
    'run_id',
    'store_for',
]

FORGE: Final = 'forge'
RCLONE: Final = 'rclone'
FOLDER: Final = 'folder'
_BACKENDS: Final = (FORGE, RCLONE, FOLDER)

ARCHIVE: Final = '.tar.zst'
MANIFEST: Final = '.manifest.json'

#: The forge's attachment limit: nothing larger is ever attached.
ATTACHMENT_LIMIT_MB: Final = 100

#: OneDrive's whole-path limit, and the characters no name may hold there.
_PATH_LIMIT: Final = 400
_FORBIDDEN: Final = frozenset('"*:<>?\\|')

_TABLE: Final = 'tool.lab_commons.artefacts'
_STAMP: Final = '%Y%m%dT%H%M%SZ'
_RUN_ID: Final = re.compile(r'^(?P<sha>[0-9a-f]{12})-(?P<platform>[a-z0-9]+)-(?P<stamp>\d{8}T\d{6}Z)$')
_SHA_TOKEN: Final = re.compile(r'\b[0-9a-f]{12,40}\b')
_MB: Final = 1024 * 1024
_RCLONE_TIMEOUT_S: Final = 3600


class ArtefactRefused(ValueError):
    """An artefact operation refused: a bad name, an overwrite, a mismatching sha256, a bad config."""


class MissingOutput(ArtefactRefused):
    """A declared output matched nothing: the run fails loudly, naming every missing declaration."""


# --- names and layout -------------------------------------------------------------------------


def run_id(sha: str, platform: str, when: datetime) -> str:
    """``<sha12>-<platform>-<utcstamp>`` -- one run, short and ASCII."""
    return f'{sha[:12]}-{platform}-{when.astimezone(UTC).strftime(_STAMP)}'


def _parsed(ident: str) -> re.Match[str]:
    found = _RUN_ID.match(ident)
    if found is None:
        msg = f'{ident!r} is not a run id (<sha12>-<platform>-<yyyymmddTHHMMSSZ>)'
        raise ArtefactRefused(msg)
    return found


def _when(ident: str) -> datetime:
    return datetime.strptime(_parsed(ident)['stamp'], _STAMP).replace(tzinfo=UTC)


def object_key(repo: str, ident: str) -> str:
    """``<repo>/<yyyy>/<mm>/<dd>/<run-id>`` -- the day folder of the run's stamp; suffixes are appended."""
    when = _when(ident)
    return f'{repo}/{when:%Y}/{when:%m}/{when:%d}/{ident}'


def check_key(key: str) -> None:
    """Refuse a key a cloud drive cannot hold: non-ASCII, forbidden characters, trailing dot/space, too long."""
    problems = []
    if not key.isascii():
        problems.append('non-ASCII')
    if len(key) > _PATH_LIMIT:
        problems.append(f'longer than {_PATH_LIMIT} characters')
    for part in key.split('/'):
        if not part:
            problems.append('an empty segment')
        elif _FORBIDDEN & set(part) or not part.isprintable():
            problems.append(f'{part!r} holds a character among {"".join(sorted(_FORBIDDEN))}')
        elif part[-1] in '. ':
            problems.append(f'{part!r} ends in a dot or space')
    if problems:
        msg = f'artefact key {key!r} refused: {"; ".join(problems)}'
        raise ArtefactRefused(msg)


# --- declared outputs -------------------------------------------------------------------------


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
        msg = f'declared outputs matched nothing in {tree}: {", ".join(missing)}'
        raise MissingOutput(msg)
    return sorted(found)


def pack(tree: Path, files: Sequence[Path], dest: Path, *, zstd: Sequence[str] = ('zstd',)) -> Path:
    """One tar of *files* (named relative to *tree*), compressed by the ``zstd`` binary into *dest*."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    with subprocess.Popen([*zstd, '-q', '-f', '-o', str(dest)], stdin=subprocess.PIPE) as proc:
        assert proc.stdin is not None  # noqa: S101 -- PIPE was asked for
        with tarfile.open(fileobj=proc.stdin, mode='w|') as tar:
            for path in files:
                tar.add(path, arcname=path.relative_to(tree).as_posix(), recursive=False)
        proc.stdin.close()
    if proc.returncode != 0:
        msg = f'zstd exited {proc.returncode} packing {dest.name}'
        raise OSError(msg)
    return dest


# --- the reference and the interface ------------------------------------------------------------


@dataclass(frozen=True)
class Ref:
    """One stored archive -- and, as :meth:`manifest`, the entry the record carries."""

    backend: str
    key: str
    bytes: int
    sha256: str

    @property
    def run_id(self) -> str:
        """The run this archive belongs to."""
        return PurePosixPath(self.key).name.removesuffix(ARCHIVE)

    def manifest(self) -> dict[str, Any]:
        """``{backend, ref, bytes, sha256}``."""
        return {'backend': self.backend, 'ref': self.key, 'bytes': self.bytes, 'sha256': self.sha256}

    @classmethod
    def of(cls, entry: dict[str, Any]) -> Ref:
        """The ref a manifest entry names."""
        return cls(entry['backend'], entry['ref'], int(entry['bytes']), entry['sha256'])


class ArtefactStore(Protocol):
    """Where archives live; every backend answers the same four calls."""

    backend: str

    def put(self, ident: str, path: Path) -> Ref:
        """Store *path* as run *ident*'s archive, write-once; the ref."""

    def get(self, ref: Ref, dest: Path) -> Path:
        """Download *ref* into directory *dest*, sha256-verified; the file."""

    def list(self, older_than: datetime | None) -> tuple[Ref, ...]:
        """Every stored archive (whose day is before *older_than*, when given), oldest first."""

    def delete(self, ref: Ref) -> None:
        """Delete *ref*'s archive and manifest; emptied folders go too."""


def _digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(_MB), b''):
            sha.update(block)
    return sha.hexdigest()


def _ref_of(backend: str, key: str, path: Path) -> Ref:
    return Ref(backend, key, path.stat().st_size, _digest(path))


def _verified(ref: Ref, fetched: Path, dest: Path) -> Path:
    """Move *fetched* into *dest* only when its sha256 is the ref's; a mismatch is deleted and refused."""
    actual = _digest(fetched)
    if actual != ref.sha256:
        fetched.unlink()
        msg = f"{ref.key}: sha256 {actual} is not the manifest's {ref.sha256}; download discarded"
        raise ArtefactRefused(msg)
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / PurePosixPath(ref.key).name
    shutil.move(fetched, target)
    return target


def _landed(existing: Ref | None, new: Ref) -> Ref | None:
    """The object already stored for *new*'s key: the same bytes are landed, different bytes are refused."""
    if existing is None:
        return None
    if existing.sha256 != new.sha256:
        msg = f'{new.key} already exists with other content: write-once, a correction is a new run id'
        raise ArtefactRefused(msg)
    return existing


def _older(ref: Ref, older_than: datetime | None) -> bool:
    if older_than is None:
        return True
    return _when(ref.run_id).date() < older_than.astimezone(UTC).date()


def _sorted(refs: Sequence[Ref], older_than: datetime | None) -> tuple[Ref, ...]:
    return tuple(sorted((ref for ref in refs if _older(ref, older_than)), key=lambda ref: (_when(ref.run_id), ref.key)))


def _scratch(near: Path | None = None) -> Path:
    return Path(tempfile.mkdtemp(prefix='artefact-', dir=near))


# --- folder ---------------------------------------------------------------------------------------


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
        new = _ref_of(self.backend, base + ARCHIVE, path)
        check_key(base + MANIFEST)
        landed = _landed(self._stored(new.key), new)
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
        scratch = _scratch()
        try:
            fetched = scratch / 'fetched'
            shutil.copyfile(self.root / ref.key, fetched)
            return _verified(ref, fetched, dest)
        finally:
            shutil.rmtree(scratch, ignore_errors=True)

    def list(self, older_than: datetime | None) -> tuple[Ref, ...]:
        """Every manifest under ``<root>/<repo>``."""
        base = self.root / self.repo
        found = [Ref.of(json.loads(p.read_text(encoding='utf-8'))) for p in base.rglob(f'*{MANIFEST}')]
        return _sorted(found if base.is_dir() else [], older_than)

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


def check_rclone_config(path: Path, *, repo: Path) -> None:
    """Refuse an rclone config inside *repo*, or (on POSIX) readable by anyone but its owner."""
    resolved, top = path.resolve(), repo.resolve()
    if resolved == top or top in resolved.parents:
        msg = f'the rclone config is never in a repo: move it out of {repo} (e.g. ~/.config/rclone/rclone.conf)'
        raise ArtefactRefused(msg)
    if os.name != 'nt' and stat.S_IMODE(resolved.stat().st_mode) & 0o077:
        msg = f'the rclone config {path} must be mode 600 (it holds the drive token): chmod 600 {path}'
        raise ArtefactRefused(msg)


@dataclass(frozen=True)
class RcloneStore:
    """Any rclone remote (``name:path``), driven through the ``rclone`` binary with argv lists only."""

    remote: str
    repo: str
    rclone: Sequence[str] = ('rclone',)
    backend: str = RCLONE

    def _at(self, key: str) -> str:
        return f'{self.remote.rstrip("/")}/{key}'

    def _run(self, *args: str, ok: Sequence[int] = (0,)) -> subprocess.CompletedProcess[str]:
        done = subprocess.run(
            [*self.rclone, *args], capture_output=True, text=True, encoding='utf-8', check=False,
            timeout=_RCLONE_TIMEOUT_S,
        )  # fmt: skip
        if done.returncode not in ok:
            msg = f'rclone {args[0]} exited {done.returncode}: {done.stderr.strip()[-300:]}'
            raise OSError(msg)
        return done

    def _files(self, key: str) -> list[dict[str, Any]]:
        done = self._run('lsjson', '-R', '--files-only', self._at(key), ok=(0, 3))  # 3: directory not found
        return json.loads(done.stdout) if done.returncode == 0 and done.stdout.strip() else []

    def _stored(self, key: str) -> Ref | None:
        folder, _, name = key.rpartition('/')
        manifest = name.removesuffix(ARCHIVE) + MANIFEST
        if not any(item['Path'] == manifest for item in self._files(folder)):
            return None
        return Ref.of(json.loads(self._run('cat', self._at(f'{folder}/{manifest}')).stdout))

    def put(self, ident: str, path: Path) -> Ref:
        """Archive first, manifest last -- both ``--immutable``, so rclone too refuses an overwrite."""
        base = object_key(self.repo, ident)
        new = _ref_of(self.backend, base + ARCHIVE, path)
        check_key(f'{self.remote.partition(":")[2]}/{base}{MANIFEST}')
        landed = _landed(self._stored(new.key), new)
        if landed is not None:
            return landed
        scratch = _scratch()
        try:
            manifest = scratch / (ident + MANIFEST)
            manifest.write_text(json.dumps(new.manifest()), encoding='utf-8')
            self._run('copyto', '--immutable', str(path), self._at(new.key))
            self._run('copyto', '--immutable', str(manifest), self._at(base + MANIFEST))
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
        return new

    def get(self, ref: Ref, dest: Path) -> Path:
        """Download and verify."""
        scratch = _scratch()
        try:
            fetched = scratch / 'fetched'
            self._run('copyto', self._at(ref.key), str(fetched))
            return _verified(ref, fetched, dest)
        finally:
            shutil.rmtree(scratch, ignore_errors=True)

    def list(self, older_than: datetime | None) -> tuple[Ref, ...]:
        """Every manifest under ``<remote>/<repo>``, read back."""
        names = [item['Path'] for item in self._files(self.repo) if item['Path'].endswith(MANIFEST)]
        refs = [Ref.of(json.loads(self._run('cat', self._at(f'{self.repo}/{name}')).stdout)) for name in names]
        return _sorted(refs, older_than)

    def delete(self, ref: Ref) -> None:
        """Delete both objects, then every emptied folder under the repo."""
        folder = ref.key.rpartition('/')[0]
        self._run('deletefile', self._at(f'{folder}/{ref.run_id}{MANIFEST}'))
        self._run('deletefile', self._at(ref.key))
        self._run('rmdirs', '--leave-root', self._at(self.repo))


# --- forge ----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ForgeStore:
    """The records home's attachments (:mod:`lab_commons.dev.forgerecords`); names are flat ``<run-id>.*``."""

    client: Client
    backend: str = FORGE

    def _assets(self) -> dict[str, Attachment]:
        return {item.name: item for item in listing(self.client)}

    def _manifest(self, item: Attachment) -> Ref:
        return Ref.of(json.loads(self.client.download(item.url)))

    def put(self, ident: str, path: Path) -> Ref:
        """Write-once on the forge too: an attachment of that name with other content is refused."""
        _parsed(ident)
        new = _ref_of(self.backend, ident + ARCHIVE, path)
        if path.stat().st_size > ATTACHMENT_LIMIT_MB * _MB:
            msg = f'{new.key} is {new.bytes} bytes, over the forge attachment limit of {ATTACHMENT_LIMIT_MB} MB'
            raise ArtefactRefused(msg)
        assets = self._assets()
        found = assets.get(ident + MANIFEST)
        landed = _landed(self._manifest(found) if found else None, new)
        if landed is not None:
            return landed
        scratch = _scratch()
        try:
            manifest = scratch / (ident + MANIFEST)
            manifest.write_text(json.dumps(new.manifest()), encoding='utf-8')
            if new.key not in assets:
                attach(self.client, path)
            attach(self.client, manifest)
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
        return new

    def get(self, ref: Ref, dest: Path) -> Path:
        """Download the attachment and verify."""
        item = self._assets().get(ref.key)
        if item is None:
            msg = f'{ref.key} is not attached on the forge (pruned, or never stored)'
            raise ArtefactRefused(msg)
        scratch = _scratch()
        try:
            fetched = scratch / 'fetched'
            fetched.write_bytes(self.client.download(item.url))
            return _verified(ref, fetched, dest)
        finally:
            shutil.rmtree(scratch, ignore_errors=True)

    def list(self, older_than: datetime | None) -> tuple[Ref, ...]:
        """Every artefact manifest attached."""
        return _sorted([self._manifest(i) for n, i in self._assets().items() if n.endswith(MANIFEST)], older_than)

    def delete(self, ref: Ref) -> None:
        """Delete the archive and manifest attachments."""
        assets = self._assets()
        if self.client.backend is GITHUB:
            base = f'{self.client.repo}/releases/assets/'
        else:
            base = f'{self.client.repo}/issues/{records_issue(self.client, create=False)}/assets/'
        for name in (ref.run_id + MANIFEST, ref.key):
            if name in assets:
                self.client.call('DELETE', f'{base}{assets[name].id}')


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
        return int(self.cap_gb * 1024 * _MB)


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


def store_for(config: Config, client: Client, repo: str, *, size: int) -> ArtefactStore:
    """The forge for an archive of *size* at or under the threshold, else the configured large backend."""
    if size <= config.threshold_mb * _MB:
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


# --- cleanup --------------------------------------------------------------------------------------


def pinned(client: Client) -> frozenset[str]:
    """The sha12s a ``keep``-labelled issue or pull request names: shas in its body, and a PR's head."""
    found: set[str] = set()
    for item in client.call('GET', f'{client.repo}/issues?state=all&labels=keep&limit=50'):
        found.update(token[:12] for token in _SHA_TOKEN.findall(item.get('body') or ''))
        if 'pull_request' in item:
            head = pull_of(client.call('GET', f'{client.repo}/pulls/{item["number"]}')).head_sha
            found.update([head[:12]] if head else [])
    return frozenset(found)


def clean(
    store: ArtefactStore, *, now: datetime, retain_days: int, cap_bytes: int, pinned: frozenset[str]
) -> tuple[Ref, ...]:
    """Delete runs older than *retain_days*, then oldest first until under *cap_bytes* (0: no cap); pins stay."""
    refs = store.list(None)
    cutoff = now.astimezone(UTC).date().toordinal() - retain_days
    held = [ref for ref in refs if _parsed(ref.run_id)['sha'] in pinned]
    doomed = [ref for ref in refs if ref not in held and _when(ref.run_id).date().toordinal() < cutoff]
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
