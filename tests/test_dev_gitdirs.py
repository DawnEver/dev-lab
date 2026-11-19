"""Controls for :mod:`dev_lab.dev.gitdirs`: the checkout walk stops at ``GIT_CEILING_DIRECTORIES`` as git does."""

from __future__ import annotations

from pathlib import Path

import pytest

from dev_lab.dev import gitdirs


def _nested(tmp_path: Path) -> tuple[Path, Path, Path]:
    outer = tmp_path / 'outer'
    (outer / '.git').mkdir(parents=True)
    ceiling = outer / 'output'
    sandbox = ceiling / 'sandbox'
    sandbox.mkdir(parents=True)
    return outer, ceiling, sandbox


def test_without_a_ceiling_a_sandbox_finds_the_enclosing_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PLANTED: the walk can say yes, so the ceiling's no below is the ceiling's doing."""
    outer, _, sandbox = _nested(tmp_path)
    monkeypatch.setenv(gitdirs.CEILING, '')
    assert gitdirs.checkout_of(sandbox) == outer
    assert gitdirs.git_dir(sandbox) == outer / '.git'


def test_below_a_ceiling_a_sandbox_is_outside_any_checkout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, ceiling, sandbox = _nested(tmp_path)
    monkeypatch.setenv(gitdirs.CEILING, str(ceiling))
    assert gitdirs.checkout_of(sandbox) is None
    assert gitdirs.git_dir(sandbox) is None


def test_a_checkout_below_the_ceiling_is_still_found(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, ceiling, sandbox = _nested(tmp_path)
    (sandbox / '.git').mkdir()
    monkeypatch.setenv(gitdirs.CEILING, str(ceiling))
    assert gitdirs.checkout_of(sandbox / 'sub' / 'deeper') == sandbox
