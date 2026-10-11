"""THE HARNESS ENTRY: tick, produce or advance, publish -- a contract break fails loudly, a silent failure alarms."""

from __future__ import annotations

import dataclasses
import subprocess
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from lab_commons.config import CONFIG_ENV
from lab_commons.dev import forgerun, forgeserve
from lab_commons.dev.forgealarm import AUTH, IDLE, RUN
from lab_commons.dev.forgetick import OPEN, Claim, TickReport, Work
from lab_commons.dev.forgework import ForgeCallFailed
from lab_commons.dev.netverb import Attempt, Diagnosis, Report
from lab_commons.dev.platformparts import ClusterPart
from lab_commons.dev.producer import RETRYABLE, ProducerExit, release_reason
from lab_commons.hpc.account import ClusterAccount

SHA = 'a' * 40
NOW = datetime(2026, 10, 11, 12, tzinfo=UTC)
FORGE_NOW = NOW + timedelta(minutes=7)  # the forge's clock, deliberately not the host's
ME = Claim('G', 'alice', NOW + timedelta(hours=6))
SEAT = ClusterAccount('ada', 'alice')


class _Proc:
    """A fake producer: prints *lines*, outlives *beats* heartbeats, exits *code*."""

    def __init__(self, code: int, lines: tuple[str, ...] = (), beats: int = 0) -> None:
        self.code, self.beats = code, beats
        self.stdout = iter(f'{line}\n' for line in lines)

    def wait(self, timeout: float | None = None) -> int:
        if self.beats:
            self.beats -= 1
            cmd = 'fake'
            raise subprocess.TimeoutExpired(cmd, timeout or 0)
        return self.code

    def kill(self) -> None:
        self.beats = 0


class _Forge:
    """Records every status post; a part's producer may post its own verdict."""

    def __init__(self) -> None:
        self.posts: list[tuple[str, str, str]] = []

    def post(self, _client, _sha, *, context, state, description) -> None:
        self.posts.append((context, state, description))

    def history(self, _client, _sha) -> tuple[SimpleNamespace, ...]:
        return tuple(SimpleNamespace(context=c, state=s, description=d) for c, s, d in self.posts)


def _client(_root: Path) -> SimpleNamespace:
    return SimpleNamespace(answered=format_datetime(FORGE_NOW, usegmt=True), whoami=lambda: 'alice')


def _serve(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    ticked: TickReport,
    procs: dict[str, _Proc] | None = None,
    forge: _Forge | None = None,
    *,
    seat: ClusterAccount | None = None,
    cluster=lambda: None,
) -> tuple[forgeserve.ServeReport, list[str], list]:
    said: list[str] = []
    alarms: list = []
    forge = forge or _Forge()
    seen: dict[str, object] = {}

    def tick(*_a: object, **kwargs: object) -> TickReport:
        seen.update(kwargs)
        return ticked

    monkeypatch.setenv(CONFIG_ENV, str(tmp_path / 'home' / 'config.toml'))
    monkeypatch.setattr(forgeserve, 'tick', tick)
    monkeypatch.setattr(forgeserve, 'origin_url', lambda _root: 'https://f/o/r.git')
    monkeypatch.setattr(forgeserve, 'flush', lambda _root, **_k: ['status: tests/windows=failure'])
    monkeypatch.setattr(forgeserve, 'status_post', forge.post)
    monkeypatch.setattr(forgeserve, 'status_history', forge.history)
    report = forgeserve.serve(
        tmp_path,
        'integrate',
        client=_client,
        machine='G',
        seat=seat,
        cluster=cluster,
        spawn=lambda argv, **_k: (procs or {})[argv[0]],
        clock=lambda: NOW,
        say=said.append,
        alarm=alarms.append,
        renew_s=0.01,
    )
    said.append(f'in_flight={seen.get("in_flight")}')
    return report, said, alarms


def _claimed(*work: Work) -> TickReport:
    return TickReport(work, work, ('tick: one line',))


def test_a_claimed_local_part_is_produced_inline_and_published(monkeypatch, tmp_path: Path) -> None:
    local = Work('integrate/main', SHA, 'windows', 'mine', ME, argv=('verify',))
    report, said, _alarms = _serve(monkeypatch, tmp_path, _claimed(local), {'verify': _Proc(1, ('collected 9',))})
    assert [(p.platform, p.returncode) for p in report.produced] == [('windows', 1)], 'a red part is not a failure'
    assert report.published == ('status: tests/windows=failure',)
    assert report.broken == ()
    assert 'tick: one line' in said
    assert '[windows] collected 9' in said


def test_a_producer_refusing_its_argv_is_a_broken_contract_not_a_skip(monkeypatch, tmp_path: Path) -> None:
    """PLANTED: a renamed flag makes argparse exit 2; that must surface as a failure with the argv shown."""
    stale = Work('integrate/main', SHA, 'windows', 'mine', ME, argv=('verify', '--install', 'x'))
    report, _said, _alarms = _serve(monkeypatch, tmp_path, _claimed(stale), {'verify': _Proc(ProducerExit.USAGE)})
    assert len(report.broken) == 1
    assert 'verify --install x' in report.broken[0]


def test_the_cli_exits_two_on_a_broken_contract(monkeypatch, tmp_path: Path, capsys) -> None:
    broken = forgeserve.ServeReport((), (), (), (), ('windows aaaa: the producer refused its argv: verify --x',))
    monkeypatch.setattr(forgeserve, 'serve', lambda *_a, **_k: broken)
    assert forgeserve.main(['--mode', 'integrate'], cwd=tmp_path, seat_of=lambda: None) == ProducerExit.USAGE
    assert 'CONTRACT BROKEN' in capsys.readouterr().err
    with pytest.raises(SystemExit):
        forgeserve.main(['--mode', 'nonsense'], cwd=tmp_path)


def test_a_live_local_producer_renews_its_claim_on_the_forges_clock(monkeypatch, tmp_path: Path) -> None:
    forge = _Forge()
    local = Work('integrate/main', SHA, 'windows', 'mine', ME, argv=('verify',))
    _serve(monkeypatch, tmp_path, _claimed(local), {'verify': _Proc(0, beats=2)}, forge)
    renewed = [d for c, s, d in forge.posts if c == 'tests/windows' and s == 'pending']
    assert len(renewed) == 2
    assert Claim.parse(renewed[0]) == dataclasses.replace(ME, until=FORGE_NOW + forgeserve.DEFAULT_LEASE)


def test_a_crashed_producer_releases_its_claim(monkeypatch, tmp_path: Path) -> None:
    """PLANTED: the producer dies without posting; its pending claim must not be left to age out."""
    forge = _Forge()
    forge.post(None, SHA, context='tests/windows', state='pending', description=ME.description())
    local = Work('integrate/main', SHA, 'windows', 'mine', ME, argv=('verify',))
    _serve(monkeypatch, tmp_path, _claimed(local), {'verify': _Proc(-9)}, forge)
    assert forge.posts[-1] == ('tests/windows', 'error', 'released: producer crashed (exit -9)')


def test_a_producer_that_posted_its_part_is_left_alone(monkeypatch, tmp_path: Path) -> None:
    forge = _Forge()
    forge.post(None, SHA, context='tests/windows', state='failure', description='FAIL')
    local = Work('integrate/main', SHA, 'windows', 'mine', ME, argv=('verify',))
    _serve(monkeypatch, tmp_path, _claimed(local), {'verify': _Proc(1)}, forge)
    assert forge.posts == [('tests/windows', 'failure', 'FAIL')]


def test_inconclusive_and_unreachable_producers_are_released_never_red(monkeypatch, tmp_path: Path) -> None:
    """PLANTED (live 2026-10-11): a runner over its wall said INCONCLUSIVE; serve said "refused its argv"."""
    for code, reason in (
        (ProducerExit.INCONCLUSIVE, release_reason(ProducerExit.INCONCLUSIVE)),
        (ProducerExit.UNREACHABLE, RETRYABLE),
    ):
        forge = _Forge()
        forge.post(None, SHA, context='tests/windows', state='pending', description=ME.description())
        local = Work('integrate/main', SHA, 'windows', 'mine', ME, argv=('verify',))
        report, _said, _alarms = _serve(monkeypatch, tmp_path, _claimed(local), {'verify': _Proc(code)}, forge)
        assert report.broken == ()
        assert forge.posts[-1][1] == 'error'
        assert forge.posts[-1][2].startswith(reason)


def test_a_claimed_cluster_part_starts_a_run_and_is_advanced_never_spawned(monkeypatch, tmp_path: Path) -> None:
    cluster_claim = dataclasses.replace(ME, hpc='ada/alice')
    part = ClusterPart('https://f/o/r.git', 'tests', tmp_path / 'parts')
    work = Work('integrate/main', SHA, 'linux', 'mine', cluster_claim, cluster=part)
    advanced: list[tuple[str, str]] = []

    def advance(_root: Path, run: forgerun.Run, **kwargs: object) -> forgerun.Run:
        me = kwargs['me']
        assert isinstance(me, Claim)
        advanced.append((run.phase, me.hpc))
        return run

    monkeypatch.setattr(forgerun, 'advance', advance)
    report, said, _alarms = _serve(monkeypatch, tmp_path, _claimed(work), seat=SEAT, cluster=lambda: 'slurm')
    assert report.produced == (), 'a cluster part is never a blocking process'
    assert advanced == [(forgerun.CLAIMED_PHASE, 'ada/alice')]
    assert report.in_flight == (SHA,)
    assert 'in_flight=False' in said
    report, said, _alarms = _serve(monkeypatch, tmp_path, TickReport((), (), ()), seat=SEAT, cluster=lambda: 'slurm')
    assert 'in_flight=True' in said, 'the next tick reads the run back from disk and claims nothing more'
    assert len(advanced) == 2


def test_a_run_with_no_cluster_to_advance_on_alarms_and_waits(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv(CONFIG_ENV, str(tmp_path / 'home' / 'config.toml'))
    part = ClusterPart('https://f/o/r.git', 'tests', tmp_path / 'parts')
    forgerun.start(Work('integrate/main', SHA, 'linux', 'mine', ME, cluster=part), ME)

    def no_grant() -> None:
        msg = 'no [[hpc.grant]] has user = "alice"'
        raise ValueError(msg)

    report, _said, alarms = _serve(monkeypatch, tmp_path, TickReport((), (), ()), seat=SEAT, cluster=no_grant)
    assert [a.kind for a in alarms] == [RUN]
    assert report.in_flight == (SHA,)
    assert len(forgerun.live('https://f/o/r.git')) == 1, 'the run is kept for the next tick'


def test_an_account_idle_with_work_pending_alarms(monkeypatch, tmp_path: Path) -> None:
    """PLANTED CONTROL: the same pending request, claimed, raises nothing."""
    pending = Work('integrate/main', SHA, 'windows', OPEN)
    idle = TickReport((pending,), (), ('tick',), ('tests/windows: not claimed -- no produce declared',))
    _report, _said, alarms = _serve(monkeypatch, tmp_path, idle)
    assert [a.kind for a in alarms] == [IDLE]
    assert 'not claimed' in alarms[0].body
    claimed = dataclasses.replace(pending, state='mine', holder=ME, argv=('verify',))
    _report, _said, alarms = _serve(monkeypatch, tmp_path, _claimed(claimed), {'verify': _Proc(0)})
    assert alarms == []


def test_a_refused_credential_alarms_and_still_fails(monkeypatch, tmp_path: Path) -> None:
    refused = Report(('GET', '/api/v1/user'), (Attempt(1, 401, 'unauthorized', Diagnosis.FORGE_REFUSED),), 3)

    def tick(*_a: object, **_k: object) -> TickReport:
        raise ForgeCallFailed(refused)

    monkeypatch.setattr(forgeserve, 'tick', tick)
    monkeypatch.setattr(forgeserve, 'origin_url', lambda _root: 'https://f/o/r.git')
    alarms: list = []
    with pytest.raises(ForgeCallFailed):
        forgeserve.serve(
            tmp_path, 'integrate', client=_client, machine='G', seat=None, cluster=lambda: None, alarm=alarms.append
        )
    assert [a.kind for a in alarms] == [AUTH]
