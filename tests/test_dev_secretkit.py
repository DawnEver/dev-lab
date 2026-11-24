"""SECRET-INTAKE-NEEDS-A-CURRENT-KIT: a stale kit never prompts a person for a secret (D94 follow-up, 2026-11-24)."""

from __future__ import annotations

import builtins
import shutil
import subprocess
from datetime import timedelta
from pathlib import Path

import pytest

from dev_lab.dev import ask, secretkit
from dev_lab.dev.locklag import LAG_WINDOW, Lag
from dev_lab.dev.lockpins import Installed

_GIT = shutil.which('git') or 'git'

_PINNED = 'a' * 40
_LOCK = f"""version = 1
[[package]]
name = "dev-lab"
version = "0.0.1"
source = {{ git = "https://forge.invalid/dev-lab.git?rev=integrate%2Fmain#{_PINNED}" }}
"""


def _checkout(tmp_path: Path) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / 'uv.lock').write_text(_LOCK, encoding='utf-8')
    (tmp_path / '.git').mkdir()
    return tmp_path


def _fresh(_root: Path) -> Lag | None:
    return Lag(0, timedelta(0))


def test_a_kit_holding_the_pin_on_a_current_checkout_is_not_refused(tmp_path: Path) -> None:
    root = _checkout(tmp_path)
    assert secretkit.refusal(root, installed=lambda: (Installed('dev-lab', _PINNED),), lag=_fresh) is None


def test_a_venv_out_of_sync_with_its_lock_is_refused_naming_both_commits_and_the_sync_door(tmp_path: Path) -> None:
    """PLANTED CONTROL beside the current kit above: one differing commit says no."""
    root = _checkout(tmp_path)
    why = secretkit.refusal(root, installed=lambda: (Installed('dev-lab', 'b' * 40),), lag=_fresh)
    assert why is not None
    assert why.startswith(f'{secretkit.RULE_ID}:')
    assert 'b' * 12 in why
    assert _PINNED[:12] in why
    assert 'dev_lab.dev.dep' in why
    assert 'nothing was asked' in why


def test_a_checkout_lagging_its_integration_past_the_window_is_refused_naming_pull_and_sync(tmp_path: Path) -> None:
    """The numerics-lab case of 2026-11-24: the venv matched its OWN lock, and that lock predated the intake."""
    root = _checkout(tmp_path)
    late = Lag(13, LAG_WINDOW + timedelta(hours=1))
    why = secretkit.refusal(root, installed=lambda: (Installed('dev-lab', _PINNED),), lag=lambda _r: late)
    assert why is not None
    assert '13 landings' in why
    assert 'git pull --ff-only' in why
    assert 'forge sync' in why
    assert 'dev_lab.dev.dep' in why
    inside = Lag(13, LAG_WINDOW - timedelta(minutes=1))
    assert secretkit.refusal(root, installed=lambda: (Installed('dev-lab', _PINNED),), lag=lambda _r: inside) is None


def test_an_interpreter_outside_any_checkout_is_not_judged(tmp_path: Path) -> None:
    assert secretkit.checkout_of(tmp_path / 'tools' / 'x') is None
    root = _checkout(tmp_path / 'repo')
    venv = root / '.claude' / 'worktrees' / 'lane'
    lane = _checkout(venv)
    assert secretkit.checkout_of(lane / '.venv') == lane
    assert secretkit.checkout_of(root / '.venvs' / 'slot') == root


def test_the_lag_is_read_from_the_last_fetched_integration_ref(tmp_path: Path) -> None:
    """A real git tree: HEAD one landing behind origin/<integration> is measured, never fetched."""

    def git(*argv: str) -> None:
        subprocess.run([_GIT, '-C', str(tmp_path), *argv], check=True, capture_output=True)

    git('init', '-q', '-b', 'integrate/main')
    git('-c', 'user.name=t', '-c', 'user.email=t@x', 'commit', '-q', '--allow-empty', '-m', 'one')
    git('update-ref', 'refs/remotes/origin/integrate/main', 'HEAD')
    git('-c', 'user.name=t', '-c', 'user.email=t@x', 'commit', '-q', '--allow-empty', '-m', 'two')
    git('update-ref', 'refs/remotes/origin/integrate/main', 'HEAD')
    git('reset', '-q', '--hard', 'HEAD~1')
    lag = secretkit.checkout_lag(tmp_path, integration=lambda _r: 'integrate/main')
    assert lag is not None
    assert lag.landings == 1
    assert secretkit.checkout_lag(tmp_path, integration=lambda _r: None) is None


def test_a_person_is_never_prompted_by_a_stale_kit(monkeypatch: pytest.MonkeyPatch) -> None:
    """The guard sits in THE intake, so every verb asking a person is covered; an injected reader is not a person."""
    prompted: list[str] = []
    monkeypatch.setattr(builtins, 'input', lambda prompt: prompted.append(prompt) or '123456')
    monkeypatch.setattr(secretkit, 'refusal_here', lambda: f'{secretkit.RULE_ID}: planted stale')
    with pytest.raises(ask.AskRefused, match='planted stale'):
        ask.value('token')
    with pytest.raises(ask.AskRefused, match='planted stale'):
        ask.code(None, what='w')
    assert prompted == []
    assert ask.code('123456', what='w') == '123456'  # a code the user GAVE is not a prompt
    assert ask.value('token', ask=lambda _p: 'v') == 'v'
    monkeypatch.setattr(secretkit, 'refusal_here', lambda: None)
    assert ask.code(None, what='w') == '123456'
    assert len(prompted) == 1
