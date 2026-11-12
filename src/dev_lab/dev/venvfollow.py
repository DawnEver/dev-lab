"""VENV-FOLLOWS-THE-LOCK: a checkout's venv is re-bootstrapped when its environment inputs moved.

User ruling 2026-11-04: session venvs never followed the lock -- a main checkout's ``.venv`` ran an older kit than
its own ``uv.lock``, because only a served checkout's host tick compared the two. That comparison now has ONE
home, :func:`stale`: the key of :data:`ENV_INPUTS` against the stamp the last successful bootstrap wrote, so an
unchanged checkout costs one hash. Its callers:

* :func:`dev_lab.dev.hostrefresh.sync_venv` -- a served checkout, every host tick;
* ``--session-start``, the ``SessionStart`` hook (:data:`dev_lab.dev.agent_wiring.WIRING`) -- a stale venv detaches
  a background :func:`follow` and the hook returns at once;
* the ``post-merge`` and ``post-checkout`` git hooks (``githooks/base.toml``, advisory) -- ``--background``.

THE TOOLCHAIN FOLLOWS AS ONE (user ruling 2026-11-12: no human approval keeps a checkout current). The venv is one
of three things a checkout can be left behind on, and the follow takes them in dependency order: the CHECKOUT first
(:func:`dev_lab.dev.checkoutfollow.advance` -- a clean primary checkout fast-forwards onto integration, which may
move the lock), then the VENV, then the HOOKS (:func:`dev_lab.dev.hook_install.rewire` -- a stale or predecessor
shim never reaches the current table, so only something outside a git hook can replace it). ``--background``
detaches when any of the three is due.

:func:`follow` skips while a run lives in the checkout or executes from its venv (TREE-HAS-A-LIVE-RUN,
:mod:`dev_lab.dev.liverun`): a stamp-less venv is retried by the next session start, merge or checkout.

``python -m dev_lab.dev.venvfollow [--root R] [--background | --session-start]``; always exits 0.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Final, TextIO

import lab_commons.launch as _door
from lab_commons.census import processes
from lab_commons.log import emit

from dev_lab.dev import checkoutfollow, hook_install, liverun
from dev_lab.dev.checkout import git_out
from dev_lab.dev.reclaimrun import detach_argv
from dev_lab.dev.venvpath import venv_interpreter

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from lab_commons.census import Process

__all__ = [
    'BOOTSTRAPPED',
    'CURRENT',
    'ENV_INPUTS',
    'ENV_STAMP',
    'FAILED',
    'SKIPPED',
    'busy',
    'detach_argv',
    'due',
    'env_key',
    'follow',
    'main',
    'stale',
    'stamp',
    'toplevel',
    'venv_python',
]

#: The files whose content decides a checkout's environment; the venv is re-bootstrapped when they change.
ENV_INPUTS: Final = ('pyproject.toml', 'uv.lock')
#: The key of :data:`ENV_INPUTS` the venv was last bootstrapped at, written only after a bootstrap succeeds.
ENV_STAMP: Final = '.lab-host-env'

#: What :func:`follow` did.
CURRENT: Final = 'current'
BOOTSTRAPPED: Final = 'bootstrapped'
FAILED: Final = 'bootstrap failed'
SKIPPED: Final = 'skipped: a live run'


def venv_python(checkout: Path) -> Path:
    """*checkout*'s own venv interpreter."""
    return checkout / venv_interpreter(os_name=os.name)


def env_key(checkout: Path) -> str:
    """The key of *checkout*'s :data:`ENV_INPUTS` as they are on disk; an absent file keys as empty."""
    digest = hashlib.sha256()
    for name in ENV_INPUTS:
        path = checkout / name
        digest.update(hashlib.sha256(path.read_bytes() if path.is_file() else b'').digest() + name.encode())
    return digest.hexdigest()


def stale(checkout: Path) -> str | None:
    """The key to stamp when *checkout*'s venv is missing or stamped at other inputs; ``None`` when current."""
    key, path = env_key(checkout), checkout / '.venv' / ENV_STAMP
    if venv_python(checkout).is_file() and path.is_file() and path.read_text(encoding='utf-8') == key:
        return None
    return key


def stamp(checkout: Path, key: str) -> None:
    """Record that *checkout*'s venv was bootstrapped at *key*."""
    path = checkout / '.venv' / ENV_STAMP
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(key, encoding='utf-8')


def busy(checkout: Path, *, census: Callable[[], Iterable[Process]] = processes) -> str:
    """The live runs reading *checkout* or executing from its venv, described; ``''`` when there are none."""
    table = tuple(census())
    reading = liverun.live_runs(checkout, census=lambda: table)
    executing = liverun.executing_from(checkout / '.venv', census=lambda: table)
    runs = {one.pid: one for one in (*reading, *executing)}
    return liverun.describe(runs.values()) if runs else ''


def _bootstrap(checkout: Path) -> int:
    """``dep --bootstrap`` IN *checkout*: the door's own rule moves a primary checkout only from itself."""
    argv = [sys.executable, '-m', 'dev_lab.dev.dep', '--bootstrap', str(checkout)]
    return _door.run(argv, cwd=checkout, check=False).returncode


def follow(
    checkout: Path,
    *,
    bootstrap: Callable[[Path], int] = _bootstrap,
    busy: Callable[[Path], str] = busy,
) -> str:
    """Re-bootstrap *checkout*'s venv when :func:`stale`, unless a run lives there; what was done."""
    key = stale(checkout)
    if key is None:
        return CURRENT
    if runs := busy(checkout):
        return f'{SKIPPED} ({runs})'
    if bootstrap(checkout):
        return FAILED
    stamp(checkout, key)
    return BOOTSTRAPPED


def toplevel(cwd: Path) -> Path | None:
    """The checkout *cwd* lies in, or ``None`` outside git."""
    out = (git_out(cwd, 'rev-parse', '--show-toplevel') or '').strip()
    return Path(out) if out else None


def due(checkout: Path) -> bool:
    """*checkout*'s venv is :func:`stale`, the checkout is behind integration, or a declared hook is not live."""
    return stale(checkout) is not None or checkoutfollow.behind(checkout) or hook_install.unwired(checkout)


def _session_root(stdin: TextIO) -> Path | None:
    try:
        payload = json.load(stdin)
    except ValueError:
        payload = {}
    cwd = (payload if isinstance(payload, dict) else {}).get('cwd') or Path.cwd()
    return toplevel(Path(cwd))


def main(argv: list[str] | None = None, *, stdin: TextIO | None = None) -> int:
    """Follow integration, the lock and the hooks: inline, ``--background`` or ``--session-start``. Always 0."""
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.venvfollow', description=main.__doc__)
    parser.add_argument('--root', type=Path, default=None, help='the checkout (default: the one cwd lies in)')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--background', action='store_true', help='detach a follow when stale and return at once')
    mode.add_argument('--session-start', action='store_true', help='the SessionStart hook: --background on its cwd')
    args = parser.parse_args(argv)
    try:
        root = _session_root(stdin or sys.stdin) if args.session_start else (args.root or toplevel(Path.cwd()))
        if root is None:
            return 0
        if args.background or args.session_start:
            if due(root):
                detach_argv(root, ['-m', 'dev_lab.dev.venvfollow', '--root', str(root)])
            return 0
        if moved := checkoutfollow.advance(root):
            emit(moved)
        emit(f'venv {root}: {follow(root)}')
        if rewired := hook_install.rewire(root):
            emit(rewired)
    except OSError as exc:  # a hook never blocks the session or the git verb it serves
        emit(f'venv follow did not run: {exc}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
