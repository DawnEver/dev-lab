"""LANDED-PRS-CLOSE: an open PR whose head is on its base is closed and commented once; its branch is kept.

Real git (a bare ``origin`` and a clone) and the stateful fake forge for the PRs. PLANTED CONTROLS: beside the
contained PR that is closed (its branch left to the forge's prune), a PR with a commit of its own is untouched;
a second tick does nothing.
"""

from __future__ import annotations

import json
from pathlib import Path

from _branch_repos import advance, clone_pair
from _forge_fake import git_out, run_git
from _forge_state import StateForge

from dev_lab.dev.forge import fetch_origin
from dev_lab.dev.prlanded import EVENT, close_landed

_MANIFEST = """[project]
name = "planted"
version = "0"

[tool.lab_commons.branchset]
trunk = "main"
sessions = ["integrate/main"]
ephemeral = ["pr/*"]

[tool.lab_commons.integrator]
"""


def _on_origin(work: Path, branch: str) -> bool:
    return bool(git_out(work, 'ls-remote', '--heads', 'origin', branch))


def _setup(tmp_path: Path) -> tuple[Path, StateForge, int, int, str]:
    """A contained PR (``pr/done``, merged into integrate/main) and an uncontained one (``pr/open``)."""
    _, work = clone_pair(tmp_path)
    (work / 'pyproject.toml').write_text(_MANIFEST, encoding='utf-8')
    head = advance(work, 'pr/done', 'd.txt', 'd\n')
    run_git(work, 'checkout', '-q', '-B', 'tmp-int', 'origin/integrate/main')
    run_git(work, '-c', 'user.name=t', '-c', 'user.email=t@t', 'merge', '-q', '--no-ff', '--no-verify', head)
    run_git(work, 'push', '-q', '--no-verify', 'origin', 'HEAD:refs/heads/integrate/main')
    run_git(work, 'fetch', '-q', 'origin')
    mine = advance(work, 'pr/open', 'o.txt', 'o\n')
    forge = StateForge()
    done = forge.add_pull('pr/done', 'integrate/main', sha=head)
    still = forge.add_pull('pr/open', 'integrate/main', sha=mine)
    return work, forge, done, still, head


def _tick(work: Path, forge: StateForge, numbers: tuple[int, ...] = ()) -> tuple[int, list[str]]:
    said: list[str] = []
    code = close_landed(work, forge, numbers, session='s', fetch=fetch_origin, say=said.append)
    return code, said


def test_a_contained_pr_is_closed_and_commented_its_branch_kept_and_an_uncontained_one_untouched(
    tmp_path: Path,
) -> None:
    work, forge, done, still, head = _setup(tmp_path)
    code, said = _tick(work, forge)
    assert code == 0
    assert forge.pulls[done]['state'] == 'closed'
    assert forge.pulls[still]['state'] == 'open', 'PLANTED: a head with a commit of its own is never touched'
    assert not forge.comments[still]
    (comment,) = forge.comments[done]
    merge = git_out(work, 'rev-parse', 'origin/integrate/main')
    assert f'landed: head {head[:12]} is on integrate/main (merged by {merge[:12]})' in comment['body']
    assert _on_origin(work, 'pr/done'), 'remote ref deletion is the prune_merged data, never this verb'
    assert _on_origin(work, 'pr/open')
    events = [json.loads(line) for line in said if line.startswith('{')]
    assert {(e['event'], e['pr']) for e in events if e['event'] == EVENT} == {(EVENT, done)}


def test_a_second_tick_does_nothing(tmp_path: Path) -> None:
    work, forge, done, _, _ = _setup(tmp_path)
    _tick(work, forge)
    code, said = _tick(work, forge)
    assert code == 0
    assert not said
    assert len(forge.comments[done]) == 1


def test_the_verb_refuses_a_named_pr_whose_head_is_not_contained(tmp_path: Path) -> None:
    work, forge, _, still, _ = _setup(tmp_path)
    code, said = _tick(work, forge, (still,))
    assert code == 1
    assert forge.pulls[still]['state'] == 'open'
    assert any(f'#{still}' in line and 'not on integrate/main' in line for line in said)
