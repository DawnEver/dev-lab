"""THE ARTEFACT STORES -- the run-id and key rules, the :class:`Ref`, and the remote backends.

The policy that picks a backend, and the local ``folder`` one, live in :mod:`lab_commons.dev.artefacts`;
this module is what a remote backend DOES: ``forge`` (:class:`ForgeStore`) and ``rclone``
(:class:`RcloneStore`), each write-once under a key :func:`check_key` admits.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Final, Protocol

from lab_commons.dev.forgerecords import Attachment, attach, listing, records_issue
from lab_commons.dev.forgework import GITHUB, Client

__all__ = [
    'ARCHIVE',
    'ATTACHMENT_LIMIT_MB',
    'FOLDER',
    'FORGE',
    'MANIFEST',
    'MB',
    'RCLONE',
    'ArtefactRefused',
    'ArtefactStore',
    'ForgeStore',
    'MissingOutput',
    'RcloneStore',
    'Ref',
    'check_key',
    'check_rclone_config',
    'landed_already',
    'object_key',
    'parsed_run_id',
    'ref_of',
    'run_id',
    'run_time',
    'scratch_dir',
    'sorted_refs',
    'verified_copy',
]

FORGE: Final = 'forge'
RCLONE: Final = 'rclone'
FOLDER: Final = 'folder'

ARCHIVE: Final = '.tar.zst'
MANIFEST: Final = '.manifest.json'

#: The forge's attachment limit: nothing larger is ever attached.
ATTACHMENT_LIMIT_MB: Final = 100

#: OneDrive's whole-path limit, and the characters no name may hold there.
_PATH_LIMIT: Final = 400
_FORBIDDEN: Final = frozenset('"*:<>?\\|')

_STAMP: Final = '%Y%m%dT%H%M%SZ'
_RUN_ID: Final = re.compile(r'^(?P<sha>[0-9a-f]{12})-(?P<platform>[a-z0-9]+)-(?P<stamp>\d{8}T\d{6}Z)$')
MB: Final = 1024 * 1024
_RCLONE_TIMEOUT_S: Final = 3600


class ArtefactRefused(ValueError):
    """An artefact operation refused: a bad name, an overwrite, a mismatching sha256, a bad config."""


class MissingOutput(ArtefactRefused):
    """A declared output matched nothing: the run fails loudly, naming every missing declaration."""


# --- names and layout -------------------------------------------------------------------------


def run_id(sha: str, platform: str, when: datetime) -> str:
    """``<sha12>-<platform>-<utcstamp>`` -- one run, short and ASCII."""
    return f'{sha[:12]}-{platform}-{when.astimezone(UTC).strftime(_STAMP)}'


def parsed_run_id(ident: str) -> re.Match[str]:
    """*ident* split into ``sha``, ``platform`` and ``stamp``; a malformed id is refused."""
    found = _RUN_ID.match(ident)
    if found is None:
        msg = f'{ident!r} is not a run id (<sha12>-<platform>-<yyyymmddTHHMMSSZ>)'
        raise ArtefactRefused(msg)
    return found


def run_time(ident: str) -> datetime:
    """When run *ident* was stamped (UTC)."""
    return datetime.strptime(parsed_run_id(ident)['stamp'], _STAMP).replace(tzinfo=UTC)


def object_key(repo: str, ident: str) -> str:
    """``<repo>/<yyyy>/<mm>/<dd>/<run-id>`` -- the day folder of the run's stamp; suffixes are appended."""
    when = run_time(ident)
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
        for block in iter(lambda: handle.read(MB), b''):
            sha.update(block)
    return sha.hexdigest()


def ref_of(backend: str, key: str, path: Path) -> Ref:
    """The :class:`Ref` of archive *path* stored under *key* on *backend*."""
    return Ref(backend, key, path.stat().st_size, _digest(path))


def verified_copy(ref: Ref, fetched: Path, dest: Path) -> Path:
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


def landed_already(existing: Ref | None, new: Ref) -> Ref | None:
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
    return run_time(ref.run_id).date() < older_than.astimezone(UTC).date()


def sorted_refs(refs: Sequence[Ref], older_than: datetime | None) -> tuple[Ref, ...]:
    """*refs* older than *older_than* (all when ``None``), oldest run first."""
    return tuple(
        sorted((ref for ref in refs if _older(ref, older_than)), key=lambda ref: (run_time(ref.run_id), ref.key))
    )


def scratch_dir(near: Path | None = None) -> Path:
    """A fresh private scratch directory, beside *near* when given."""
    return Path(tempfile.mkdtemp(prefix='artefact-', dir=near))


# --- folder ---------------------------------------------------------------------------------------


def _posix_mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def check_rclone_config(
    path: Path, *, repo: Path, mode_of: Callable[[Path], int] | None = _posix_mode if os.name != 'nt' else None
) -> None:
    """Refuse an rclone config inside *repo*, or readable by anyone but its owner (*mode_of* None: no POSIX modes)."""
    resolved, top = path.resolve(), repo.resolve()
    if resolved == top or top in resolved.parents:
        msg = f'the rclone config is never in a repo: move it out of {repo} (e.g. ~/.config/rclone/rclone.conf)'
        raise ArtefactRefused(msg)
    if mode_of is not None and mode_of(resolved) & 0o077:
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
        new = ref_of(self.backend, base + ARCHIVE, path)
        check_key(f'{self.remote.partition(":")[2]}/{base}{MANIFEST}')
        landed = landed_already(self._stored(new.key), new)
        if landed is not None:
            return landed
        scratch = scratch_dir()
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
        scratch = scratch_dir()
        try:
            fetched = scratch / 'fetched'
            self._run('copyto', self._at(ref.key), str(fetched))
            return verified_copy(ref, fetched, dest)
        finally:
            shutil.rmtree(scratch, ignore_errors=True)

    def list(self, older_than: datetime | None) -> tuple[Ref, ...]:
        """Every manifest under ``<remote>/<repo>``, read back."""
        names = [item['Path'] for item in self._files(self.repo) if item['Path'].endswith(MANIFEST)]
        refs = [Ref.of(json.loads(self._run('cat', self._at(f'{self.repo}/{name}')).stdout)) for name in names]
        return sorted_refs(refs, older_than)

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
        parsed_run_id(ident)
        new = ref_of(self.backend, ident + ARCHIVE, path)
        if path.stat().st_size > ATTACHMENT_LIMIT_MB * MB:
            msg = f'{new.key} is {new.bytes} bytes, over the forge attachment limit of {ATTACHMENT_LIMIT_MB} MB'
            raise ArtefactRefused(msg)
        assets = self._assets()
        found = assets.get(ident + MANIFEST)
        landed = landed_already(self._manifest(found) if found else None, new)
        if landed is not None:
            return landed
        scratch = scratch_dir()
        try:
            manifest = scratch / (ident + MANIFEST)
            manifest.write_text(json.dumps(new.manifest()), encoding='utf-8')
            if new.key not in assets:  # an attachment is named by its file: the archive goes up as <run-id>.tar.zst
                attach(self.client, Path(shutil.copyfile(path, scratch / new.key)))
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
        scratch = scratch_dir()
        try:
            fetched = scratch / 'fetched'
            fetched.write_bytes(self.client.download(item.url))
            return verified_copy(ref, fetched, dest)
        finally:
            shutil.rmtree(scratch, ignore_errors=True)

    def list(self, older_than: datetime | None) -> tuple[Ref, ...]:
        """Every artefact manifest attached."""
        return sorted_refs([self._manifest(i) for n, i in self._assets().items() if n.endswith(MANIFEST)], older_than)

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
