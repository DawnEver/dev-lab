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
