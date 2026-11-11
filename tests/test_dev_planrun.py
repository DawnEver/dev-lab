"""A plan's steps on its host: every door checked BEFORE a code is spent (preflight).

Every blocker has its planted control: the green host below, with the one fault removed, passes.
"""

from __future__ import annotations

import dataclasses
import json
import shlex
from pathlib import Path

import pytest
from _ops_fixtures import config

from dev_lab.dev import planrun
from dev_lab.ops import __main__ as ops_main
from dev_lab.ops import configdoor
from dev_lab.ops.consent.credential import ConsentRefused
from dev_lab.ops.consent.plan import parsed

HOST = 'ops@judge.example.org'
CANDIDATE = '/srv/plan/candidate.toml'
APPLY = {'action': 'ops.config', 'subject': 'a' * 64}
PLACE = {'action': 'ops.secret.place', 'subject': 'b' * 64}
PLAN = parsed({'host': HOST, 'grants': [APPLY, PLACE]})
STEPS = planrun.Steps(
    '/etc/dev-lab/supervise.toml', '/usr/bin/python3',
    (('config', 'apply', '--from', CANDIDATE), ('secret', 'place', '--path', '/etc/x')), (None, '/srv/plan/x.secret'),
)  # fmt: skip


class FakeHost:
    """A host whose sudo doors, ``consent ready`` and derived subjects are set per test; it records each command."""

    def __init__(self) -> None:
        """The green host: every door, a ready verifier, the plan's subjects."""
        self.doors = {('consent', 'ready'), ('config', 'apply'), ('secret', 'place')}
        self.ready = (0, '[ops consent] ready: key abcdef, uses register at the local issuer')
        self.subjects = {'config': APPLY['subject'], 'secret': PLACE['subject']}
        self.commands: list[str] = []
        self.files: dict[str, str] = {}

    def run(self, command: str) -> tuple[str, int]:
        self.commands.append(command)
        words = shlex.split(command.split(' < ', maxsplit=1)[0])
        verb = tuple(words[words.index('--config') + 2 :][:2]) if '--config' in words else ()
        if words[:3] == ['sudo', '-n', '-l']:
            return ('', 0) if verb in self.doors else ('sudo: a password is required', 1)
        if verb == ('consent', 'ready'):
            return self.ready[1], self.ready[0]
        if '--subject' in words:
            return self.subjects[verb[0]] + '\n', 0
        return '', 0

    def put(self, path: str, text: str) -> None:
        self.files[path] = text


def test_a_host_with_every_door_is_green() -> None:
    """The planted control of every blocker below."""
    host = FakeHost()
    green, lines = planrun.preflight(PLAN, STEPS, host)
    assert green, lines
    assert lines[-1].startswith('preflight: green')
    assert any(command.endswith('< /srv/plan/x.secret') and '--subject' in command for command in host.commands)


def test_a_host_that_cannot_verify_or_register_is_blocked() -> None:
    host = FakeHost()
    host.ready = (2, 'refused: no consent public key: set [consent] public_key')
    green, lines = planrun.preflight(PLAN, STEPS, host)
    assert not green
    assert 'BLOCKED -- refused: no consent public key' in lines[0]


def test_a_missing_ready_door_is_blocked_by_name() -> None:
    host = FakeHost()
    host.doors.discard(('consent', 'ready'))
    green, lines = planrun.preflight(PLAN, STEPS, host)
    assert not green
    assert 'no sudo door for `consent ready`' in lines[0]


def test_a_missing_door_with_no_config_step_before_it_is_blocked() -> None:
    host = FakeHost()
    host.doors.discard(('config', 'apply'))
    green, lines = planrun.preflight(PLAN, STEPS, host)
    assert not green
    assert lines[1].startswith('step 1 ops.config: BLOCKED -- no sudo door')


def test_a_door_installed_by_an_earlier_config_apply_is_after_that_step_not_a_failure() -> None:
    host = FakeHost()
    host.doors.discard(('secret', 'place'))
    green, lines = planrun.preflight(PLAN, STEPS, host)
    assert green, lines
    assert lines[2].startswith('step 2 ops.secret.place: after step 1')


def test_a_subject_the_host_derives_differently_is_blocked() -> None:
    host = FakeHost()
    host.subjects['config'] = 'c' * 64
    green, lines = planrun.preflight(PLAN, STEPS, host)
    assert not green
    assert 'derives subject cccccccccccc, the plan grants aaaaaaaaaaaa' in lines[1]


def test_the_door_check_names_the_credential_flag_the_run_will_pass() -> None:
    host = FakeHost()
    planrun.preflight(PLAN, STEPS, host)
    asked = [command for command in host.commands if command.startswith('sudo -n -l') and 'apply' in command]
    assert asked == [planrun.ops_command(STEPS, [*STEPS.argv[0], '--credential', '.dev-lab/consent/preflight.json'],
                                         sudo='sudo -n -l')]  # fmt: skip


def _steps_file(tmp_path: Path, steps: object) -> Path:
    path = tmp_path / 'steps.json'
    path.write_text(json.dumps({'config': '/etc/c.toml', 'python': 'python3', 'steps': steps}), encoding='utf-8')
    return path


def test_a_steps_file_lists_one_step_per_grant(tmp_path: Path) -> None:
    good = [{'argv': ['config', 'apply']}, {'argv': ['secret', 'place'], 'stdin': '/h/x'}]
    assert planrun.load_steps(_steps_file(tmp_path, good), PLAN).stdin == (None, '/h/x')  # the control
    with pytest.raises(ConsentRefused, match='one step per grant'):
        planrun.load_steps(_steps_file(tmp_path, good[:1]), PLAN)
    with pytest.raises(ConsentRefused, match='the runner adds them'):
        planrun.load_steps(_steps_file(tmp_path, [good[0], {'argv': ['secret', 'place', '--credential', 'x']}]), PLAN)


def test_config_apply_subject_prints_the_candidates_digest_and_applies_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    host = config(tmp_path, [])
    candidate = tmp_path / 'candidate.toml'
    candidate.write_text('[ops]\nchanged = true\n', encoding='utf-8')
    before = host.path.read_text(encoding='utf-8')
    argv = ['--config', str(host.path), 'config', 'apply', '--from', str(candidate), '--subject']
    assert ops_main.main(argv) == 0
    assert capsys.readouterr().out.strip() == configdoor.digest(candidate.read_text(encoding='utf-8'))
    assert host.path.read_text(encoding='utf-8') == before


def test_secret_place_subject_binds_the_stdin_content_and_places_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    host = config(tmp_path, [])
    content = b'planted-secret\n'
    monkeypatch.setattr(
        'sys.stdin', type('S', (), {'buffer': type('B', (), {'read': staticmethod(lambda: content)})})()
    )
    assert ops_main.main(['--config', str(host.path), 'secret', 'place', '--path', '/etc/x', '--subject']) == 0
    from dev_lab.ops.secretplace import subject  # noqa: PLC0415

    assert capsys.readouterr().out.strip() == subject('/etc/x', content)
    assert ops_main.main(['--config', str(host.path), 'secret', 'place', '--path', '/etc/x']) == 2  # no credential


def test_consent_ready_is_green_at_the_issuer_and_blocked_where_no_use_can_register(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    host = config(tmp_path, [])
    assert ops_main._ready(host) == 0  # the control: the issuer's own host
    assert 'ready: key' in capsys.readouterr().out
    assert ops_main._ready(dataclasses.replace(host, consent=None)) == 2
    assert 'refused' in capsys.readouterr().err
