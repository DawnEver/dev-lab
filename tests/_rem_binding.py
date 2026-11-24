"""Stand in for rem: write a binding exactly as rem's prompt hook does, and plant the harness registries naming rem.

rem owns the binding and is its only writer (its ``hooks/task-authority.js``, on the user's ``task: <slug>`` prompt);
dev-lab only reads it (:mod:`dev_lab.dev.taskbinding`). The contract is rem's ``skills/rem/reference/tasks.md``
section "The binding file", pinned on rem's side by ``tests/task-bind.test.mjs`` and the shared fixture
``_rem_fixtures/session-binding.jsonl``. This helper writes that shape --
``<machine home>/state/sessions/<session>.json``
= ``{"session": <id>, "task": "<slug>@<authority>", "ledger": {"repo_key": ..., "path": <ledger>}}`` (D34) -- and
nothing else; :func:`bind_in_retired_store` plants the retired per-repo record a reader must refuse.
"""

from __future__ import annotations

import hashlib
import json
import sys
from typing import TYPE_CHECKING

from dev_lab.dev import taskbinding

if TYPE_CHECKING:
    from pathlib import Path

#: The plugin id the planted registries name.
_REM = 'rem@cc-market'


def repo_key(common: str, *, caseless: bool = sys.platform in {'win32', 'darwin'}) -> str:
    """lab_commons.repostate's key of the repo whose common git dir is spelled *common* (posix): ``<name>-<digest>``."""
    text = common.casefold() if caseless else common
    name = common.rstrip('/').rsplit('/', 2)[-2] if common.endswith('/.git') else common.rstrip('/').rsplit('/', 1)[-1]
    return f'{name}-{hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]}'


def bind_as_rem(root: Path, session: str, slug: str) -> str:
    """Bind *session* to the OPEN task *slug* of *root*'s ledger as rem would; the task id written."""
    task = taskbinding.task_id(root, slug)
    tasks = taskbinding.ledger(root)
    record = {
        'session': session,
        'task': task,
        'ledger': {'repo_key': repo_key(tasks.parent.parent.joinpath('.git').as_posix()), 'path': tasks.as_posix()},
    }
    target = taskbinding.binding_path(session)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(record), encoding='utf-8')
    return task


def bind_in_retired_store(root: Path, session: str, slug: str) -> Path:
    """The record the retired per-repo store held, ``<ledger>/.bindings/<session>.json``; its path."""
    target = taskbinding.ledger(root) / taskbinding.RETIRED_BINDINGS / f'{session}.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({'session': session, 'task': taskbinding.task_id(root, slug)}), encoding='utf-8')
    return target


def plant_claude_rem(home: Path, version: str | None, *, enabled: bool | None = True, plugin: str = _REM) -> None:
    """Claude Code's registry under *home*: *version* installed (``None``: not installed), its enabledPlugins switch."""
    plugins = home / '.claude' / 'plugins'
    plugins.mkdir(parents=True, exist_ok=True)
    installs = {} if version is None else {plugin: [{'scope': 'user', 'version': version, 'installPath': 'x'}]}
    (plugins / 'installed_plugins.json').write_text(json.dumps({'version': 2, 'plugins': installs}), encoding='utf-8')
    settings = {} if enabled is None else {'enabledPlugins': {plugin: enabled}}
    (home / '.claude' / 'settings.json').write_text(json.dumps(settings), encoding='utf-8')


def plant_codex_rem(home: Path, *versions: str, enabled: bool = True) -> None:
    """Codex's registry under *home*: config.toml's rem table and the cached *versions*."""
    root = home / '.codex'
    root.mkdir(parents=True, exist_ok=True)
    (root / 'config.toml').write_text(f'[plugins."{_REM}"]\nenabled = {str(enabled).lower()}\n', encoding='utf-8')
    for version in versions:
        (root / 'plugins' / 'cache' / 'cc-market' / 'rem' / version).mkdir(parents=True, exist_ok=True)


def plant_agy_rem(
    home: Path,
    version: str | None,
    *,
    enabled: bool | None = None,
    manifest_disabled: bool = False,
    include_only: list[str] | None = None,
    claude_fallback: bool = False,
    tilde_path: bool = False,
) -> None:
    """Antigravity's registry under *home*: ``plugins.json``, the market dir, and optional ``config.json``."""
    gemini = home / '.gemini' / 'config'
    gemini.mkdir(parents=True, exist_ok=True)
    market = home / 'cc-market'
    entry: dict[str, object] = {'path': '~/cc-market' if tilde_path else market.as_posix()}
    if include_only is not None:
        entry['include_only'] = include_only
    (gemini / 'plugins.json').write_text(json.dumps({'entries': [entry]}), encoding='utf-8')
    if version is not None:
        sub = '.claude-plugin' if claude_fallback else '.antigravity-plugin'
        manifest_dir = market / 'rem' / sub
        manifest_dir.mkdir(parents=True, exist_ok=True)
        manifest: dict[str, object] = {'name': 'rem', 'version': version}
        if manifest_disabled:
            manifest['disabled'] = True
        (manifest_dir / 'plugin.json').write_text(json.dumps(manifest), encoding='utf-8')
    if enabled is not None:
        (gemini / 'config.json').write_text(json.dumps({'plugins': {'rem': {'enabled': enabled}}}), encoding='utf-8')
