"""``ops upgrade --sha S --credential F``: an upgrade is a plan step, consented as ``ops.upgrade`` (subject = S).

The host refuses an S that is not the declared ``[ops.upgrade] ref``'s tip, and an S already installed is done
without spending the credential (idempotent); ``--subject`` prints the tip a plan's grant must name.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest
from test_ops_upgrade_installs_the_locked_family import LOCK, OLD, TIP, _config

from dev_lab.ops import upgrade
from dev_lab.ops.consent.actions import ACTIONS, SINGLE
from dev_lab.ops.consent.credential import ConsentRefused


class Host:
    """An installed commit, the ref's tip, and a record of every install and redeem."""

    def __init__(self, installed: str = OLD) -> None:
        """A host with *installed* as its dev-lab commit."""
        self.installed, self.installs, self.redeemed, self.fetched = installed, [], [], []

    def probe(self, argv: Sequence[str]) -> tuple[int, str]:
        return (0, self.installed) if '-c' in argv and 'direct_url' in argv[-1] else (0, '')

    def install(self, argv: Sequence[str]) -> tuple[int, str]:
        self.installs.append(list(argv))
        self.installed = argv[-1].rpartition('@')[2]
        return 0, ''

    def fetch(self, _source: str, ref: str) -> tuple[str, str]:
        self.fetched.append(ref)
        return TIP, LOCK

    def redeem(self, _credential: object, subject: str) -> None:
        self.redeemed.append(subject)


def _planned(tmp_path: Path, host: Host, sha: str) -> tuple[int, str]:
    return upgrade.planned(_config(tmp_path), sha, redeem=host.redeem, credential={}, install=host.install,
                           probe=host.probe, fetch=host.fetch)  # fmt: skip


def test_the_action_is_a_single_use_boundary_row() -> None:
    assert (ACTIONS[upgrade.ACTION].scope, ACTIONS[upgrade.ACTION].boundary) == (SINGLE, True)


def test_the_tip_is_redeemed_then_installed(tmp_path: Path) -> None:
    """The planted control of both refusals below."""
    host = Host()
    code, said = _planned(tmp_path, host, TIP)
    assert code == 0, said
    assert host.redeemed == [TIP]
    assert host.installs[0][-1].endswith(f'@{TIP}')
    assert host.fetched == ['integrate/main']  # one fetch: the tip checked is the tip installed


def test_a_sha_not_the_declared_refs_tip_is_refused_and_spends_nothing(tmp_path: Path) -> None:
    host = Host()
    code, said = _planned(tmp_path, host, 'f' * 40)
    assert code == 2
    assert 'not the tip of [ops.upgrade] ref integrate/main' in said
    assert (host.redeemed, host.installs) == ([], [])


def test_an_installed_sha_is_done_again_without_spending_the_credential(tmp_path: Path) -> None:
    host = Host(installed=TIP)
    code, said = _planned(tmp_path, host, TIP)
    assert code == 0
    assert 'already' in said
    assert (host.redeemed, host.installs) == ([], [])


def test_a_refused_credential_installs_nothing(tmp_path: Path) -> None:
    host = Host()

    def refuse(_credential: object, _subject: str) -> None:
        msg = 'the credential names another subject'
        raise ConsentRefused(msg)

    host.redeem = refuse  # type: ignore[method-assign]
    with pytest.raises(ConsentRefused):
        _planned(tmp_path, host, TIP)
    assert host.installs == []


def test_the_subject_is_the_declared_refs_tip(tmp_path: Path) -> None:
    assert upgrade.subject(_config(tmp_path), fetch=Host().fetch) == TIP


def test_the_ops_door_prints_the_subject_and_refuses_a_sha_without_its_credential(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from dev_lab.ops import __main__ as ops_main  # noqa: PLC0415

    path = _config(tmp_path).path
    monkeypatch.setattr(upgrade, 'subject', lambda _config: TIP)
    assert ops_main.main(['--config', str(path), 'upgrade', '--subject']) == 0
    assert capsys.readouterr().out.strip() == TIP
    assert ops_main.main(['--config', str(path), 'upgrade', '--sha', TIP]) == 2
    assert '--sha and --credential come together' in capsys.readouterr().err
