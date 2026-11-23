"""``hpcaccount reclaim-foreign``: entries OTHER fleet accounts own under one account's home, removed by their owners.

MEASURED 2026-11-23 (``look stuck``): 206,412 entries under alyyw103's ``drwx------`` home belonged to five other fleet
accounts in their ``drwxr-s---`` directories -- the account could not remove them, the owners could not reach them.
The door grants each owner traverse on the ancestor chain, has each owner delete ITS OWN entries, removes the rest,
and revokes every grant in a ``finally``, verified by re-reading the ACLs.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from lab_commons.hpc.grants import AccessRefused

from dev_lab.dev.hpcaccount import reclaim

HOME = '/gpfs01/home/u1'
TARGET = 'ci/experiments/old'
_CENSUS = f'home {HOME}\n  56 o1\n  25 o2\n   7 u1\n'


class _Fleet:
    """Every account's runner records its commands; *fail* names an account whose delete fails."""

    def __init__(
        self, monkeypatch: pytest.MonkeyPatch, *, census: str = _CENSUS, fail: str = '', acl: str = ''
    ) -> None:
        self.ran: list[tuple[str, str]] = []
        self.fail, self.acl, self.census = fail, acl, census
        grants = {user: SimpleNamespace(user=user) for user in ('u1', 'o1', 'o2')}

        def grant(user: str) -> SimpleNamespace:
            if user == 'other-role':
                refusal = 'other-role is a verification account -- hold the integrator session role'
                raise AccessRefused(refusal)
            if user not in grants:
                undeclared = f'no [[hpc.grant]] declares user {user!r}'
                raise LookupError(undeclared)
            return grants[user]

        monkeypatch.setattr(reclaim, 'reached_machine', lambda _users: SimpleNamespace(grant=grant))

    def connect(self, grant: SimpleNamespace) -> object:
        def run(command: str, _stdin: str | None) -> str:
            self.ran.append((grant.user, command))
            if command.startswith(reclaim.CENSUS_MARK):
                return self.census
            if command.startswith(reclaim.VERIFY_MARK):
                return self.acl
            if grant.user == self.fail and ' -delete' in command:
                denied = 'find: cannot delete: Permission denied'
                raise RuntimeError(denied)
            return 'ok\nleft 0\n'

        return run

    def of(self, user: str) -> list[str]:
        return [command for who, command in self.ran if who == user]


def _run(fleet: _Fleet, path: str = TARGET, *, apply: bool = True) -> tuple[int, list[str]]:
    said: list[str] = []
    code = reclaim.reclaim('u1', path, apply=apply, connect=fleet.connect, say=said.append)
    return code, said


def test_dry_run_prints_the_plan_per_owner_and_writes_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    fleet = _Fleet(monkeypatch)
    code, said = _run(fleet, apply=False)
    assert code == 0
    assert f'reclaim-foreign: {HOME}/{TARGET} (dry run)' in said
    assert '  o1: 56 entries -- o1 deletes them through a traverse grant' in said
    assert '  o2: 25 entries -- o2 deletes them through a traverse grant' in said
    assert '  u1: 7 entries -- u1 removes them last' in said
    assert [who for who, _ in fleet.ran] == ['u1'], 'only the census ran'


def test_apply_grants_deletes_per_owner_removes_the_rest_and_revokes(monkeypatch: pytest.MonkeyPatch) -> None:
    fleet = _Fleet(monkeypatch)
    code, said = _run(fleet)
    assert code == 0, said
    mine = fleet.of('u1')
    grant = next(c for c in mine if c.startswith('setfacl -m'))
    for ancestor in (HOME, f'{HOME}/ci', f'{HOME}/ci/experiments'):
        assert f'u:o1:x {ancestor}' in grant
        assert f'u:o2:x {ancestor}' in grant
    assert '-type d -user u1 -exec setfacl -m u:o1:rwx' in grant, 'every u1 directory under the target opens to o1'
    assert any(f'find {HOME}/{TARGET} -user o1 -delete' in c for c in fleet.of('o1'))
    assert any(f'find {HOME}/{TARGET} -user o2 -delete' in c for c in fleet.of('o2'))
    assert not any('-user o2' in c for c in fleet.of('o1')), 'each owner deletes only its own'
    last = [c for c in mine if not c.startswith((reclaim.CENSUS_MARK, reclaim.VERIFY_MARK))]
    assert f'find {HOME}/{TARGET} -user u1 -delete' in last[-2]
    assert last[-1].startswith('setfacl -x')
    assert 'u:o1' in last[-1]
    assert 'u:o2' in last[-1]
    assert mine[-1].startswith(reclaim.VERIFY_MARK)
    assert any(line.startswith('reclaim-foreign: grants revoked and verified') for line in said)


def test_planted_control_grants_are_revoked_when_an_owner_delete_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    fleet = _Fleet(monkeypatch, fail='o1')
    code, said = _run(fleet)
    assert code == 2
    assert any('o1' in line and 'Permission denied' in line for line in said)
    mine = fleet.of('u1')
    assert any(c.startswith('setfacl -x') for c in mine)
    assert mine[-1].startswith(reclaim.VERIFY_MARK)


def test_a_grant_left_after_the_revoke_is_named_and_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    fleet = _Fleet(monkeypatch, acl=f'# file: {HOME}\nuser:o1:--x\n')
    code, said = _run(fleet)
    assert code == 2
    assert any('NOT revoked' in line and 'user:o1:--x' in line for line in said)


def test_planted_control_an_undeclared_owner_is_refused_before_any_write(monkeypatch: pytest.MonkeyPatch) -> None:
    fleet = _Fleet(monkeypatch, census=f'home {HOME}\n  56 o1\n   3 stranger\n')
    code, said = _run(fleet)
    assert code == 2
    assert "  stranger: no [[hpc.grant]] declares user 'stranger'" in said
    assert all(c.startswith(reclaim.CENSUS_MARK) for _, c in fleet.ran)


@pytest.mark.parametrize('path', ['', '..', '../u2/x', '/etc', 'ci/../../x', 'ci/$(id)', 'a b', '.'])
def test_planted_control_a_path_escape_is_refused_before_anything_runs(
    monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    fleet = _Fleet(monkeypatch)
    code, said = _run(fleet, path)
    assert code == 2
    assert said[0].startswith('reclaim-foreign: ')
    assert fleet.ran == []


def test_nothing_foreign_is_said_and_writes_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    fleet = _Fleet(monkeypatch, census=f'home {HOME}\n   7 u1\n')
    code, said = _run(fleet)
    assert code == 0
    assert any('no entry another account owns' in line for line in said)
    assert len(fleet.ran) == 1


def test_an_owner_this_session_cannot_reach_is_refused_naming_its_door(monkeypatch: pytest.MonkeyPatch) -> None:
    """MEASURED 2026-11-23: two of the five owners are verification accounts a research machine does not reach."""
    fleet = _Fleet(monkeypatch, census=f'home {HOME}\n  56 o1\n   3 other-role\n')
    code, said = _run(fleet)
    assert code == 2
    assert any('other-role' in line and 'integrator session role' in line for line in said)
    assert all(c.startswith(reclaim.CENSUS_MARK) for _, c in fleet.ran)
