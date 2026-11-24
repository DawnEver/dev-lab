"""THE RENDERED ``.claude/settings.json`` (user ruling 2026-11-24): family base plus the repo's declared delta.

The whole file is a render, like ``.gitignore``: a hand edit reds (:func:`drift`). The family base is

* ``hooks`` -- every event's rows from :func:`dev_lab.dev.agent_wiring.rows` (the family's and the repo's declared
  ``[[tool.dev_lab.agent_hooks]]``), the same rows :func:`dev_lab.dev.agent_guard.wire_settings` wires;
* ``permissions.allow`` -- the door rows of :func:`dev_lab.dev.autodoors.claude_rows`, the one source that also
  renders ``.codex/rules/family-doors.rules``;
* ``env.MPLBACKEND = "Agg"`` -- no agent run opens a plot window.

The repo's delta is ``[tool.dev_lab.claude]`` in its ``pyproject.toml``: ``env`` (a table merged over the base's),
``allow`` and ``deny`` (lists appended to the permissions). ``enabledPlugins`` is not written: the sharp-review
switch retired with the plugin. ``settings.local.json`` stays machine-local and is never rendered.

``python -m dev_lab.dev.claudesettings render|check [--repo PATH] [--shell-door REL ...]``
"""

from __future__ import annotations

import argparse
import json
import tomllib
from pathlib import Path
from typing import Any, Final

from lab_commons.log import emit

from dev_lab.dev import autodoors
from dev_lab.dev.agent_wiring import SETTINGS_REL, rows
from dev_lab.dev.family import declared_table

__all__ = ['BASE_ENV', 'DELTA_TABLE', 'RENDER_COMMAND', 'document', 'drift', 'main', 'render', 'write']

#: The environment every agent session of a family repo runs with.
BASE_ENV: Final[dict[str, str]] = {'MPLBACKEND': 'Agg'}
#: The repo's delta: ``[tool.dev_lab.claude]``.
DELTA_TABLE: Final = 'claude'
_DELTA_KEYS: Final = frozenset({'env', 'allow', 'deny'})
RENDER_COMMAND: Final = 'python -m dev_lab.dev.claudesettings render'


def _delta(root: Path) -> dict[str, Any]:
    path = root / 'pyproject.toml'
    data = tomllib.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}
    delta = dict(declared_table(data, DELTA_TABLE, {}))
    if unknown := sorted(set(delta) - _DELTA_KEYS):
        msg = f'[tool.dev_lab.{DELTA_TABLE}] declares {unknown}; a delta holds only {sorted(_DELTA_KEYS)}'
        raise ValueError(msg)
    return delta


def _hooks(root: Path) -> dict[str, list[dict[str, Any]]]:
    hooks: dict[str, list[dict[str, Any]]] = {}
    for row in rows(root):
        hook = {'type': 'command', 'command': row.command, 'timeout': row.timeout}
        entry = {'matcher': row.matcher, 'hooks': [hook]} if row.matcher else {'hooks': [hook]}
        hooks.setdefault(row.event, []).append(entry)
    return hooks


def document(root: Path, *, shell_doors: tuple[str, ...] = ()) -> dict[str, Any]:
    """The settings document *root* renders: the family base, then its ``[tool.dev_lab.claude]`` delta."""
    delta = _delta(root)
    doors = autodoors.claude_rows(autodoors.script_doors(root, shell_doors=shell_doors), autodoors.cli_doors(root))
    permissions: dict[str, list[str]] = {'allow': [*sorted(doors), *delta.get('allow', [])]}
    if delta.get('deny'):
        permissions['deny'] = list(delta['deny'])
    return {'env': {**BASE_ENV, **delta.get('env', {})}, 'hooks': _hooks(root), 'permissions': permissions}


def render(root: Path, *, shell_doors: tuple[str, ...] = ()) -> str:
    """The file's bytes: :func:`document` as indented JSON, newline-terminated."""
    return json.dumps(document(root, shell_doors=shell_doors), indent=2, ensure_ascii=False) + '\n'


def drift(root: Path, *, shell_doors: tuple[str, ...] = ()) -> str | None:
    """Why *root*'s settings file is not the render (absent, or hand-edited / stale), else ``None``."""
    path = root / SETTINGS_REL
    if not path.is_file():
        return f'{SETTINGS_REL}: absent -- {RENDER_COMMAND}'
    if path.read_text(encoding='utf-8') != render(root, shell_doors=shell_doors):
        return f'{SETTINGS_REL}: differs from the render (hand-edited, or a source moved) -- {RENDER_COMMAND}'
    return None


def write(root: Path, *, shell_doors: tuple[str, ...] = ()) -> str:
    """Render *root*'s settings file; one status line."""
    path = root / SETTINGS_REL
    text = render(root, shell_doors=shell_doors)
    if path.is_file() and path.read_text(encoding='utf-8') == text:
        return f'{SETTINGS_REL}: current'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8', newline='\n')
    return f'{SETTINGS_REL}: rendered'


def main(argv: list[str] | None = None) -> int:
    """CLI: ``render`` writes, ``check`` exits 1 naming the drift."""
    parser = argparse.ArgumentParser(description='Render a family repo`s .claude/settings.json.')
    parser.add_argument('action', choices=('render', 'check'))
    parser.add_argument('--repo', type=Path, default=Path.cwd())
    parser.add_argument('--shell-door', action='append', default=[], help='a repo-relative shell door (repeatable)')
    args = parser.parse_args(argv)
    root, doors = args.repo.resolve(), tuple(args.shell_door)
    if args.action == 'check':
        problem = drift(root, shell_doors=doors)
        emit(f'[claudesettings] {problem or f"{SETTINGS_REL}: current"}')
        return 1 if problem else 0
    emit(f'[claudesettings] {write(root, shell_doors=doors)}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
