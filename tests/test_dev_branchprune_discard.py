"""DISCARD-ON-RULING: ``branchprune discard <branch> --approved "<words>"`` drops an origin branch WITHOUT landing it.

MEASURED 2026-11-24 (numerics-lab, public): the user ordered an origin branch deleted because it carries a PRIVATE
pre-GitHub history -- a second root. LOSSLESS-DELETE refused it (commits on it alone) and prescribed landing it by a
``git merge -s ours`` PR, which would publish that very root into the mainline; the raw delete is refused by
PUSH-REMOTE-DELETE. No door existed. Real git (a bare origin, a clone whose pre-push runs the REAL
``lossless-delete`` row) and the stateful fake forge. PLANTED CONTROLS: refused without approval and the branch
survives; deleted with approval through the same hook; the second-root hint shows only on a second root.
"""

from __future__ import annotations

import json
from pathlib import Path

from _branch_repos import advance, commit
from _forge_fake import git_out, run_git
from _forge_state import StateForge
from test_dev_pushdelete import _hooked, _on_origin, _shell_delete

from dev_lab.dev.branchdelete import DISCARDED_EVENT, delete, discard
from dev_lab.dev.branchprune import main
from dev_lab.dev.forge import fetch_origin

SESSION = 'session_aaaabbbbcccc'
RULING = 'user 2026-11-24: delete it, it carries the private history'


def _private_root(work: Path, branch: str) -> str:
    """Push *branch* to origin as a history of its own root (an orphan commit); its sha."""
    run_git(work, 'checkout', '-q', '--orphan', 'tmp-private')
    run_git(work, 'rm', '-q', '-rf', '--cached', '.')
    sha = commit(work, 'secret.txt', 'private\n')
    run_git(work, 'push', '-q', '--no-verify', 'origin', f'HEAD:refs/heads/{branch}')
    run_git(work, 'checkout', '-q', '-f', '--detach', 'origin/main')
    run_git(work, 'clean', '-q', '-fdx')
    run_git(work, 'fetch', '-q', 'origin')
    return sha


def _discard(work: Path, branch: str, approved: str) -> tuple[int, list[str], list[object]]:
    said: list[str] = []
    alarms: list[object] = []
    code = discard(
        work,
        [branch],
        approved=approved,
        client=StateForge(),
        session=SESSION,
        fetch=fetch_origin,
        say=said.append,
        alarm=alarms.append,
    )
    return code, said, alarms


def test_a_discard_without_the_users_words_is_refused_by_name_and_the_branch_survives(tmp_path: Path) -> None:
    work, _ = _hooked(tmp_path)
    _private_root(work, 'pr/private')
    code, said, alarms = _discard(work, 'pr/private', '  ')
    assert code == 2
    assert _on_origin(work, 'pr/private')
    assert any('--approved "<the user' in line for line in said), said
    assert not alarms


def test_the_cli_refuses_discard_without_approved(tmp_path: Path, capsys) -> None:
    assert main(['discard', 'pr/private'], cwd=tmp_path) == 2
    assert '--approved' in capsys.readouterr().err


def test_an_approved_discard_deletes_through_the_hook_and_records_sha_and_words(tmp_path: Path) -> None:
    work, log = _hooked(tmp_path)
    sha = _private_root(work, 'pr/private')
    code, said, alarms = _discard(work, 'pr/private', RULING)
    assert code == 0, said
    assert not _on_origin(work, 'pr/private')
    assert 'refs/heads/pr/private' in log.read_text(encoding='utf-8'), 'the door`s push ran the hook'
    (record,) = [json.loads(line) for line in said if line.startswith('{')]
    assert record == {'event': DISCARDED_EVENT, 'ref': 'pr/private', 'sha': sha, 'approved': RULING, 'session': SESSION}
    (alarm,) = alarms
    assert sha[:12] in alarm.body
    assert RULING in alarm.body
    common = Path(git_out(work, 'rev-parse', '--path-format=absolute', '--git-common-dir'))
    assert not any((common / 'dev_lab').rglob('*.grant')), 'the grant is spent; no bundle or backup is kept (R2)'


def test_the_grant_is_one_branch_at_one_sha_a_shell_delete_of_another_is_still_refused(tmp_path: Path) -> None:
    """PLANTED CONTROL: an approved discard opens nothing for any other delete the hook judges."""
    work, _ = _hooked(tmp_path)
    _private_root(work, 'pr/private')
    advance(work, 'pr/other', 'o.txt', 'o\n')
    assert _discard(work, 'pr/private', RULING)[0] == 0
    done = _shell_delete(work, 'pr/other')
    assert done.returncode != 0
    assert _on_origin(work, 'pr/other')


def test_an_approved_discard_never_takes_integration_or_an_open_pr_head(tmp_path: Path) -> None:
    work, _ = _hooked(tmp_path)
    advance(work, 'pr/open', 'x.txt', 'x\n')
    forge = StateForge()
    forge.add_pull('pr/open', 'integrate/main')
    said: list[str] = []
    for branch in ('integrate/main', 'pr/open'):
        code = discard(
            work,
            [branch],
            approved=RULING,
            client=forge,
            session=SESSION,
            fetch=fetch_origin,
            say=said.append,
            alarm=said.append,
        )
        assert code == 1
        assert _on_origin(work, branch)
    assert len([line for line in said if 'never deleted' in line]) == 2


def test_a_refused_delete_of_a_second_root_names_the_discard_door(tmp_path: Path) -> None:
    work, _ = _hooked(tmp_path)
    root = _private_root(work, 'pr/private')
    said: list[str] = []
    assert (
        delete(
            work,
            ['pr/private'],
            client=StateForge(),
            session='s',
            fetch=fetch_origin,
            say=said.append,
            alarm=said.append,
        )
        == 1
    )
    (line,) = said
    assert f'a root of its own ({root[:12]})' in line
    assert 'branchprune discard pr/private --approved' in line
    hooked = _shell_delete(work, 'pr/private')
    assert 'branchprune discard pr/private --approved' in hooked.stderr, 'the pre-push refusal names it too'


def test_a_refused_delete_on_the_shared_root_never_offers_discard(tmp_path: Path) -> None:
    """PLANTED CONTROL for the hint: an ordinary unlanded branch is told MERGE or LAND only."""
    work, _ = _hooked(tmp_path)
    advance(work, 'pr/mine', 'm.txt', 'm\n')
    said: list[str] = []
    assert (
        delete(
            work, ['pr/mine'], client=StateForge(), session='s', fetch=fetch_origin, say=said.append, alarm=said.append
        )
        == 1
    )
    assert 'discard' not in said[0]
    assert 'discard' not in _shell_delete(work, 'pr/mine').stderr
