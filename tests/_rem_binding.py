"""Stand in for rem: write a binding exactly as rem's prompt hook does, and plant the harness registries naming rem.

rem owns the binding and is its only writer (its ``hooks/task-authority.js``, on the user's ``task: <slug>`` prompt);
dev-lab only reads it (:mod:`dev_lab.dev.taskbinding`). The contract is rem's ``skills/rem/reference/tasks.md``
section "The binding file", pinned on rem's side by ``tests/task-bind.test.mjs``. This helper writes that shape --
``<ledger>/.bindings/<session>.json`` = ``{"session": <id>, "task": "<slug>@<authority>"}`` -- and nothing else.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from dev_lab.dev import taskbinding

if TYPE_CHECKING:
    from pathlib import Path

#: The plugin id the planted registries name.
_REM = 'rem@cc-market'


def bind_as_rem(root: Path, session: str, slug: str) -> str:
    """Bind *session* to the OPEN task *slug* of *root*'s ledger as rem would; the task id written."""
    task = taskbinding.task_id(root, slug)
    target = taskbinding.ledger(root) / taskbinding.BINDINGS / f'{session}.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({'session': session, 'task': task}), encoding='utf-8')
    return task


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
