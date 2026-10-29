"""SUPERSEDED-PRS-CLOSE: a salvaged PR is closed and commented, its branch never deleted; refusals touch nothing.

Real git (a bare origin and a clone) and the stateful fake forge. PLANTED CONTROLS: an unnamed open PR is
untouched; a closed target, a merged replacement and a closed replacement each refuse before any write.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from _branch_repos import advance, clone_pair
from _forge_fake import git_out, run_git
from _forge_state import StateForge

from dev_lab.dev.forge import fetch_origin
from dev_lab.dev.forgework import ForgeCallFailed
from dev_lab.dev.netverb import Report
from dev_lab.dev.prsuperseded import close_superseded

_MANIFEST = """[project]
name = "planted"
version = "0"

[tool.dev_lab.branchset]
trunk = "main"
sessions = ["integrate/main"]
ephemeral = ["pr/*"]

[tool.dev_lab.integrator]
integration = "integrate/main"
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


def _close(work: Path, forge: StateForge, numbers: tuple[int, ...], by: int | str) -> tuple[int, list[str]]:
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
    )
    return code, said


def test_a_salvaged_pr_is_closed_and_commented_and_its_branch_kept(tmp_path: Path) -> None:
    work, forge, old, new, other = _setup(tmp_path)
    code, _ = _close(work, forge, (old,), new)
    assert code == 0
    assert forge.pulls[old]['state'] == 'closed'
    assert [c['body'] for c in forge.comments[old]][-1].endswith(f'superseded by #{new}: salvaged')
    assert git_out(work, 'ls-remote', '--heads', 'origin', 'pr/old'), 'remote ref deletion is never this verb'
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


def test_a_number_named_twice_is_closed_and_commented_once(tmp_path: Path) -> None:
    work, forge, old, new, _ = _setup(tmp_path)
    assert _close(work, forge, (old, old), new)[0] == 0
    assert len(forge.comments[old]) == 1


def test_a_close_that_fails_writes_no_comment_and_stops(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """CLOSE FIRST: a PR the forge would not close is never left open saying it is superseded."""
    work, forge, old, new, other = _setup(tmp_path)
    real = forge.call

    def call(method: str, path: str, *args: object, **kwargs: object) -> object:
        if method == 'PATCH' and path.endswith(f'/pulls/{old}'):
            raise ForgeCallFailed(Report(('PATCH', path), (), 1))
        return real(method, path, *args, **kwargs)

    monkeypatch.setattr(forge, 'call', call)
    code, said = _close(work, forge, (old, other), new)
    assert code == 1
    assert not forge.comments[old]
    assert forge.pulls[other]['state'] == 'open', 'the PRs after the failure are untouched'
    assert any('stopped' in line for line in said)


def test_a_commit_carrier_supersedes_without_an_open_pr(tmp_path: Path) -> None:
    """``--by <sha|ref>``: the salvage may live on a commit with no PR; the comment names its sha."""
    work, forge, old, _, other = _setup(tmp_path)
    carrier = git_out(work, 'rev-parse', 'origin/pr/new')
    code, said = _close(work, forge, (old,), 'pr/new')
    assert code == 0, said
    assert forge.pulls[old]['state'] == 'closed'
    assert forge.comments[old][-1]['body'].endswith(f'superseded by {carrier[:12]}: salvaged')
    assert git_out(work, 'ls-remote', '--heads', 'origin', 'pr/old')
    assert forge.pulls[other]['state'] == 'open'


def test_an_unresolvable_carrier_is_refused_and_nothing_is_written(tmp_path: Path) -> None:
    work, forge, old, _, _ = _setup(tmp_path)
    code, said = _close(work, forge, (old,), 'no-such-ref')
    assert code == 1
    assert forge.pulls[old]['state'] == 'open'
    assert not forge.comments[old]
    assert any('no-such-ref' in line and 'refused' in line for line in said)
