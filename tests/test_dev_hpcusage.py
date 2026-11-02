"""An HPC account's last day: the one sacct read's parse, its one call per tick, and the host card's table."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from lab_commons.hpc.slurm import Node, Quota, Snapshot

from dev_lab.dev import forgeslurm, hpcusage
from dev_lab.dev.forgehosts import HostCard

#: Recorded shape of ``sacct -n -P -o JobID,JobName,State,AllocCPUS,CPUTimeRAW,TotalCPU,ReqMem,MaxRSS``.
SACCT = """\
101|run-0123456789ab-tests|COMPLETED|4|14400|03:30:00|16G|
101.batch|batch|COMPLETED|4|14400|03:30:00||6000M
102|run-0123456789ab-heavy|OUT_OF_MEMORY|8|28800|1-02:00:00|8000M|
102.batch|batch|OUT_OF_MEMORY|8|28800|1-02:00:00||8100000K
103|sweep|TIMEOUT|10|36000|01:00:00|4G|
103.batch|batch|CANCELLED|10|36000|01:00:00||1G
104|sweep|CANCELLED by 42|2|7200|00:00:00|4G|
105|lab|RUNNING|16|57600|00:00:00|32G|
106|oom-nostep|FAILED|1|3600|59:30.500|2G|
106.0|python|OUT_OF_MEMORY|1|3600|59:30.500||
107|run-fedcba987654-base|COMPLETED|1|3600|01:00:00|1G|
"""
ALLOC = 14400 + 28800 + 36000 + 7200 + 57600 + 3600 + 3600


def _summary(text: str = SACCT) -> dict[str, Any]:
    return hpcusage.parse(text).summary()


def test_the_day_counts_jobs_core_hours_states_and_the_forge_share() -> None:
    summary = _summary()
    assert summary['jobs'] == 7
    assert summary['core_hours'] == pytest.approx(ALLOC / 3600, abs=1e-3)
    assert summary['states'] == {
        'COMPLETED': 2, 'FAILED': 0, 'CANCELLED': 1, 'OUT_OF_MEMORY': 2, 'TIMEOUT': 1, 'RUNNING': 1,
    }  # fmt: skip
    assert summary['forge_share'] == pytest.approx((14400 + 28800 + 3600) / ALLOC, abs=1e-4)


def test_core_hours_per_run_are_what_the_budget_binds() -> None:
    """Every part of a sha is that sha's use; PLANTED CONTROL: a job not named ``run-<sha12>-`` is no run's."""
    assert hpcusage.parse(SACCT).per_run() == {'0123456789ab': 12.0, 'fedcba987654': 1.0}


def test_efficiency_reads_a_day_prefixed_totalcpu_and_skips_running_jobs() -> None:
    """``1-02:00:00`` is 26 h; the RUNNING job's zero TotalCPU is not counted as waste."""
    used = 3.5 * 3600 + 26 * 3600 + 3600 + 0 + 3570.5 + 3600
    assert _summary()['cpu_efficiency'] == pytest.approx(used / (ALLOC - 57600), abs=1e-4)
    assert _summary('105|lab|RUNNING|16|57600|00:00:00|32G|\n')['cpu_efficiency'] is None


def test_the_least_efficient_finished_jobs_rank_by_wasted_core_hours() -> None:
    top = _summary()['top_inefficient']
    assert [one['job'] for one in top] == ['103', '104', '101', '106', '102']
    assert top[0] == {'job': '103', 'name': 'sweep', 'cores': 10, 'cpu_eff': 0.1, 'core_h': 10.0}


def test_an_oom_or_timeout_job_takes_its_steps_state_and_an_oom_carries_ask_and_maxrss() -> None:
    """TIMEOUT on the job row stays; OUT_OF_MEMORY on a step overrides the row's FAILED."""
    assert _summary()['oom'] == [
        {'job': '102', 'name': 'run-0123456789ab-heavy', 'req_mem_mb': 8000, 'max_rss_mb': round(8100000 / 1024)},
        {'job': '106', 'name': 'oom-nostep', 'req_mem_mb': 2048, 'max_rss_mb': None},
    ]


def _snapshot() -> Snapshot:
    quota = Quota(account='a', cpus=64, mem_mb=None, gpus=None, default_qos='q', qos_max_submit={}, queued={})
    return Snapshot(nodes=(Node('n1', ('defq',), 64, 65536, 0, schedulable=True),), partitions={}, quota=quota)


def test_a_tick_reads_sacct_once_for_both_the_budget_and_the_card(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    def shell(command: str, *_rest: object) -> str:
        calls.append(command)
        return SACCT if command.startswith('sacct') else ''

    monkeypatch.setattr(forgeslurm, 'probe', lambda *_a: _snapshot())
    machine: Any = SimpleNamespace(grants=[SimpleNamespace(user='alice', slurm_account='a')])
    cluster = forgeslurm.SlurmCluster(tmp_path, machine, cast('Any', None), lambda _g: shell, lambda: None)
    standing = cluster.standing()
    assert [c for c in calls if c.startswith('sacct')] == [hpcusage.COMMAND]
    assert standing.usage == {'0123456789ab': 12.0, 'fedcba987654': 1.0}
    assert standing.facts['usage'] == _summary()


def test_the_card_renders_the_table_with_values_escaped() -> None:
    summary = _summary()
    summary['oom'][1]['name'] = 'x|<img src=y>`*z*`'  # a job name is the submitter's free text
    card = HostCard('ada/alice', 'bot', 'linux', '2026-11-02T10:00:00+00:00', facts={'usage': summary})
    text = card.text().split('```json')[0]
    assert 'last 24 h | jobs | core-h | CPU eff | forge share | states' in text
    assert 'COMPLETED 2, CANCELLED 1, OUT\\_OF\\_MEMORY 2, TIMEOUT 1, RUNNING 1' in text
    assert '106 | x\\|&lt;img src=y&gt;\\`\\*z\\*\\` | 2048 | n/a' in text
    assert '<img' not in text
    plain = HostCard('ada/alice', 'bot', 'linux', '2026-11-02T10:00:00+00:00').text()
    assert 'last 24 h' not in plain, 'PLANTED CONTROL: a card with no usage carries no table'
