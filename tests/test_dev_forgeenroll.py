"""``devhost enroll``: one plan mints every missing declared login; the user code is the only input; no token shown."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import pytest

from dev_lab.dev.credstore import DeclaredForge
from dev_lab.dev.forgecredential import STORE_ONLY
from dev_lab.dev.forgeenroll import (
    SCOPE,
    Enrollment,
    EnrollRefused,
    complete,
    load_enrollment,
    missing,
    ops_door,
    prepare,
)
from dev_lab.dev.planrunsteps import stdout_path
from dev_lab.ops.forgerequests import TokenRequest

_PLANTED = 'tok3n-planted-value'  # a planted value no output may carry
_HOST = 'forge.example'
_DEV = {'forges': {_HOST: ['dev-user'], 'github.com': ['someone']}, 'helpers': {_HOST: 'store'}}
_FORGE = DeclaredForge(Path('forge.toml'), (_HOST,), {'dev-user': ('team/repo',)})
_ACCESS = """
[ops.access]
account = "ops"
commands = ["/usr/bin/systemctl reload *", "/opt/v/bin/python -m dev_lab.ops --config /etc/x/supervise.toml forge *"]
"""


def _store(tmp_path: Path, *lines: str) -> Path:
    store = tmp_path / '.git-credentials'
    store.write_text(''.join(f'{line}\n' for line in lines), encoding='utf-8')
    return store


def _prepare(
    tmp_path: Path, *lines: str, helpers: list[str] = STORE_ONLY, forge: DeclaredForge = _FORGE, rotate: bool = False
) -> tuple[list[str], Enrollment | None, list[str]]:
    fixed: list[str] = []
    said, plan = prepare(
        dev=_DEV, machine='WS9', forge=forge, door=ops_door(_forge_file(tmp_path)), dest_host='forgehost.example',
        out=tmp_path / 'consent', store=_store(tmp_path, *lines), helpers_for=lambda _h: list(helpers),
        store_for=fixed.append, rotate=rotate,
    )  # fmt: skip
    return said, plan, fixed


def _forge_file(tmp_path: Path, body: str = _ACCESS) -> Path:
    path = tmp_path / 'forge.toml'
    path.write_text(body, encoding='utf-8')
    return path


def test_the_ops_door_is_read_from_the_forge_hosts_sudo_line(tmp_path: Path) -> None:
    door = ops_door(_forge_file(tmp_path))
    assert (door.account, door.python, door.config) == ('ops', '/opt/v/bin/python', '/etc/x/supervise.toml')


def test_a_forge_host_without_a_forge_sudo_line_is_refused(tmp_path: Path) -> None:
    with pytest.raises(EnrollRefused, match='forge \\*'):
        ops_door(_forge_file(tmp_path, '[ops.access]\naccount = "ops"\ncommands = ["/usr/bin/systemctl reload *"]\n'))


def test_only_logins_on_the_forges_sites_and_absent_from_the_store_are_missing(tmp_path: Path) -> None:
    assert missing(_DEV, _FORGE, store=_store(tmp_path)) == ['dev-user']
    assert missing(_DEV, _FORGE, store=_store(tmp_path, f'https://dev-user:{_PLANTED}@{_HOST}')) == []


def test_a_stored_machine_writes_no_plan(tmp_path: Path) -> None:
    said, plan, fixed = _prepare(tmp_path, f'https://dev-user:{_PLANTED}@{_HOST}')
    assert plan is None
    assert fixed == []
    assert 'nothing to mint' in said[-1]
    assert not (tmp_path / 'consent').exists()


def test_a_wrong_helper_is_fixed_without_consent(tmp_path: Path) -> None:
    _said, _plan, fixed = _prepare(tmp_path, f'https://dev-user:{_PLANTED}@{_HOST}', helpers=['manager'])
    assert fixed == [_HOST]


def test_a_wrong_helper_is_kept_while_the_store_lacks_the_login(tmp_path: Path) -> None:
    """PLANTED CONTROL: switching before the mint cuts the host off the forge; placing switches it later."""
    _said, plan, fixed = _prepare(tmp_path, helpers=['manager'])
    assert plan is not None
    assert fixed == []


def test_the_plan_mints_each_missing_login_named_after_the_machine(tmp_path: Path) -> None:
    _said, plan, _fixed = _prepare(tmp_path)
    assert plan is not None
    body = json.loads(plan.plan.read_text(encoding='utf-8'))
    assert body['hosts'] == ['ops@forgehost.example']
    assert body['grants'] == [{'host': 'ops@forgehost.example', 'action': 'ops.forge.token',
                               'subject': TokenRequest('dev-user', 'WS9', SCOPE, rotate=False).subject()}]  # fmt: skip
    steps = json.loads(plan.steps.read_text(encoding='utf-8'))
    assert steps['python'] == '/opt/v/bin/python'
    assert steps['config'] == '/etc/x/supervise.toml'
    assert steps['steps'][0]['argv'] == ['forge', 'token', 'mint', '--login', 'dev-user', '--name', 'WS9',
                                         '--scope', SCOPE]  # fmt: skip
    assert load_enrollment(plan.plan, plan.steps) == plan


def test_rotate_replaces_the_machines_token_the_forge_already_holds(tmp_path: Path) -> None:
    """A machine that lost its stored token: the forge still holds one by its name, so a plain mint is refused."""
    _said, plan, _fixed = _prepare(tmp_path, rotate=True)
    assert plan is not None
    body = json.loads(plan.plan.read_text(encoding='utf-8'))
    rotated = TokenRequest('dev-user', 'WS9', SCOPE, rotate=True).subject()
    assert rotated != TokenRequest('dev-user', 'WS9', SCOPE, rotate=False).subject()  # control: rotate is consented
    assert [grant['subject'] for grant in body['grants']] == [rotated]
    steps = json.loads(plan.steps.read_text(encoding='utf-8'))
    assert steps['steps'][0]['argv'] == ['forge', 'token', 'mint', '--login', 'dev-user', '--name', 'WS9',
                                         '--scope', SCOPE, '--rotate']  # fmt: skip


def test_a_login_the_forge_cannot_mint_is_refused_before_any_plan(tmp_path: Path) -> None:
    with pytest.raises(EnrollRefused, match='cannot be minted'):
        _prepare(tmp_path, forge=DeclaredForge(Path('f'), (_HOST,), {'other': ('team/repo',)}))
    assert not (tmp_path / 'consent').exists()


class _Run:
    def __init__(self, home: Path, *, hold: int = 0, mint: bool = True) -> None:
        self.calls: list[list[str]] = []
        self.home, self.hold, self.mint = home, hold, mint

    def __call__(self, argv: Sequence[str]) -> int:
        self.calls.append(list(argv))
        if 'dev_lab.dev.sshhold' in argv:
            return self.hold
        if self.mint:
            path = stdout_path('dev-user-WS9.token', self.home)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(_PLANTED + '\n', encoding='utf-8')
        return 0


def _complete(tmp_path: Path, run: _Run, placed: int = 0) -> tuple[int, list[str], list[dict]]:
    _said, plan, _fixed = _prepare(tmp_path)
    assert plan is not None
    said: list[str] = []
    places: list[dict] = []

    def place(**kwargs: object) -> int:
        places.append(dict(kwargs))
        return placed

    status = complete(plan, code='123456', dev=_DEV, forge=_FORGE, python='py', run=run, say=said.append,
                      home=run.home, place=place)  # fmt: skip
    return status, said, places


def test_the_code_opens_the_plan_mints_and_places_then_deletes_the_minted_file(tmp_path: Path) -> None:
    run = _Run(tmp_path / 'home')
    status, said, places = _complete(tmp_path, run)
    assert status == 0
    assert run.calls[0][:4] == ['py', '-m', 'dev_lab.dev.sshhold', 'open']
    assert run.calls[0][-2:] == ['--code', '123456']
    assert run.calls[1][:4] == ['py', '-m', 'dev_lab.dev.planrun', 'run']
    assert [(p['login'], p['token']) for p in places] == [('dev-user', _PLANTED)]
    assert not stdout_path('dev-user-WS9.token', run.home).exists()
    assert not any(_PLANTED in line for line in said)


def test_a_refused_placement_keeps_the_minted_file_and_names_the_retry(tmp_path: Path) -> None:
    """A minted token is spent consent: deleting it on a failed placement threw away a code (2026-11-23).

    PLANTED CONTROL: the placed case above still deletes it.
    """
    run = _Run(tmp_path / 'home')
    status, said, _places = _complete(tmp_path, run, placed=2)
    kept = stdout_path('dev-user-WS9.token', run.home)
    assert status == 2
    assert kept.read_text(encoding='utf-8').strip() == _PLANTED
    assert any(str(kept) in line and 'dev_lab.dev.devcredential' in line for line in said)
    assert not any(_PLANTED in line for line in said)


def test_a_code_the_plan_refuses_mints_nothing(tmp_path: Path) -> None:
    run = _Run(tmp_path / 'home', hold=2)
    status, said, places = _complete(tmp_path, run)
    assert status == 2
    assert len(run.calls) == 1
    assert places == []
    assert 'no token was minted' in said[0]


def test_a_mint_that_wrote_nothing_is_a_failure_never_a_silent_pass(tmp_path: Path) -> None:
    run = _Run(tmp_path / 'home', mint=False)
    status, said, places = _complete(tmp_path, run)
    assert status == 2
    assert places == []
    assert 'no minted token' in said[0]
