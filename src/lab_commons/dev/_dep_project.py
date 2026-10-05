"""Target project declarations and commands for the dependency door."""

import os
import shutil
import subprocess
import sys
import tomllib
from collections.abc import Sequence
from pathlib import Path

from lab_commons.dev.installdoor import floating_requirements
from lab_commons.dev.venvpath import venv_interpreter


def _checkout(cwd: Path, git_binary: str) -> tuple[Path, Path] | None:
    result = subprocess.run(
        [git_binary, '-C', str(cwd), 'rev-parse', '--show-toplevel', '--git-common-dir'],
        capture_output=True,
        text=True,
        encoding='utf-8',
        check=False,
        timeout=30,
    )
    if result.returncode:
        return None
    lines = result.stdout.splitlines()
    common = Path(lines[1])
    return Path(lines[0]).resolve(), (cwd / common).resolve()


def target_root(root: Path | None, cwd: Path) -> Path:
    """A primary checkout's environment may move only from that checkout."""
    git_binary = shutil.which('git')
    if git_binary is None:
        msg = 'git is required to identify the target worktree safely'
        raise FileNotFoundError(msg)
    current = _checkout(cwd, git_binary)
    target = (cwd / root).resolve() if root is not None else current[0] if current else cwd.resolve()
    checkout = _checkout(target, git_binary)
    if checkout is not None and target == checkout[1].parent and (current is None or current[0] != target):
        msg = f'a worktree may not mutate main at {target}; bootstrap its own environment'
        raise ValueError(msg)
    return target


def uv_command(
    root: Path, python: str, selected: Sequence[str], *, syncing: bool, upgrade_packages: Sequence[str]
) -> list[str]:
    """One target-addressed command; a sync re-resolves every declared floating Git requirement."""
    uv = shutil.which('uv')
    if uv is None:
        msg = 'bootstrap/sync requires uv on PATH'
        raise FileNotFoundError(msg)
    command = [
        uv,
        'sync' if syncing else 'lock',
        '--project',
        str(root),
        '--python',
        python if Path(python).is_file() else sys.executable,
    ]
    if syncing:
        for extra in selected:
            command.extend(('--extra', extra))
    upgrades = set(upgrade_packages)
    if syncing:
        upgrades.update(floating_requirements(root / 'pyproject.toml'))
    for package in sorted(upgrades):
        command.extend(('--upgrade-package', package))
    return command


def anchor_paths(root: Path, anchors: object) -> tuple[Path, ...]:
    """Resolve only project-owned anchors, including symlink and drive-path refusals."""
    if not isinstance(anchors, (list, tuple)) or any(not isinstance(path, str) for path in anchors):
        msg = 'tool.lab_commons.dep.anchors must be an array of project-relative paths'
        raise ValueError(msg)
    paths = tuple((root / path).resolve() for path in anchors)
    if any(
        Path(path).is_absolute() or ':' in path or resolved == root or not resolved.is_relative_to(root)
        for path, resolved in zip(anchors, paths, strict=True)
    ):
        msg = 'dependency verdict anchors must stay inside the target project'
        raise ValueError(msg)
    return paths


def read_project(root: Path, requested: Sequence[str] | None) -> tuple[str, tuple[str, ...], tuple[Path, ...]]:
    """Validate target-owned environment, extras and anchors before mutation."""
    manifest = tomllib.loads((root / 'pyproject.toml').read_text(encoding='utf-8'))
    declaration = manifest.get('tool', {}).get('lab_commons', {}).get('dep', {})
    available = manifest.get('project', {}).get('optional-dependencies', {})
    selected = requested if requested is not None else declaration.get('extras', tuple(available))
    if not isinstance(selected, (list, tuple)) or any(not isinstance(name, str) for name in selected):
        msg = 'tool.lab_commons.dep.extras must be an array of declared extra names'
        raise ValueError(msg)
    unknown = set(selected) - set(available)
    if unknown:
        msg = f'unknown dependency extras: {sorted(unknown)}'
        raise ValueError(msg)
    prefix = root / '.venv'
    if prefix.resolve() != prefix:
        msg = f'{root} must use its own environment, not the alias {prefix} -> {prefix.resolve()}'
        raise ValueError(msg)
    python = str(root / venv_interpreter(os_name=os.name))
    return python, tuple(selected), anchor_paths(root, declaration.get('anchors', ()))
