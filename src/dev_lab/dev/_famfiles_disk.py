"""The project files a checkout TRACKS, against the family list: what is on disk, unaccounted for, or unplaced.

Split out of :mod:`dev_lab.dev.famfiles` (2026-11-25, MODULE-SIZE-ALARM) along its own seam: that module is the
list and its renderers, imported by the light merge job (through ``GENERATED``); this one reads a checkout's git
index and the CI declaration, so the heavy ciworkflows import stays here, off the light path.
"""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

import lab_commons.launch as _door

from dev_lab.dev import ciworkflowshape
from dev_lab.dev.ciworkflows import declared_paths
from dev_lab.dev.famfiles import PROJECT_FILES, RETIRED_PROJECT_FILES

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

__all__ = ['project_files_on_disk', 'unaccounted', 'unplaced_workflows']


def _git_lines(root: Path, *args: str) -> tuple[str, ...]:
    done = _door.run(
        [shutil.which('git') or 'git', '-C', str(root), *args],
        capture_output=True,
        text=True,
        encoding='utf-8',
        check=False,
        timeout=60,
    )
    if done.returncode != 0:
        msg = f'git {" ".join(args)} failed in {root}: {done.stderr.strip()}'
        raise RuntimeError(msg)
    return tuple(line for line in done.stdout.splitlines() if line)


def project_files_on_disk(root: Path) -> tuple[str, ...]:
    """The tracked project-level files of *root*: every top-level FILE, plus the registry's nested paths."""
    tracked = _git_lines(root, 'ls-files')
    nested = {path for path in (*PROJECT_FILES, *RETIRED_PROJECT_FILES) if '/' in path}
    return tuple(sorted(path for path in tracked if '/' not in path or path in nested or _is_workflow(path)))


def _is_workflow(path: str) -> bool:
    return any(
        path.startswith(f'{directory.as_posix()}/') and path.count('/') == directory.as_posix().count('/') + 1
        for directory in ciworkflowshape.WORKFLOW_DIRS.values()
    )


def unaccounted(root: Path, owned_here: Mapping[str, str]) -> tuple[str, ...]:
    """Project-level files in *root* that neither the family list nor the repo's own *owned_here* names."""
    known = {*PROJECT_FILES, *RETIRED_PROJECT_FILES, *owned_here}
    return tuple(path for path in project_files_on_disk(root) if path not in known and not _is_workflow(path))


def unplaced_workflows(root: Path) -> tuple[str, ...]:
    """Tracked workflow files of *root* its ``[tool.dev_lab.ci]`` does not place (``ciworkflows.declared_paths``)."""
    on_disk = [path for path in project_files_on_disk(root) if _is_workflow(path)]
    if not on_disk:
        return ()
    allowed = declared_paths(root)
    return tuple(path for path in on_disk if path not in allowed)
