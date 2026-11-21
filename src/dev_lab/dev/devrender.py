"""The machine file RENDERED: family ⊕ host ⊕ local, with a header naming the sources and their digests.

:mod:`dev_lab.dev.devhost` states the three layers and owns the verbs (``render``, ``drift``, ``local``); this
module is the render itself and the config source it reads, split from ``devhost`` at the module-size band
(2026-11-21) so every reader of a render (``devhost``, ``hpcaccount``, ``bringup``, ``planrun``) imports it one way.
"""

from __future__ import annotations

import hashlib
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

from lab_commons import config as machineconfig

from dev_lab.dev import accounthost, devprofile
from dev_lab.dev._machinefile import dumps
from dev_lab.dev.checkout import git_out
from dev_lab.dev.devdeclared import OWN_TABLE, declared, merge
from dev_lab.dev.devschema import CHANNELS_TABLE, hpc_reach
from dev_lab.dev.venvpath import running_interpreter

__all__ = ['RENDER_DOOR', 'config_source', 'host_file', 'read_toml', 'render', 'sources']

#: The door that re-renders this machine's file from its recorded host and clone.
RENDER_DOOR: Final = f'{running_interpreter()} -m dev_lab.dev.devhost render --write'


def read_toml(path: Path) -> dict[str, Any]:
    """*path* parsed as TOML."""
    return tomllib.loads(path.read_text(encoding='utf-8'))


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def host_file(host: str) -> str:
    """Where *host*'s declaration lives in the config source, relative to its root."""
    return f'hosts/{host}.toml'


def sources(clone: Path, host: str) -> tuple[Path, Path]:
    """The family file and *host*'s host file in the config-source *clone*."""
    return clone / 'family.toml', clone / host_file(host)


def config_source(live: Mapping[str, Any] | None = None) -> str:
    """The config source's forge URL: the ``origin`` of the clone the machine file's ``[devhost]`` names.

    Raises:
        ValueError: the machine file is not a render (no ``[devhost] source``), the source is relative (it would
            follow the CWD to another clone, #556), or that clone has no ``origin``.

    """
    own = (machineconfig.machine() if live is None else live).get(OWN_TABLE, {})
    if not own.get('source'):
        msg = f'the machine file has no [{OWN_TABLE}] source: render it (devhost render --host NAME --from CLONE)'
        raise ValueError(msg)
    if not Path(own['source']).is_absolute():
        msg = (f"the machine file's [{OWN_TABLE}] source {own['source']!r} is relative, so it would resolve against "
               f"the current directory and read another clone's origin: re-render it with an absolute clone -- "
               f"devhost render --host {own.get('host') or 'NAME'} --from <absolute clone> --write")  # fmt: skip
        raise ValueError(msg)
    url = git_out(Path(own['source']), 'remote', 'get-url', 'origin')
    if not url:
        msg = f'{own["source"]} has no origin remote: the config source is unknown here'
        raise ValueError(msg)
    return url.strip()


def _family_facts_stay_home(layered: Mapping[str, Any], family: Mapping[str, Any], clone: Path) -> dict[str, Any]:
    """*layered* without every leaf the family file holds, and with ``[family] source`` naming that file's clone.

    The machine file is the host and local layers only: a reader layers the family file under it
    (``lab_commons.config.section``) and refuses any leaf both hold. Measured 2026-11-20: the render copied the
    family's ``[storage] remotes`` and then ``[breakglass] endpoint`` into the machine file and both readers refused.

    Raises:
        ValueError: the host layer gives a family leaf another value -- the reader refuses a restated leaf, so the
            value is changed in the family file (or the host declares a key the family does not hold).

    """

    def strip(rows: Mapping[str, Any], shared: Mapping[str, Any], where: str) -> dict[str, Any]:
        kept: dict[str, Any] = {}
        for key, value in rows.items():
            if key not in shared or key == machineconfig.FAMILY_TABLE:
                kept[key] = value
            elif isinstance(value, Mapping) and isinstance(shared[key], Mapping):
                if inner := strip(value, shared[key], f'{where}.{key}' if where else key):
                    kept[key] = inner
            elif value != shared[key]:
                leaf = f'[{where}].{key}' if where else key
                msg = (f'{leaf} = {value!r} gives the family key ({shared[key]!r}) another value: change it in the '
                       f'family file through its pull request, then {RENDER_DOOR}')  # fmt: skip
                raise ValueError(msg)
        return kept

    kept = strip(layered, family, '')
    kept.setdefault(machineconfig.FAMILY_TABLE, {'source': clone.resolve().as_posix()})
    return kept


def render(clone: Path, host: str, live: Mapping[str, Any]) -> str:
    """The machine file for *host*: family ⊕ host (``[dev]`` aside) ⊕ the *live* file's local-only tables."""
    family_file, host_file = sources(clone, host)
    family = read_toml(family_file)
    parsed, unmanaged = devprofile.host_declaration(clone, host)
    layered = merge({k: v for k, v in family.items() if k != 'dev'}, {k: v for k, v in parsed.items() if k != 'dev'})
    vendors = parsed.get('dev', {}).get('vendors', {})
    seats = {name: {'seats': vendor['seats']} for name, vendor in vendors.items() if vendor.get('seats')}
    layered = merge(layered, {'capabilities': seats} if seats else {})
    layered = merge(layered, {'hpc': {'reach': hpc_reach(parsed.get('dev', {}))}} if 'hpc' in layered else {})
    layered = merge(layered, accounthost.derived(host, family) if accounthost.is_account(parsed) else {})
    if not accounthost.is_account(parsed):
        dev = declared(host_file, family_file)
        layered = merge(layered, devprofile.bridge_tables(dev, live))
        layered = merge(layered, {OWN_TABLE: {'hooks': dev['hooks']}} if 'hooks' in dev else {})
    if channels := parsed.get('dev', {}).get('channels'):
        layered = merge(layered, {CHANNELS_TABLE: {'channels': channels}})
    shared = {k: v for k, v in family.items() if k != 'dev'}
    layered = _family_facts_stay_home(layered, shared, clone)
    # a local table never holds a family table: an older render's copy of one is dropped, not kept as local
    local = {k: v for k, v in live.items() if k not in layered and k not in shared and k != OWN_TABLE}
    own = {'host': host, 'source': clone.resolve().as_posix()}  # absolute: never the reader's CWD (#556)
    own |= {devprofile.UNMANAGED: host} if unmanaged else {}
    own = {OWN_TABLE: {**layered.pop(OWN_TABLE, {}), **own}}
    declaration = 'is the family default (unmanaged)' if unmanaged else f'sha256:{_digest(host_file)}'
    header = (
        f'# RENDERED by python -m dev_lab.dev.devhost render --host {host}: edit the sources, not this file.\n'
        f'# family.toml sha256:{_digest(family_file)}; hosts/{host}.toml {declaration}; '
        f'this machine keeps {sorted(local)}.\n\n'
    )
    return header + dumps({**layered, **local, **own})
