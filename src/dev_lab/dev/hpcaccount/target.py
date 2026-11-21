"""Where one account deploys (:class:`Target`), and the shell lines that run in its kit checkout there.

Split from :mod:`dev_lab.dev.hpcaccount.fleet` at the module-size band (2026-11-21): the fleet decides WHICH
accounts deploy and launches them; this module is the per-account target and the kit steps every remote verb
(``deploy-fleet``, ``credential``, ``forget``, ``retention``) composes -- a first install, a kit refresh, a command
run in the kit's venv.
"""

from __future__ import annotations

import shlex
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Final

from lab_commons.hpc.grants import Grant

from dev_lab.dev.hpcaccount.spec import KIT, paths_of_root
from dev_lab.dev.venvpointer import shell_interpreter

__all__ = ['UV_INSTALLER', 'Target', 'first_install', 'in_checkout', 'refresh_kit', 'repo_dir']


@dataclass(frozen=True)
class Target:
    """Where one account deploys: its declared login host, checkout root and role (``''``: undeclared)."""

    host: str
    root: str
    role: str = ''
    repos: tuple[tuple[str, str, str], ...] = ()  # (name, https url, ref): what a first install clones


def repo_dir(target: Target, name: str) -> PurePosixPath:
    """*target*'s checkout of *name*: ``<root>/repos/<name>`` (:mod:`lab_commons.hpc.layout`).

    A ``~/`` root is an account deployed before the declared root (only :func:`declared_target`'s *as_deployed*
    read yields one): its checkouts sit at ``~/<root>/<name>``, the layout it was deployed with.
    """
    if target.root.startswith('~/'):
        return PurePosixPath(target.root, name)
    return PurePosixPath(paths_of_root(target.root).repo(name))


def in_checkout(target: Target, argv: Sequence[str]) -> str:
    """The shell line that runs ``python <argv>`` in *target*'s declared dev-lab checkout, with its venv."""
    kit = repo_dir(target, KIT)  # every cluster login host is POSIX
    return f'cd {kit} && {shell_interpreter(".")} {shlex.join(argv)}'


#: The official uv installer (user approval 2026-11-16: an HPC account may install uv into ``~/.local/bin``).
UV_INSTALLER: Final = 'https://astral.sh/uv/install.sh'


def first_install(grant: Grant, target: Target) -> str:
    """The shell line that gives *target* a kit venv when it has none, else does nothing.

    A key-only account has no door for a first install (raw ssh is refused), and every later step runs the kit's
    venv python. So, only when that interpreter is missing: uv into ``~/.local/bin`` unless one is on PATH, each
    declared repo cloned at its ref where its checkout is absent, then ``uv sync --frozen`` in the kit.
    """
    root = PurePosixPath(paths_of_root(target.root).root) / 'repos'
    kit = root / KIT
    clones = [  # the kit alone: a forge-hosted product repo needs a reader credential the deploy places later
        f'{{ [ -d {root / name}/.git ] || git clone -q --branch {shlex.quote(ref)} {shlex.quote(url)} {root / name}; }}'
        for name, url, ref in target.repos
        if name == KIT
    ]
    steps = [
        f'echo "[first-install] {grant.user}: no kit venv in {kit}"',
        'export PATH="$HOME/.local/bin:$PATH" GIT_TERMINAL_PROMPT=0',
        f'{{ command -v uv >/dev/null || curl -LsSf {UV_INSTALLER} | env UV_NO_MODIFY_PATH=1 sh; }}',
        f'mkdir -p {root}', *clones, f'( cd {kit} && uv sync --frozen )',
    ]  # fmt: skip
    body = ' && '.join([*grant.setup, *steps])
    return f'{{ [ -x {shell_interpreter(str(kit))} ] || ( {body} ); }}'


def refresh_kit(grant: Grant, target: Target) -> str:
    """The shell line that brings *target*'s kit to its declared tip BEFORE the deploy runs, and records the sha.

    A dead account cannot heal itself: its kit moves only on its own cron tick, which never runs, so a fix to
    ``deploy`` would never reach it. The step is the kit's OWN tick (:mod:`dev_lab.dev.hpcaccount.tick`, the one
    writer of the host checkout), never a second refresh; in the grant's ``setup`` environment, as the cron line
    runs it (:func:`dev_lab.dev.hpcaccount.spec.tick_command`). The deploy follows whatever the tick exits: a
    research kit refreshes, then refuses to serve.
    """
    kit = repo_dir(target, KIT)
    recorded = f'echo "[deploy-fleet] kit at $(git -C {kit} rev-parse HEAD)"'
    ref = next((ref for name, _url, ref in target.repos if name == KIT), '')
    tick = f'{in_checkout(target, ["-m", "dev_lab.dev.hpcaccount", "tick", KIT])} ; {recorded}'
    if ref:
        tick = f'{_move_kit(kit, ref)} ; {recorded}'
    return f'bash -lc {shlex.quote("; ".join([*grant.setup, tick]))}' if grant.setup else tick


def _move_kit(kit: PurePosixPath, ref: str) -> str:
    """The kit fast-forwarded to its LAYER-declared *ref* and its own venv re-synced, under the cron tick's lock.

    Never through the kit's tick: that reads the account's machine file, which is the stale thing this deploy is
    about to render over (2026-11-20: a retired key crashed it before it refreshed; an old root sent it to another
    checkout). The lock is the cron tick's, so the kit keeps one writer at a time.
    """
    remote = f'refs/remotes/origin/{ref}'
    python = shell_interpreter('.')
    body = ' && '.join([
        f'git fetch -q origin {shlex.quote(f"+refs/heads/{ref}:{remote}")}',
        f'git checkout -q -B {shlex.quote(ref)} {shlex.quote(remote)}',
        f'py={python}',
        'UV_PROJECT_ENVIRONMENT="${py%/bin/python}" uv sync --frozen',
    ])  # fmt: skip
    serve = kit.parent.parent / 'serve'  # <root>/repos/dev-lab -> <root>/serve: the cron tick's own lock
    lock = serve / f'{KIT}.lock'
    return (
        f'( export PATH="$HOME/.local/bin:$PATH" GIT_TERMINAL_PROMPT=0; mkdir -p {serve}; cd {kit} && '
        f'flock -w 600 {lock} bash -c {shlex.quote(body)} )'
    )
