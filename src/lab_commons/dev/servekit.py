"""A DEPLOYED HOST KEEPS ITS OWN LAB-COMMONS CURRENT -- every serve tick fast-forwards it before claiming.

THE DEFECT (live 2026-10-12, integrate/main 4e394b6). The cluster's serving checkout of lab-commons moved
only when a human re-ran the deploy, so the producer judged with code older than what it judged: it read
a table newer than itself as empty. The producer is itself part of what
is integrated; a host that serves it must follow it.

WHO. A host whose machine file declares ``[deploy]`` (:mod:`lab_commons.hpc.deploy_spec`) -- a cluster
account. The deploy OWNS ``~/<root>/lab-commons`` and the branch it follows (the ``--repo
lab-commons=<url>@<ref>`` it was given), so that declaration is the one source for what "current" means.
A workstation declares no ``[deploy]``: its serving checkout is a human's (the integrator's main
checkout), never moved by a tick, and what it judges no longer depends on it (:mod:`lab_commons.dev.shatree`).

WHICH REF. The deployed ref -- the INTEGRATION branch today, not the trunk. A kit refuses a declaration
newer than itself (:mod:`lab_commons.hpc.declared`), so a host following the trunk could never judge the
integration commit that introduces a table, and that commit could never reach the trunk: a deadlock.
Following the branch it judges keeps the kit at least as new as every integrated declaration.

WHAT A TICK DOES, before anything is claimed (:func:`current`): fetch the kit checkout's origin; refuse --
alarm and exit 1, claiming nothing -- when it is dirty, off its declared branch, or cannot fast-forward;
otherwise fast-forward it. When HEAD moved, reinstall it into this serve's own venv unless that venv
already imports it from the checkout (:func:`lab_commons.hpc.deploy_steps.overlay_argv`, the deploy's own
step), then RE-EXEC the serve so this tick runs the new code; the child carries :data:`CURRENT_VAR` and
does not update again.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Final

import lab_commons
from lab_commons.config import config_path
from lab_commons.dev.forge import _GIT, fetch_origin
from lab_commons.dev.forgealarm import RUN, Alarm, sound
from lab_commons.hpc.deploy_spec import LAB_COMMONS, checkout_of, load
from lab_commons.hpc.deploy_steps import overlay_argv
from lab_commons.log import emit

__all__ = ['CURRENT_VAR', 'KitRefused', 'current', 'fast_forward']

#: Set in the re-executed serve: its kit was brought current by its parent this tick.
CURRENT_VAR: Final = 'LAB_FORGE_KIT_CURRENT'

#: Where the running kit was imported from: inside the checkout means the venv already follows it.
_RUNNING: Final = Path(lab_commons.__file__).resolve().parent


class KitRefused(RuntimeError):
    """The kit checkout cannot be brought current by a fast-forward; the message names why and the remedy."""


def _git(kit: Path, *args: str, run: Callable[..., Any]) -> str:
    done = run([_GIT, '-C', str(kit), *args], capture_output=True, text=True, encoding='utf-8', check=False)
    if done.returncode:
        msg = f'git {" ".join(args)} in {kit} exited {done.returncode}: {(done.stderr or "").strip()}'
        raise KitRefused(msg)
    return (done.stdout or '').strip()


def fast_forward(kit: Path, ref: str, *, run: Callable[..., Any], fetch: Callable[[Path], None]) -> tuple[str, str]:
    """``(before, after)`` HEAD of *kit* fast-forwarded to ``origin/<ref>``.

    Raises:
        KitRefused: dirty, off *ref*, or not a fast-forward; nothing was changed.

    """
    if dirt := _git(kit, 'status', '--porcelain', '--untracked-files=no', run=run):
        msg = f'{kit} has local changes ({dirt.splitlines()[0]} ...); commit or discard them, the tick never does'
        raise KitRefused(msg)
    if (branch := _git(kit, 'rev-parse', '--abbrev-ref', 'HEAD', run=run)) != ref:
        msg = f'{kit} is on {branch}, not the deployed {ref}; check out {ref} or re-run the deploy'
        raise KitRefused(msg)
    before = _git(kit, 'rev-parse', 'HEAD', run=run)
    fetch(kit)
    try:
        _git(kit, 'merge', '--ff-only', '-q', f'refs/remotes/origin/{ref}', run=run)
    except KitRefused as diverged:
        msg = f'{kit} cannot fast-forward to origin/{ref}: {diverged}'
        raise KitRefused(msg) from None
    return before, _git(kit, 'rev-parse', 'HEAD', run=run)


def current(
    rest: Sequence[str],
    serve: Callable[[list[str]], int],
    *,
    home: Path | None = None,
    machine_file: Path | None = None,
    environ: Mapping[str, str] = os.environ,
    run: Callable[..., Any] = subprocess.run,
    fetch: Callable[[Path], None] = fetch_origin,
    alarm: Callable[[Alarm], object] = sound,
    running: Path = _RUNNING,
) -> int:
    """Serve *rest* with a current kit (module docstring): ``serve(rest)``, or the re-executed serve's exit code."""
    spec = load(config_path() if machine_file is None else machine_file)
    if spec is None or environ.get(CURRENT_VAR):
        return serve(list(rest))
    home = Path.home() if home is None else home
    lab = next(repo for repo in spec.repos if repo.name == LAB_COMMONS)
    kit = checkout_of(spec, home, lab)
    try:
        before, after = fast_forward(kit, lab.ref, run=run, fetch=fetch)
    except (KitRefused, OSError) as refused:
        alarm(Alarm(RUN, lab.url, f'the serving lab-commons on {spec.host} cannot be brought current', str(refused)))
        emit(f'[serve] kit not current, nothing claimed: {refused}', err=True)
        return 1
    if before == after:
        return serve(list(rest))
    emit(f'[serve] lab-commons {before[:12]} -> {after[:12]}', err=True)
    if not running.is_relative_to(kit.resolve()):  # this venv holds an installed copy, not the checkout
        uv = [shutil.which('uv') or 'uv']
        done = run(overlay_argv(uv, Path(sys.executable), kit), cwd=home, check=False)
        if done.returncode:
            alarm(Alarm(RUN, lab.url, f'lab-commons {after[:12]} did not install on {spec.host}', 'uv pip install'))
            return 1
    argv = [sys.executable, '-m', 'lab_commons.dev.forge', 'serve', *rest]
    return run(argv, env={**environ, CURRENT_VAR: after}, check=False).returncode
