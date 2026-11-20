"""The effective ``[dev]`` declaration of a host: the family's table under the host file's.

Split from :mod:`dev_lab.dev.devhost` at the module-size band (2026-11-20) so the credential doors
(:mod:`dev_lab.dev.forgecredential`, :mod:`dev_lab.dev.devcredential`) read a machine's declaration without the
render. It owns ``OWN_TABLE``, the machine file's record of the host and clone it was rendered from. A host
with no host file falls back to the family's default profile (:mod:`dev_lab.dev.devprofile`).
"""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

from lab_commons import config as machineconfig

from dev_lab.dev import devprofile

__all__ = ['OWN_TABLE', 'declared', 'declared_by', 'layered', 'merge', 'this_machine']

#: The render's own table in a machine file: which host and clone it came from.
OWN_TABLE: Final = 'devhost'


def _read(path: Path) -> dict[str, Any]:
    return tomllib.loads(path.read_text(encoding='utf-8'))


def merge(under: Mapping[str, Any], over: Mapping[str, Any]) -> dict[str, Any]:
    """*under* with *over* laid on top, tables merged key by key and every other value replaced."""
    out = dict(under)
    for key, value in over.items():
        both = isinstance(value, Mapping) and isinstance(out.get(key), Mapping)
        out[key] = merge(out[key], value) if both else value
    return out


def layered(live: Mapping[str, Any]) -> dict[str, Any]:
    """*live* over the family file its ``[family] source`` names (``[dev]`` aside): the whole machine a reader sees.

    A rendered machine file holds the host and local layers only; a caller handed the whole file (drift, the
    family-repo census) reads family facts through this view, never from a copy in the machine file.
    """
    declared_family = live.get(machineconfig.FAMILY_TABLE)
    if not isinstance(declared_family, Mapping) or 'source' not in declared_family:
        return dict(live)
    source = Path(str(declared_family['source'])).expanduser()
    path = source / str(declared_family.get('file', 'family.toml')) if source.is_dir() else source
    family = {k: v for k, v in _read(path).items() if k != 'dev'} if path.is_file() else {}
    return merge(family, live)


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


def this_machine(host_config: Path | None = None) -> dict[str, Any]:
    """The effective ``[dev]`` of *host_config*, else of the host and clone this machine's render records."""
    if host_config is not None:
        return declared(host_config, host_config.parent.parent / 'family.toml')
    return declared_by(machineconfig.machine().get(OWN_TABLE, {}))
