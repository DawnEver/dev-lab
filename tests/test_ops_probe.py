"""The forge probe: protection drift and failed CI runs on either forge, each alerted ONCE, through ``[alerts]``.

The forges are in-memory fakes (:mod:`_protect_fakes`); the evidence is the alerts the role sent and what it kept.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest
from _protect_fakes import GITEA_TEXT, GITHUB_TEXT, FakeGitea, FakeGitHub

from dev_lab.dev.forge import forge_of_url
from dev_lab.dev.forgeprotect import apply, targets
from dev_lab.ops import install
from dev_lab.ops.config import OpsConfig, load
from dev_lab.ops.probe import run

HUB = 'https://github.com/owner/alpha.git'
TEA = 'https://gitea.example/owner/alpha.git'


def _config(tmp: Path, repos: tuple[str, ...] = (HUB, TEA), tokens: str = '') -> OpsConfig:
    listed = ', '.join(f'"{url}"' for url in repos)
    tokens = tokens or ''.join(f'"{forge_of_url(url).host}" = "{(tmp / "token").as_posix()}"\n' for url in repos)
    path = tmp / 'supervise.toml'
    path.write_text(
        f'[ops]\nhome = "{(tmp / "home").as_posix()}"\npython = "/opt/ops/bin/python"\nrepos = []\n'
        f'[ops.probe]\nuser = "probe"\nschedule = "*:0/15"\nstate = "{(tmp / "state").as_posix()}"\n'
        f'repos = [{listed}]\n[ops.probe.tokens]\n{tokens}',
        encoding='utf-8',
    )
    return load(path, environ={})


def _declared(fake: FakeGitHub | FakeGitea, text: str, url: str) -> None:
    """*fake* holds *text* on both branches and its protection exactly as declared."""
    fake.manifest = {'main': text, 'integrate/main': text}
    forge = forge_of_url(url)
    apply(fake, forge, targets(text, 'p', forge))
    fake.writes.clear()


def _run(number: int, conclusion: str, *, event: str = 'schedule', path: str = 'ci.yml') -> dict[str, object]:
    return {'id': number, 'event': event, 'path': path, 'conclusion': conclusion, 'status': 'completed',
            'branch': 'integrate/main', 'head_sha': f'{number:040d}', 'html_url': f'https://runs/{number}'}  # fmt: skip


@dataclass
class Host:
    config: OpsConfig
    hub: FakeGitHub = field(default_factory=FakeGitHub)
    tea: FakeGitea = field(default_factory=FakeGitea)
    alerts: list[tuple[str, str]] = field(default_factory=list)
    delivers: bool = True

    def tick(self) -> list[str]:
        return run(self.config, lambda url: self.hub if url == HUB else self.tea, self._alert)

    def _alert(self, title: str, detail: str) -> bool:
        self.alerts.append((title, detail))
        return self.delivers

    def titles(self) -> list[str]:
        return [title for title, _ in self.alerts]


@pytest.fixture
def host(tmp_path: Path) -> Host:
    made = Host(_config(tmp_path))
    _declared(made.hub, GITHUB_TEXT, HUB)
    _declared(made.tea, GITEA_TEXT, TEA)
    return made


def test_a_clean_forge_pair_alerts_nothing_and_writes_nothing(host: Host) -> None:
    host.hub.runs = [_run(1, 'success')]
    assert host.tick() == []
    assert host.alerts == []
    assert host.hub.writes == host.tea.writes == []  # the probe only reads


def test_drift_alerts_once_while_it_stands_again_when_it_changes_and_clears(host: Host) -> None:
    host.tea.protections['main']['block_admin_merge_override'] = False
    assert host.tick() == ['alerted gitea.example/owner/alpha|protection']
    assert 'block_admin_merge_override: live=False declared=True' in host.alerts[0][1]
    assert host.tick() == []  # still standing: no second alert
    host.tea.protections['main']['enable_force_push'] = True
    assert host.tick() == ['alerted gitea.example/owner/alpha|protection']  # a different drift is new
    _declared(host.tea, GITEA_TEXT, TEA)
    assert host.tick() == ['cleared gitea.example/owner/alpha|protection']
    assert len(host.alerts) == 2


def test_a_ruleset_deleted_by_hand_on_github_is_drift(host: Host) -> None:
    """PLANTED: the gap-3 state -- no ruleset at all -- must never read as clean."""
    host.hub.rulesets.clear()
    host.tick()
    assert host.titles() == ['protection drift: github.com/owner/alpha (run `forge protect apply` as an administrator)']


def test_a_failing_nightly_alerts_once_until_it_passes_and_then_again(host: Host) -> None:
    host.hub.runs = [_run(1, 'failure')]
    assert host.tick() == ['alerted github.com/owner/alpha|run|schedule|ci.yml']
    assert 'concluded failure: https://runs/1' in host.alerts[0][1]
    host.hub.runs.append(_run(2, 'failure'))
    assert host.tick() == []  # failing still: one alert per new failure, not per run
    host.hub.runs.append(_run(3, 'success'))
    assert host.tick() == ['cleared github.com/owner/alpha|run|schedule|ci.yml']
    host.hub.runs.append(_run(4, 'timed_out'))
    assert host.tick() == ['alerted github.com/owner/alpha|run|schedule|ci.yml']


def test_only_the_latest_run_of_each_workflow_counts(host: Host) -> None:
    host.tea.runs = [_run(5, 'failure', path='promote.yml'), _run(6, 'success', path='promote.yml'),
                     _run(7, 'cancelled', path='merge.yml')]  # fmt: skip
    assert host.tick() == []


def test_an_integration_push_run_failure_alerts_and_another_branch_does_not(host: Host) -> None:
    other = _run(8, 'failure', event='push') | {'branch': 'pr/x'}
    host.tea.runs = [other, _run(9, 'startup_failure', event='push', path='merge.yml')]
    assert host.tick() == ['alerted gitea.example/owner/alpha|run|push|merge.yml']


def test_an_undelivered_alert_is_not_recorded_and_is_sent_again(host: Host) -> None:
    host.hub.runs = [_run(1, 'failure')]
    host.delivers = False
    assert host.tick() == ['UNDELIVERED github.com/owner/alpha|run|schedule|ci.yml']
    host.delivers = True
    assert host.tick() == ['alerted github.com/owner/alpha|run|schedule|ci.yml']


def test_a_forge_the_probe_cannot_read_is_a_finding_alerted_once(host: Host) -> None:
    """PLANTED: an unreachable forge (or a declaration it cannot serve) is never a quiet, clean probe."""
    host.hub.down = True
    host.tea.manifest = {}
    host.tick()
    assert sorted(host.titles()) == ['probe cannot read gitea.example/owner/alpha',
                                     'probe cannot read github.com/owner/alpha']  # fmt: skip
    assert host.tick() == []


def test_a_probe_with_a_forge_and_no_token_is_refused_at_load(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match='names no token'):
        _config(tmp_path, tokens=f'"github.com" = "{(tmp_path / "t").as_posix()}"\n')


def test_install_renders_the_probe_timer_as_its_user(tmp_path: Path) -> None:
    config = _config(tmp_path)
    rendered = install.files(config)
    service = rendered['etc/systemd/system/dev-lab-ops-probe.service']
    assert 'User=probe' in service
    assert service.rstrip().endswith('Nice=10')
    assert ' probe' in next(line for line in service.splitlines() if line.startswith('ExecStart='))
    assert 'OnCalendar=*:0/15' in rendered['etc/systemd/system/dev-lab-ops-probe.timer']
    assert 'systemctl enable --now dev-lab-ops-probe.timer' in install.install(config, tmp_path / 'root').next_steps
