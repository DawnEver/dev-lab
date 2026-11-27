"""A REPO'S MANIFEST TEXT -- its own ``pyproject.toml``, or the declaration its family row implies.

A repo with no manifest of its own (a data repo) is declared once, by its ``[family_repos]`` row. Split from
:mod:`dev_lab.dev.familyrepos` because the hook path reads it (:mod:`dev_lab.dev.lanepolicy`): this module imports
nothing beyond the machine config and one git read, never the clone or network doors.
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

from lab_commons import config as machineconfig

from dev_lab.dev.checkout import git_out

__all__ = ['FAMILY_TABLE', 'declaration', 'family_rows', 'live_config', 'manifest_text', 'remote_key']

#: The shared layer's table: name -> ``{remote, branch}``.
FAMILY_TABLE: Final = 'family_repos'


def remote_key(url: str) -> str:
    """A remote url as ``host/owner/name``, lower case: scheme, user, ``.git`` and a trailing slash dropped."""
    text = url.strip().lower()
    text = re.sub(r'^[a-z][a-z0-9+.-]*://', '', text)
    text = re.sub(r'^[^/@]+@', '', text).replace(':', '/', 1) if '@' in text.split('/', 1)[0] else text
    return re.sub(r'(?:\.git)?/*$', '', text)


def family_rows(live: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    """The ``[family_repos]`` rows of *live*, name -> row; a malformed table reads as none."""
    table = live.get(FAMILY_TABLE, {})
    return {name: row for name, row in table.items() if isinstance(row, Mapping)} if isinstance(table, Mapping) else {}


def live_config(machine: Path | None) -> dict[str, Any]:
    """The machine config at *machine* (default: this machine's); a missing file reads as empty."""
    path = machine or machineconfig.config_path()
    return tomllib.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}


def declaration(remote: str, live: Mapping[str, Any]) -> str:
    """The ``[tool.dev_lab.*]`` text the family row for *remote* implies (``''`` when no row names it).

    A repo with no manifest of its own (a data repo) is declared once, by its family row: its ``branch`` is both
    its trunk and its integration branch; the branch set's other keys keep their family defaults.
    """
    wanted = remote_key(remote)
    for row in family_rows(live).values():
        branch = str(row.get('branch', '')).strip()
        if branch and remote_key(str(row.get('remote', ''))) == wanted:
            return (
                f'[tool.dev_lab.branchset]\ntrunk = "{branch}"\nsessions = []\n\n'
                f'[tool.dev_lab.integrator]\nintegration = "{branch}"\n'
            )
    return ''


def manifest_text(root: Path) -> tuple[str, str]:
    """*root*'s ``pyproject.toml`` text and name; with none, its family row's :func:`declaration` and its source.

    No manifest and no row: ``''`` and a name pointing at both doors, so each reader refuses naming them.
    """
    manifest = root / 'pyproject.toml'
    if manifest.is_file():
        return manifest.read_text(encoding='utf-8'), str(manifest)

    remote = (git_out(root, 'remote', 'get-url', 'origin') or '').strip()
    try:
        text = declaration(remote, live_config(None)) if remote else ''
    except OSError, ValueError:
        text = ''
    if text:
        return text, f'[{FAMILY_TABLE}] row for {remote} in {machineconfig.config_path()}'
    return '', f'{manifest} (or a [{FAMILY_TABLE}] row for this repo in the config source)'
