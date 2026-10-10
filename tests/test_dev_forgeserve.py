"""THE HARNESS ENTRY: tick, produce, publish, route in one call -- and a contract break fails loudly."""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from lab_commons.dev import forgeserve
from lab_commons.dev.forgetick import TickReport, Work
from lab_commons.hpc.records import write_record

SHA = 'a' * 40


def _record(sha: str) -> dict[str, object]:
    return {'sha': sha, 'platform': 'linux', 'scope': 'full', 'req': 't0', 'outcomes': {'t::a': 'failed'}, 'handed': {}}


def _serve(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, claimed: tuple[Work, ...], codes: dict[str, int]
) -> tuple[forgeserve.ServeReport, list[list[str]]]:
    calls: list[list[str]] = []
    monkeypatch.setattr(forgeserve, 'tick', lambda *_a, **_k: TickReport((), claimed, ('tick: one line',)))
    monkeypatch.setattr(forgeserve, 'flush', lambda _root, **_k: ['status: tests/linux=failure'])
    monkeypatch.setattr(forgeserve, 'pyproject_at', lambda _root, _sha: '')
    monkeypatch.setattr(
        forgeserve,
        'route',
        lambda _client, _record, _areas: (SimpleNamespace(area='core', action='created', number=7),),
    )

    def run(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, codes[argv[0]])

    report = forgeserve.serve(
        tmp_path, 'integrate', client=lambda _r: None, now=datetime.now(UTC), machine='G', grants=(), run=run
    )
    return report, calls


def test_every_claimed_part_is_produced_then_published_then_its_records_routed(monkeypatch, tmp_path: Path) -> None:
    out = tmp_path / 'parts'
    write_record(_record(SHA), out)
    cluster = Work('integrate/main', SHA, 'linux', 'mine', argv=('cluster', '--sha', SHA, '-o', str(out)))
    local = Work('integrate/main', SHA, 'windows', 'mine', argv=('verify',))
    report, calls = _serve(monkeypatch, tmp_path, (cluster, local), {'cluster': 0, 'verify': 1})
    assert calls == [list(cluster.argv), list(local.argv)]
    assert [(p.platform, p.returncode, p.routed) for p in report.produced] == [
        ('linux', 0, ('core created #7',)),
        ('windows', 1, ()),
    ], 'a red local part is a posted FAIL part, not a harness failure; only the cluster wrote a record'
    assert report.published == ('status: tests/linux=failure',)
    assert report.broken == ()


def test_a_producer_refusing_its_argv_is_a_broken_contract_not_a_skip(monkeypatch, tmp_path: Path) -> None:
    """PLANTED: a renamed flag makes argparse exit 2; that must surface as a failure with the argv shown."""
    stale = Work('integrate/main', SHA, 'linux', 'mine', argv=('cluster', '--install', 'x'))
    report, _calls = _serve(monkeypatch, tmp_path, (stale,), {'cluster': forgeserve.USAGE_ERROR})
    assert len(report.broken) == 1
    assert 'cluster --install x' in report.broken[0]


def test_the_cli_exits_two_on_a_broken_contract(monkeypatch, tmp_path: Path, capsys) -> None:
    broken = forgeserve.ServeReport((), (), (), ('linux aaaa: the producer refused its argv: cluster --x',))
    monkeypatch.setattr(forgeserve, 'serve', lambda *_a, **_k: broken)
    assert forgeserve.main(['--mode', 'integrate'], cwd=tmp_path) == forgeserve.USAGE_ERROR
    assert 'CONTRACT BROKEN' in capsys.readouterr().err
    with pytest.raises(SystemExit):
        forgeserve.main(['--mode', 'nonsense'], cwd=tmp_path)
