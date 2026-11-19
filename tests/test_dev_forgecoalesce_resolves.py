"""``forgecoalesce._resolves``: a ref that resolved is asked of git once per process; a missing one every time."""

from __future__ import annotations

from typing import TYPE_CHECKING

import lab_commons.launch as door
from _forge_fake import git_out, run_git

from dev_lab.dev import forgecoalesce

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def test_a_resolved_ref_is_asked_once_and_a_missing_one_every_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One ``forge queue`` read asked whether the integration branch resolves 16 times (2026-11-18).

    PLANTED CONTROL: a ref that does not resolve is never held -- it is asked again, and found once it exists.
    """
    run_git(tmp_path, 'init', '-q')
    run_git(tmp_path, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '--allow-empty', '-m', 'init')
    head = git_out(tmp_path, 'rev-parse', 'HEAD')
    spawned: list[str] = []
    real = door.run

    def counted(argv: list[str], *args: object, **kwargs: object) -> object:
        spawned.extend(str(one) for one in argv if one == 'rev-parse')
        return real(argv, *args, **kwargs)

    monkeypatch.setattr(door, 'run', counted)
    for _ in range(3):
        assert forgecoalesce._resolves(tmp_path, 'HEAD')
    assert len(spawned) == 1, 'a resolved ref was asked of git again'
    assert not forgecoalesce._resolves(tmp_path, 'refs/heads/later')
    assert not forgecoalesce._resolves(tmp_path, 'refs/heads/later')
    assert len(spawned) == 3, 'a missing ref was held'
    run_git(tmp_path, 'branch', 'later', head)
    assert forgecoalesce._resolves(tmp_path, 'refs/heads/later'), 'a ref that appeared later was not found'
