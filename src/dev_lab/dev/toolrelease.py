"""A user-space tool installed from its upstream release at a PINNED version, sha256-checked before anything runs it.

``python -m dev_lab.dev.toolrelease install <tool> [--dry-run]`` and ``where <tool>``.

WHY. A tool the toolchain drives itself (rclone, for the artifact and large-file stores) must be present on every
host that runs the toolchain, and a host's setup must put it there without a person: the cluster account deploy
(:data:`dev_lab.dev.hpcaccount.checks.INSTALLERS`) and the workstation deploy (:mod:`dev_lab.dev.workstation`) both
install every :data:`RELEASES` tool they cannot resolve, through this one door.

PINNED, NEVER "LATEST". :class:`Release` holds the version and, per platform, the asset's file name and its sha256,
read from that release's ``SHA256SUMS`` when the pin was set. A bump edits the version and every digest together,
from the new release's ``SHA256SUMS``; nothing is resolved live, so a compromised mirror cannot move the pin.

ORDER OF TRUST. The asset is downloaded into a FRESH EMPTY directory (``tempfile.mkdtemp``), hashed, and refused
with the download discarded unless the digest equals the pin (:class:`ChecksumMismatch`). Only then is the one
declared member read out of the archive (never ``extractall``: no path from the archive is ever joined to a
directory) and written into :func:`tool_dir` by an atomic replace. Nothing from the download runs before that.

WHERE. :func:`tool_dir` is user-space and removable: ``~/.local/bin`` on POSIX (already first on a cluster tick's
PATH, :func:`dev_lab.dev.hpcaccount.spec.tick_dirs`), ``%LOCALAPPDATA%/dev-lab/bin`` on Windows. :func:`resolve`
reads that directory first, then ``PATH``; absent from both is :class:`ToolAbsent`, whose message names this door.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import platform
import shutil
import tarfile
import tempfile
import urllib.error
import urllib.request
import zipfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from lab_commons import home as _home
from lab_commons.log import emit
from lab_commons.temp import TEMP_PREFIX

__all__ = [
    'RCLONE',
    'RELEASES',
    'USER_AGENT',
    'ChecksumMismatch',
    'DownloadRefused',
    'Release',
    'ToolAbsent',
    'UnsupportedPlatform',
    'door',
    'install',
    'install_release',
    'main',
    'platform_key',
    'request',
    'resolve',
    'tool_dir',
]

_DOWNLOAD_TIMEOUT_S: Final = 600
#: The client name every download sends. downloads.rclone.org answers urllib's default ``Python-urllib/<v>`` with
#: 403 (measured 2026-11-19); a generic tool name is answered 200. It carries no user, host or machine detail.
USER_AGENT: Final = 'dev-lab-toolrelease'


@dataclass(frozen=True)
class Release:
    """One tool's pinned upstream release: where each platform's archive is and what its sha256 must be."""

    name: str
    version: str
    url: str  # ``{version}`` and ``{asset}`` are filled in
    assets: Mapping[str, tuple[str, str]]  # platform key -> (archive file name, sha256 from SHA256SUMS)
    member: str  # the executable's path inside the archive; ``{stem}`` is the archive name without ``.zip``

    def exe(self, *, windows: bool) -> str:
        """The executable's file name on this platform."""
        return f'{self.name}.exe' if windows else self.name


#: rclone, pinned 2026-11-18 from https://downloads.rclone.org/v1.76.0/SHA256SUMS (D76).
RCLONE: Final = Release(
    name='rclone',
    version='1.76.0',
    url='https://downloads.rclone.org/v{version}/{asset}',
    assets={
        'linux-amd64': (
            'rclone-v1.76.0-linux-amd64.zip',
            'b00f00b3266c3764413afe599d3ec316f6f43b3e0ea8a0bc1d186d2133e46df7',
        ),
        'linux-arm64': (
            'rclone-v1.76.0-linux-arm64.zip',
            'ee169016675e23a69d77240565133ff7dbc9b33d16fa8f7053d4af39f1eaeb78',
        ),
        'osx-amd64': (
            'rclone-v1.76.0-osx-amd64.zip',
            '4f5835733d52b818340f97b1fc0348a70461534d123363a183ca2b660219595a',
        ),
        'osx-arm64': (
            'rclone-v1.76.0-osx-arm64.zip',
            'e72dc90b70f4947a7b72b61bde4a4fbba5777b2874fb448951ffdde67ebd0ab7',
        ),
        'windows-amd64': (
            'rclone-v1.76.0-windows-amd64.zip',
            '8b4fd2737ade4e70c057ef4a49deb7cffe94b0fb9d7587c189d149823f21a1dc',
        ),
        'windows-arm64': (
            'rclone-v1.76.0-windows-arm64.zip',
            'c406c8a69a5a408e50624aa990fbb0a6266b3a4e83782a94de3cb96f50f86f10',
        ),
    },
    member='{stem}/rclone',
)

#: Every tool a host's setup installs through this door, by name.
RELEASES: Final[Mapping[str, Release]] = {RCLONE.name: RCLONE}

_SYSTEMS: Final = {'linux': 'linux', 'darwin': 'osx', 'windows': 'windows'}
_MACHINES: Final = {'x86_64': 'amd64', 'amd64': 'amd64', 'aarch64': 'arm64', 'arm64': 'arm64'}


class ToolAbsent(LookupError):
    """A declared tool resolves nowhere; the message names the door that installs it."""


class UnsupportedPlatform(LookupError):
    """The pinned release publishes no archive for this platform."""


class DownloadRefused(OSError):
    """The release host answered the download with an HTTP error; the message names the status and the url."""


class ChecksumMismatch(ValueError):
    """A download's sha256 is not the pinned one; the download was discarded and nothing ran."""


def door(name: str) -> str:
    """The command that installs *name* on this host."""
    return f'python -m dev_lab.dev.toolrelease install {name}'


def platform_key(system: str | None = None, machine: str | None = None) -> str:
    """``<os>-<arch>`` as the release names its archives (``windows-amd64``, ``linux-arm64``, ...)."""
    found = (system or platform.system()).lower(), (machine or platform.machine()).lower()
    return f'{_SYSTEMS.get(found[0], found[0])}-{_MACHINES.get(found[1], found[1])}'


def tool_dir(*, windows: bool | None = None, environ: Mapping[str, str] | None = None) -> Path:
    """Where this door installs: :func:`lab_commons.home.pinned_bin`, the one place a product resolves it too."""
    return _home.pinned_bin(windows=windows, environ=environ)


def resolve(
    name: str,
    *,
    directory: Path | None = None,
    which: Callable[[str], str | None] = shutil.which,
    windows: bool | None = None,
) -> Path:
    """*name*'s executable: the install directory first, then ``PATH``; absent from both raises :class:`ToolAbsent`."""
    on_windows = os.name == 'nt' if windows is None else windows
    exe = RELEASES[name].exe(windows=on_windows) if name in RELEASES else name
    placed = (directory or tool_dir(windows=on_windows)) / exe
    if placed.is_file():
        return placed
    if found := which(name):
        return Path(found)
    msg = f'{name} is not installed (not in {placed.parent}, not on PATH): run `{door(name)}`'
    raise ToolAbsent(msg)


def request(url: str) -> urllib.request.Request:
    """The GET a download sends: *url* with :data:`USER_AGENT`, never urllib's default client name."""
    return urllib.request.Request(url, headers={'User-Agent': USER_AGENT})  # noqa: S310 -- https, pinned


def _download(url: str, to: Path, *, opener: Callable[..., object] = urllib.request.urlopen) -> None:
    try:
        answer = opener(request(url), timeout=_DOWNLOAD_TIMEOUT_S)
    except urllib.error.HTTPError as why:
        msg = (
            f'{url} answered HTTP {why.code} {why.reason} to client {USER_AGENT!r}; nothing was installed. '
            f'Check the host is reachable from here, then re-run `{door_for_url(url)}`'
        )
        raise DownloadRefused(msg) from why
    with answer as body, to.open('wb') as out:  # type: ignore[attr-defined]
        shutil.copyfileobj(body, out)  # type: ignore[arg-type]


def door_for_url(url: str) -> str:
    """The install door of the release whose archive *url* is (the generic door when none matches)."""
    for name, release in RELEASES.items():
        if url.startswith(release.url.split('{', 1)[0]):
            return door(name)
    return 'python -m dev_lab.dev.toolrelease install <tool>'


def install(
    name: str,
    *,
    directory: Path | None = None,
    key: str | None = None,
    fetch: Callable[[str, Path], None] = _download,
) -> Path:
    """Download *name*'s pinned archive for *key*, verify its sha256, and place its executable in *directory*."""
    return install_release(RELEASES[name], directory=directory, key=key, fetch=fetch)


def _member(archive: Path, member: str) -> bytes:
    """The one declared *member* of a ``.zip`` or ``.tar.gz`` *archive*; no other path is ever read or written."""
    if archive.name.endswith('.tar.gz'):
        with tarfile.open(archive, 'r:gz') as bundle:
            found = bundle.extractfile(member)
            if found is None:
                msg = f'{archive.name} carries no file {member}'
                raise KeyError(msg)
            return found.read()
    with zipfile.ZipFile(archive) as bundle:
        return bundle.read(member)


def install_release(
    release: Release,
    *,
    directory: Path | None = None,
    key: str | None = None,
    fetch: Callable[[str, Path], None] = _download,
) -> Path:
    """Download *release*'s archive for *key*, verify its sha256, and place its executable in *directory*."""
    name = release.name
    where = key or platform_key()
    if where not in release.assets:
        msg = f'{name} {release.version} publishes no archive for {where} (it has: {", ".join(sorted(release.assets))})'
        raise UnsupportedPlatform(msg)
    asset, pinned = release.assets[where]
    windows = where.startswith('windows-')
    target = (directory or tool_dir(windows=windows)) / release.exe(windows=windows)
    scratch = Path(tempfile.mkdtemp(prefix=f'{TEMP_PREFIX}toolrelease-'))
    try:
        archive = scratch / asset
        fetch(release.url.format(version=release.version, asset=asset), archive)
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        if digest != pinned:
            msg = f'{asset} has sha256 {digest}, not the pinned {pinned}; the download was discarded'
            raise ChecksumMismatch(msg)
        stem = asset.removesuffix('.zip').removesuffix('.tar.gz')
        member = release.member.format(stem=stem) + ('.exe' if windows else '')
        body = _member(archive, member)
        target.parent.mkdir(parents=True, exist_ok=True)
        staged = target.with_name(f'{target.name}.{TEMP_PREFIX}new')
        staged.write_bytes(body)
        if not windows:
            staged.chmod(0o755)
        staged.replace(target)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return target


def main(argv: Sequence[str] | None = None) -> int:
    """``install <tool> [--dry-run]`` or ``where <tool>``; 0 done, 2 refused with its reason."""
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.toolrelease', description=__doc__.splitlines()[0])
    parser.add_argument('verb', choices=('install', 'where'))
    parser.add_argument('tool', choices=sorted(RELEASES))
    parser.add_argument('--dry-run', action='store_true', help='print what install would do; change nothing')
    args = parser.parse_args(argv)
    release = RELEASES[args.tool]
    try:
        if args.verb == 'where':
            emit(str(resolve(args.tool)))
            return 0
        if args.dry_run:
            emit(f'would install {args.tool} {release.version} ({platform_key()}) into {tool_dir()}')
            return 0
        emit(f'installed {args.tool} {release.version}: {install(args.tool)}')
    except (
        ToolAbsent,
        UnsupportedPlatform,
        ChecksumMismatch,
        OSError,
        zipfile.BadZipFile,
        tarfile.TarError,
        KeyError,
    ) as why:
        emit(f'{args.tool}: refused -- {why}', err=True)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
