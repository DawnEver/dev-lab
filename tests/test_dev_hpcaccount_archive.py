"""``hpcaccount archive`` / ``archive-clean``: the declared run store, the account's reach, and delete-after-verify.

User ruling 2026-11-25: results of record are archived with hash verification before the local copy is deleted.
The walls each name their door: an undeclared run store, an account that does not reach it. The planted control of
the clean half: an account half that does NOT release the tree must leave the clean door uncalled.
"""

from __future__ import annotations

import json
import shlex
from types import SimpleNamespace
from typing import Any

import pytest

from dev_lab.dev.hpcaccount import archive, archivestream
from dev_lab.dev.hpcaccount.fleet import Target
from dev_lab.dev.storage import DEFAULT_RCLONE

ROOT = '/scratch/u1/lab'
DECLARED = SimpleNamespace(runs='vault:bucket', runs_remote='vault', reach=[SimpleNamespace(name='vault')])


class _Account:
    """A fake account: what each command asked, and the account half's lines and verdict."""

    def __init__(self, verdict: dict[str, Any], *, reaches: bool = True) -> None:
        self.verdict, self.reaches, self.ran, self.specs = verdict, reaches, [], []

    def __call__(self, command: str, stdin: str | None) -> str:
        self.ran.append(command)
        if stdin == archive.STREAM_SOURCE:
            self.specs.append(json.loads(shlex.split(command.split(' - ', 1)[1])[0]))
            return f'archive: a line\n{archivestream.VERDICT}{json.dumps(self.verdict)}\n'
        return '/opt/rclone\n'


@pytest.fixture(autouse=True)
def fake(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    grant = SimpleNamespace(user='u1')
    machine = SimpleNamespace(grants=[grant])
    monkeypatch.setattr(archive, 'reached_machine', lambda _users: machine)
    monkeypatch.setattr(archive, 'declared_target', lambda _g, _shell: Target('login1', ROOT))
    return {'machine': machine}


def _wire(monkeypatch: pytest.MonkeyPatch, account: _Account) -> dict[str, Any]:
    said = 'vault: reached' if account.reaches else 'check refused: no secret'
    monkeypatch.setattr(archive, 'check_in_kit', lambda _run, _g, _remote: (account.reaches, said))
    return {'connect': lambda _g: account, 'pin': lambda _g, _host: account}


def test_the_destination_is_the_run_store_under_archive_user_and_path() -> None:
    assert archive.destination('vault:bucket', 'u1', 'work/data') == 'vault:bucket/archive/u1/work/data'
    assert archive.destination('vault:bucket/', 'u1', 'data', 'data-2') == 'vault:bucket/archive/u1/data-2'


def test_an_undeclared_run_store_is_refused_naming_where_it_is_declared_before_any_account_is_reached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account, said = _Account({'ok': True}), []
    undeclared = SimpleNamespace(runs=None, runs_remote=None, reach=[SimpleNamespace(name='vault')])
    assert archive.archive('u1', 'work', apply=True, declared=undeclared, say=said.append,
                           **_wire(monkeypatch, account)) == 2  # fmt: skip
    assert '[storage]' in said[0]
    assert 'runs = "<remote>:<path>"' in said[0]
    assert 'devhost render --write' in said[0]
    assert 'vault' in said[0], 'the remotes this machine reaches are named'
    assert account.ran == []


def test_an_account_that_does_not_reach_the_store_is_refused_naming_its_doors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account, said = _Account({'ok': True}, reaches=False), []
    assert archive.archive('u1', 'work', apply=True, declared=DECLARED, say=said.append,
                           **_wire(monkeypatch, account)) == 2  # fmt: skip
    assert 'secretplace distribute --remote vault' in said[0]
    assert 'hpcaccount storage-check --account u1 vault' in said[0]
    assert account.specs == [], 'nothing was streamed'


@pytest.mark.parametrize(('apply', 'mode'), [(True, 'archive'), (False, 'plan')])
def test_the_account_half_gets_the_store_the_accounts_rclone_and_the_mode(
    monkeypatch: pytest.MonkeyPatch, *, apply: bool, mode: str
) -> None:
    account, said = _Account({'ok': True, 'verdict': 'archived'}), []
    assert archive.archive('u1', 'work/data', apply=apply, declared=DECLARED, say=said.append,
                           **_wire(monkeypatch, account)) == 0  # fmt: skip
    (spec,) = account.specs
    assert spec == {
        'mode': mode, 'path': 'work/data', 'dest': 'vault:bucket/archive/u1/work/data', 'rclone': ['/opt/rclone'],
        'config': DEFAULT_RCLONE.as_posix(), 'part_bytes': archivestream.PART_BYTES, 'tar': ['tar'],
    }  # fmt: skip
    assert said == ['archive: a line']


def test_a_refused_account_half_is_exit_2_with_its_words(monkeypatch: pytest.MonkeyPatch) -> None:
    account, said = _Account({'ok': False, 'verdict': 'refused', 'why': 'tar exited 2'}), []
    assert archive.archive('u1', 'work', apply=True, declared=DECLARED, say=said.append,
                           **_wire(monkeypatch, account)) == 2  # fmt: skip
    assert said[-1] == 'archive: u1: refused -- tar exited 2'


@pytest.mark.parametrize(('path', 'name'), [('../x', ''), ('/etc', ''), ('a b', ''), ('work', 'a/b'), ('work', '..')])
def test_a_path_or_name_of_another_shape_is_refused_before_anything_is_reached(
    monkeypatch: pytest.MonkeyPatch, path: str, name: str
) -> None:
    account, said = _Account({'ok': True}), []
    assert archive.archive('u1', path, apply=True, name=name, declared=DECLARED, say=said.append,
                           **_wire(monkeypatch, account)) == 2  # fmt: skip
    assert account.ran == []


def test_a_released_tree_goes_through_the_clean_door_confined_to_its_parent(
    monkeypatch: pytest.MonkeyPatch, fake: dict[str, Any]
) -> None:
    released = {'ok': True, 'verdict': 'released', 'parent': '/scratch/u1/work', 'name': 'data'}
    account, said, cleaned = _Account(released), [], []

    def clean(argv: list[str], **door: object) -> int:
        cleaned.append(argv)
        assert door['machine'] is fake['machine']
        return 0

    for apply in (False, True):
        assert archive.archive_clean('u1', 'work/data', apply=apply, timeout=60, declared=DECLARED, clean=clean,
                                     say=said.append, **_wire(monkeypatch, account)) == 0  # fmt: skip
    head = ['--root', '/scratch/u1/work', '--grant', 'u1', '--timeout', '60', 'data']
    assert cleaned == [[*head, '--dry-run'], head]
    assert [spec['mode'] for spec in account.specs] == ['release', 'release']


def test_planted_control_an_unreleased_tree_never_reaches_the_clean_door(monkeypatch: pytest.MonkeyPatch) -> None:
    account = _Account({'ok': False, 'verdict': 'refused', 'why': 'changed since it was archived'})
    said: list[str] = []
    cleaned: list[list[str]] = []

    def clean(argv: list[str], **_door: object) -> int:
        cleaned.append(argv)
        return 0

    assert archive.archive_clean('u1', 'work/data', apply=True, declared=DECLARED, clean=clean, say=said.append,
                                 **_wire(monkeypatch, account)) == 2  # fmt: skip
    assert cleaned == []
    assert said[-1] == 'archive-clean: u1: refused, nothing deleted -- changed since it was archived'
