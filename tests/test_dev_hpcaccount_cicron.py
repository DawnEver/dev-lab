"""``--credential`` on the CI cron verbs: a grant for this cluster, these accounts and this direction is redeemed first.

Every case runs the REAL :func:`dev_lab.ops.consent.client.redeem` against a fake issuer (a test key signs, a list
registers each use), so a refusal is the verifier's, and "untouched" is read off the crontab and the ledger.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

import pytest
from _hpcaccount_fakes import FLEET, HOST, fleet_source, home_of, tools_of
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from dev_lab.dev.hpcaccount import accountset, cicron, cimark, cipause, deploy
from dev_lab.dev.hpcaccount.spec import MARK, cron_lines, load
from dev_lab.dev.planrunsteps import LOCAL_VERBS, load_steps
from dev_lab.ops.consent.actions import ACTIONS
from dev_lab.ops.consent.client import redeem
from dev_lab.ops.consent.credential import ConsentRefused, params_hash, sign
from dev_lab.ops.consent.plan import parsed

NOW: Final = 1_900_000_000.0
_KEY: Final = Ed25519PrivateKey.generate()


class Issuer:
    """A fake issuer: holds credentials in a state dir, registers each use in :attr:`ledger`."""

    def __init__(self, home: Path) -> None:
        """An issuer whose credentials live under *home*."""
        self.home = home
        self.ledger: list[str] = []

    def grant(self, ident: str, subject: str, action: str = cicron.ACTION) -> str:
        fields = {
            'id': ident, 'action': action, 'subject': subject, 'params': {}, 'params_hash': params_hash({}),
            'scope': 'single', 'cap': None, 'plan': None, 'issued': NOW, 'expires': NOW + 600, 'issuer': 'test',
        }  # fmt: skip
        held = self.home / '.dev-lab-consent' / f'{ident}.json'
        held.parent.mkdir(parents=True, exist_ok=True)
        held.write_text(json.dumps(sign(fields, _KEY)), encoding='utf-8')
        return ident

    def redeem(self, credential: Mapping[str, Any], subject: str) -> object:
        def register(found: Mapping[str, Any], _amount: int) -> None:
            self.ledger.append(str(found['id']))

        return redeem(credential, action=cicron.ACTION, subject=subject, key=_KEY.public_key(), register=register,
                      now=NOW)  # fmt: skip


@pytest.fixture
def issuer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Issuer:
    found = Issuer(tmp_path)
    monkeypatch.setattr(cicron, 'state_dir', lambda _home=None: tmp_path / '.dev-lab-consent')
    monkeypatch.setattr(cicron, '_live', found.redeem)
    monkeypatch.setattr(deploy, 'slurm_dirs', lambda: ['/opt/slurm/bin'])
    return found


def test_the_action_is_registered_single_use() -> None:
    row = ACTIONS[cicron.ACTION]
    assert (row.scope, dict(row.params)) == ('single', {})


def test_the_subject_sorts_its_accounts_and_names_the_direction() -> None:
    assert cicron.subject('ci-pause', 'c1', ['rita', 'alice']) == 'pause c1 alice,rita'
    assert cicron.subject('ci-pause-fleet'.removesuffix('-fleet'), 'c1', ['alice']) != cicron.subject(
        'ci-resume', 'c1', ['alice']
    )


# --- on the account -----------------------------------------------------------------------------------------------


def _account(tmp_path: Path) -> tuple[Path, list[str]]:
    home, clone, machine = home_of(tmp_path)
    spec = load(machine)
    lines = cron_lines(spec, home, slurm=['/opt/slurm/bin']) if spec else []
    (tmp_path / 'crontab.txt').write_text(''.join(f'{line}\n' for line in lines), encoding='utf-8')
    return home, ['--config', str(machine), '--from', str(clone), '--host', HOST]


def _cron(tmp_path: Path) -> str:
    return (tmp_path / 'crontab.txt').read_text(encoding='utf-8')


def test_a_matching_credential_pauses_and_is_spent_once(tmp_path: Path, issuer: Issuer) -> None:
    home, args = _account(tmp_path)
    ident = issuer.grant('0123abcd-1', 'pause c1 alice')
    assert cipause.ci_pause([*args, '--credential', ident, '--cluster', 'c1'], home=home, tools=tools_of(tmp_path)) == 0
    assert MARK not in _cron(tmp_path)
    assert issuer.ledger == [ident]


@pytest.mark.parametrize('subject', ['pause c2 alice', 'pause c1 alice,bob', 'resume c1 alice'])
def test_a_mismatched_credential_is_refused_before_any_change(
    tmp_path: Path, issuer: Issuer, subject: str, capsys: pytest.CaptureFixture[str]
) -> None:
    home, args = _account(tmp_path)
    before = _cron(tmp_path)
    ident = issuer.grant('0123abcd-2', subject)
    assert cipause.ci_pause([*args, '--credential', ident, '--cluster', 'c1'], home=home, tools=tools_of(tmp_path)) == 2
    assert _cron(tmp_path) == before
    assert not cimark.marker((home.parent / 'root').as_posix()).exists()
    assert issuer.ledger == [], 'refused before its use was registered'
    assert 'another request' in capsys.readouterr().err


def test_another_actions_credential_is_refused(tmp_path: Path, issuer: Issuer) -> None:
    home, args = _account(tmp_path)
    before = _cron(tmp_path)
    ident = issuer.grant('0123abcd-3', 'pause c1 alice', action='ops.config')
    assert cipause.ci_pause([*args, '--credential', ident, '--cluster', 'c1'], home=home, tools=tools_of(tmp_path)) == 2
    assert _cron(tmp_path) == before


def test_resume_redeems_its_own_direction(tmp_path: Path, issuer: Issuer) -> None:
    home, args = _account(tmp_path)
    assert cipause.ci_pause(args, home=home, tools=tools_of(tmp_path)) == 0  # the user's own pause, no credential
    paused = _cron(tmp_path)
    resume = ['--config', args[1], '--credential', issuer.grant('0123abcd-4', 'pause c1 alice'), '--cluster', 'c1']
    assert cipause.ci_resume(resume, home=home, tools=tools_of(tmp_path)) == 2
    assert _cron(tmp_path) == paused
    resume[3] = issuer.grant('0123abcd-5', 'resume c1 alice')
    assert cipause.ci_resume(resume, home=home, tools=tools_of(tmp_path)) == 0
    assert MARK in _cron(tmp_path)
    assert issuer.ledger == ['0123abcd-5']


def test_a_credential_without_its_cluster_is_refused(tmp_path: Path, issuer: Issuer) -> None:
    home, args = _account(tmp_path)
    before = _cron(tmp_path)
    ident = issuer.grant('0123abcd-6', 'pause c1 alice')
    assert cipause.ci_pause([*args, '--credential', ident], home=home, tools=tools_of(tmp_path)) == 2
    assert _cron(tmp_path) == before


# --- across the fleet ---------------------------------------------------------------------------------------------


def _fleet(tmp_path: Path, clusters: tuple[str, ...], ident: str) -> tuple[int, list[str], list[str]]:
    started: list[str] = []
    said: list[str] = []
    code = accountset.start_on_selected(
        FLEET, (), clusters, home=tmp_path, source=fleet_source(tmp_path), say=said.append, verb='ci-pause',
        serving_only=lambda target: target.role == 'verification', consent=accountset.consent_of('ci-pause', ident),
        launch=lambda dest, command, _log: started.append(f'{dest} {command}'),
    )  # fmt: skip
    return code, started, said


def test_a_fleet_credential_admits_its_cluster(tmp_path: Path, issuer: Issuer) -> None:
    code, started, _ = _fleet(tmp_path, ('c1',), issuer.grant('0123abcd-7', 'pause c1 alice'))
    assert code == 0
    assert [line.split()[0] for line in started] == ['alice@login01.example']
    assert issuer.ledger == ['0123abcd-7']


def test_a_fleet_credential_for_cluster_a_does_not_admit_cluster_b(tmp_path: Path, issuer: Issuer) -> None:
    code, started, said = _fleet(tmp_path, ('c2',), issuer.grant('0123abcd-8', 'pause c1 alice'))
    assert (code, started, issuer.ledger) == (2, [], [])
    assert 'no account started' in said[-1]


def test_a_fleet_credential_never_spans_two_clusters(tmp_path: Path, issuer: Issuer) -> None:
    code, started, said = _fleet(tmp_path, ('c1', 'c2'), issuer.grant('0123abcd-9', 'pause c1 alice'))
    assert (code, started, issuer.ledger) == (2, [], [])
    assert 'one cluster' in said[-1]


# --- a consent plan carries the step ------------------------------------------------------------------------------


def test_a_plan_step_runs_the_verb_here_with_its_argv(tmp_path: Path) -> None:
    plan = parsed(
        {'hosts': ['ops@h'], 'grants': [{'host': 'ops@h', 'action': cicron.ACTION, 'subject': 'pause c1 alice'}]}
    )
    path = tmp_path / 'steps.json'
    path.write_text(
        json.dumps(
            {
                'config': '/etc/c.toml',
                'python': 'py',
                'steps': [{'local': True, 'argv': ['ci-pause-fleet', '--cluster', 'c1']}],
            }
        ),
        'utf-8',
    )
    (step,) = load_steps(path, plan).steps
    assert step.local
    assert step.argv == ('dev_lab.dev.hpcaccount', 'ci-pause-fleet', '--cluster', 'c1')
    assert LOCAL_VERBS[cicron.ACTION].table == 'consent'
    for bad in (['drift-fleet', '--cluster', 'c1'], ['ci-pause-fleet', '--credential', 'x'], None):
        path.write_text(
            json.dumps(
                {'config': '/etc/c.toml', 'python': 'py', 'steps': [{'local': True} | ({'argv': bad} if bad else {})]}
            ),
            'utf-8',
        )
        with pytest.raises(ConsentRefused, match='ci-pause'):
            load_steps(path, plan)
