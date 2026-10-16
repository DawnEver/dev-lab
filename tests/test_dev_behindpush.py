"""BEHIND-IS-BOUNDED at push time (D12), driven on a REAL repository with a real ``origin/<integration>`` ref.

A planted control on each side: a lane exactly at the bound is admitted, one commit past it is refused
naming the remedy; the integration and trunk refs are exempt however far behind; a deletion passes.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from lab_commons.dev.behindpush import ALLOWED, COULD_NOT_JUDGE, REFUSED, refusal
from lab_commons.dev.githooks.table import base_rows
from lab_commons.dev.lanepolicy import Policy

_GIT = shutil.which('git') or 'git'
_ZERO = '0' * 40
_POLICY = Policy(behind_max=2)


def _git(root: Path, *args: str) -> str:
    done = subprocess.run(
        [_GIT, '-c', 'user.email=t@t', '-c', 'user.name=t', *args],
        cwd=root, check=True, capture_output=True, text=True, encoding='utf-8', timeout=60,
    )  # fmt: skip
    return done.stdout.strip()


def _planted(root: Path, ahead: int) -> tuple[Path, str]:
    """A repo whose ``origin/integrate/main`` is *ahead* commits past the lane's base; returns the lane sha."""
    root.mkdir()
    _git(root, 'init', '-q', '-b', 'main')
    _git(root, 'commit', '-q', '--allow-empty', '-m', 'base')
    lane = _git(root, 'rev-parse', 'HEAD')
    for n in range(ahead):
        _git(root, 'commit', '-q', '--allow-empty', '-m', f'upstream {n}')
    _git(root, 'update-ref', 'refs/remotes/origin/integrate/main', 'HEAD')
    return root, lane


def _line(branch: str, sha: str) -> str:
    return f'refs/heads/{branch} {sha} refs/heads/{branch} {_ZERO}'


def test_a_lane_at_the_bound_is_admitted(tmp_path: Path) -> None:
    root, lane = _planted(tmp_path / 'r', 2)
    assert refusal(root, lines=[_line('lane/x', lane)], policy=_POLICY) == (ALLOWED, '')


def test_a_lane_past_the_bound_is_refused_naming_the_remedy(tmp_path: Path) -> None:
    root, lane = _planted(tmp_path / 'r', 3)
    code, text = refusal(root, lines=[_line('lane/x', lane)], policy=_POLICY)
    assert code == REFUSED
    assert 'lane/x is 3 behind' in text
    assert 'python -m lab_commons.dev.forge sync' in text


def test_the_integration_and_trunk_pushes_are_exempt(tmp_path: Path) -> None:
    root, lane = _planted(tmp_path / 'r', 5)
    lines = [_line('integrate/main', lane), _line('main', lane)]
    assert refusal(root, lines=lines, policy=_POLICY) == (ALLOWED, '')


def test_a_deletion_and_a_tag_pass(tmp_path: Path) -> None:
    root, lane = _planted(tmp_path / 'r', 5)
    lines = [f'(delete) {_ZERO} refs/heads/lane/x {lane}', f'refs/tags/v1 {lane} refs/tags/v1 {_ZERO}']
    assert refusal(root, lines=lines, policy=_POLICY) == (ALLOWED, '')


def test_a_checkout_without_an_integration_branch_passes(tmp_path: Path) -> None:
    root = tmp_path / 'r'
    root.mkdir()
    _git(root, 'init', '-q', '-b', 'main')
    _git(root, 'commit', '-q', '--allow-empty', '-m', 'base')
    assert refusal(root, lines=[_line('lane/x', _git(root, 'rev-parse', 'HEAD'))], policy=_POLICY) == (ALLOWED, '')


def test_a_commit_git_cannot_count_is_not_judged(tmp_path: Path) -> None:
    root, _ = _planted(tmp_path / 'r', 1)
    code, text = refusal(root, lines=[_line('lane/x', 'f' * 40)], policy=_POLICY)
    assert code == COULD_NOT_JUDGE
    assert 'lane/x' in text


def test_the_family_hook_table_runs_it_at_pre_push() -> None:
    rows = [row for row in base_rows()['pre-push'] if row['id'] == 'behind-push']
    assert [row['run'] for row in rows] == [['python', '-m', 'lab_commons.dev.behindpush']]
