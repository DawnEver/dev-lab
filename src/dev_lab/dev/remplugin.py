"""WHICH REM BINDS THIS SESSION: the rem plugin installed and enabled for the session's harness, read from its registry.

rem writes a session's task binding (:mod:`dev_lab.dev.taskbinding`), and only from release :data:`BINDS_SINCE` on. A
host whose rem is absent, disabled or older writes none, so a gate that finds no binding would only say "none is
bound" while the user had typed ``task: <slug>`` (a measured skew, 2026-11-16). :func:`binder_door` names that cause.

A PURE READER: it opens the harness's own plugin registry and writes nothing, spawns nothing, reaches no network.
Anything it cannot read for certain -- no harness, a missing or malformed registry, a version it cannot parse -- is
``None``, and the caller keeps its plain door. It never reads an old binding location: the binding is rem's alone.

* Claude Code: ``<config>/plugins/installed_plugins.json`` (``<config>`` = ``$CLAUDE_CONFIG_DIR`` or ``~/.claude``),
  enabled by ``enabledPlugins`` in ``<config>/settings.json``, then the checkout's ``.claude/settings.json`` and
  ``.claude/settings.local.json`` (the later layer wins; no entry anywhere is not enabled).
* Codex: ``[plugins."rem@<marketplace>"]`` in ``<codex home>/config.toml`` (``$CODEX_HOME`` or ``~/.codex``),
  ``enabled`` defaulting to true, and the versions cached under ``plugins/cache/<marketplace>/rem/<version>/``.
"""

from __future__ import annotations

import json
import re
import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from dev_lab.dev.native_session import primary_of

__all__ = ['BINDS_SINCE', 'Binder', 'binder_door', 'find']

#: The first rem release whose UserPromptSubmit hook writes the binding (cc-market #26, rem 2.6.0).
BINDS_SINCE: Final = (2, 6, 0)
_PLUGIN: Final = 'rem@cc-market'
_VERSION: Final = re.compile(r'(\d+)\.(\d+)\.(\d+)')


@dataclass(frozen=True, slots=True)
class Binder:
    """What a harness's registry says of rem: id ``rem@<marketplace>``, version (``None``: not installed), switch."""

    harness: str
    plugin: str
    version: tuple[int, int, int] | None
    enabled: bool


def _version(text: object) -> tuple[int, int, int]:
    found = _VERSION.fullmatch(str(text))
    if found is None:
        msg = f'not a release version: {text!r}'
        raise ValueError(msg)
    return int(found[1]), int(found[2]), int(found[3])


def _json(path: Path) -> dict:
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict):
        msg = f'{path} is not a JSON object'
        raise TypeError(msg)
    return data


def _claude(env: Mapping[str, str], home: Path, root: Path) -> Binder:
    config = Path(env['CLAUDE_CONFIG_DIR']) if env.get('CLAUDE_CONFIG_DIR') else home / '.claude'
    installed = _json(config / 'plugins' / 'installed_plugins.json').get('plugins') or {}
    plugin = next((name for name in installed if name.startswith('rem@')), _PLUGIN)
    versions = [_version(row['version']) for row in installed.get(plugin) or []]
    enabled = False
    for layer in (
        config / 'settings.json',
        root / '.claude' / 'settings.json',
        root / '.claude' / 'settings.local.json',
    ):
        try:
            switch = (_json(layer).get('enabledPlugins') or {}).get(plugin)
        except FileNotFoundError:
            continue
        if isinstance(switch, bool):
            enabled = switch
    return Binder('Claude Code', plugin, max(versions, default=None), enabled)


def _codex(env: Mapping[str, str], home: Path, root: Path) -> Binder:
    del root
    codex = Path(env['CODEX_HOME']) if env.get('CODEX_HOME') else home / '.codex'
    plugins = tomllib.loads((codex / 'config.toml').read_text(encoding='utf-8')).get('plugins') or {}
    plugin = next((name for name in plugins if name.startswith('rem@')), _PLUGIN)
    table = plugins.get(plugin)
    if not isinstance(table, dict):
        return Binder('Codex', plugin, None, enabled=False)
    cache = codex / 'plugins' / 'cache' / plugin.split('@', 1)[1] / 'rem'
    names = [entry.name for entry in cache.iterdir() if entry.is_dir()] if cache.is_dir() else []
    versions = [_version(name) for name in names if _VERSION.fullmatch(name)]
    return Binder('Codex', plugin, max(versions, default=None), table.get('enabled', True) is True)


#: The registry reader of each harness, by the primary session key it declares (``native_session.json``).
_READERS: Final[dict[str, Callable[[Mapping[str, str], Path, Path], Binder]]] = {
    'CLAUDE_CODE_SESSION_ID': _claude,
    'CODEX_THREAD_ID': _codex,
}


def find(env: Mapping[str, str], home: Path, root: Path) -> Binder | None:
    """What the registry of *env*'s harness says of rem, or ``None`` when it cannot be read for certain."""
    try:
        reader = _READERS.get(primary_of(env))
        return None if reader is None else reader(env, home, root)
    except (OSError, ValueError, TypeError, AttributeError, KeyError, tomllib.TOMLDecodeError):
        return None


def binder_door(env: Mapping[str, str], home: Path, root: Path) -> str | None:
    """Why rem cannot have bound this session -- absent, disabled or too old -- with its door; else ``None``.

    The door is a line of its own, so the wall it ends names one (:func:`dev_lab.dev.walls.has_remedy`).

    ``None`` also when the registry cannot be read: the caller keeps the plain door (the user's ``task:`` prompt).
    """
    binder = find(env, home, root)
    if binder is None:
        return None
    plugin, harness, since = binder.plugin, binder.harness, '.'.join(map(str, BINDS_SINCE))
    if binder.version is None:
        cause, door, verb = f'no rem plugin is installed for {harness}', f'install {plugin}', 'install'
        codex = f'`codex plugin add {plugin}`'
    elif not binder.enabled:
        cause, door, verb = f'{plugin} is installed but not enabled for {harness}', f'enable {plugin}', 'enable'
        codex = f'`enabled = true` under `[plugins."{plugin}"]` in config.toml'
    elif binder.version < BINDS_SINCE:
        found = '.'.join(map(str, binder.version))
        cause = f'{harness} runs {plugin} {found}, which predates the binding (rem binds since {since})'
        door, verb = f'update rem to >= {since}', 'update'
        codex = f'`codex plugin marketplace upgrade {plugin.split("@", 1)[1]}`, then `codex plugin add {plugin}`'
    else:
        return None
    how = f'Claude Code: `claude plugin {verb} {plugin}`; Codex: {codex}'
    door_line = f'Door: {door} ({how}), then the user binds with `task: <slug>`'
    return f'{cause}, so no prompt can bind this session.\n{door_line}'
