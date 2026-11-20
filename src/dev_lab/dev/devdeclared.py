"""The effective ``[dev]`` declaration of a host: the family's table under the host file's.

Split from :mod:`dev_lab.dev.devhost` at the module-size band (2026-11-20) so the credential doors
(:mod:`dev_lab.dev.forgecredential`, :mod:`dev_lab.dev.devcredential`) read a machine's declaration without the
render. A host with no host file falls back to the family's default profile (:mod:`dev_lab.dev.devprofile`).
"""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from dev_lab.dev import devprofile

__all__ = ['declared', 'declared_by', 'merge']


def _read(path: Path) -> dict[str, Any]:
    return tomllib.loads(path.read_text(encoding='utf-8'))


def merge(under: Mapping[str, Any], over: Mapping[str, Any]) -> dict[str, Any]:
    """*under* with *over* laid on top, tables merged key by key and every other value replaced."""
    out = dict(under)
    for key, value in over.items():
        both = isinstance(value, Mapping) and isinstance(out.get(key), Mapping)
        out[key] = merge(out[key], value) if both else value
    return out


def declared(host_file: Path, family_file: Path) -> dict[str, Any]:
    """The effective ``[dev]``: the family's under the host's -- under the default profile's for an undeclared host."""
    family = _read(family_file) if family_file.is_file() else {}
    shared = devprofile.family_dev(family)
    if not host_file.is_file():
        host, _ = devprofile.host_declaration(family_file.parent, host_file.stem)
        return {**shared, **host['dev']}  # the profile REPLACES a shared key: its forges = {} grants no account
    return merge(shared, _read(host_file).get('dev', {}))


def declared_by(own: Mapping[str, Any]) -> dict[str, Any]:
    """The effective ``[dev]`` of the host and clone a render recorded (*own*: its ``host`` and ``source``)."""
    if not own.get('host') or not own.get('source'):
        return {}
    source = Path(own['source'])
    return declared(source / 'hosts' / f'{own["host"]}.toml', source / 'family.toml')
