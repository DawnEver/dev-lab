"""ONE CODE PER PLAN: a subject only an unreached host derives is READ through the issuer, never bought with a code.

User ruling 2026-11-16: a host-derived subject is read through a read-only channel that needs no code, so a plan
still takes exactly ONE code -- spent once preflight is green. Before this, such a plan needed a first code to open
the host's hold for the read, then the plan's own code.

PLANTED controls: the read channel refuses every form that could act (a credential, ``--follow``, another verb, an
action with no declared read, stdin content), and a subject the host derives differently still blocks.
"""

from __future__ import annotations

import json
import shlex
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from _ops_fixtures import NOW, RFC_KEY, code
from lab_commons.home import HOME_ENV

from dev_lab.dev import planrunpreflight, planrunsteps, sshholdplan
from dev_lab.ops import __main__ as ops_main
from dev_lab.ops.consent import serve
from dev_lab.ops.consent.actions import ACTIONS
from dev_lab.ops.consent.credential import ConsentRefused
from dev_lab.ops.consent.door import offer, subject_read
from dev_lab.ops.consent.issuer import Issuer, keygen
from dev_lab.ops.consent.plan import Plan, parsed

HOST = 'ops@issuer.example.org'
OTHER = 'ops@worker.example.org'
TIP = 'c' * 40
CONF, PY = '/etc/dev-lab/supervise.toml', '/usr/bin/python3'
TABLE = {'endpoint': HOST}
UPGRADE = planrunsteps.Step(('upgrade', '--sha', TIP), HOST, CONF, PY)


@pytest.fixture
def issuer(tmp_path: Path) -> Issuer:
    (tmp_path / 'totp').write_text(RFC_KEY + '\n', encoding='utf-8')
    keygen(tmp_path / 'consent.key')
    return Issuer(tmp_path / 'totp', tmp_path / 'consent.key', tmp_path / 'state', 'test issuer', lambda: NOW)


class Wire:
    """The issuer's serve verb over a fake ssh: its host derives ``upgrade --subject`` as *TIP*; all recorded."""

    def __init__(self, issuer: Issuer, tip: str = TIP) -> None:
        """*tip* is what this host's ``upgrade --subject`` prints."""
        self.issuer, self.tip = issuer, tip
        self.sent: list[dict[str, Any]] = []
        self.derived: list[list[str]] = []

    def derive(self, argv: Sequence[str]) -> tuple[int, str]:
        self.derived.append(list(argv))
        return 0, self.tip + '\n'

    def __call__(self, _table: object, request: dict[str, Any]) -> tuple[int, str]:
        self.sent.append(request)
        try:
            return 0, serve.handle(self.issuer, json.dumps(request), derive=self.derive)
        except ConsentRefused as refused:
            return 2, f'refused: {refused}'


class Unreached:
    """A host with no hold that admits no login without a code: every command answers ssh's refusal."""

    def __init__(self) -> None:
        """Nothing run yet."""
        self.commands: list[str] = []

    def run(self, command: str, stdin: bytes | None = None) -> tuple[str, int]:
        del stdin
        self.commands.append(command)
        return 'ops@h: Permission denied (publickey,keyboard-interactive).', 255

    def put(self, path: str, text: str) -> None:
        msg = f'preflight writes nothing (asked to put {path})'
        del text
        raise AssertionError(msg)


def _plan(subject: str = TIP, host: str = HOST) -> Plan:
    return parsed({'hosts': [host], 'grants': [{'host': host, 'action': 'ops.upgrade', 'subject': subject}]})


def _readers(wire: Wire) -> planrunpreflight.Readers:
    return planrunpreflight.Readers(
        issued=lambda dest, action, argv: subject_read(TABLE, dest, action, argv, send=wire)
    )


def test_a_host_derived_subject_on_an_unreached_host_goes_green_without_any_code(issuer: Issuer) -> None:
    """The ruling's case: no hold, a subject only the host derives -- preflight is green, and no code was sent."""
    wire, host = Wire(issuer), Unreached()
    green, lines = planrunpreflight.preflight(
        _plan(), planrunsteps.Steps((UPGRADE,)), lambda _d: host, readers=_readers(wire)
    )
    assert green, lines
    assert any('subject read from the host, no code' in line for line in lines), lines
    assert [request['verb'] for request in wire.sent] == ['subject']
    assert not any('code' in request for request in wire.sent)
    assert wire.derived == [['upgrade', '--sha', TIP, '--subject']]


def test_a_read_subject_the_host_derives_differently_still_blocks(issuer: Issuer) -> None:
    green, lines = planrunpreflight.preflight(
        _plan(), planrunsteps.Steps((UPGRADE,)), lambda _d: Unreached(), readers=_readers(Wire(issuer, 'e' * 40))
    )
    assert not green
    assert any('derives subject eeeeeeeeeeee, the plan grants cccccccccccc (read)' in line for line in lines), lines


def test_the_issuer_reads_only_its_own_hosts_subject(issuer: Issuer) -> None:
    """PLANTED: a step on another host is not read from the issuer's host (its subject would be the wrong host's)."""
    wire = Wire(issuer)
    step = planrunsteps.Step(UPGRADE.argv, OTHER, CONF, PY)
    green, lines = planrunpreflight.preflight(
        _plan(host=OTHER), planrunsteps.Steps((step,)), lambda _d: Unreached(), readers=_readers(wire)
    )
    assert not green
    assert any('reads only its own host, not worker.example.org' in line for line in lines), lines
    assert wire.sent == []


def test_a_step_whose_subject_hashes_local_stdin_is_never_read_remotely(issuer: Issuer, tmp_path: Path) -> None:
    (tmp_path / 'x').write_text('planted', encoding='utf-8')
    wire = Wire(issuer)
    step = planrunsteps.Step(UPGRADE.argv, HOST, CONF, PY, str(tmp_path / 'x'))
    green, lines = planrunpreflight.preflight(
        _plan(), planrunsteps.Steps((step,)), lambda _d: Unreached(), readers=_readers(wire)
    )
    assert not green
    assert any('stdin that never leaves here' in line for line in lines), lines
    assert wire.sent == []


@pytest.mark.parametrize(
    ('action', 'argv', 'why'),
    [
        ('ops.upgrade', ['upgrade', '--sha', TIP], ''),  # the planted control: the read form is admitted
        ('ops.upgrade', ['upgrade', '--sha', TIP, '--credential', 'credential.json'], 'never carries'),
        ('ops.upgrade', ['upgrade', '--follow'], 'never carries'),
        ('ops.upgrade', ['config', 'apply'], 'runs `upgrade ...` only'),
        ('ops.config', ['config', 'tick'], 'runs `config apply ...` only'),
        ('ops.secret.place', ['secret', 'place', '--path', '/etc/x'], 'admits no subject read'),
        ('breakglass.wave', ['breakglass', 'serve'], 'admits no subject read'),
        ('ops.upgrade', 'upgrade --follow', 'runs `upgrade ...` only'),
    ],
)
def test_the_subject_verb_refuses_every_form_that_could_write(
    issuer: Issuer, action: str, argv: object, why: str
) -> None:
    """A write through the read channel is refused at the issuer, before anything runs on its host."""
    wire = Wire(issuer)
    line = json.dumps({'verb': 'subject', 'action': action, 'argv': argv})
    if not why:
        assert serve.handle(issuer, line, derive=wire.derive) == TIP
        assert isinstance(argv, list)
        assert wire.derived == [[*argv, '--subject']]
        return
    with pytest.raises(ConsentRefused, match=why):
        serve.handle(issuer, line, derive=wire.derive)
    assert wire.derived == []


def test_an_issuer_given_no_reader_derives_nothing(issuer: Issuer) -> None:
    line = json.dumps({'verb': 'subject', 'action': 'ops.upgrade', 'argv': ['upgrade']})
    with pytest.raises(ConsentRefused, match='derives no subjects'):
        serve.handle(issuer, line)


def test_every_declared_read_is_a_verb_with_a_subject_flag() -> None:
    """The registry's ``reads`` name real ops verbs whose ``--subject`` returns before acting (each parses)."""
    seen = []
    for row in ACTIONS.values():
        if not row.reads:
            continue
        seen.append(row.name)
        words = [*row.reads, *(['--login', 'x'] if 'forge' in row.reads and 'protect' not in row.reads else [])]
        words += ['--name', 'n', '--scope', 'read:repository'] if row.reads[-1] == 'mint' else []
        words += ['--item', 'n:read:repository'] if row.reads[-1] == 'mint-batch' else []
        words += ['--name', 'n'] if row.reads[-1] == 'revoke' else []
        words += ['--repo', 'o/n'] if 'protect' in row.reads else []
        with pytest.raises(SystemExit) as parsed_ok:
            ops_main.main(['--config', '/nonexistent.toml', *words, '--subject', '--help'])
        assert parsed_ok.value.code == 0, (row.name, shlex.join(words))
    assert set(seen) == {
        'ops.config', 'ops.forge.account', 'ops.forge.token', 'ops.forge.tokens', 'ops.forge.revoke', 'ops.upgrade',
        'ops.forge.protect',
    }  # fmt: skip


def test_once_the_read_preflight_is_green_the_plan_takes_exactly_one_code(
    issuer: Issuer, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Preflight (no code), the offer (no code), then ONE code: the issuer grant and the host's open share it."""
    monkeypatch.setenv(HOME_ENV, str(tmp_path / 'home'))
    wire = Wire(issuer)
    plan = _plan()
    found = planrunpreflight.preflight(
        plan, planrunsteps.Steps((UPGRADE,)), lambda _d: Unreached(), readers=_readers(wire)
    )
    green, lines = planrunpreflight.offered(plan, found, table=TABLE, send=wire, home=tmp_path)
    assert green, lines
    offer(plan, TABLE, send=wire, home=tmp_path)  # the door the code is asked behind: open
    assert not any('code' in request for request in wire.sent)
    path = tmp_path / 'plan.json'
    path.write_text(json.dumps({'hosts': [HOST], 'grants': [dict(plan.grants[0])]}), encoding='utf-8')
    given = code()
    codes: list[str] = []

    def grant(_plan: Path, _shown: str, spent: str, _issuer: str) -> list[Path]:
        codes.append(spent)
        return [tmp_path / 'credential.json']

    def opener(dest: str, _hours: float, spent: str, *, ssh: tuple[str, ...]) -> str:
        del ssh
        codes.append(spent)
        return f'{dest}: open'

    opened, said = sshholdplan.open_planned(
        1, given, path, plan.digest, routes=lambda _d: ('ssh',), grant=grant, opener=opener, held=lambda _d: False
    )
    assert opened, said
    assert codes == [given, given]  # ONE code, verified once by the issuer and once by the host
    assert not any('NOT opened' in line for line in said)
