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
        self,
        monkeypatch: pytest.MonkeyPatch,
        *,
        census: str = _CENSUS,
        fail: str = '',
        acl: str = '',
        cluster: str = 'ada',
    ) -> None:
        self.ran: list[tuple[str, str]] = []
        self.fail, self.acl, self.census = fail, acl, census
        grants = {user: SimpleNamespace(user=user, cluster=cluster) for user in ('u1', 'o1', 'o2')}

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


#: The account's modes before any chmod: two ancestors, the target (setgid), one account-owned directory under it.
_MODES = {HOME: '700', f'{HOME}/ci': '700', f'{HOME}/ci/experiments': '700', f'{HOME}/{TARGET}': '2750'}


class _Gpfs(_Fleet):
    """MEASURED 2026-11-24: GPFS refuses ``setfacl`` -- ``Operation not supported``; modes are what it honours."""

    def __init__(
        self,
        monkeypatch: pytest.MonkeyPatch,
        *,
        owner_groups: str = '60200513',
        group: str = 'lab-team',
        **kwargs: object,
    ) -> None:
        super().__init__(monkeypatch, **kwargs)
        self.owner_groups, self.group, self.modes, self.stdin = owner_groups, group, dict(_MODES), {}
        self.restored: dict[str, str] | None = None

    def connect(self, grant: SimpleNamespace) -> object:
        inner = super().connect(grant)

        def run(command: str, stdin: str | None) -> str:
            if command.startswith('setfacl -m'):
                self.ran.append((grant.user, command))
                unsupported = f'setfacl: {HOME}: Operation not supported'
                raise RuntimeError(unsupported)
            if command.startswith(reclaim.RECORD_MARK):
                self.ran.append((grant.user, command))
                rows = [f'{mode} 60200513 {self.group}|{path}' for path, mode in self.modes.items()]
                return '\n'.join([*rows, f'groups o1 {self.owner_groups}', f'groups o2 {self.owner_groups} 7'])
            if command.startswith('chmod '):
                self.ran.append((grant.user, command))
                self.modes = dict.fromkeys(self.modes, '777')
                return 'ok\n'
            if command.startswith(reclaim.RESTORE_MARK):
                self.ran.append((grant.user, command))
                self.stdin['restore'] = stdin or ''
                self.modes |= dict(line.split(' ', 1)[::-1] for line in (stdin or '').splitlines())
                return 'restored\n'
            if command.startswith(reclaim.MODES_MARK):
                self.ran.append((grant.user, command))
                return ''.join(f'{self.modes[p]} {p}\n' for p in (line.split(' ', 1)[1] for line in stdin.splitlines()))
            return inner(command, stdin)

        return run


def test_gpfs_falls_back_to_group_bits_when_every_owner_shares_the_group(monkeypatch: pytest.MonkeyPatch) -> None:
    fleet = _Gpfs(monkeypatch)
    code, said = _run(fleet)
    assert code == 0, said
    chmod = next(c for c in fleet.of('u1') if c.startswith('chmod '))
    assert chmod.startswith(f'chmod g+x {HOME} {HOME}/ci {HOME}/ci/experiments')
    assert '-exec chmod g+rwx' in chmod
    assert 'o+' not in chmod
    assert fleet.stdin['restore'] == ''.join(f'{mode} {path}\n' for path, mode in _MODES.items())
    assert fleet.modes == _MODES
    assert any(line.startswith('reclaim-foreign: modes restored and verified') for line in said)


def _refused_before_any_write(fleet: _Gpfs, said: list[str], why: str) -> None:
    assert not any(c.startswith(('chmod ', reclaim.RESTORE_MARK)) for _, c in fleet.ran), 'nothing was written'
    assert fleet.modes == _MODES
    assert not any(' -delete' in c for _, c in fleet.ran)
    assert any(why in line for line in said), said
    assert any("only the owners' admin or a site admin can remove" in line for line in said)
    assert f'  request: rm -rf {HOME}/{TARGET}' in said
    assert '  o1: 56 entries' in said
    assert '  o2: 25 entries' in said
    assert not any('o+' in c for _, c in fleet.ran), 'never an other-bits widening (user ruling 2026-11-24)'


def test_planted_control_a_site_wide_shared_group_is_refused_before_any_write(monkeypatch: pytest.MonkeyPatch) -> None:
    """MEASURED 2026-11-24: on Ada the one group every owner shares is ``domain users`` -- the whole university."""
    fleet = _Gpfs(monkeypatch, group='domain users')
    code, said = _run(fleet)
    assert code == 2
    _refused_before_any_write(fleet, said, "the shared group 'domain users' is site-wide on ada")


def test_planted_control_no_shared_group_is_refused_before_any_write(monkeypatch: pytest.MonkeyPatch) -> None:
    fleet = _Gpfs(monkeypatch, owner_groups='99')
    code, said = _run(fleet)
    assert code == 2
    _refused_before_any_write(fleet, said, 'no group every owner shares')


def test_a_cluster_with_no_declared_site_wide_groups_widens_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    fleet = _Gpfs(monkeypatch, cluster='elsewhere')
    code, said = _run(fleet)
    assert code == 2
    _refused_before_any_write(fleet, said, "cluster 'elsewhere' declares no site-wide groups")


def test_planted_control_modes_are_restored_exactly_when_an_owner_delete_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    fleet = _Gpfs(monkeypatch, fail='o1')
    code, said = _run(fleet)
    assert code == 2
    assert fleet.modes == _MODES
    assert fleet.stdin['restore'] == ''.join(f'{mode} {path}\n' for path, mode in _MODES.items())
    assert any(line.startswith('reclaim-foreign: modes restored and verified') for line in said)


def test_a_mode_left_changed_after_the_restore_is_named_and_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    fleet = _Gpfs(monkeypatch)
    real = fleet.connect

    def stuck(grant: SimpleNamespace) -> object:
        run = real(grant)

        def once(command: str, stdin: str | None) -> str:
            out = run(command, stdin)
            if command.startswith(reclaim.RESTORE_MARK):
                fleet.modes[HOME] = '710'  # PLANTED: the restore missed one
            return out

        return once

    said: list[str] = []
    assert reclaim.reclaim('u1', TARGET, apply=True, connect=stuck, say=said.append) == 2
    assert any('modes NOT restored' in line and f'{HOME}: 710, was 700' in line for line in said)
