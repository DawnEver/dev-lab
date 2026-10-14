"""FILES ARE A RESOURCE (user ruling 2026-10-14): the home's file quota is read, admitted against and alarmed on.

The incident: Ada alyyw103's GPFS home sat at files 2,020,000 = its hard limit with 43 GB of 1 TB used, every
write failed ``Disk quota exceeded``, serve kept claiming, and the alarm named neither the limit nor the
1.34 M-file experiment directory the forge does not own. Each refusal below has its PLANTED CONTROL beside it.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from lab_commons.compute import learned
from lab_commons.compute.admission import admit
from lab_commons.compute.model import Job, Supply
from lab_commons.compute.probe import account
from lab_commons.dev import forgeslurm, retention
from lab_commons.dev.diskusage import Usage, consumers, parse_mmlsquota, parse_quota, pressure_text, storage_text
from lab_commons.dev.retention import Doomed, Plan, Policy, apply
from lab_commons.hpc.slurm import Node, Quota, Snapshot

NOW = datetime(2026, 10, 14, 9, tzinfo=UTC)
REPO = 'https://g/files.git'
JOB = Job(REPO, 'a' * 40, 'slurm')
_HEAD = (
    '                         Block Limits                                               |     File Limits\n'
    'Filesystem Fileset    type             KB      quota      limit   in_doubt    grace |    files   quota    '
    'limit in_doubt    grace  Remarks\n'
)
#: The incident, as mmlsquota printed it: files AT the hard limit, in a 7-day grace; blocks 43 GB of 1 TB.
AT_FILE_LIMIT = _HEAD + (
    'dss2fs01   HOME       USR        45088768 1048576000 1101004800        0     none |  2020000 2000000  '
    '2020000        0   7 days \n'
)
#: The PLANTED CONTROL: blocks over quota in their grace (a two-word grace before the bar), files at 25%.
AT_BYTE_LIMIT = _HEAD + (
    'dss2fs01   HOME       USR      1060000000 1048576000 1101004800        0   6 days |   500000 2000000  '
    '2020000        0     none \n'
)


def _snapshot() -> Snapshot:
    quota = Quota(
        account='a', cpus=64, mem_mb=None, gpus=None, default_qos='normal', qos_max_submit={}, queued={},
    )  # fmt: skip
    return Snapshot(nodes=(Node('n1', ('defq',), 64, 65536, 0, schedulable=True),), partitions={}, quota=quota)


def _supply(text: str) -> Supply:
    usage = parse_mmlsquota(text)
    assert usage is not None
    return account('slurm:alyyw103', [(_snapshot(), 'normal')], files=usage.files_left)


def test_a_home_at_its_file_limit_refuses_admission_naming_files_and_the_numbers() -> None:
    demand = learned.cluster_demand(REPO)(frozenset())
    refused = admit(JOB, demand, _supply(AT_FILE_LIMIT))
    assert not refused
    assert refused.lacking == ('files',)
    assert refused.why == 'lacking files (50000 asked, 0 free)'
    assert admit(JOB, demand, _supply(AT_BYTE_LIMIT)), 'PLANTED CONTROL: 1.5 M files of headroom admits'


def test_a_supply_that_states_no_files_refuses_nothing_on_files() -> None:
    """A box, or an account whose quota went unread, lists no ``files``: the prior must not make it unclaimable."""
    demand = learned.cluster_demand(REPO)(frozenset())
    full = _supply(AT_FILE_LIMIT)
    assert admit(JOB, demand, Supply(full.scope, full.resources, full.present - {'files'}))
    assert not admit(JOB, demand, full), 'PLANTED CONTROL: stated at 0, it refuses'


def test_a_measured_file_cost_replaces_the_prior() -> None:
    learned.record_run(REPO, learned.SLURM, (), learned.Run(0.0, 1.0, 1.0, files=1200.0))
    assert learned.cluster_demand(REPO)(frozenset())['files'] == 1200.0
    assert learned.box_demand(REPO, frozenset(), cpu=1, mem_gb=1)['files'] == 0.0, 'a box part has no file quota'


def test_quota_minus_w_is_the_fallback_and_reads_both_limits() -> None:
    text = (
        'Disk quotas for user alyyw103 (uid 1001):\n'
        '     Filesystem  blocks   quota   limit   grace   files   quota   limit   grace\n'
        '      /dev/sdb1  45088768*  41943040  52428800  6days   2020000  2000000  2020000\n'
    )
    assert parse_quota(text) == Usage(45088768 * 1024, 41943040 * 1024, 2020000, 2000000)
    assert parse_quota('Disk quotas for user x (uid 1): none\n') is None, 'PLANTED CONTROL: no row is unread'


def test_the_card_states_the_storage_and_says_a_full_home_claims_nothing(tmp_path: Path, monkeypatch) -> None:
    full = parse_mmlsquota(AT_FILE_LIMIT)
    assert storage_text(full).endswith('files 2020000/2000000 -- AT THE FILE LIMIT: claims nothing')
    assert 'AT THE FILE LIMIT' not in storage_text(parse_mmlsquota(AT_BYTE_LIMIT)), 'PLANTED CONTROL'
    assert storage_text(None).startswith('unread'), 'unreadable is stated, never a zero'
    snapshot = _snapshot()
    machine: Any = SimpleNamespace(grants=[SimpleNamespace(user='alyyw103', slurm_account='a')])
    cluster = forgeslurm.SlurmCluster(tmp_path, machine, cast('Any', None), lambda _g: lambda *_a: '', lambda: full)
    monkeypatch.setattr(forgeslurm, 'probe', lambda *_a: snapshot)
    standing = cluster.standing()
    assert standing.supply.resources['files'] == 0.0
    assert 'files' in standing.supply.present
    assert 'AT THE FILE LIMIT' in str(standing.facts['storage'])


def test_the_alarm_names_the_binding_limit_and_a_foreign_directory_it_never_deletes(tmp_path: Path) -> None:
    experiment = tmp_path / 'experiment'
    for i in range(30):
        (experiment / f'f{i}').parent.mkdir(parents=True, exist_ok=True)
        (experiment / f'f{i}').write_text('x', encoding='utf-8')
    (tmp_path / 'ci' / 'trees' / 'abc').mkdir(parents=True)
    heavy = consumers(tmp_path)
    assert heavy[0] == (experiment, 31, False)
    assert (tmp_path / 'ci' / 'trees', 2, True) in heavy
    body = pressure_text(parse_mmlsquota(AT_FILE_LIMIT), (0, 0), tmp_path)
    assert 'on files: bytes 43.0/1000.0 GB, files 2020000/2000000' in body
    assert f'- {experiment}: 31 files (not forge-owned, not touched)' in body
    assert f'- {tmp_path / "ci" / "trees"}: 2 files\n' in body + '\n', 'a forge-owned directory is not so marked'
    assert ' on bytes: ' in pressure_text(parse_mmlsquota(AT_BYTE_LIMIT), (0, 0), None), 'PLANTED CONTROL'
    assert len(list(experiment.iterdir())) == 30, 'counted, never touched'


def test_serve_pass_puts_the_named_alarm_on_the_outcome(tmp_path: Path) -> None:
    (tmp_path / 'experiment').mkdir()
    done = retention.serve_pass(
        Path(), cluster=True, home=tmp_path, state=tmp_path / 'state.json', table={'uv_prune': False},
        usage=lambda: parse_mmlsquota(AT_FILE_LIMIT), live=set, say=lambda _: None, run=lambda *_a, **_k: None,
        now=NOW, planner=lambda *_a, **_k: Plan(()),
    )  # fmt: skip
    assert done is not None
    assert done.over
    assert 'on files:' in done.alarm
    assert 'experiment: 1 files (not forge-owned, not touched)' in done.alarm


def test_when_files_bind_the_harder_runs_go_most_files_first(tmp_path: Path) -> None:
    """Oldest-first frees bytes; at the FILE limit the run holding the most files goes first, with its tree."""
    for sha, files in (('old', 1), ('big', 20)):
        for where in ('runs', 'trees'):
            (tmp_path / where / sha).mkdir(parents=True)
        for i in range(files):
            (tmp_path / 'trees' / sha / f'f{i}').write_text('x', encoding='utf-8')
    harder = tuple(Doomed(tmp_path / w / s, 'quota-pressure') for s in ('old', 'big') for w in ('runs', 'trees'))
    plan = Plan((), harder)
    near_files = Usage(used=1, limit=100, files=1_000_000, files_limit=1_000_010)
    lines: list[str] = []
    apply(plan, Policy(uv_prune=False, target=0.0), usage=near_files, dry_run=True, say=lines.append)
    assert [_name(line) for line in lines[:2]] == ['big', 'big']
    lines.clear()
    near_bytes = Usage(used=99, limit=100, files=1, files_limit=1_000_010)
    apply(plan, Policy(uv_prune=False, target=0.0), usage=near_bytes, dry_run=True, say=lines.append)
    assert [_name(line) for line in lines[:2]] == ['old', 'old'], 'PLANTED CONTROL: bytes keep age order'


def _name(line: str) -> str:
    return Path(json.loads(line)['path']).name
