"""An ``ops.config`` subject is derived HERE from the reviewed source, so a plan is built with no session on its host.

The planted controls: the local subject EQUALS what the host's own ``config apply --subject`` path renders for the same
source (:func:`configdoor.fetch` over a clone of it), and a tampered candidate -- host file or family file -- differs.
"""

from __future__ import annotations

import json
import shlex
from collections.abc import Mapping
from pathlib import Path

import pytest

from dev_lab.dev import planrun, planrunpreflight, planrunsteps, sshholdwire
from dev_lab.ops import configdoor
from dev_lab.ops.config import ConfigSource
from dev_lab.ops.consent.credential import ConsentRefused
from dev_lab.ops.consent.plan import Plan, parsed

SOURCE = 'https://forge.example/team/host-config.git'
HOST_NAME = 'judge'
HOST_FILE = f'hosts/{HOST_NAME}.toml'
FAMILY_TEXT = '[judge]\nmonthly_usd = 40\n'
HOST_TEXT = f"""[cycle]
interval_s = 60

[ops.config]
source = "{SOURCE}"
path = "{HOST_FILE}"
token_file = "/etc/dev-lab/token"
ref = "main"
family = {{ file = "family.toml", to = "/etc/dev-lab/family.toml" }}
"""
REPO = {HOST_FILE: HOST_TEXT, 'family.toml': FAMILY_TEXT}
DEST = 'ops@judge.example.org'
OTHER = 'ops@worker.example.org'
CONF, PY = '/etc/dev-lab/supervise.toml', '/usr/bin/python3'


def _reader(repo: Mapping[str, str], reads: list[tuple[str, str, str]] | None = None) -> planrunpreflight.SourceReader:
    def read(source: str, path: str, ref: str) -> str:
        if reads is not None:
            reads.append((source, path, ref))
        assert (source, ref) == (SOURCE, 'main')
        return repo[path]

    return read


def _host_rendered(tmp_path: Path, repo: Mapping[str, str]) -> str:
    """What the host prints for ``config apply --subject``: its fetch of the clone, then :func:`configdoor.digest`."""
    token = tmp_path / 'token'
    token.write_text('planted-token\n', encoding='utf-8')
    family = {'file': 'family.toml', 'to': '/etc/dev-lab/family.toml'}
    declared = ConfigSource(SOURCE, HOST_FILE, str(token), 'main', family=family)

    def clone(argv: list[str], _env: Mapping[str, str]) -> tuple[int, str]:
        target = Path(argv[-1])
        for name, text in repo.items():
            (target / name).parent.mkdir(parents=True, exist_ok=True)
            (target / name).write_text(text, encoding='utf-8', newline='\n')
        return 0, ''

    fetched = configdoor.fetch(declared, run=clone)
    return configdoor.digest(fetched.host, fetched.family)


def _readers(repo: Mapping[str, str] = REPO) -> planrunpreflight.Readers:
    return planrunpreflight.Readers(text=_reader(repo), config_source=lambda: SOURCE)


def test_the_subject_derived_here_is_the_one_the_host_renders(tmp_path: Path) -> None:
    """PLANTED: a tampered host file and a tampered family file each give another subject."""
    reads: list[tuple[str, str, str]] = []
    here = planrunpreflight.config_subject(HOST_NAME, _reader(REPO, reads), SOURCE)
    assert here == _host_rendered(tmp_path, REPO)
    assert reads == [(SOURCE, HOST_FILE, 'main'), (SOURCE, 'family.toml', 'main')]
    for name, text in REPO.items():
        tampered = {**REPO, name: text + '# one more line\n'}
        assert planrunpreflight.config_subject(HOST_NAME, _reader(tampered), SOURCE) != here, name
        assert planrunpreflight.config_subject(HOST_NAME, _reader(tampered), SOURCE) == _host_rendered(
            tmp_path, tampered
        )


def test_the_host_subject_does_not_depend_on_whether_the_family_file_is_already_placed(tmp_path: Path) -> None:
    """An unchanged placed family file must not change the subject: the host's state is invisible here."""
    family = configdoor.Family(tmp_path / 'family.toml', FAMILY_TEXT)
    before = configdoor.digest(HOST_TEXT, family)
    family.to.write_text(FAMILY_TEXT, encoding='utf-8')
    assert configdoor.digest(HOST_TEXT, family) == before
    assert configdoor.digest(HOST_TEXT) != before  # the control: the family text is bound


def test_a_file_declaring_another_source_or_none_is_the_hosts_to_derive() -> None:
    elsewhere = {**REPO, HOST_FILE: HOST_TEXT.replace(SOURCE, 'https://forge.example/other/repo.git')}
    with pytest.raises(configdoor.ConfigRefused, match='derive it there'):
        planrunpreflight.config_subject(HOST_NAME, _reader(elsewhere), SOURCE)
    bare = {**REPO, HOST_FILE: '[cycle]\ninterval_s = 60\n'}
    with pytest.raises(configdoor.ConfigRefused, match=r'no \[ops.config\]'):
        planrunpreflight.config_subject(HOST_NAME, _reader(bare), SOURCE)


class _Host:
    """A host that answers (its doors and subject) or is down (no held session)."""

    def __init__(self, subject: str, *, down: bool = False) -> None:
        self.subject, self.down = subject, down
        self.commands: list[str] = []

    def run(self, command: str, _stdin: bytes | None = None) -> tuple[str, int]:
        if self.down:
            msg = 'no held session'
            raise sshholdwire.HoldRefused(msg)
        self.commands.append(command)
        words = shlex.split(command)
        if '--subject' in words:
            return self.subject + '\n', 0
        return '', 0

    def put(self, path: str, text: str) -> None:
        del path, text


def _plan(subject: str, *hosts: str) -> Plan:
    grants = [{'host': host, 'action': 'ops.config', 'subject': subject} for host in hosts]
    return parsed({'hosts': list(hosts), 'grants': grants})


def _step(dest: str, *, derivable: bool = True) -> planrunsteps.Step:
    return planrunsteps.Step(('config', 'apply'), dest, CONF, PY, config_host=HOST_NAME if derivable else '')


def test_an_unreachable_host_has_its_config_subject_derived_here(tmp_path: Path) -> None:
    """PLANTED: a plan granting another subject is blocked, naming both; a step with no declaration is blocked."""
    want = _host_rendered(tmp_path, REPO)
    down = _Host(want, down=True)
    green, lines = planrunpreflight.preflight(
        _plan(want, DEST), planrunsteps.Steps((_step(DEST),)), lambda _d: down, readers=_readers()
    )
    assert green, lines
    assert any('UNREACHABLE' in line for line in lines)
    assert any('subject derived here' in line and 'door is checked at run' in line for line in lines), lines
    green, lines = planrunpreflight.preflight(
        _plan('f' * 64, DEST), planrunsteps.Steps((_step(DEST),)), lambda _d: down, readers=_readers()
    )
    assert not green
    assert any(f'derived here {want[:12]}' in line for line in lines), lines
    green, lines = planrunpreflight.preflight(
        _plan(want, DEST), planrunsteps.Steps((_step(DEST, derivable=False),)), lambda _d: down, readers=_readers()
    )
    assert not green
    assert any("the host's to derive" in line for line in lines), lines


def test_a_reachable_host_is_still_asked_for_its_subject(tmp_path: Path) -> None:
    """The host's own answer stands when a session exists: a host deriving another subject blocks."""
    want = _host_rendered(tmp_path, REPO)
    up = _Host(want)
    green, lines = planrunpreflight.preflight(
        _plan(want, DEST), planrunsteps.Steps((_step(DEST),)), lambda _d: up, readers=_readers()
    )
    assert green, lines
    assert any('--subject' in command for command in up.commands)
    other = _Host('e' * 64)
    green, _ = planrunpreflight.preflight(
        _plan(want, DEST), planrunsteps.Steps((_step(DEST),)), lambda _d: other, readers=_readers()
    )
    assert not green


def test_a_two_host_plan_is_built_with_neither_host_reachable() -> None:
    worker = 'hosts/worker.toml'
    repo = {**REPO, worker: HOST_TEXT.replace(HOST_FILE, worker)}
    subjects = [planrunpreflight.config_subject(name, _reader(repo), SOURCE) for name in (HOST_NAME, 'worker')]
    grants = [
        {'host': dest, 'action': 'ops.config', 'subject': subject}
        for dest, subject in zip((DEST, OTHER), subjects, strict=True)
    ]
    plan = parsed({'hosts': [DEST, OTHER], 'grants': grants})
    hosts = {DEST: _Host('', down=True), OTHER: _Host('', down=True)}
    other = planrunsteps.Step(('config', 'apply'), OTHER, CONF, PY, config_host='worker')
    steps = planrunsteps.Steps((_step(DEST), other))
    green, lines = planrunpreflight.preflight(plan, steps, hosts.__getitem__, readers=_readers(repo))
    assert green, lines
    assert sum('UNREACHABLE' in line for line in lines) == 2


@pytest.mark.parametrize(
    ('action', 'argv'), [('ops.secret.place', ['secret', 'place']), ('ops.config', ['config', 'apply', '--from', 'x'])]
)
def test_config_host_names_only_a_config_step_reading_its_reviewed_source(
    tmp_path: Path, action: str, argv: list[str]
) -> None:
    plan = parsed({'hosts': [DEST], 'grants': [{'host': DEST, 'action': action, 'subject': 'a' * 64}]})
    path = tmp_path / 'steps.json'
    body = {'config': CONF, 'python': PY, 'steps': [{'argv': argv, 'config_host': HOST_NAME}]}
    path.write_text(json.dumps(body), encoding='utf-8')
    with pytest.raises(ConsentRefused, match='config_host'):
        planrunsteps.load_steps(path, plan)
    config = parsed({'hosts': [DEST], 'grants': [{'host': DEST, 'action': 'ops.config', 'subject': 'a' * 64}]})
    body['steps'] = [{'argv': ['config', 'apply'], 'config_host': HOST_NAME}]
    path.write_text(json.dumps(body), encoding='utf-8')
    assert planrunsteps.load_steps(path, config).steps[0].config_host == HOST_NAME  # the control


def test_planrun_subject_config_prints_the_subject_with_no_host(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert planrun.main(['subject', '--config', HOST_NAME], readers=_readers()) == 0
    assert capsys.readouterr().out.strip() == _host_rendered(tmp_path, REPO)
    assert planrun.main(['subject', '--config', 'absent'], readers=_readers({**REPO, 'hosts/absent.toml': 'x ='})) == 2
