"""``devcredential``: a minted token placed in THIS machine's store, only for a declared login, verified first."""

from __future__ import annotations

import json
from pathlib import Path

from dev_lab.dev.credstore import DeclaredForge, Shell, digest
from dev_lab.dev.devcredential import place
from dev_lab.dev.devschema import check_family

_FORGE = DeclaredForge(Path('forge-a.toml'), ('forge.example',), {'dev-user': ('org/repo',)})
_DEV = {'forges': {'forge.example': ['dev-user']}, 'helpers': {'forge.example': 'store'}}
_MINTED = 'tok3n-SECRET-value'


def _shell(answers: str, seen: list[tuple[str, str | None]]) -> Shell:
    def shell(cmd: str, stdin: str | None = None) -> str:
        seen.append((cmd, stdin))
        if 'auth role' in cmd:
            return json.dumps({'login': answers})
        if cmd.startswith('umask 077 && f='):
            return 'backup ~/.git-credentials.bak-x\n'
        return ''

    return shell


def _place(
    *,
    login: str = 'dev-user',
    answers: str = 'dev-user',
    dev: dict | None = None,
    helpers: tuple[str, ...] = ('', 'store'),
    stored: list[str] | None = None,
    token: str = _MINTED,
) -> tuple[int, list[str], list[tuple[str, str | None]]]:
    said: list[str] = []
    seen: list[tuple[str, str | None]] = []
    rc = place(
        login=login, token=token, url='', forge=_FORGE, dev=_DEV if dev is None else dev, say=said.append,
        shell=_shell(answers, seen), helpers_for=lambda _host: list(helpers),
        store_for=(stored if stored is not None else []).append, python='py',
    )  # fmt: skip
    return rc, said, seen


def test_a_declared_login_is_verified_then_placed_and_the_token_never_printed() -> None:
    rc, said, seen = _place()
    assert rc == 0
    assert digest(_MINTED) in said[0]
    assert _MINTED not in ' '.join(said)
    assert all(_MINTED not in cmd for cmd, _ in seen)
    assert [stdin for _, stdin in seen if stdin] == [f'https://dev-user:{_MINTED}@forge.example\n']
    assert seen[-1][0].startswith('umask 077 && f=')


def test_a_wrong_answer_discards_the_staged_line_and_keeps_the_store() -> None:
    rc, said, seen = _place(answers='someone-else')
    assert rc == 2
    assert 'untouched' in said[0]
    assert seen[-1][0].startswith('rm -f')


def test_refusals_come_before_anything_is_staged() -> None:
    for kwargs, named in (
        ({'login': 'intruder', 'dev': {'forges': {'forge.example': ['intruder']}}}, 'cannot be minted'),
        ({'dev': {'forges': {}}}, 'not a login this machine declares'),
        ({'dev': {'forges': {'forge.example': ['dev-user']}}}, 'declares no store helper'),
        ({'token': ''}, 'no token'),
    ):
        rc, said, seen = _place(**kwargs)
        assert (rc, seen) == (2, [])
        assert named in said[0]


def test_a_declared_store_helper_is_applied_before_placing_only_when_not_already_set() -> None:
    stored: list[str] = []
    rc, said, _ = _place(helpers=('manager',), stored=stored)
    assert (rc, stored) == (0, ['forge.example'])
    assert 'reads only the store' in said[0]
    stored.clear()
    assert _place(stored=stored)[0] == 0
    assert stored == []


def test_a_helper_outside_the_declared_set_is_refused() -> None:
    assert any(
        'helpers.forge.example' in line for line in check_family({'dev': {'helpers': {'forge.example': 'manager'}}})
    )
    assert check_family({'dev': {'helpers': {'forge.example': 'store'}}}) == []
