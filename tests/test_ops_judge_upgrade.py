"""The judge role runs one ``forge review judge`` per configured repo; ``upgrade`` installs only the configured tip."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from dev_lab.ops import __main__ as door
from dev_lab.ops import install as install_module
from dev_lab.ops import judge, upgrade
from dev_lab.ops.config import OpsConfig, load
from dev_lab.ops.install import install

ALPHA = 'https://gitea.example/owner/alpha'
BETA = 'https://github.com/owner/beta'


def _config(tmp: Path, body: str) -> OpsConfig:
    path = tmp / 'supervise.toml'
    head = f'[ops]\nhome = "{(tmp / "home").as_posix()}"\npython = "/opt/ops/bin/python"\n'
    path.write_text(head + body, encoding='utf-8')
    return load(path, environ={})


def _judge_table(tmp: Path) -> str:
    gitea, github = (tmp / 'judge-gitea').as_posix(), (tmp / 'judge-github').as_posix()
    return (
        f'[ops.judge]\nuser = "judge"\nschedule = "*:0/5"\nrepos = ["{ALPHA}", "{BETA}"]\n'
        f'environment_file = "{(tmp / "judge.env").as_posix()}"\nmemory_max = "3G"\n'
        f'[ops.judge.tokens]\n"gitea.example" = "{gitea}"\n"github.com" = "{github}"\n'
    )


def test_install_renders_the_judge_unit_and_timer(tmp_path: Path) -> None:
    host = _config(tmp_path, _judge_table(tmp_path))
    done = install(host, tmp_path / 'root')
    units = tmp_path / 'root' / 'etc' / 'systemd' / 'system'
    service = (units / 'dev-lab-ops-judge.service').read_text(encoding='utf-8')
    timer = (units / 'dev-lab-ops-judge.timer').read_text(encoding='utf-8')
    assert 'User=judge\n' in service
    assert f'EnvironmentFile={(tmp_path / "judge.env").as_posix()}\n' in service
    assert service.splitlines()[-2].endswith(' judge')  # ExecStart=<python> -m dev_lab.ops --config <file> judge
    assert 'MemoryMax=3G\n' in service
    assert 'OnCalendar=*:0/5\n' in timer
    assert any('useradd' in step and 'judge' in step for step in done.next_steps)
    assert any(step.startswith('chown judge ') and 'judge-github' in step for step in done.next_steps)
    assert any(step.startswith('chown root:root') and 'judge.env' in step for step in done.next_steps)


def test_no_judge_table_renders_no_judge_unit(tmp_path: Path) -> None:
    install(_config(tmp_path, ''), tmp_path / 'root')
    assert not (tmp_path / 'root' / 'etc' / 'systemd' / 'system' / 'dev-lab-ops-judge.service').exists()


@pytest.mark.parametrize(
    ('repos', 'tokens', 'why'),
    [
        ('', '', 'serves no repo'),
        (f'"{ALPHA}", "{ALPHA}"', '"gitea.example" = "t"\n', 'twice'),
        (f'"{ALPHA}", "{BETA}"', '"gitea.example" = "t"\n', 'names no token'),
        (f'"{ALPHA}"', '"gitea.example" = "t"\n"github.com" = "u"\n', 'serves no repo in'),
    ],
)
def test_a_judge_declaration_that_lies_is_refused(tmp_path: Path, repos: str, tokens: str, why: str) -> None:
    table = f'[ops.judge]\nuser = "judge"\nschedule = "*:0/5"\nrepos = [{repos}]\n[ops.judge.tokens]\n{tokens}'
    with pytest.raises(ValueError, match=why):
        _config(tmp_path, table)


def test_the_judge_runs_one_pass_and_a_failing_repo_does_not_stop_the_next(tmp_path: Path) -> None:
    host = _config(tmp_path, _judge_table(tmp_path))
    ran: list[list[str]] = []

    def fake(argv: Sequence[str]) -> int:
        ran.append(list(argv))
        return 2 if ALPHA in argv else 0

    outcomes = judge.run(host, runner=fake)
    assert [o.state for o in outcomes] == ['failed', 'judged']
    assert ran[1] == [
        '/opt/ops/bin/python', '-m', 'dev_lab.dev.forge', 'review', 'judge', '--url', BETA,
        '--token-file', (tmp_path / 'judge-github').as_posix(),
    ]  # fmt: skip


def test_the_judge_verb_alerts_a_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    host = _config(tmp_path, _judge_table(tmp_path))
    alerts: list[str] = []
    monkeypatch.setattr(door, '_alert', lambda _c, title, _d: alerts.append(title))
    monkeypatch.setattr(judge, '_subprocess', lambda argv: 1 if BETA in argv else 0)
    assert door.main(['--config', str(host.path), 'judge']) == 1
    assert alerts == [f'judge FAILED {BETA}']


def test_the_judge_verb_refuses_a_host_with_no_judge(tmp_path: Path) -> None:
    host = _config(tmp_path, '')
    assert door.main(['--config', str(host.path), 'judge']) == 2


UPGRADE = (
    '[ops.upgrade]\nsource = "https://forge.example/owner/dev-lab.git"\nref = "main"\nextras = ["ops"]\n'
    'overrides = "/etc/dev-lab/overrides.txt"\nuv = "/usr/local/bin/uv"\n'
    'packages = ["ai-lab @ git+https://forge.example/owner/ai-lab.git"]\n'
)


def test_upgrade_builds_exactly_the_configured_command(tmp_path: Path) -> None:
    assert upgrade.command(_config(tmp_path, UPGRADE)) == [
        '/usr/local/bin/uv', 'pip', 'install', '--python', '/opt/ops/bin/python', '--reinstall-package', 'dev-lab',
        '--override', '/etc/dev-lab/overrides.txt',
        'dev-lab[ops] @ git+https://forge.example/owner/dev-lab.git@main',
        'ai-lab @ git+https://forge.example/owner/ai-lab.git',
    ]  # fmt: skip


def test_upgrade_reports_old_to_new_and_runs_only_the_configured_install(tmp_path: Path) -> None:
    versions = iter(['1.0', '1.1'])
    installed: list[list[str]] = []

    def fake(argv: Sequence[str]) -> tuple[int, str]:
        installed.append(list(argv))
        return 0, ''

    host = _config(tmp_path, UPGRADE)
    said = upgrade.run(host, install=fake, probe=lambda _argv: (0, next(versions)))
    assert said == (0, 'dev-lab 1.0 -> 1.1')
    assert installed == [upgrade.command(host)]


@pytest.mark.parametrize('extra', [['deadbeef'], ['--ref', 'x'], ['https://forge.example/other.git']])
def test_upgrade_accepts_no_argument(tmp_path: Path, extra: list[str]) -> None:
    host = _config(tmp_path, UPGRADE)
    with pytest.raises(SystemExit) as refused:
        door.main(['--config', str(host.path), 'upgrade', *extra])
    assert refused.value.code == 2


def test_upgrade_refuses_a_host_with_no_upgrade_table(tmp_path: Path) -> None:
    host = _config(tmp_path, '')
    assert door.main(['--config', str(host.path), 'upgrade']) == 2
    with pytest.raises(ValueError, match=r'\[ops.upgrade\]'):
        upgrade.command(host)


def test_upgrade_refuses_a_table_with_no_source(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match='source'):
        _config(tmp_path, '[ops.upgrade]\nref = "main"\n')


def _app_table(tmp: Path) -> str:
    key = (tmp / 'github-app.pem').as_posix()
    return (
        f'[ops.judge]\nuser = "forge-judge"\nschedule = "*:0/5"\nrepos = ["{BETA}"]\n'
        f'[ops.judge.apps]\n"github.com" = {{app_id = 5619495, key_file = "{key}"}}\n'
    )


def test_a_github_app_judge_runs_with_the_app_credential(tmp_path: Path) -> None:
    host = _config(tmp_path, _app_table(tmp_path))
    assert judge.command(host, BETA)[-4:] == [
        '--app-id', '5619495', '--app-key-file', (tmp_path / 'github-app.pem').as_posix(),
    ]  # fmt: skip


def test_install_hands_the_app_key_to_the_judge_and_gives_it_a_home(tmp_path: Path) -> None:
    host = _config(tmp_path, _app_table(tmp_path))
    done = install(host, tmp_path / 'root')
    service = (tmp_path / 'root' / 'etc/systemd/system/dev-lab-ops-judge.service').read_text(encoding='utf-8')
    assert 'Environment=HOME=/var/lib/forge-judge\n' in service
    assert 'EnvironmentFile' not in service  # the model key lives in the HOME's credential store, never a unit file
    assert any(step.startswith('chown forge-judge ') and 'github-app.pem' in step for step in done.next_steps)
    assert any('--create-home --home-dir /var/lib/forge-judge forge-judge' in step for step in done.next_steps)
    assert any('credential.helper store' in step for step in done.next_steps)


def test_install_names_the_remedy_when_the_judge_cannot_enter_its_keys_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The deployed fault: the key 600 forge-judge's, its directory root:root 700; the remedy is named, not applied.

    Install never opens a directory it did not make. PLANTED CONTROL: an enterable directory gets no such step.
    """
    host = _config(tmp_path, _app_table(tmp_path))
    root = tmp_path / 'root'
    keys = root / tmp_path.relative_to(tmp_path.anchor)
    keys.mkdir(parents=True)
    (keys / 'github-app.pem').write_text('k', encoding='utf-8')
    where = tmp_path.as_posix()
    remedy = f'forge-judge cannot enter {where}: chown root:forge-judge {where} && chmod 750 {where}'
    for enters, named in ((False, True), (True, False)):
        monkeypatch.setattr(install_module, '_may_enter', lambda path, _user, enters=enters: enters or path != keys)
        steps = install(host, root, chown=lambda *_: None).next_steps
        assert any(step.startswith(remedy) for step in steps) is named


@pytest.mark.parametrize(
    ('apps', 'tokens', 'why'),
    [
        ('"github.com" = {app_id = 1, key_file = "k"}\n', '"github.com" = "t"\n', 'both a token and an app'),
        ('"github.com" = {app_id = true, key_file = "k"}\n', '', 'must be'),
        ('"github.com" = {app_id = 1}\n', '', 'must be'),
        ('"github.com" = {app_id = 1, key_file = "k", slug = "x"}\n', '', 'must be'),
        ('"gitea.example" = {app_id = 1, key_file = "k"}\n', '"github.com" = "t"\n', 'serves no repo in'),
    ],
)
def test_an_app_declaration_that_lies_is_refused(tmp_path: Path, apps: str, tokens: str, why: str) -> None:
    table = (
        f'[ops.judge]\nuser = "judge"\nschedule = "*:0/5"\nrepos = ["{BETA}"]\n'
        f'[ops.judge.tokens]\n{tokens}[ops.judge.apps]\n{apps}'
    )
    with pytest.raises(ValueError, match=why):
        _config(tmp_path, table)
