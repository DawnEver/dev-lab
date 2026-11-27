"""A detached run starts from its checkout's CURRENT environment, never the one its parent happened to run from.

MEASURED 2026-11-17 on a consumer's main checkout: a legacy ``.venv`` directory never drained, because every
detached follow and reclaim restarted the interpreter of the process that detached it -- the legacy one -- so
something always executed from it. PLANTED CONTROL: with no pointer the legacy ``.venv`` is current and stays.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from _venv_fake import linked_env

from dev_lab.dev import backgroundrun, venvpointer
from dev_lab.dev.venvpath import VENV_LAYOUTS

if TYPE_CHECKING:
    import pytest

TAIL = VENV_LAYOUTS[os.name][1:]


def _interpreter(env: Path) -> Path:
    python = env.joinpath(*TAIL)
    python.parent.mkdir(parents=True, exist_ok=True)
    python.write_text('', encoding='utf-8')
    return python


def test_a_detached_run_takes_the_current_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / 'main'
    legacy = _interpreter(root / venvpointer.HOME / 'old')
    current = _interpreter(linked_env(root, 'x'))
    started: list[list[str]] = []
    monkeypatch.setattr(backgroundrun._door, 'popen', lambda argv, **_: started.append(argv))
    monkeypatch.setattr(sys, 'executable', str(legacy))
    backgroundrun.detach_argv(root, ['-m', 'dev_lab.dev.reclaimrun'])
    assert Path(started[-1][0]).resolve() == current.resolve()
    assert started[-1][1:] == ['-m', 'dev_lab.dev.reclaimrun']
    link = root / venvpointer.POINTER
    link.unlink() if link.is_symlink() else link.rmdir()
    backgroundrun.detach_argv(root, ['-m', 'dev_lab.dev.reclaimrun'])
    assert started[-1][0] == str(legacy), 'PLANTED CONTROL: no .venv: unchanged'


def test_a_run_left_inside_the_hooks_job_is_reported_as_not_outliving_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#1002: Windows refusing the breakaway left the run in the hook's job, which ended it; the caller now hears so.

    PLANTED CONTROL: a breakaway the job allows outlives the hook.
    """
    flags: list[int] = []

    def popen(_argv: list[str], *, creationflags: int = 0, **_k: object) -> None:
        flags.append(creationflags)
        if refuse and creationflags & backgroundrun._BREAKAWAY:
            raise PermissionError(5, 'Access is denied')

    monkeypatch.setattr(backgroundrun._door, 'popen', popen)
    monkeypatch.setattr(sys, 'platform', 'win32')
    refuse = True
    assert backgroundrun.detach_argv(tmp_path, ['-m', 'x']) is False
    assert not flags[-1] & backgroundrun._BREAKAWAY, 'it still started, inside the job'
    refuse = False
    assert backgroundrun.detach_argv(tmp_path, ['-m', 'x']) is True
