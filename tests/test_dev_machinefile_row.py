"""MACHINE-FILE-IS-RENDERED's row imports wherever the machine file is, home or an override outside it.

THE INCIDENT (2026-11-19): an override outside home (every test that places its own machine file) made the row's
import raise, so every hook importing the deny registry -- the pre-push hook among them -- died with a traceback.
PLANTED CONTROL: the default file below home still yields its home-relative tail.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from lab_commons.config import CONFIG_ENV
from lab_commons.home import HOME_ENV

_PRINT = 'from dev_lab.dev import _deny_machinefile_row as r; print("/".join(r._PARTS))'


def _parts(env: dict[str, str]) -> str:
    done = subprocess.run(
        [sys.executable, '-c', _PRINT], env=env, capture_output=True, text=True, encoding='utf-8', check=False
    )
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


def test_an_override_outside_home_still_imports_and_keeps_the_file_tail(tmp_path: Path) -> None:
    env = os.environ | {HOME_ENV: str(tmp_path / 'home'), CONFIG_ENV: str(tmp_path / 'elsewhere' / 'm.toml')}
    assert _parts(env) == 'elsewhere/m.toml'


def test_the_default_file_keeps_its_home_relative_tail(tmp_path: Path) -> None:
    env = {k: v for k, v in os.environ.items() if k != CONFIG_ENV} | {HOME_ENV: str(tmp_path / 'home')}
    tail = _parts(env)
    assert tail
    assert not tail.startswith(tmp_path.as_posix())
