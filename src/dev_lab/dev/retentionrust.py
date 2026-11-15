"""WHAT RETENTION DELETES OF THE RUST TOOLCHAIN -- every rustup toolchain nothing pins, and extracted crate sources.

Measured 2026-11-14 on a serving cluster account: ``~/.rustup/toolchains`` held 135 k files (another account 757);
one toolchain is 45-65 k files, so each toolchain no commit asks for is a quarter of a run's tree, kept forever.

* A TOOLCHAIN (``~/.rustup/toolchains/<channel>-<host triple>``) is kept while something can build with it: the
  ``rust-toolchain.toml`` channel of every tree :func:`dev_lab.dev.retentionplan.in_flight` keeps (the ONE
  definition of in flight, never a second notion) and of every served checkout, plus rustup's own default (a tree
  pinning nothing builds with it). ``toolchain-not-pinned`` otherwise -- the directory and its
  ``update-hashes/<name>`` file, which is what ``rustup toolchain uninstall`` removes; done here so every file is
  counted like the rest and no rustup binary has to be on the tick's PATH. A pin that cannot be read (an in-flight
  sha with no tree, an unreadable queue) keeps every toolchain: an unprovable reference is a reference.
* EXTRACTED CRATE SOURCES (``~/.cargo/registry/src/<index>/<crate>``) are a cache of a cache: cargo re-extracts each
  from its ``registry/cache/<index>/<crate>.crate`` on the next build that needs it, with no network. They go as
  ``cargo-registry-src`` once untouched for ``min_age_hours`` (a build extracting now keeps them); the ``.crate``
  files stay.
"""

from __future__ import annotations

import tomllib
from collections.abc import Iterable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Final

__all__ = ['RULE_REGISTRY', 'RULE_TOOLCHAIN', 'pinned_channels', 'registry_sources', 'unpinned_toolchains']

RULE_TOOLCHAIN: Final = 'toolchain-not-pinned'
RULE_REGISTRY: Final = 'cargo-registry-src'
_PIN_FILES: Final = ('rust-toolchain.toml', 'rust-toolchain')


def _channel(checkout: Path) -> str | None:
    """The channel *checkout* pins, ``''`` when it pins none, ``None`` when its pin file cannot be read."""
    for name in _PIN_FILES:
        pin = checkout / name
        if not pin.is_file():
            continue
        try:
            text = pin.read_text(encoding='utf-8')
        except OSError:
            return None
        if name == 'rust-toolchain' and not text.lstrip().startswith('['):
            return text.strip()
        try:
            return str(tomllib.loads(text).get('toolchain', {}).get('channel', ''))
        except tomllib.TOMLDecodeError:
            return None
    return ''


def _default(rustup: Path) -> str:
    try:
        settings = tomllib.loads((rustup / 'settings.toml').read_text(encoding='utf-8'))
    except (OSError, tomllib.TOMLDecodeError):
        return ''
    return str(settings.get('default_toolchain', ''))


def pinned_channels(rustup: Path, checkouts: Iterable[Path]) -> set[str] | None:
    """Every channel *checkouts* pin plus rustup's default; ``None`` when one cannot be proved (keep everything)."""
    channels = {_default(rustup)}
    for checkout in checkouts:
        if not checkout.is_dir():
            return None
        channel = _channel(checkout)
        if channel is None:
            return None
        channels.add(channel)
    return {c for c in channels if c}


def _is_pinned(name: str, channels: set[str]) -> bool:
    return any(name == c or name.startswith(f'{c}-') for c in channels)


def unpinned_toolchains(rustup: Path, channels: set[str] | None) -> list[Path]:
    """Each installed toolchain no channel names, with its ``update-hashes`` file; nothing when *channels* is ``None``.

    With no default and no pin at all nothing is proved either, so nothing goes.
    """
    if not channels:
        return []
    out: list[Path] = []
    toolchains = rustup / 'toolchains'
    for entry in sorted(toolchains.iterdir()) if toolchains.is_dir() else []:
        if not _is_pinned(entry.name, channels):
            out += [entry, rustup / 'update-hashes' / entry.name]
    return [p for p in out if p.exists() or p.is_symlink()]


def registry_sources(cargo: Path, now: datetime, young: timedelta) -> list[Path]:
    """Every extracted crate under ``registry/src`` untouched for *young*; the ``.crate`` cache is never named."""
    src = cargo / 'registry' / 'src'
    indexes = [i for i in sorted(src.iterdir()) if i.is_dir()] if src.is_dir() else []
    crates = [crate for index in indexes for crate in sorted(index.iterdir())]
    return [c for c in crates if now - datetime.fromtimestamp(c.lstat().st_mtime, now.tzinfo) >= young]
