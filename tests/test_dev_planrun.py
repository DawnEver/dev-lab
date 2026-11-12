"""A plan's steps on its host: every door checked BEFORE a code is spent, then the granted steps run in order.

Every blocker and every stop has its planted control: the green host below, with the one fault removed, passes.
"""

from __future__ import annotations

import dataclasses
import getpass
import json
import shlex
from pathlib import Path

import pytest
from _ops_fixtures import NOW as FIXED
from _ops_fixtures import RFC_KEY, code, config

from dev_lab.dev import planrun
from dev_lab.ops import __main__ as ops_main
from dev_lab.ops import configdoor, consentverbs
from dev_lab.ops.consent import serve
from dev_lab.ops.consent.client import spent_ids
from dev_lab.ops.consent.credential import ConsentRefused
from dev_lab.ops.consent.issuer import Issuer, keygen
from dev_lab.ops.consent.plan import parsed
from dev_lab.ops.secretplace import subject

HOST = 'ops@judge.example.org'
CANDIDATE = '/srv/plan/candidate.toml'
APPLY = {'action': 'ops.config', 'subject': 'a' * 64}
PLACE = {'action': 'ops.secret.place', 'subject': 'b' * 64}
PLAN = parsed({'host': HOST, 'grants': [APPLY, PLACE]})
CONF, PY = '/etc/dev-lab/supervise.toml', '/usr/bin/python3'
STEPS = planrun.Steps((
    planrun.Step(('config', 'apply', '--from', CANDIDATE), HOST, CONF, PY),
    planrun.Step(('secret', 'place', '--path', '/etc/x'), HOST, CONF, PY, 'x.secret'),
))  # fmt: skip
SECRET, LOCAL = b'bot-token-PLANTED-7f3a', 'x.secret'


@pytest.fixture(autouse=True)
def secret_here(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The secret step's ``stdin_local`` file, on THIS machine (relative to the test's own cwd)."""
    monkeypatch.chdir(tmp_path)
    local = tmp_path / LOCAL
    local.write_bytes(SECRET)
    return local


class FakeHost:
    """A host whose sudo doors, ``consent ready`` and derived subjects are set per test; it records each command."""

    def __init__(self) -> None:
        """The green host: every door, a ready verifier, the plan's subjects."""
        self.doors = {('config', 'apply'), ('secret', 'place')}
        self.ready = (0, '[ops consent] ready: key abcdef, uses register at the local issuer')
        self.subjects = {'config': APPLY['subject'], 'secret': PLACE['subject']}
        self.commands: list[str] = []
        self.files: dict[str, str] = {}
        self.outcomes: dict[str, tuple[str, int, bool]] = {}  # verb -> (output, status, registers its use)
        self.ledger: set[str] = set()
        self.carried: list[str] = []
        self.stdins: list[tuple[str, bytes | None]] = []

    def run(self, command: str, stdin: bytes | None = None) -> tuple[str, int]:
        self.commands.append(command)
        self.stdins.append((command, stdin))
        words = shlex.split(command)
        verb = tuple(words[words.index('--config') + 2 :][:2]) if '--config' in words else ()
        if words[:3] == ['sudo', '-n', '-l']:
            return ('', 0) if verb in self.doors else ('sudo: a password is required', 1)
        if verb == ('consent', 'ready'):
            return self.ready[1], self.ready[0]
        if '--subject' in words:
            return self.subjects[verb[0]] + '\n', 0
        if words[:2] == ['rm', '-f']:
            self.files.pop(words[2], None)
            return '', 0
        if '--credential' in words:
            carried = self.files[words[words.index('--credential') + 1]]
            self.carried.append(carried)
            output, status, registers = self.outcomes.get(verb[0], ('ok', 0, True))
            if registers:
                self.ledger.add(json.loads(carried)['id'])
            return output, status
        return '', 0

    def put(self, path: str, text: str) -> None:
        self.files[path] = text


def test_a_host_with_every_door_is_green() -> None:
    """The planted control of every blocker below."""
    host = FakeHost()
    green, lines = planrun.preflight(PLAN, STEPS, lambda _dest: host)
    assert green, lines
    assert lines[-1].startswith('preflight: green')
    assert any(given == SECRET and '--subject' in command for command, given in host.stdins)
    assert not any(SECRET.decode() in command for command in host.commands)


def test_a_host_that_cannot_verify_or_register_is_blocked() -> None:
    host = FakeHost()
    host.ready = (2, 'refused: no consent public key: set [consent] public_key')
    green, lines = planrun.preflight(PLAN, STEPS, lambda _dest: host)
    assert not green
    assert 'BLOCKED -- refused: no consent public key' in lines[0]


def test_consent_ready_is_asked_without_sudo_so_a_host_needs_no_sudoers_row_for_it() -> None:
    host = FakeHost()
    planrun.preflight(PLAN, STEPS, lambda _dest: host)
    asked = [command for command in host.commands if command.endswith('consent ready')]
    assert asked == [shlex.join([PY, '-m', 'dev_lab.ops', '--config', CONF, 'consent', 'ready'])]


def test_a_missing_stdin_local_file_is_blocked_before_any_code(secret_here: Path) -> None:
    host = FakeHost()
    assert planrun.preflight(PLAN, STEPS, lambda _dest: host)[0]  # the control: the file is here
    secret_here.unlink()
    green, lines = planrun.preflight(PLAN, STEPS, lambda _dest: host)
    assert not green
    assert f'BLOCKED -- no stdin_local file here: {LOCAL}' in lines[2]


def test_a_missing_door_with_no_config_step_before_it_is_blocked() -> None:
    host = FakeHost()
    host.doors.discard(('config', 'apply'))
    green, lines = planrun.preflight(PLAN, STEPS, lambda _dest: host)
    assert not green
    assert lines[1].startswith('step 1 ops.config: BLOCKED -- no sudo door')


def test_a_door_installed_by_an_earlier_config_apply_is_after_that_step_not_a_failure() -> None:
    host = FakeHost()
    host.doors.discard(('secret', 'place'))
    green, lines = planrun.preflight(PLAN, STEPS, lambda _dest: host)
    assert green, lines
    assert lines[2].startswith('step 2 ops.secret.place: after step 1')


def test_a_subject_after_an_earlier_config_apply_on_its_host_is_derived_after_that_step() -> None:
    """The earlier apply changes the live config the subject is derived from (a family file fetched once declared)."""
    host = FakeHost()
    host.subjects['secret'] = 'd' * 64
    green, lines = planrun.preflight(PLAN, STEPS, lambda _dest: host)
    assert green, lines
    assert lines[2].startswith('step 2 ops.secret.place: after step 1 (subject derived once step 1 applied) on ')


def test_a_subject_the_host_derives_differently_is_blocked() -> None:
    host = FakeHost()
    host.subjects['config'] = 'c' * 64
    green, lines = planrun.preflight(PLAN, STEPS, lambda _dest: host)
    assert not green
    assert 'derives subject cccccccccccc, the plan grants aaaaaaaaaaaa' in lines[1]


def test_the_door_check_names_the_credential_flag_the_run_will_pass() -> None:
    host = FakeHost()
    planrun.preflight(PLAN, STEPS, lambda _dest: host)
    asked = [command for command in host.commands if command.startswith('sudo -n -l') and 'apply' in command]
    first = STEPS.steps[0]
    door = planrun.ops_command(
        first, [*first.argv, '--credential', '.dev-lab/consent/preflight.json'], sudo='sudo -n -l'
    )
    assert asked == [door]


def _steps_file(tmp_path: Path, steps: object) -> Path:
    path = tmp_path / 'steps.json'
    path.write_text(json.dumps({'config': '/etc/c.toml', 'python': 'python3', 'steps': steps}), encoding='utf-8')
    return path


def test_a_steps_file_lists_one_step_per_grant(tmp_path: Path) -> None:
    good = [{'argv': ['config', 'apply']}, {'argv': ['secret', 'place'], 'stdin_local': '/h/x'}]
    assert planrun.load_steps(_steps_file(tmp_path, good), PLAN, HOST).steps[1].stdin_local == '/h/x'  # the control
    with pytest.raises(ConsentRefused, match='stdin_local'):  # the host-side `stdin` is gone, not aliased
        planrun.load_steps(_steps_file(tmp_path, [good[0], {'argv': ['secret', 'place'], 'stdin': '/h/x'}]), PLAN, HOST)
    with pytest.raises(ConsentRefused, match='one step per grant'):
        planrun.load_steps(_steps_file(tmp_path, good[:1]), PLAN, HOST)
    with pytest.raises(ConsentRefused, match='the runner adds them'):
        planrun.load_steps(
            _steps_file(tmp_path, [good[0], {'argv': ['secret', 'place', '--credential', 'x']}]), PLAN, HOST
        )


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

    assert capsys.readouterr().out.strip() == subject('/etc/x', content)
    assert ops_main.main(['--config', str(host.path), 'secret', 'place', '--path', '/etc/x']) == 2  # no credential


def test_consent_ready_is_green_at_the_issuer_and_blocked_where_no_use_can_register(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    host = config(tmp_path, [])
    assert consentverbs.ready(host, alert=lambda *_: None) == 0  # the control: the issuer's own host
    assert 'ready: key' in capsys.readouterr().out
    assert consentverbs.ready(dataclasses.replace(host, consent=None, consent_client=None), alert=lambda *_: None) == 2
    assert 'refused' in capsys.readouterr().err


NOW = 1_800_000_000.0


def _granted(home: Path, plan: object = PLAN) -> list[Path]:
    """One local credential per grant, as ``sshhold open --plan`` writes them (only the fields the runner reads)."""
    folder = home / 'state' / 'consent'
    folder.mkdir(parents=True, exist_ok=True)
    written = []
    for index, grant in enumerate(plan.grants):
        path = folder / f'id-{index}.json'
        fields = {**grant, 'id': f'id-{index}', 'plan': plan.digest, 'issued': NOW, 'expires': NOW + 900}
        path.write_text(json.dumps(fields), 'utf-8')
        written.append(path)
    return written


def _run(host: FakeHost, home: Path, *, spent: planrun.Spent | None = None) -> tuple[bool, list[str]]:
    asked = spent or (lambda ids: set(ids) & host.ledger)
    return planrun.run_plan(PLAN, STEPS, lambda _dest: host, spent=asked, home=home, now=lambda: NOW)


def test_a_granted_plan_runs_in_order_and_deletes_only_spent_credentials(tmp_path: Path) -> None:
    """The planted control of every stop below."""
    host, written = FakeHost(), _granted(tmp_path)
    finished, lines = _run(host, tmp_path)
    assert finished, lines
    assert [json.loads(text)['id'] for text in host.carried] == ['id-0', 'id-1']
    assert not any(path.exists() for path in written)
    assert host.files == {}  # every carried copy removed from the host
    secret = next(command for command in host.commands if '--credential' in command and 'secret' in command)
    assert dict(host.stdins)[secret] == SECRET
    assert SECRET.decode() not in secret


def test_a_refusal_stops_the_run_and_keeps_every_unspent_credential(tmp_path: Path) -> None:
    host, written = FakeHost(), _granted(tmp_path)
    host.outcomes['config'] = ('refused: no consent public key', 2, False)
    finished, lines = _run(host, tmp_path)
    assert not finished
    assert 'STOPPED -- refused (exit 2)' in lines[-1]
    assert 'NOT spent, kept' in lines[-1]
    assert all(path.exists() for path in written)  # incident (b): the unspent credential survives
    assert len(host.carried) == 1  # step 2 never ran
    assert host.files == {}


def test_a_step_that_spent_its_credential_and_then_failed_deletes_it_and_stops(tmp_path: Path) -> None:
    host, written = FakeHost(), _granted(tmp_path)
    host.outcomes['config'] = ('refused: the forge is down', 1, True)
    finished, lines = _run(host, tmp_path)
    assert not finished
    assert 'credential spent, deleted' in lines[-1]
    assert [path.exists() for path in written] == [False, True]


def test_a_success_the_issuer_did_not_register_keeps_the_credential(tmp_path: Path) -> None:
    host, written = FakeHost(), _granted(tmp_path)
    host.outcomes['config'] = ('[ops config] unchanged', 0, False)
    finished, lines = _run(host, tmp_path)
    assert finished
    assert 'NOT spent, kept' in lines[0]
    assert [path.exists() for path in written] == [True, False]


def test_an_issuer_that_cannot_answer_keeps_the_credential(tmp_path: Path) -> None:
    host, written = FakeHost(), _granted(tmp_path)

    def unreachable(_ids: list[str]) -> set[str]:
        msg = 'the consent issuer could not say'
        raise ConsentRefused(msg)

    finished, lines = _run(host, tmp_path, spent=unreachable)
    assert not finished
    assert 'so it is kept' in lines[-1]
    assert all(path.exists() for path in written)


def test_a_second_run_resumes_where_the_first_stopped(tmp_path: Path) -> None:
    host, written = FakeHost(), _granted(tmp_path)
    host.outcomes['secret'] = ('refused: no door', 2, False)
    assert not _run(host, tmp_path)[0]
    del host.outcomes['secret']  # the blocker fixed
    finished, lines = _run(host, tmp_path)
    assert finished, lines
    assert lines[0] == f'step 1 ops.config on {HOST}: done earlier'
    assert [json.loads(text)['id'] for text in host.carried] == ['id-0', 'id-1', 'id-1']
    assert not any(path.exists() for path in written)


def test_a_step_with_no_live_credential_stops_before_running(tmp_path: Path) -> None:
    host, written = FakeHost(), _granted(tmp_path)
    stale = {**PLACE, 'id': 'id-1', 'plan': PLAN.digest, 'issued': NOW - 7200, 'expires': NOW - 3600}
    written[1].write_text(json.dumps(stale), 'utf-8')
    finished, lines = _run(host, tmp_path)
    assert not finished
    assert lines[-1].startswith(f'step 2 ops.secret.place on {HOST}: STOPPED -- no unexpired credential')
    assert len(host.carried) == 1


def test_a_credential_issued_from_another_plan_is_never_carried(tmp_path: Path) -> None:
    """Same grants, another plan (another host): its signed ``plan`` digest is not this run's, so it is not used."""
    host = FakeHost()
    _granted(tmp_path, parsed({'host': 'ops@other.example.org', 'grants': [APPLY, PLACE]}))
    finished, lines = _run(host, tmp_path)
    assert not finished
    assert 'STOPPED -- no unexpired credential' in lines[-1]
    assert host.carried == []
    _granted(tmp_path)  # the control: this plan's credentials run
    assert _run(host, tmp_path)[0]


def test_the_issuer_answers_which_ids_were_spent(tmp_path: Path) -> None:
    (tmp_path / 'totp').write_text(RFC_KEY + '\n', encoding='utf-8')
    keygen(tmp_path / 'k')
    issuer = Issuer(tmp_path / 'totp', tmp_path / 'k', tmp_path / 's', 'test', lambda: FIXED)
    first, second = issuer.issue_plan({'host': HOST, 'grants': [APPLY, PLACE]}, code(0))
    issuer.register(first)

    def send(_table: object, payload: dict[str, object]) -> tuple[int, str]:
        return 0, serve.handle(issuer, json.dumps(payload))

    asked = [first['id'], second['id'], 'never-granted']
    assert spent_ids(asked, {'endpoint': 'consent@forge'}, send=send) == {first['id']}


JUDGE = 'ops@judge.example.org:2222'
JUDGE_APPLY = {'action': 'ops.config', 'subject': 'c' * 64}
WAVE = {'action': 'breakglass.wave', 'subject': 'wave'}
WIDE = parsed({'host': HOST, 'grants': [APPLY, JUDGE_APPLY, PLACE, WAVE]})
WIDE_STEPS = planrun.Steps((
    STEPS.steps[0],
    planrun.Step(('config', 'apply', '--from', '/srv/plan/judge.toml'), JUDGE, '/etc/dev-lab/judge.toml', PY),
    STEPS.steps[1],
    planrun.Step(('breakglass', 'open'), local=True),
))  # fmt: skip
ENDPOINT = {'endpoint': 'breakglass@forge'}


def _hosts() -> dict[str, FakeHost]:
    hosts = {HOST: FakeHost(), JUDGE: FakeHost()}
    hosts[JUDGE].subjects['config'] = JUDGE_APPLY['subject']
    return hosts


def _wide_preflight(hosts: dict[str, FakeHost], table: dict[str, str] = ENDPOINT) -> tuple[bool, list[str]]:
    return planrun.preflight(WIDE, WIDE_STEPS, hosts.__getitem__, machine=lambda _table: table)


def test_a_plan_across_hosts_and_a_local_wave_is_green_with_every_check_on_its_own_host() -> None:
    """The planted control of every cross-host blocker below."""
    hosts = _hosts()
    green, lines = _wide_preflight(hosts)
    assert green, lines
    assert lines[:2] == [f'host {HOST}: ready', f'host {JUDGE}: ready']
    assert lines[3] == f'step 2 ops.config: green on {JUDGE}'
    assert lines[5].startswith('step 4 breakglass.wave: green (here: forge breakglass open via breakglass@forge')
    judged = [command for command in hosts[JUDGE].commands if '--subject' in command]
    assert judged == [planrun.ops_command(WIDE_STEPS.steps[1], [*WIDE_STEPS.steps[1].argv, '--subject'])]
    assert all('judge.toml' not in command for command in hosts[HOST].commands)


def test_a_second_host_that_cannot_register_is_blocked_by_its_name() -> None:
    hosts = _hosts()
    hosts[JUDGE].ready = (2, 'refused: no consent public key')
    green, lines = _wide_preflight(hosts)
    assert not green
    assert lines[:2] == [f'host {HOST}: ready', f'host {JUDGE}: BLOCKED -- refused: no consent public key']


def test_a_config_apply_on_another_host_installs_no_door_here() -> None:
    hosts = _hosts()
    hosts[JUDGE].doors.discard(('config', 'apply'))  # step 1 applies on HOST, not on the judge
    green, lines = _wide_preflight(hosts)
    assert not green
    assert lines[3].startswith('step 2 ops.config: BLOCKED -- no sudo door for `config apply')


def test_a_local_step_with_no_endpoint_in_the_machine_file_is_blocked() -> None:
    green, lines = _wide_preflight(_hosts(), {})
    assert not green
    assert lines[5] == 'step 4 breakglass.wave: BLOCKED -- the machine file has no [breakglass] endpoint'


def _wide_run(hosts: dict[str, FakeHost], home: Path, local: planrun.Local) -> tuple[bool, list[str]]:
    def spent(ids: list[str]) -> set[str]:
        return set(ids) & (hosts[HOST].ledger | hosts[JUDGE].ledger)

    return planrun.run_plan(WIDE, WIDE_STEPS, hosts.__getitem__, spent=spent, local=local, home=home, now=lambda: NOW)


def test_one_plan_runs_across_its_hosts_and_redeems_the_wave_here(tmp_path: Path) -> None:
    hosts, written, opened = _hosts(), _granted(tmp_path, WIDE), []

    def local(words: list[str]) -> tuple[str, int]:
        opened.append(list(words))
        hosts[HOST].ledger.add(words[-1])  # the forge's issuer registers the wave's use
        return '[breakglass] wave open', 0

    finished, lines = _wide_run(hosts, tmp_path, local)
    assert finished, lines
    assert [json.loads(text)['id'] for text in hosts[HOST].carried] == ['id-0', 'id-2']
    assert [json.loads(text)['id'] for text in hosts[JUDGE].carried] == ['id-1']
    assert opened == [['breakglass', 'open', '--credential', 'id-3']]
    assert lines[3] == 'step 4 breakglass.wave here: ran ([breakglass] wave open); credential spent, deleted'
    assert not any(path.exists() for path in written)


def test_a_wave_the_forge_refused_unspent_keeps_its_credential_and_resumes_there(tmp_path: Path) -> None:
    hosts, written = _hosts(), _granted(tmp_path, WIDE)
    finished, lines = _wide_run(hosts, tmp_path, lambda _words: ('[breakglass] refused', 2))
    assert not finished
    assert 'NOT spent, kept' in lines[-1]
    assert [path.exists() for path in written] == [False, False, False, True]
    finished, lines = _wide_run(hosts, tmp_path, lambda words: (hosts[HOST].ledger.add(words[-1]), ('ok', 0))[1])
    assert finished, lines
    assert lines[2] == f'step 3 ops.secret.place on {HOST}: done earlier'
    assert not written[3].exists()


def test_a_steps_file_names_each_steps_host_and_a_local_wave(tmp_path: Path) -> None:
    good = [
        {'argv': ['config', 'apply']}, {'argv': ['config', 'apply'], 'dest': JUDGE, 'config': '/etc/j.toml'},
        {'argv': ['secret', 'place']}, {'local': True},
    ]  # fmt: skip
    steps = planrun.load_steps(_steps_file(tmp_path, good), WIDE, HOST).steps  # the control
    assert [(step.dest, step.config, step.local) for step in steps] == [
        (HOST, '/etc/c.toml', False), (JUDGE, '/etc/j.toml', False), (HOST, '/etc/c.toml', False), ('', '', True),
    ]  # fmt: skip
    assert steps[3].argv == ('breakglass', 'open')
    with pytest.raises(ConsentRefused, match='redeemed here'):
        planrun.load_steps(_steps_file(tmp_path, [*good[:3], {'argv': ['breakglass', 'open']}]), WIDE, HOST)
    with pytest.raises(ConsentRefused, match='redeemed on a host'):
        planrun.load_steps(_steps_file(tmp_path, [{'local': True}, *good[1:]]), WIDE, HOST)


BUNDLE = 'OPENAI_API_KEY=sk-PLANTED-9c1e\n'
TASK_STEPS = planrun.Steps((
    STEPS.steps[0],
    dataclasses.replace(STEPS.steps[1], stdin_local=None, stdin_task='judge'),
))  # fmt: skip


@pytest.fixture
def stored(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """The forge-secrets store of this machine, as task -> bundle."""
    bundles = {'judge': BUNDLE}
    monkeypatch.setattr(planrun.forgesecrets, 'stored_bundle', lambda task: bundles.get(task, ''))
    return bundles


@pytest.mark.usefixtures('stored')
def test_a_task_bundle_streams_as_the_steps_stdin_and_never_rides_a_command() -> None:
    host = FakeHost()
    green, lines = planrun.preflight(PLAN, TASK_STEPS, lambda _dest: host)
    assert green, lines
    assert any(given == BUNDLE.encode() and '--subject' in command for command, given in host.stdins)
    assert not any('sk-PLANTED' in command for command in host.commands)
    assert not any('sk-PLANTED' in line for line in lines)


def test_a_task_with_no_stored_bundle_is_blocked_before_any_code(stored: dict[str, str]) -> None:
    host = FakeHost()
    assert planrun.preflight(PLAN, TASK_STEPS, lambda _dest: host)[0]  # the control: the bundle is stored
    stored.clear()
    green, lines = planrun.preflight(PLAN, TASK_STEPS, lambda _dest: host)
    assert not green
    assert 'BLOCKED -- no stored bundle for task judge here' in lines[2]


@pytest.mark.usefixtures('stored')
def test_a_granted_task_step_streams_its_bundle_and_writes_no_file(tmp_path: Path) -> None:
    host, _ = FakeHost(), _granted(tmp_path)
    before = set(tmp_path.rglob('*'))
    finished, lines = planrun.run_plan(PLAN, TASK_STEPS, lambda _dest: host, spent=lambda ids: set(ids) & host.ledger,
                                       home=tmp_path, now=lambda: NOW)  # fmt: skip
    assert finished, lines
    secret = next(command for command in host.commands if '--credential' in command and 'secret' in command)
    assert dict(host.stdins)[secret] == BUNDLE.encode()
    assert not any('sk-PLANTED' in path.read_text(errors='ignore') for path in set(tmp_path.rglob('*')) - before
                   if path.is_file())  # fmt: skip
    assert host.files == {}


def test_a_step_names_exactly_one_stdin_source(tmp_path: Path) -> None:
    one = [{'argv': ['config', 'apply']}, {'argv': ['secret', 'place'], 'stdin_task': 'judge'}]
    assert planrun.load_steps(_steps_file(tmp_path, one), PLAN, HOST).steps[1].stdin_task == 'judge'  # the control
    both = [one[0], {**one[1], 'stdin_local': 'x.secret'}]
    with pytest.raises(ConsentRefused, match='exactly one source'):
        planrun.load_steps(_steps_file(tmp_path, both), PLAN, HOST)


def test_consent_ready_stats_the_issuer_key_and_never_reads_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    host = config(tmp_path, [])

    def unreadable(*_: object, **__: object) -> bytes:
        raise PermissionError(13, 'Permission denied', host.consent.key)

    monkeypatch.setattr(Path, 'read_bytes', unreadable)  # present but root 600: opening it is refused
    assert consentverbs.ready(host, alert=lambda *_: None) == 0
    assert 'ready: key' in capsys.readouterr().out
    Path(host.consent.key).unlink()  # planted control: a missing key reads not ready, by its path
    assert consentverbs.ready(host, alert=lambda *_: None) == 2
    assert f'issuer key missing: {Path(host.consent.key)}' in capsys.readouterr().err


def test_an_unsearchable_issuer_key_directory_is_the_readiness_answer_not_a_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    host = config(tmp_path, [])

    def hidden(*_: object, **__: object) -> object:
        raise PermissionError(13, 'Permission denied', host.consent.key)

    monkeypatch.setattr(Path, 'stat', hidden)
    assert consentverbs.ready(host, alert=lambda *_: None) == 2
    assert f'issuer key not visible to {getpass.getuser()}: {Path(host.consent.key)}' in capsys.readouterr().err


def test_the_issuer_is_ready_without_a_published_key_and_says_so(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """2026-11-12 forge-a1: requiring the published key at the issuer deadlocked the config that would declare it."""
    host = config(tmp_path, [])

    def unpublished(_table: object) -> object:
        msg = 'no consent public key: set [consent] public_key in the machine file'
        raise consentverbs.ConsentRefused(msg)

    monkeypatch.setattr(consentverbs, 'public_key', unpublished)
    assert consentverbs.ready(host, alert=lambda *_: None) == 0
    assert 'no published key declared here' in capsys.readouterr().out
    Path(host.consent.key).unlink()  # planted control: the private key itself still decides
    assert consentverbs.ready(host, alert=lambda *_: None) == 2


MINTED = 'forge-PLANTED-91c2'


def _minting(host: FakeHost, home: Path, stdout_local: str | None) -> tuple[bool, list[str]]:
    """Step 2 runs with *stdout_local* as it is printed by the host (a ``forge token mint``)."""
    steps = planrun.Steps((STEPS.steps[0], dataclasses.replace(STEPS.steps[1], stdout_local=stdout_local)))
    return planrun.run_plan(
        PLAN, steps, lambda _dest: host, spent=lambda ids: set(ids) & host.ledger, home=home, now=lambda: NOW
    )


def test_a_step_without_stdout_local_shows_its_last_line(tmp_path: Path) -> None:
    """The planted control: the output IS shown when the step does not declare it private."""
    host, _ = FakeHost(), _granted(tmp_path)
    host.outcomes['secret'] = (f'minting\n{MINTED}\n', 0, True)
    finished, lines = _minting(host, tmp_path, None)
    assert finished, lines
    assert MINTED in lines[1]


def test_a_stdout_local_step_writes_its_output_privately_and_never_shows_it(tmp_path: Path) -> None:
    host, _ = FakeHost(), _granted(tmp_path)
    host.outcomes['secret'] = (f'minting\n{MINTED}\n', 0, True)
    finished, lines = _minting(host, tmp_path, 'tokens/judge.token')
    assert finished, lines
    kept = tmp_path / 'state' / 'consent' / 'outputs' / 'tokens' / 'judge.token'
    assert kept.read_text(encoding='utf-8') == f'minting\n{MINTED}\n'
    assert MINTED not in '\n'.join(lines)
    assert f'wrote {kept} (sha256 ' in lines[1]
    assert f'{len(kept.read_bytes())} bytes)' in lines[1]


def test_a_failed_stdout_local_step_withholds_its_output_and_writes_nothing(tmp_path: Path) -> None:
    host, _ = FakeHost(), _granted(tmp_path)
    host.outcomes['secret'] = (f'{MINTED}\n', 3, False)
    finished, lines = _minting(host, tmp_path, 't.token')
    assert not finished
    assert MINTED not in '\n'.join(lines)
    assert 'exit 3' in lines[-1]
    assert 'output withheld' in lines[-1]
    assert not (tmp_path / 'state' / 'consent' / 'outputs' / 't.token').exists()


@pytest.mark.parametrize('name', ['/abs/x', '../x', 'a/../../x', '', 'C:/x', 'C:x', '\\\\srv\\x'])
def test_stdout_local_is_a_relative_name_without_dotdot(tmp_path: Path, name: str) -> None:
    good = [{'argv': ['config', 'apply']}, {'argv': ['secret', 'place'], 'stdout_local': 'ok/x'}]
    assert planrun.load_steps(_steps_file(tmp_path, good), PLAN, HOST).steps[1].stdout_local == 'ok/x'  # control
    bad = [{'argv': ['config', 'apply']}, {'argv': ['secret', 'place'], 'stdout_local': name}]
    with pytest.raises(ConsentRefused, match='stdout_local'):
        planrun.load_steps(_steps_file(tmp_path, bad), PLAN, HOST)


def test_a_grant_this_client_does_not_know_blocks_the_preflight_naming_the_update() -> None:
    """A plan written against a newer registry is BLOCKED here, before a code -- not refused after the user gave one."""
    newer = parsed({'host': HOST, 'grants': [APPLY, {'action': 'ops.not.yet.known', 'subject': 'c' * 64}]})
    steps = planrun.Steps((*STEPS.steps[:1], planrun.Step(('not', 'known'), HOST, CONF, PY)))
    green, lines = planrun.preflight(newer, steps, lambda _dest: FakeHost())
    assert not green
    blocked = [line for line in lines if 'ops.not.yet.known' in line and 'BLOCKED' in line]
    assert blocked, lines
    assert 'local dev-lab is older than the plan; update it' in blocked[0]
    assert planrun.preflight(PLAN, STEPS, lambda _dest: FakeHost())[0]  # the control: every action known
