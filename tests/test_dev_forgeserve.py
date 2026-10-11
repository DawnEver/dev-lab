"""THE HARNESS ENTRY: tick, produce, publish, route in one call -- and a contract break fails loudly."""

from __future__ import annotations

import dataclasses
import subprocess
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from lab_commons.dev import forgeserve
from lab_commons.dev.forgetick import Claim, TickReport, Work
from lab_commons.dev.producer import RETRYABLE, ProducerExit, release_reason
from lab_commons.hpc.records import write_record

SHA = 'a' * 40
NOW = datetime(2026, 10, 11, 12, tzinfo=UTC)
ME = Claim('G', 'alice', NOW + timedelta(hours=6))
GRANT = dataclasses.replace(ME, hpc='alice:acct42')


def _record(sha: str) -> dict[str, object]:
    return {'sha': sha, 'platform': 'linux', 'scope': 'full', 'req': 't0', 'outcomes': {'t::a': 'failed'}, 'handed': {}}


class _Proc:
    """A fake producer: prints *lines*, outlives *beats* heartbeats, exits *code*; meets *barrier* first."""

    def __init__(self, code: int, lines: tuple[str, ...] = (), beats: int = 0, barrier=None) -> None:
        self.code, self.beats, self.barrier = code, beats, barrier
        self.stdout = iter(f'{line}\n' for line in lines)

    def wait(self, timeout: float | None = None) -> int:
        if self.barrier is not None:
            self.barrier.wait(timeout=5)  # breaks unless every producer is alive at once
            self.barrier = None
        if self.beats:
            self.beats -= 1
            cmd = 'fake'
            raise subprocess.TimeoutExpired(cmd, timeout or 0)
        return self.code

    def kill(self) -> None:
        self.beats = 0


class _Forge:
    """Records every status post; a part's producer may post its own verdict through *settles*."""

    def __init__(self) -> None:
        self.posts: list[tuple[str, str, str]] = []

    def post(self, _client, sha, *, context, state, description) -> None:
        self.posts.append((context, state, description))

    def history(self, _client, sha) -> tuple[SimpleNamespace, ...]:
        return tuple(SimpleNamespace(context=c, state=s, description=d) for c, s, d in self.posts)


def _serve(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    claimed: tuple[Work, ...],
    procs: dict[str, _Proc],
    forge: _Forge | None = None,
) -> tuple[forgeserve.ServeReport, list[list[str]], list[str]]:
    calls: list[list[str]] = []
    said: list[str] = []
    forge = forge or _Forge()
    monkeypatch.setattr(forgeserve, 'tick', lambda *_a, **_k: TickReport((), claimed, ('tick: one line',)))
    monkeypatch.setattr(forgeserve, 'flush', lambda _root, **_k: ['status: tests/linux=failure'])
    monkeypatch.setattr(forgeserve, 'pyproject_at', lambda _root, _sha: '')
    monkeypatch.setattr(forgeserve, 'status_post', forge.post)
    monkeypatch.setattr(forgeserve, 'status_history', forge.history)
    monkeypatch.setattr(
        forgeserve,
        'route',
        lambda _client, _record, _areas: (SimpleNamespace(area='core', action='created', number=7),),
    )

    def spawn(argv: list[str], **_kwargs: object) -> _Proc:
        calls.append(argv)
        return procs[argv[0]]

    report = forgeserve.serve(
        tmp_path,
        'integrate',
        client=lambda _r: None,
        now=NOW,
        machine='G',
        grants=(),
        spawn=spawn,
        clock=lambda: NOW,
        say=said.append,
        renew_s=0.01,
    )
    return report, calls, said


def test_every_claimed_part_is_produced_then_published_then_its_records_routed(monkeypatch, tmp_path: Path) -> None:
    out = tmp_path / 'parts'
    write_record(_record(SHA), out)
    cluster = Work('integrate/main', SHA, 'linux', 'mine', argv=('cluster', '--sha', SHA, '-o', str(out)))
    local = Work('integrate/main', SHA, 'windows', 'mine', argv=('verify',))
    report, calls, _said = _serve(monkeypatch, tmp_path, (cluster, local), {'cluster': _Proc(0), 'verify': _Proc(1)})
    assert sorted(calls) == sorted([list(cluster.argv), list(local.argv)])
    assert [(p.platform, p.returncode, p.routed) for p in report.produced] == [
        ('linux', 0, ('core created #7',)),
        ('windows', 1, ()),
    ], 'a red local part is a posted FAIL part, not a harness failure; only the cluster wrote a record'
    assert report.published == ('status: tests/linux=failure',)
    assert report.broken == ()


def test_a_producer_refusing_its_argv_is_a_broken_contract_not_a_skip(monkeypatch, tmp_path: Path) -> None:
    """PLANTED: a renamed flag makes argparse exit 2; that must surface as a failure with the argv shown."""
    stale = Work('integrate/main', SHA, 'linux', 'mine', argv=('cluster', '--install', 'x'))
    report, _calls, _said = _serve(monkeypatch, tmp_path, (stale,), {'cluster': _Proc(ProducerExit.USAGE)})
    assert len(report.broken) == 1
    assert 'cluster --install x' in report.broken[0]


def test_the_cli_exits_two_on_a_broken_contract(monkeypatch, tmp_path: Path, capsys) -> None:
    broken = forgeserve.ServeReport((), (), (), ('linux aaaa: the producer refused its argv: cluster --x',))
    monkeypatch.setattr(forgeserve, 'serve', lambda *_a, **_k: broken)
    assert forgeserve.main(['--mode', 'integrate'], cwd=tmp_path) == ProducerExit.USAGE
    assert 'CONTRACT BROKEN' in capsys.readouterr().err
    with pytest.raises(SystemExit):
        forgeserve.main(['--mode', 'nonsense'], cwd=tmp_path)


def test_parts_on_different_seats_start_concurrently(monkeypatch, tmp_path: Path) -> None:
    """PLANTED: both fakes wait on one barrier; run in turn, the first waits alone and the barrier breaks."""
    meet = threading.Barrier(2)
    cluster = Work('integrate/main', SHA, 'linux', 'mine', holder=GRANT, argv=('cluster',))
    local = Work('integrate/main', SHA, 'windows', 'mine', holder=ME, argv=('verify',))
    procs = {'cluster': _Proc(0, barrier=meet), 'verify': _Proc(0, barrier=meet)}
    report, _calls, _said = _serve(monkeypatch, tmp_path, (local, cluster), procs)
    assert not meet.broken
    assert [p.platform for p in report.produced] == ['windows', 'linux'], 'the report keeps the claim order'


def test_parts_on_one_seat_run_in_turn() -> None:
    a = Work('r', SHA, 'windows', 'mine', holder=ME)
    b = Work('r', SHA, 'linux', 'mine', holder=GRANT)
    assert forgeserve._seat(a) == 'local'
    assert forgeserve._seat(b) == 'hpc:alice:acct42'
    assert forgeserve._seat(dataclasses.replace(b, holder=ME)) == 'local'


def test_output_streams_prefixed_by_platform(monkeypatch, tmp_path: Path) -> None:
    local = Work('integrate/main', SHA, 'windows', 'mine', holder=ME, argv=('verify',))
    _report, _calls, said = _serve(monkeypatch, tmp_path, (local,), {'verify': _Proc(0, ('collected 9',))})
    assert 'tick: one line' in said
    assert '[windows] collected 9' in said


def test_a_live_producer_renews_its_claim(monkeypatch, tmp_path: Path) -> None:
    forge = _Forge()
    local = Work('integrate/main', SHA, 'windows', 'mine', holder=ME, argv=('verify',))
    _serve(monkeypatch, tmp_path, (local,), {'verify': _Proc(0, beats=2)}, forge)
    renewed = [d for c, s, d in forge.posts if c == 'tests/windows' and s == 'pending']
    assert len(renewed) == 2
    assert Claim.parse(renewed[0]) == dataclasses.replace(ME, until=NOW + forgeserve.DEFAULT_LEASE)


def test_a_crashed_producer_releases_its_claim(monkeypatch, tmp_path: Path) -> None:
    """PLANTED: the producer dies without posting; its pending claim must not be left to age out."""
    forge = _Forge()
    local = Work('integrate/main', SHA, 'windows', 'mine', holder=ME, argv=('verify',))
    forge.post(None, SHA, context='tests/windows', state='pending', description=ME.description())
    _serve(monkeypatch, tmp_path, (local,), {'verify': _Proc(-9)}, forge)
    assert forge.posts[-1] == ('tests/windows', 'error', 'released: producer crashed (exit -9)')


def test_a_producer_that_posted_its_part_is_left_alone(monkeypatch, tmp_path: Path) -> None:
    forge = _Forge()
    forge.post(None, SHA, context='tests/windows', state='failure', description='FAIL')
    local = Work('integrate/main', SHA, 'windows', 'mine', holder=ME, argv=('verify',))
    _serve(monkeypatch, tmp_path, (local,), {'verify': _Proc(1)}, forge)
    assert forge.posts == [('tests/windows', 'failure', 'FAIL')]


def test_an_inconclusive_producer_is_released_not_called_a_broken_contract(monkeypatch, tmp_path: Path) -> None:
    """PLANTED (live 2026-10-11): a runner over its wall said INCONCLUSIVE; serve said "refused its argv"."""
    forge = _Forge()
    forge.post(None, SHA, context='tests/windows', state='pending', description=ME.description())
    local = Work('integrate/main', SHA, 'windows', 'mine', holder=ME, argv=('verify',))
    procs = {'verify': _Proc(ProducerExit.INCONCLUSIVE)}
    report, _calls, _said = _serve(monkeypatch, tmp_path, (local,), procs, forge)
    assert report.broken == ()
    assert forge.posts[-1] == ('tests/windows', 'error', release_reason(ProducerExit.INCONCLUSIVE))


def test_unreachable_infrastructure_releases_the_claim_as_retryable_not_red(monkeypatch, tmp_path: Path) -> None:
    forge = _Forge()
    forge.post(None, SHA, context='tests/linux', state='pending', description=GRANT.description())
    cluster = Work('integrate/main', SHA, 'linux', 'mine', holder=GRANT, argv=('cluster',))
    procs = {'cluster': _Proc(ProducerExit.UNREACHABLE)}
    report, _calls, _said = _serve(monkeypatch, tmp_path, (cluster,), procs, forge)
    assert report.broken == ()
    context, state, description = forge.posts[-1]
    assert (context, state) == ('tests/linux', 'error')
    assert description.startswith(RETRYABLE)
    assert not any(s == 'failure' for _c, s, _d in forge.posts), 'an outage is never a red part'
