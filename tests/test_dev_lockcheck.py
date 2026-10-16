"""LOCKS RECORD (D8/D20): a pushed commit commits ``uv.lock``, pins its git requirements, and was upgraded lately.

Driven on REAL planted repositories, read at the pushed SHA; each refusal has a planted control that passes.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from datetime import date
from pathlib import Path

from lab_commons.dev.githooks.table import base_rows
from lab_commons.dev.lockcheck import REMEDY, TRAILER, lock_problems, locked_git, main, pushed_shas, upgraded_on

_GIT = shutil.which('git') or 'git'
_TODAY = date(2026, 10, 16)
_SHA = 'c' * 40

_MANIFEST = """[project]
name = "planted"
version = "0"
dependencies = ["kit @ git+https://forge.invalid/o/kit.git"]

[tool.lab_commons.integrator]
lock_max_age_days = 3
"""
_PINNED = f"""version = 1

[[package]]
name = "kit"
version = "1.0"
source = {{ git = "https://forge.invalid/o/kit.git#{_SHA}" }}
"""
_FLOATING = _PINNED.replace(f'#{_SHA}', '')


def _git(root: Path, *argv: str, when: str = '2026-10-15T12:00:00Z') -> str:
    env = {**os.environ, 'GIT_COMMITTER_DATE': when, 'GIT_AUTHOR_DATE': when}
    done = subprocess.run(
        [_GIT, '-c', 'user.name=t', '-c', 'user.email=t@t', *argv],
        cwd=root, env=env, check=True, capture_output=True, text=True, timeout=60,
    )  # fmt: skip
    return done.stdout.strip()


def _commit(root: Path, files: dict[str, str], *, message: str = 'c', when: str = '2026-10-15T12:00:00Z') -> str:
    for name, text in files.items():
        (root / name).write_text(text, encoding='utf-8')
        _git(root, 'add', name)
    _git(root, 'commit', '-q', '--allow-empty', '-m', message, when=when)
    return _git(root, 'rev-parse', 'HEAD')


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / 'r'
    root.mkdir()
    _git(root, 'init', '-q', '-b', 'main')
    return root


def _upgraded(day: str) -> str:
    return f'chore(deps): uv lock --upgrade\n\n{TRAILER}: {day}'


def test_a_pinned_freshly_upgraded_lock_passes_and_each_defect_is_refused_by_name(tmp_path: Path) -> None:
    """PLANTED CONTROLS: no lock, a floating git source, never upgraded, upgraded too long ago -- each named."""
    root = _repo(tmp_path)
    unlocked = _commit(root, {'pyproject.toml': _MANIFEST})
    (why,) = lock_problems(root, unlocked, today=_TODAY)
    assert why == f'{unlocked[:12]} commits no uv.lock: its environment is whatever floats on the day'
    never = _commit(root, {'uv.lock': _PINNED})
    assert any('never upgraded' in why for why in lock_problems(root, never, today=_TODAY))
    fresh = _commit(root, {}, message=_upgraded('2026-10-15'), when='2026-10-15T12:00:00Z')
    assert lock_problems(root, fresh, today=_TODAY) == ()
    assert upgraded_on(root, fresh) == date(2026, 10, 15)
    assert any('past lock_max_age_days=3' in why for why in lock_problems(root, fresh, today=date(2026, 10, 19)))
    floating = _commit(root, {'uv.lock': _FLOATING})
    assert lock_problems(root, floating, today=_TODAY) == (
        'kit is a git requirement uv.lock does not resolve to a commit: it floats',
    )


def test_locked_git_reads_the_commit_each_git_source_resolved_to() -> None:
    assert locked_git(_PINNED) == {'kit': _SHA}
    assert locked_git(_FLOATING) == {'kit': ''}, 'PLANTED: a git source with no commit floats'


def test_the_hook_judges_each_pushed_branch_sha_and_names_the_remedy(tmp_path: Path, capsys) -> None:
    root = _repo(tmp_path)
    bad = _commit(root, {'pyproject.toml': _MANIFEST})
    good = _commit(root, {'uv.lock': _PINNED}, message=_upgraded('2026-10-16'))
    line = 'refs/heads/x {sha} refs/heads/x ' + '0' * 40
    assert pushed_shas([line.format(sha=good), f'refs/tags/t {bad} refs/tags/t {"0" * 40}']) == (good,)
    assert pushed_shas([f'(delete) {"0" * 40} refs/heads/x {bad}']) == (), 'a deletion is allowed'
    assert main([str(root)], lines=[line.format(sha=good)], today=_TODAY) == 0
    assert main([str(root)], lines=[line.format(sha=bad)], today=_TODAY) == 1
    assert REMEDY in capsys.readouterr().err
    assert REMEDY.count('uv lock --upgrade') == 1


def test_the_family_hook_base_runs_the_lock_check_at_push() -> None:
    rows = {row['id']: row for row in base_rows()['pre-push']}
    assert rows['lock']['run'] == ['python', '-m', 'lab_commons.dev.lockcheck']
