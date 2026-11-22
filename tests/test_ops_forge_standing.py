"""A MINT'S REFUSAL NEVER SPENDS ITS CONSENT, and its ``--subject`` read names the refusal before any code.

Incident 2026-11-22: ``forge token mint`` redeemed the credential and THEN refused "already holds a token named
...; --rotate deletes it and mints anew" -- the user's code was spent on a request the forge could have refused with
no credential at all. Every such refusal is :func:`dev_lab.ops.forgeaccounts.standing`: raised before the redeem,
and printed by the read form on the line before the subject (:data:`dev_lab.ops.consent.actions.STANDING`).

PLANTED controls: the same request on a forge that admits it redeems and mints, and its read prints the subject
alone.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path

import pytest
from test_ops_forgeaccounts import FakeGitea, _batch, _role

from dev_lab.ops import forgeaccounts
from dev_lab.ops.consent.actions import STANDING, read_answer
from dev_lab.ops.forgerequests import TokenRequest
from dev_lab.ops.giteaadmin import ForgeRefused

LOGIN = 'server-reader'
HELD = {LOGIN: {'host-x': 'read:repository'}}


def _counting() -> tuple[list[str], Callable[[object, str], None]]:
    spent: list[str] = []
    return spent, lambda _credential, asked: spent.append(asked)


@pytest.mark.parametrize(
    ('gitea', 'match'),
    [
        (FakeGitea(users={LOGIN}, tokens=HELD), 'already holds a token named host-x'),
        (FakeGitea(), 'no login server-reader'),
    ],
)
def test_a_mint_the_forge_refuses_as_it_stands_spends_no_consent(tmp_path: Path, gitea: FakeGitea, match: str) -> None:
    request = TokenRequest(LOGIN, 'host-x', 'read:repository', rotate=False)
    spent, redeem = _counting()
    with pytest.raises(ForgeRefused, match=match):
        forgeaccounts.mint(_role(tmp_path), gitea, request, redeem=redeem, credential={}, by='ops')
    assert spent == []
    batch = _batch(('host-w', 'read:repository', False), ('host-x', 'read:repository', False))
    with pytest.raises(ForgeRefused, match=match):
        forgeaccounts.mint_batch(_role(tmp_path), gitea, batch, redeem=redeem, credential={}, by='ops',
                                 place=lambda *_a: None)  # fmt: skip
    assert spent == []


def test_the_same_mint_on_a_forge_that_admits_it_redeems_once_and_mints(tmp_path: Path) -> None:
    """PLANTED: the counter can count -- a clean forge spends the consent, exactly once."""
    request = TokenRequest(LOGIN, 'host-x', 'read:repository', rotate=False)
    spent, redeem = _counting()
    minted = forgeaccounts.mint(
        _role(tmp_path), FakeGitea(users={LOGIN}), request, redeem=redeem, credential={}, by='ops'
    )
    assert (minted, spent) == ('secret-host-x', [request.subject()])


def _read(tmp_path: Path, gitea: FakeGitea, *words: str) -> int:
    """The exit status of the read form ``forge token <words> --subject`` on *gitea*; it must never redeem."""
    parser = argparse.ArgumentParser()
    forgeaccounts.add_parser(parser.add_subparsers(dest='verb'))
    args = parser.parse_args(['forge', 'token', *words, '--subject'])
    return forgeaccounts.run_verb(_role(tmp_path), args, lambda _a: pytest.fail, admin=lambda _role: gitea)


MINT = ('mint', '--login', LOGIN, '--name', 'host-x', '--scope', 'read:repository')


def test_the_read_form_names_a_held_name_before_the_subject_and_still_prints_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    gitea = FakeGitea(users={LOGIN}, tokens=HELD)
    assert _read(tmp_path, gitea, *MINT) == 0
    subject, refusal = read_answer(capsys.readouterr().out)
    assert subject == TokenRequest(LOGIN, 'host-x', 'read:repository', rotate=False).subject()
    assert refusal == 'server-reader already holds a token named host-x; --rotate deletes it and mints anew'
    assert gitea.tokens == HELD  # a read: nothing minted, nothing deleted
    assert _read(tmp_path, gitea, 'mint-batch', '--login', LOGIN, '--item', 'host-x:read:repository') == 0
    assert 'already holds a token named host-x' in (read_answer(capsys.readouterr().out)[1] or '')


def test_the_read_form_of_an_admitted_mint_prints_the_subject_alone(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """PLANTED: no standing line where the forge would mint -- with ``--rotate``, or on a free name."""
    held = FakeGitea(users={LOGIN}, tokens=HELD)
    for gitea, words in ((held, (*MINT, '--rotate')), (FakeGitea(users={LOGIN}), MINT)):
        assert _read(tmp_path, gitea, *words) == 0
        printed = capsys.readouterr().out
        assert STANDING not in printed
        assert read_answer(printed)[1] is None


def test_a_forge_that_cannot_be_read_is_named_and_the_subject_still_derived(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    class Unreadable(FakeGitea):
        def user_exists(self, login: str) -> bool:
            msg = f'gitea admin user list failed (exit 1) for {login}'
            raise ForgeRefused(msg)

    assert _read(tmp_path, Unreadable(), *MINT) == 0
    subject, refusal = read_answer(capsys.readouterr().out)
    assert len(subject) == 64
    assert 'admin user list failed' in (refusal or '')


def test_read_answer_takes_only_a_standing_line_directly_before_the_subject() -> None:
    assert read_answer('') == ('', None)
    assert read_answer('warning: x\nabc\n') == ('abc', None)
    assert read_answer(f'{STANDING}held\nabc\n') == ('abc', 'held')
    assert read_answer(f'{STANDING}held\nnoise\nabc\n') == ('abc', None)
