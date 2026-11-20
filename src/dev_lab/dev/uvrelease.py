"""THE uv that writes a lock is the pinned release itself, installed user-space beside every other pinned uv.

THE INCIDENT (2026-11-19/20, host G). One host, one global uv, several pins in flight: a full relock of dev-lab
moved :data:`~dev_lab.dev.lockcheck.UV_PIN` to the newest release (0.13.9) and the follow moved the host's uv
with it; a consumer's ``--upgrade-package`` relock under a kit still pinning 0.13.7 then asked the host to move
BACK, and ``winget install --version 0.13.7`` failed 3/3. Every pin was right; sharing one binary was not.

THE RULE. A lock is written by :func:`writer`: the uv of exactly the pinned version, at
``<tool_dir>/uv/<version>/``, downloaded once from that release and sha256-checked against the digests the pin
file carries (:mod:`dev_lab.dev.toolrelease`, D76) -- never by moving the host's ``PATH`` uv. Two pins coexist;
nothing flips. The PATH uv is used as is when it already IS the pinned version.

THE DIGESTS LIVE WITH THE PIN (``uv.toml`` ``[sha256]``, one per :data:`ASSETS` platform), read from each
asset's ``.sha256`` on the release when the pin moves (:func:`digests`), so a bump carries its digests in the
same reviewed change -- the order of trust rclone's pin keeps.
"""

from __future__ import annotations

import tomllib
import urllib.request
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Final

from dev_lab.dev import toolrelease

__all__ = ['ASSETS', 'URL', 'digests', 'pinned', 'release', 'writer']

#: uv's archive per platform key (:func:`dev_lab.dev.toolrelease.platform_key`); the names carry no version.
ASSETS: Final[Mapping[str, str]] = {
    'windows-amd64': 'uv-x86_64-pc-windows-msvc.zip',
    'windows-arm64': 'uv-aarch64-pc-windows-msvc.zip',
    'linux-amd64': 'uv-x86_64-unknown-linux-gnu.tar.gz',
    'linux-arm64': 'uv-aarch64-unknown-linux-gnu.tar.gz',
    'osx-amd64': 'uv-x86_64-apple-darwin.tar.gz',
    'osx-arm64': 'uv-aarch64-apple-darwin.tar.gz',
}
URL: Final = 'https://github.com/astral-sh/uv/releases/download/{version}/{asset}'


def pinned(version: str, sums: Mapping[str, str]) -> toolrelease.Release:
    """Uv *version* with, per platform, its archive and the sha256 *sums* holds for it."""
    missing = sorted(set(ASSETS) - set(sums))
    if missing:
        msg = f'uv {version} has no sha256 for {missing}: re-pin it (lockcheck.pin_uv)'
        raise ValueError(msg)
    # Windows archives hold uv.exe at the root (:func:`_member_for`); the tarballs hold <stem>/uv.
    return toolrelease.Release(
        name='uv',
        version=version,
        url=URL,
        assets={key: (asset, sums[key]) for key, asset in ASSETS.items()},
        member='{stem}/uv',
    )


def release(pin: Path, version: str, *, read: Callable[[str], str] | None = None) -> toolrelease.Release:
    """Uv *version*: from *pin*'s ``[sha256]`` when *pin* pins it, else from that release's own ``.sha256`` files.

    The second case is a pin MOVING (a full relock raises it to the newest release): its digests are read once,
    here, and :func:`dev_lab.dev.lockcheck.pin_uv` writes them into the pin in the same change.
    """
    data = tomllib.loads(pin.read_text(encoding='utf-8')) if pin.is_file() else {}
    if data.get('version') == version:
        return pinned(version, data.get('sha256', {}))
    return pinned(version, digests(version, read=read))


def _member_for(key: str, pinned: toolrelease.Release) -> toolrelease.Release:
    if key.startswith('windows-'):
        return toolrelease.Release(pinned.name, pinned.version, pinned.url, pinned.assets, member='uv')
    return pinned


def writer(
    wanted: toolrelease.Release,
    path_uv: str | None,
    *,
    version_of: Callable[[str], str],
    key: str | None = None,
    base: Path | None = None,
    install: Callable[..., Path] | None = None,
) -> str:
    """The uv that writes a lock: *path_uv* when it already is *wanted*'s version, else that exact one beside it."""
    pinned = wanted
    if path_uv and version_of(path_uv) == pinned.version:
        return path_uv
    where = key or toolrelease.platform_key()
    home = (base or toolrelease.tool_dir()) / 'uv' / pinned.version
    placed = home / pinned.exe(windows=where.startswith('windows-'))
    if not placed.is_file():
        placed = (install or toolrelease.install_release)(_member_for(where, pinned), directory=home, key=where)
    return str(placed)


def digests(version: str, *, read: Callable[[str], str] | None = None) -> dict[str, str]:
    """Every :data:`ASSETS` archive's sha256 for uv *version*, from the release's ``<asset>.sha256`` files."""

    def _read(url: str) -> str:
        with urllib.request.urlopen(toolrelease.request(url), timeout=60) as body:  # noqa: S310 -- https, pinned host
            return body.read().decode('utf-8')

    fetch = read or _read
    found: dict[str, str] = {}
    for key, asset in ASSETS.items():
        words = fetch(URL.format(version=version, asset=asset) + '.sha256').split()
        if not words or len(words[0]) != 64:  # noqa: PLR2004 -- a sha256 is 64 hex digits
            msg = f'uv {version}: {asset}.sha256 carries no sha256'
            raise ValueError(msg)
        found[key] = words[0]
    return found
