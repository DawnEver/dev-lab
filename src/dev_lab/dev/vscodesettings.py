"""The editor keys a checkout's ``.vscode/settings.json`` carries, rendered from facts declared elsewhere.

The directories an editor must not index or watch ARE the bulky trees a checkout holds: the in-tree defaults of
:data:`lab_commons.storage.KINDS` (output, venvs, worktrees, build), the venv pointer of
:data:`dev_lab.dev.venvpath.VENV_LAYOUTS`, and whatever the repo declares as its own
(``[tool.dev_lab.vscode] exclude = ["attic"]``). Nothing here lists a directory by hand.

Only the MANAGED keys are written; every other key of the file is the user's and is kept as it was. The file
is read as strict JSON: a ``settings.json`` holding comments is refused by name rather than rewritten, because
a rewrite would silently drop them. ``render`` writes, ``check`` reports drift (exit 1), and :func:`follow`
renders on a session start or a relock (:mod:`dev_lab.dev.venvfollow`) without ever raising.

``python -m dev_lab.dev.vscodesettings render|check [--repo PATH]``
"""

from __future__ import annotations

import argparse
import json
import tomllib
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, Final

from lab_commons.log import emit
from lab_commons.storage import KINDS

from dev_lab.dev.family import declared_table
from dev_lab.dev.venvpath import VENV_LAYOUTS

if TYPE_CHECKING:
    from collections.abc import Iterable

__all__ = [
    'RELATIVE',
    'RENDER_COMMAND',
    'TABLE',
    'SettingsError',
    'check',
    'drift',
    'excluded',
    'follow',
    'main',
    'managed',
    'render',
]

#: Where the editor reads a folder's settings.
RELATIVE: Final = PurePosixPath('.vscode/settings.json')
#: The repo's own table: ``exclude`` names directories only that repo holds.
TABLE: Final = 'vscode'
#: The one door that writes the managed keys.
RENDER_COMMAND: Final = 'python -m dev_lab.dev.vscodesettings render'


class SettingsError(ValueError):
    """A declaration or a settings file refused: the message names the file or key and its remedy."""


def _repo_extras(root: Path) -> tuple[str, ...]:
    path = root / 'pyproject.toml'
    if not path.is_file():
        return ()
    table = declared_table(tomllib.loads(path.read_text(encoding='utf-8')), TABLE, {})
    extra = table.get('exclude', []) if isinstance(table, dict) else None
    if not isinstance(extra, list) or not all(isinstance(item, str) and item.strip('/') for item in extra):
        msg = f'{path}: [tool.dev_lab.{TABLE}] exclude must be a list of directory names, e.g. ["attic"]'
        raise SettingsError(msg)
    return tuple(item.strip('/') for item in extra)


def _outermost(paths: Iterable[str]) -> tuple[str, ...]:
    """Drop every path that lies inside another: a nested kind is already covered by its parent."""
    unique = sorted({PurePosixPath(path).as_posix() for path in paths})
    return tuple(path for path in unique if not any(path != other and path.startswith(f'{other}/') for other in unique))


def excluded(root: Path) -> tuple[str, ...]:
    """Every directory an editor of *root* must neither index nor watch, outermost only, sorted."""
    kinds = (default for default in KINDS.values() if default is not None)
    pointers = {layout[0] for layout in VENV_LAYOUTS.values()}
    return _outermost((*kinds, *pointers, *_repo_extras(root)))


def managed(root: Path) -> dict[str, Any]:
    """The keys this module owns in *root*'s ``settings.json``, with the values they must hold."""
    dirs = excluded(root)
    return {
        'npm.autoDetect': 'off',
        'search.followSymlinks': False,
        'search.exclude': {f'**/{name}': True for name in dirs},
        'files.watcherExclude': {f'**/{name}/**': True for name in dirs},
    }


def _read(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding='utf-8') or '{}')
    except json.JSONDecodeError as exc:
        msg = (
            f'{path} is not strict JSON ({exc.msg} at line {exc.lineno}); comments or trailing commas would be lost '
            f'on a rewrite -- remove them, then re-run `{RENDER_COMMAND}`'
        )
        raise SettingsError(msg) from exc
    if not isinstance(data, dict):
        msg = f'{path} must hold a JSON object'
        raise SettingsError(msg)
    return data


def drift(root: Path) -> tuple[str, ...]:
    """The managed keys whose value in *root*'s settings file is not the rendered one."""
    current = _read(root / RELATIVE)
    return tuple(key for key, value in managed(root).items() if current.get(key) != value)


def render(root: Path) -> tuple[str, ...]:
    """Write the managed keys into *root*'s settings file, keeping every other key; the keys that changed."""
    path = root / RELATIVE
    current = _read(path)
    changed = drift(root)
    if changed:
        merged = {**current, **managed(root)}
        path.parent.mkdir(parents=True, exist_ok=True)
        fresh = path.with_name(f'{path.name}.new')
        fresh.write_text(json.dumps(merged, indent=2) + '\n', encoding='utf-8', newline='\n')
        fresh.replace(path)
    return changed


def check(root: Path) -> int:
    """0 when the managed keys hold their rendered values, else 1 naming each key and the door."""
    stale = drift(root)
    for key in stale:
        emit(f'[vscode] {root / RELATIVE}: {key} is not the rendered value -- run `{RENDER_COMMAND}`')
    return 1 if stale else 0


def follow(root: Path) -> str:
    """Render on a session start or relock; never raises, ``''`` when nothing changed."""
    try:
        changed = render(root)
    except (SettingsError, OSError, ValueError) as exc:
        return f'vscode {root}: not rendered -- {exc}'
    return f'vscode {root}: rendered {", ".join(changed)}' if changed else ''


def main(argv: list[str] | None = None) -> int:
    """CLI: ``render`` writes the managed keys, ``check`` reports drift."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument('verb', choices=('render', 'check'))
    parser.add_argument('--repo', type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    root = args.repo.resolve()
    try:
        if args.verb == 'check':
            return check(root)
        changed = render(root)
    except SettingsError as exc:
        emit(f'[vscode] refused -- {exc}')
        return 2
    emit(f'[vscode] {root / RELATIVE}: ' + (f'rendered {", ".join(changed)}' if changed else 'already current'))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
