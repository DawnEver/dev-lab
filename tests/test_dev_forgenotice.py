"""FORGE NOTICES: a red, conflicted or stalled PR head tells the session its commits carry, once per (head, kind).

Real git (a bare ``origin`` and a clone) and the stateful fake forge; the evidence is the PR's one integration comment
and what ``forge notices`` prints. Every notice has its planted control: the same PR without the fault says nothing.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from _branch_repos import clone_pair
from _forge_fake import git_out, run_git
from _forge_state import StateForge

from lab_commons.dev import forgenotice
from lab_commons.dev.forgeintegration import tick
from lab_commons.dev.labsession import TRAILER
from lab_commons.dev.lanepolicy import Policy, policy_from

SESSION = 'session_aaaabbbbcccc'
_NOW = datetime.now(UTC) + timedelta(minutes=5)


def _head(work: Path, branch: str, name: str, *, session: str = SESSION) -> str:
    start = f'origin/{branch}' if git_out(work, 'branch', '-r', '--list', f'origin/{branch}') else 'origin/main'
    run_git(work, 'checkout', '-q', '-B', 'tmp', start)
    (work / name).write_text(name, encoding='utf-8')
    run_git(work, 'add', name)
    message = f'feat: {name}' + (f'\n\n{TRAILER}: {session}' if session else '')
    run_git(work, 'commit', '-q', '--no-verify', '-m', message)
    run_git(work, 'push', '-q', '--no-verify', 'origin', f'HEAD:refs/heads/{branch}')
    run_git(work, 'fetch', '-q', 'origin')
    run_git(work, 'checkout', '-q', '--detach')
    return git_out(work, 'rev-parse', 'HEAD')


def _dir(path: Path) -> Path:
    path.mkdir()
    return path


def _world(tmp_path: Path, *, session: str = SESSION) -> tuple[Path, StateForge, int, str]:
    _, work = clone_pair(tmp_path)
    head = _head(work, 'pr/x', 'x.txt', session=session)
    forge = StateForge()
    return work, forge, forge.add_pull('pr/x', 'integrate/main', sha=head), head


def _part(forge: StateForge, sha: str, state: str) -> None:
    forge.statuses.setdefault(sha, []).append(
        {'id': len(forge.statuses.get(sha, [])) + 1, 'context': 'tests/base', 'status': state, 'state': state,
         'description': 'scope=full ran=3 hands=-', 'target_url': 'https://records/1'}
    )  # fmt: skip


def _tick(work: Path, forge: StateForge, head: str, *, now: datetime = _NOW, host: str = 'h1') -> None:
    tick(work, forge, Policy(), fetch_pull=lambda _r, _m, _n: head, host=host, clock=lambda _c: now)


def _notices(work: Path, forge: StateForge, *argv: str, now: datetime = _NOW) -> tuple[int, str]:
    out: list[str] = []
    import lab_commons.dev.forgenotice as module  # noqa: PLC0415

    real = module.emit
    module.emit = lambda line, **_k: out.append(line)  # type: ignore[assignment]
    try:
        code = forgenotice.main(list(argv), cwd=work, client=forge, clock=lambda: now)
    finally:
        module.emit = real
    return code, '\n'.join(out)


def test_a_red_head_notifies_its_session_once_and_a_green_head_closes_it(tmp_path: Path) -> None:
    """PLANTED control: another session sees nothing, and a later green head closes the notice."""
    work, forge, number, head = _world(tmp_path)
    _part(forge, head, 'failure')
    _tick(work, forge, head)
    _tick(work, forge, head)
    (comment,) = forge.comments[number]
    assert comment['body'].count(f'{number}-{head[:12]}-red') == 1, 'one notice, not one per tick'
    assert comment['body'].count('"kind": "red"') == 1
    code, said = _notices(work, forge, '--session', SESSION)
    assert code == 1
    assert 'tests/base' in said
    assert 'https://records/1' in said
    assert _notices(work, forge, '--session', 'session_someone_else')[0] == 0
    green = _head(work, 'pr/x', 'y.txt')
    _part(forge, green, 'success')
    _tick(work, forge, green)
    assert _notices(work, forge, '--session', SESSION) == (0, '')


def test_an_unaddressed_or_unanswered_notice_goes_to_the_integrator(tmp_path: Path) -> None:
    """PLANTED control: an addressed notice is the integrator's only after notice_escalate with no new push."""
    work, forge, _, head = _world(tmp_path, session='')
    _part(forge, head, 'failure')
    _tick(work, forge, head)
    assert _notices(work, forge, '--integrator')[0] == 1, 'no Lab-Session: unaddressed'

    work, forge, _, head = _world(_dir(tmp_path / 'b'))
    _part(forge, head, 'failure')
    _tick(work, forge, head)
    assert _notices(work, forge, '--integrator')[0] == 0
    assert _notices(work, forge, '--integrator', now=_NOW + timedelta(hours=3))[0] == 1


def test_a_head_unsettled_past_notice_stall_is_a_stall(tmp_path: Path) -> None:
    """PLANTED control: the same unsettled head inside notice_stall says nothing."""
    work, forge, number, head = _world(tmp_path)
    _tick(work, forge, head)
    assert _notices(work, forge)[0] == 0
    _tick(work, forge, head, now=_NOW + timedelta(hours=7))
    code, said = _notices(work, forge, '--session', SESSION)
    assert code == 1
    assert f'{number}-{head[:12]}-stall' in said


def test_an_acked_notice_leaves_the_session_view_and_a_hostless_tick_keeps_it(tmp_path: Path) -> None:
    """PLANTED control: before the ack the session sees it; ``forge integration`` (no host) erases nothing."""
    work, forge, number, head = _world(tmp_path)
    _part(forge, head, 'failure')
    _tick(work, forge, head)
    _tick(work, forge, head, host='')
    assert _notices(work, forge, '--session', SESSION)[0] == 1
    assert _notices(work, forge, '--ack', f'{number}-{head[:12]}-red')[0] == 0
    _tick(work, forge, head)
    assert _notices(work, forge, '--session', SESSION)[0] == 0
    assert _notices(work, forge)[0] == 1, 'acked is not closed'


def test_a_conflict_is_its_own_kind() -> None:
    """PLANTED control: no conflict, no part failed, inside the stall: nothing."""
    calm = forgenotice.kinds((), conflicts=(), settled=False, age=timedelta(0), stall=timedelta(hours=6))
    assert calm == {}
    found = forgenotice.kinds((), conflicts=('a.py',), settled=False, age=timedelta(0), stall=timedelta(hours=6))
    assert set(found) == {forgenotice.CONFLICT}


def test_the_notice_durations_are_declared_with_a_unit() -> None:
    policy = policy_from("[tool.lab_commons.integrator]\nnotice_escalate = '30 min'\n", 'p')
    assert forgenotice.duration('notice_escalate', policy.notice_escalate) == timedelta(minutes=30)
    with pytest.raises(ValueError, match='needs a unit'):
        forgenotice.duration('notice_escalate', '2')
