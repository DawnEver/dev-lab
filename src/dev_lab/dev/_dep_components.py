"""Which ``[tool.lab_commons.components]`` packages an environment holds at a tree that has since MOVED.

INCIDENT (motronics, 2026-10-19): ``components/numerics-lab`` moved to a commit adding
``TrialNotEvaluable``; its lock source is ``{ directory = "components/numerics-lab" }``, installed
non-editable at a version string that did not change, so uv called it current and every sync exited 0
over the OLD module. A version is no identity for a path build (:class:`dev_lab.dev.dep.Version`).

THE EVIDENCE is the component's own tree: its git ``HEAD``, plus a hash of ``git diff HEAD`` when it is
dirty. :func:`record` stamps it into the environment after a successful sync; :func:`changed` names every
declared package whose stamp is absent or differs, which ``dep`` reinstalls (``--reinstall-package``) on
EVERY sync -- by construction, no flag to remember. The components table (:mod:`dev_lab.dev.components`)
is the one source of which packages are components.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Final

import lab_commons.launch as _door

from dev_lab.dev.components import components_of

__all__ = ['STAMP_FILE', 'changed', 'record']

#: Where an environment keeps the trees its component packages were installed from.
STAMP_FILE: Final = 'dev-lab-components.json'

_GIT: Final = shutil.which('git') or 'git'


def _tree(path: Path) -> str:
    """``HEAD`` of the component checkout at *path*, ``+<hash>`` of its diff when dirty; ``''`` when unreadable."""

    def git(*args: str) -> str:
        done = _door.run(
            [_GIT, '-C', str(path), *args], capture_output=True, text=True, encoding='utf-8', errors='replace',
            check=False, timeout=60,
        )  # fmt: skip
        return done.stdout if done.returncode == 0 else ''

    head = git('rev-parse', 'HEAD').strip()
    diff = git('diff', 'HEAD') + git('ls-files', '--others', '--exclude-standard')
    return head + (f'+{hashlib.sha256(diff.encode()).hexdigest()[:16]}' if diff else '') if head else ''


def _stamps(root: Path) -> dict[str, str]:
    manifest = root / 'pyproject.toml'
    rows = components_of(manifest.read_text(encoding='utf-8')) if manifest.is_file() else ()
    return {row.package: _tree(root / row.path) for row in rows if row.package}


def _recorded(prefix: Path) -> dict[str, str]:
    try:
        found = json.loads((prefix / STAMP_FILE).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    return found if isinstance(found, dict) else {}


def changed(root: Path, prefix: Path) -> tuple[str, ...]:
    """Every component package of *root* whose tree differs from the one *prefix* was last synced at."""
    recorded = _recorded(prefix)
    return tuple(sorted(name for name, tree in _stamps(root).items() if not tree or recorded.get(name) != tree))


def record(root: Path, prefix: Path) -> None:
    """Stamp *prefix* with the trees *root*'s components are at now -- only after a sync that succeeded."""
    prefix.mkdir(parents=True, exist_ok=True)
    (prefix / STAMP_FILE).write_text(json.dumps(_stamps(root), indent=2, sort_keys=True), encoding='utf-8')
