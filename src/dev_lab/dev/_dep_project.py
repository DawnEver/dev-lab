"""Target project declarations and commands for the dependency door."""

import os
import shutil
import sys
import tomllib
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import lab_commons.launch as _door
from lab_commons.log import emit

from dev_lab.dev._dep_network import CHILD_WALL_S, run_change
from dev_lab.dev.installdoor import floating_requirements
from dev_lab.dev.lockcheck import TOOLCHAIN, UV_VERSION, newest_stable, pin_stable, unreasoned_holds
from dev_lab.dev.venvpath import venv_interpreter


def _checkout(cwd: Path, git_binary: str) -> tuple[Path, Path] | None:
    result = _door.run(
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


class OtherUvRefused(RuntimeError):
    """The uv on PATH is not :data:`~dev_lab.dev.lockcheck.UV_VERSION`, and this command would write a lock."""


def parse_uv_version(said: str) -> str:
    """The version word of ``uv --version`` (``uv 0.13.5 (...)``); empty when uv said nothing parseable."""
    words = said.split()
    return words[1] if len(words) > 1 and words[0] == 'uv' else ''


def installed_uv_version(uv: str) -> str:
    """What the *uv* binary says it is."""
    done = _door.run([uv, '--version'], capture_output=True, text=True, encoding='utf-8', check=False, timeout=60)
    return parse_uv_version(done.stdout) if done.returncode == 0 else ''


def lock_writer(uv: str) -> str:
    """*uv*, if it is the one uv that writes every lock in the family; else refused by name with the remedy."""
    found = installed_uv_version(uv)
    if found != UV_VERSION:
        msg = (
            f'{uv} is uv {found or "(unreadable)"}, but every lock is written by uv {UV_VERSION} '
            f'(dev_lab.dev.lockcheck.UV_VERSION): a lock written by another uv churns its revision line. '
            f'Run `uv self update {UV_VERSION}` (WinGet: `winget install --id astral-sh.uv -e --version {UV_VERSION}`)'
        )
        raise OtherUvRefused(msg)
    return uv


def uv_command(
    root: Path,
    python: str,
    selected: Sequence[str],
    *,
    syncing: bool,
    upgrade_packages: Sequence[str],
    frozen: bool = False,
    reinstall_packages: Sequence[str] = (),
) -> list[str]:
    """One target-addressed command; a sync re-resolves every declared floating Git requirement.

    A *frozen* sync builds exactly the committed ``uv.lock`` (``--frozen``) and re-resolves nothing: how a
    commit's own environment is materialised, so two hosts on two days build the same revisions.
    *reinstall_packages* are rebuilt from source whatever their version says (a component whose tree moved,
    :mod:`dev_lab.dev._dep_components`).
    """
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
        for package in reinstall_packages:
            command.extend(('--reinstall-package', package))
    if frozen:
        return [*command, '--frozen']
    command[0] = lock_writer(uv)  # an unfrozen sync or lock may rewrite uv.lock
    upgrades = set(upgrade_packages)
    if syncing:
        upgrades.update(floating_requirements(root / 'pyproject.toml'))
    for package in sorted(upgrades):
        command.extend(('--upgrade-package', package))
    return command


def lock_upgrade_command(root: Path, python: str) -> list[str]:
    """``uv lock --upgrade`` for *root*: every requirement re-resolved to the newest its declaration admits."""
    uv = shutil.which('uv')
    if uv is None:
        msg = 'a lock upgrade requires uv on PATH'
        raise FileNotFoundError(msg)
    interpreter = python if Path(python).is_file() else sys.executable
    uv = lock_writer(uv)
    return [uv, 'lock', '--upgrade', '--project', str(root), '--python', interpreter]


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


def lock_upgrade(
    root: Path,
    python: str,
    *,
    run: Callable[..., Any],
    dry_run: bool,
    environment: dict[str, str],
    stable: Callable[[], str] = newest_stable,
) -> int:
    """Rewrite *root*'s lock at the newest resolution -- the remedy :mod:`dev_lab.dev.lockcheck` names.

    The holds the forge refuses (famtests.lockpin) are refused HERE first, before anything resolves: a lock written
    under an unreasoned hold would only be refused again at the push. Only the lock -- and a pinned
    ``rust-toolchain.toml``, moved to *stable* (user ruling 2026-10-25) -- moves in this step; the
    environment then follows it through the seated frozen sync in :func:`dev_lab.dev.dep.main`.
    """
    holds = unreasoned_holds((root / 'pyproject.toml').read_text(encoding='utf-8'))
    if holds:
        emit('REFUSED: ' + '; '.join(f'{hold} holds a requirement below the newest with no reason' for hold in holds))
        return 1
    try:
        command = lock_upgrade_command(root, python)
    except OtherUvRefused as exc:
        emit(f'REFUSED: {exc}')
        return 1
    if dry_run:
        emit('would run: ' + ' '.join(command))
        return 0
    code = run_change(command, run=run, timeout=CHILD_WALL_S, cwd=root, environment=environment)
    if code == 0 and (root / TOOLCHAIN).is_file():
        pin_stable(root, stable())
    return code
