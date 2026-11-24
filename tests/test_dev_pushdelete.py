"""LOSSLESS-DELETE at pre-push: every branch a push deletes is judged, however the push was spelled.

MEASURED 2026-11-17: a session built its refspecs at run time (``refs=$(printf ':refs/heads/pr/%s ' ...)``, then
``git push origin $refs``) and deleted nine origin branches holding unlanded commits. The deny row
``PUSH-REMOTE-DELETE`` reads command TEXT, which held no ``:ref``; the pre-push hook never judged a delete. Now the
base ``lossless-delete`` row judges every deleted branch on git's own ref lines with the judgment
``branchprune delete`` makes (:func:`dev_lab.dev.deletejudge.judge`).

Real git throughout: a bare ``origin``, a clone, and for the end-to-end cases a REAL ``git push`` whose pre-push hook
runs the real runner over the base table's ``lossless-delete`` row(s) -- before the row existed it ran nothing, and
the shell-assembled delete went through. Only the forge's open-PR listing is faked (:class:`StateForge`). The
evidence is what ``origin`` holds afterwards. PLANTED CONTROLS: the landed twin of each refused branch goes.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from _branch_repos import advance, clone_pair
from _forge_fake import git_out, run_git
from _forge_state import StateForge

from dev_lab.dev import disclosure, forgeclient, pushdelete, walls
from dev_lab.dev.branchdelete import delete
from dev_lab.dev.forge import fetch_origin
from dev_lab.dev.forgefailure import ForgeCallFailed
from dev_lab.dev.githooks.runner import ZERO_SHA, run_stage
from dev_lab.dev.githooks.table import base_rows, merge
from dev_lab.dev.lanepolicy import Derived, policy_from
from dev_lab.dev.netverb import Attempt, Diagnosis, Report

ROOT = Path(__file__).resolve().parents[1]
#: The planted repo's integrator table declaring the component bump lane DERIVED (decision D23).
_DERIVED = (
    "[tool.dev_lab.integrator]\nintegration = 'integrate/main'\n"
    "derived = [{ branch = 'pr/components-bump', producer = 'dev_lab.dev.componentbump' }]\n"
)
TESTS = Path(__file__).resolve().parent
SH = shutil.which('sh')

#: The pre-push hook a planted clone runs: the REAL runner over the base table's ``lossless-delete`` row(s), the
#: forge's open-PR listing answered by a :class:`StateForge` holding the heads ``PLANTED_OPEN_HEADS`` names.
_HOOK = """
import os, sys
from pathlib import Path
sys.path.insert(0, {tests!r})
from _forge_state import StateForge
from dev_lab.dev import forgeclient
from dev_lab.dev.githooks.runner import run_stage
from dev_lab.dev.githooks.table import base_rows, merge
forge = StateForge()
for head in filter(None, os.environ.get('PLANTED_OPEN_HEADS', '').split(',')):
    forge.add_pull(head, 'integrate/main')
forgeclient.client_for = lambda root, **_: forge
stdin = sys.stdin.read()
with Path({log!r}).open('a', encoding='utf-8') as seen:
    seen.write(stdin)
rows = [hook for hook in merge(base_rows(), {{}})['pre-push'] if hook.id == 'lossless-delete']
sys.exit(run_stage('pre-push', sys.argv[1:], root=Path.cwd(), stdin=stdin, hooks=rows))
"""


class _Unreadable(StateForge):
    """A forge answering every call 502: the open PR heads cannot be read."""

    def call(self, method: str, path: str, body: object = None, durable: object = None) -> object:
        del body, durable
        raise ForgeCallFailed(Report((method, path), (Attempt(1, 502, 'bad gateway', Diagnosis.UNCLASSIFIED),), 1))


def _rows() -> list[object]:
    return [hook for hook in merge(base_rows(), {})['pre-push'] if hook.id == pushdelete.HOOK_ID]


def _hooked(tmp_path: Path) -> tuple[Path, Path]:
    """``(clone, the hook's log of every ref line it was handed)``: a planted repo whose pushes run the hook."""
    _, work = clone_pair(tmp_path)
    hooks = tmp_path / 'hooks'
    hooks.mkdir()
    log = tmp_path / 'hook-lines.txt'
    script = hooks / 'pre_push.py'
    script.write_text(_HOOK.format(tests=TESTS.as_posix(), log=log.as_posix()), encoding='utf-8')
    shim = f'#!/bin/sh\nexec "{Path(sys.executable).as_posix()}" "{script.as_posix()}" "$@"\n'
    (hooks / 'pre-push').write_text(shim, encoding='utf-8', newline='\n')
    (hooks / 'pre-push').chmod(0o755)
    run_git(work, 'config', 'core.hooksPath', hooks.as_posix())
    return work, log


def _on_origin(work: Path, branch: str) -> bool:
    return bool(git_out(work, 'ls-remote', '--heads', 'origin', branch))


def _landed(work: Path, branch: str) -> str:
    """Put *branch* on origin at integration's new tip (contained, so lossless); its sha."""
    tip = advance(work, 'integrate/main', f'{branch.replace("/", "-")}.txt', 'landed\n')
    run_git(work, 'push', '-q', '--no-verify', 'origin', f'{tip}:refs/heads/{branch}')
    run_git(work, 'fetch', '-q', 'origin')
    return tip


def _shell_delete(
    work: Path, *branches: str, heads: tuple[str, ...] = (), env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """The incident's spelling: the refspecs assembled into ``$refs`` at run time, so no ``:ref`` is in the text."""
    assert SH is not None, 'no sh on PATH: the incident`s shell spelling cannot be replayed on this box'
    script = 'refs=$(printf ":refs/heads/%s " "$@"); git push origin $refs'
    env = {**os.environ, 'GIT_TERMINAL_PROMPT': '0', 'PLANTED_OPEN_HEADS': ','.join(heads), **(env or {})}
    return subprocess.run(
        [SH, '-c', script, 'sh', *branches],
        cwd=work,
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        env=env,
        timeout=300,
        check=False,
    )


def _bump(work: Path, branch: str) -> str:
    """A component bump as ``componentbump`` opens one -- one gitlink commit on integration's tip -- on *branch*."""
    run_git(work, 'checkout', '-q', '-B', 'tmp-bump', 'origin/integrate/main')
    engine = git_out(work, 'rev-parse', 'HEAD')
    run_git(work, 'update-index', '--add', '--cacheinfo', f'160000,{engine},engines/core')
    run_git(work, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '--no-verify', '-m', 'bump core')
    tip = git_out(work, 'rev-parse', 'HEAD')
    run_git(work, 'push', '-q', '--no-verify', 'origin', f'{tip}:refs/heads/{branch}')
    run_git(work, 'fetch', '-q', 'origin')
    return tip


def _line(branch: str, sha: str) -> str:
    return f'(delete) {ZERO_SHA} refs/heads/{branch} {sha}\n'


def _judged(work: Path, lines: str, forge: StateForge | None = None, **kwargs: object) -> list[str]:
    return pushdelete.refusals(work, lines, client=lambda: forge or StateForge(), **kwargs)


# --------------------------------------------------------------------------------------------- end to end


def test_a_shell_assembled_delete_of_an_unlanded_branch_is_refused_and_the_ref_survives(tmp_path: Path) -> None:
    """THE INCIDENT, replayed: before the ``lossless-delete`` row the hook ran nothing and the branch was gone."""
    work, _ = _hooked(tmp_path)
    unique = advance(work, 'pr/mine', 'm.txt', 'm\n')
    done = _shell_delete(work, 'pr/mine')
    assert done.returncode != 0, done.stderr
    assert _on_origin(work, 'pr/mine'), 'the unlanded branch survives on origin'
    assert f'{pushdelete.RULE}: pr/mine: refused -- 1 commit(s) exist on it alone ({unique[:12]})' in done.stderr
    assert '-m dev_lab.dev.branchprune delete pr/mine' in done.stderr


def test_the_same_shell_assembled_delete_of_a_landed_branch_goes(tmp_path: Path) -> None:
    """PLANTED CONTROL for the refusal above: the hook is the same, only the branch's content is held."""
    work, log = _hooked(tmp_path)
    _landed(work, 'pr/done')
    done = _shell_delete(work, 'pr/done')
    assert done.returncode == 0, done.stderr
    assert not _on_origin(work, 'pr/done')
    assert 'refs/heads/pr/done' in log.read_text(encoding='utf-8'), 'the hook judged the delete'


def test_an_open_pr_head_is_refused_though_its_commits_are_landed(tmp_path: Path) -> None:
    work, _ = _hooked(tmp_path)
    _landed(work, 'pr/open')
    done = _shell_delete(work, 'pr/open', heads=('pr/open',))
    assert done.returncode != 0
    assert _on_origin(work, 'pr/open')
    assert 'pr/open: refused -- it is the head of open PR #' in done.stderr


def test_the_door_deletes_a_landed_branch_through_the_same_hook(tmp_path: Path) -> None:
    """``branchprune delete`` judges, then pushes the delete; the hook judges it again and lets it go -- no bypass."""
    work, log = _hooked(tmp_path)
    _landed(work, 'feat/done')
    said: list[str] = []
    code = delete(
        work, ['feat/done'], client=StateForge(), session='s', fetch=fetch_origin, say=said.append, alarm=said.append
    )
    assert code == 0, said
    assert not _on_origin(work, 'feat/done')
    assert 'refs/heads/feat/done' in log.read_text(encoding='utf-8'), 'the door`s push ran the hook'


def test_a_tag_on_origin_holds_no_delete_whatever_the_env_says(tmp_path: Path) -> None:
    """D22, no archive tags: a tag holding the tip, and the retired approval variable set, hold nothing."""
    work, _ = _hooked(tmp_path)
    tip = advance(work, 'lane/old', 'o.txt', 'o\n')
    run_git(work, 'push', '-q', '--no-verify', 'origin', f'{tip}:refs/tags/keep/lane-old')
    done = _shell_delete(work, 'lane/old', env={'DEV_LAB_DELETE_APPROVED': 'drop the old lane'})
    assert done.returncode != 0, done.stderr
    assert _on_origin(work, 'lane/old')
    assert 'lane/old: refused -- 1 commit(s) exist on it alone' in done.stderr
    assert '`git merge -s ours`' in done.stderr, 'the door names MERGE or LAND, never a tag'


def test_a_held_red_bump_on_a_declared_derived_branch_deletes_through_the_hook(tmp_path: Path) -> None:
    """D23: ``pr/components-bump`` is declared derived with its producer, so its held gitlink commit goes.

    PLANTED CONTROL: the very same commit on ``pr/relock``, machine-looking but undeclared, is refused -- and the
    derived branch, which may go any time, holds nothing for it.
    """
    work, _ = _hooked(tmp_path)
    tip = _bump(work, 'pr/components-bump')
    run_git(work, 'push', '-q', '--no-verify', 'origin', f'{tip}:refs/heads/pr/relock')
    run_git(work, 'fetch', '-q', 'origin')
    (work / 'pyproject.toml').write_text(_DERIVED, encoding='utf-8')
    undeclared = _shell_delete(work, 'pr/relock')
    assert undeclared.returncode != 0, undeclared.stderr
    assert _on_origin(work, 'pr/relock')
    assert 'pr/relock: refused -- 1 commit(s) exist on it alone' in undeclared.stderr
    derived = _shell_delete(work, 'pr/components-bump')
    assert derived.returncode == 0, derived.stderr
    assert not _on_origin(work, 'pr/components-bump')
    assert _on_origin(work, 'pr/relock'), 'the undeclared twin still stands'


# ------------------------------------------------------------------------------------------- the runner


def test_run_stage_refuses_a_zero_sha_line_for_an_unlanded_sha(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bare, work = clone_pair(tmp_path)
    sha = advance(work, 'lane/mine', 'm.txt', 'm\n')
    monkeypatch.setattr(forgeclient, 'client_for', lambda _root, **_: StateForge())
    rows = _rows()
    assert len(rows) == 1, 'the base declares one lossless-delete pre-push row'
    assert rows[0].always_run, 'it judges every push, a delete-only one included'
    assert rows[0].refs is None, 'a ref filter drops deletion lines'
    assert run_stage('pre-push', ['origin', str(bare)], root=work, stdin=_line('lane/mine', sha), hooks=rows) == 1
    landed = _landed(work, 'lane/done')
    assert run_stage('pre-push', ['origin', str(bare)], root=work, stdin=_line('lane/done', landed), hooks=rows) == 0


# ------------------------------------------------------------------------------------------- the judgment


def test_branches_holding_only_each_others_commits_are_refused_when_deleted_together(tmp_path: Path) -> None:
    """A branch deleted in the same push holds nothing: nine lanes sharing commits went in one push."""
    _, work = clone_pair(tmp_path)
    tip = advance(work, 'lane/a', 'a.txt', 'a\n')
    run_git(work, 'push', '-q', '--no-verify', 'origin', f'{tip}:refs/heads/lane/b')
    run_git(work, 'fetch', '-q', 'origin')
    found = _judged(work, _line('lane/a', tip) + _line('lane/b', tip))
    assert [text.split(':', 2)[1].strip() for text in found] == ['lane/a', 'lane/b']
    assert _judged(work, _line('lane/a', tip)) == [], 'PLANTED CONTROL: alone, lane/a is held by lane/b'


def test_a_push_deleting_nothing_never_asks_the_forge(tmp_path: Path) -> None:
    _, work = clone_pair(tmp_path)
    sha = git_out(work, 'rev-parse', 'HEAD')

    def unreachable() -> StateForge:
        msg = 'a push deleting no branch must not read the forge'
        raise AssertionError(msg)

    pushed = f'refs/heads/lane/x {sha} refs/heads/lane/x {ZERO_SHA}\n'
    tag = f'(delete) {ZERO_SHA} refs/tags/v1 {sha}\n'
    assert pushdelete.refusals(work, pushed + tag, client=unreachable) == []


def test_a_deleted_sha_this_clone_never_fetched_is_refused(tmp_path: Path) -> None:
    _, work = clone_pair(tmp_path)
    found = _judged(work, _line('lane/ghost', 'f' * 40), fetch=lambda _root: None)
    assert len(found) == 1
    assert 'not a commit this clone holds' in found[0]


@pytest.mark.parametrize(
    'row',
    [
        "{ branch = 'pr/components-bump' }",
        "{ branch = 'pr/components-bump', producer = '' }",
        "{ producer = 'dev_lab.dev.componentbump' }",
        "{ branch = 'pr/components-bump', producer = 'dev_lab.dev.componentbump', why = 'x' }",
        "'pr/components-bump'",
    ],
)
def test_a_derived_row_naming_no_producer_is_refused_at_policy_load(row: str) -> None:
    text = f"[tool.dev_lab.integrator]\nintegration = 'integrate/main'\nderived = [{row}]\n"
    with pytest.raises(ValueError, match='must name its branch AND the producer'):
        policy_from(text, 'pyproject.toml')


def test_a_derived_row_with_its_producer_is_read_and_a_malformed_one_refuses_the_delete(tmp_path: Path) -> None:
    """PLANTED CONTROL for the refusals above: the full row parses; the hook refuses a delete under a malformed one."""
    assert policy_from(_DERIVED, 'pyproject.toml').derived == (
        Derived('pr/components-bump', 'dev_lab.dev.componentbump'),
    )
    _, work = clone_pair(tmp_path)
    tip = _bump(work, 'pr/components-bump')
    malformed = _DERIVED.replace(", producer = 'dev_lab.dev.componentbump'", '')
    (work / 'pyproject.toml').write_text(malformed, encoding='utf-8')
    found = _judged(work, _line('pr/components-bump', tip))
    assert len(found) == 1
    assert found[0].startswith(f'{pushdelete.UNJUDGED}:')


# ------------------------------------------------------------------------------------- fail closed, teach


def test_an_unreadable_forge_refuses_naming_the_cause_and_the_retry(tmp_path: Path) -> None:
    _, work = clone_pair(tmp_path)
    tip = _landed(work, 'lane/done')
    found = _judged(work, _line('lane/done', tip), _Unreadable())
    assert len(found) == 1, 'a landed branch is still refused while the open PR heads cannot be read'
    assert found[0].startswith(f'{pushdelete.UNJUDGED}: the forge cannot be read')
    assert 'push again once' in found[0].splitlines()[1]


def test_a_repo_declaring_no_integration_branch_refuses_by_name(tmp_path: Path) -> None:
    _, work = clone_pair(tmp_path)
    tip = _landed(work, 'lane/done')
    (work / 'pyproject.toml').write_text('[project]\nname = "x"\n', encoding='utf-8')
    found = _judged(work, _line('lane/done', tip))
    assert len(found) == 1
    assert found[0].startswith(f'{pushdelete.UNJUDGED}:')
    assert 'names no integration branch' in found[0]


def test_every_refusal_leads_with_its_rule_puts_its_door_on_line_two_and_points_at_its_section(
    tmp_path: Path,
) -> None:
    _, work = clone_pair(tmp_path)
    unique = advance(work, 'lane/mine', 'm.txt', 'm\n')
    tip = _landed(work, 'lane/done')
    unreadable = _Unreadable()
    said = {
        'lossy': (pushdelete.RULE, _judged(work, _line('lane/mine', unique))),
        'protected': (pushdelete.RULE, _judged(work, _line('integrate/main', tip))),
        'forge unreadable': (pushdelete.UNJUDGED, _judged(work, _line('lane/done', tip), unreadable)),
    }
    texts = {case: found[0] for case, (_, found) in said.items()}
    assert {case: len(found) for case, (_, found) in said.items()} == dict.fromkeys(said, 1)
    expected = {case: rule for case, (rule, _) in said.items()}
    assert {case: walls.rule_of(text) for case, text in texts.items()} == expected
    assert {case for case, text in texts.items() if not text.splitlines()[1].startswith('Door: ')} == set()
    assert {case for case, text in texts.items() if not walls.has_remedy(text)} == set()
    assert disclosure.unresolved_pointers(texts, ROOT) == []
    folded = {case: ' '.join(text.splitlines()[:-1]) for case, text in texts.items()}
    assert {case for case, text in folded.items() if walls.has_remedy(text)} == set(), 'PLANTED: one line, no door'
