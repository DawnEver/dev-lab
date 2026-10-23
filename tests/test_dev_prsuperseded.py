"""SUPERSEDED-PRS-CLOSE: a salvaged PR is commented, closed and its branch LOSSLESS-deleted; refusals touch nothing.

Real git (a bare origin and a clone) and the stateful fake forge. PLANTED CONTROLS: an unnamed open PR is
untouched; a closed target, a merged replacement and a closed replacement each refuse before any write.
"""

from __future__ import annotations

from pathlib import Path

from _branch_repos import advance, clone_pair
from _forge_fake import git_out, run_git
from _forge_state import StateForge

from dev_lab.dev.forge import fetch_origin
from dev_lab.dev.prsuperseded import close_superseded

_MANIFEST = """[project]
name = "planted"
version = "0"

[tool.lab_commons.branchset]
trunk = "main"
sessions = ["integrate/main"]
ephemeral = ["pr/*"]

[tool.lab_commons.integrator]
"""


def _setup(tmp_path: Path) -> tuple[Path, StateForge, int, int, int]:
    """``pr/old`` (salvaged), ``pr/new`` (its open replacement, carrying old's commit), ``pr/other`` (unrelated)."""
    _, work = clone_pair(tmp_path)
    (work / 'pyproject.toml').write_text(_MANIFEST, encoding='utf-8')
    old = advance(work, 'pr/old', 'o.txt', 'o\n')
    run_git(work, 'push', '-q', '--no-verify', 'origin', f'{old}:refs/heads/pr/new')
    run_git(work, 'fetch', '-q', 'origin')
    new = advance(work, 'pr/new', 'n.txt', 'n\n')
    other = advance(work, 'pr/other', 'x.txt', 'x\n')
    forge = StateForge()
    return (
        work,
        forge,
        forge.add_pull('pr/old', 'integrate/main', sha=old),
        forge.add_pull('pr/new', 'integrate/main', sha=new),
        forge.add_pull('pr/other', 'integrate/main', sha=other),
    )


def _close(work: Path, forge: StateForge, numbers: tuple[int, ...], by: int) -> tuple[int, list[str]]:
    said: list[str] = []
    code = close_superseded(
        work,
        forge,
        numbers,
        by=by,
        line='salvaged',
        session='s',
        fetch=fetch_origin,
        say=said.append,
        alarm=lambda _a: None,
    )
    return code, said


def test_a_salvaged_pr_is_commented_closed_and_its_branch_deleted(tmp_path: Path) -> None:
    work, forge, old, new, other = _setup(tmp_path)
    code, _ = _close(work, forge, (old,), new)
    assert code == 0
    assert forge.pulls[old]['state'] == 'closed'
    assert [c['body'] for c in forge.comments[old]][-1].endswith(f'superseded by #{new}: salvaged')
    assert not git_out(work, 'ls-remote', '--heads', 'origin', 'pr/old')
    assert forge.pulls[other]['state'] == 'open', 'PLANTED: an unnamed PR is untouched'


def test_a_closed_target_is_refused_and_nothing_is_written(tmp_path: Path) -> None:
    work, forge, old, new, _ = _setup(tmp_path)
    forge.pulls[old]['state'] = 'closed'
    code, said = _close(work, forge, (old,), new)
    assert code == 1
    assert not forge.comments[old]
    assert any('refused' in line for line in said)


def test_a_replacement_not_open_or_already_merged_is_refused(tmp_path: Path) -> None:
    work, forge, old, new, _ = _setup(tmp_path)
    forge.pulls[new]['state'] = 'closed'
    assert _close(work, forge, (old,), new)[0] == 1
    forge.pulls[new]['state'] = 'open'
    run_git(work, 'push', '-q', '--no-verify', 'origin', 'origin/pr/new:refs/heads/integrate/main')
    code, said = _close(work, forge, (old,), new)
    assert code == 1
    assert any('already merged' in line for line in said)
    assert forge.pulls[old]['state'] == 'open'
