"""PLATFORM PARTS: one declaration per marker, one assignment rule, a strict part from a run record."""

from __future__ import annotations

from pathlib import Path

import pytest

from lab_commons.dev import platformparts
from lab_commons.dev.verdictledger import entries
from lab_commons.hpc.platforms import assign, cannot_run, host_platform, read_table, runnable
from lab_commons.hpc.records import write_record

SHA = 'a' * 40

PYPROJECT = """
[tool.lab_commons.platforms]
femm = ["windows"]
matlab = ["windows", "linux"]
"""


def _record(outcomes: dict[str, str], handed: dict[str, list[str]] | None = None) -> dict[str, object]:
    return {
        'sha': SHA,
        'platform': 'linux',
        'system': 'linux-x86_64/glibc2.28',
        'scope': 'full',
        'req': 't0',
        'cluster': 'login.ada',
        'python': '3.13.1',
        'plan': {},
        'outcomes': outcomes,
        'handed': handed or {},
    }


def test_the_table_is_one_declaration_per_marker() -> None:
    table = read_table(PYPROJECT)
    assert table == {'femm': ('windows',), 'matlab': ('windows', 'linux')}
    assert cannot_run(table, 'linux') == 'femm'
    assert cannot_run(table, 'macos') == 'femm or matlab'
    assert cannot_run(table, 'windows') == '', 'an unlisted marker runs everywhere'
    assert read_table('[project]\nname = "x"\n') == {}
    with pytest.raises(ValueError, match='platforms are a list'):
        read_table('[tool.lab_commons.platforms]\nfemm = ["win32"]\n')
    assert host_platform('win32') == 'windows'


def test_the_part_is_derived_strictly_from_the_run() -> None:
    passing = _record(
        {'t::a': 'passed', 't::b': 'skipped', 't::c': 'xfailed', 't::f': 'not-covered'}, {'t::f': ['windows']}
    )
    run, *tests = platformparts.run_part(passing, log='r@d')
    assert (run.result, run.part, run.commit, run.tier) == ('PASS', 'linux', SHA, 'full'), (
        "platform and scope are the record's"
    )
    assert run.env == 'hpc:login.ada:linux-x86_64/glibc2.28:python-3.13.1', 'the env names the cluster, not this box'
    assert run.handed == {'t::f': ['windows']}
    assert {t.test for t in tests} == {'t::a', 't::c'}
    for bad in ('failed', 'error'):
        failing = platformparts.run_part(_record({'t::a': 'passed', 't::x': bad}), log='r@d')
        assert failing[0].result == 'FAIL', bad


@pytest.mark.parametrize('unrun', ['lost', 'missing'])
def test_a_part_whose_ids_never_reported_is_inconclusive_and_never_recorded_as_fail(unrun: str) -> None:
    """Measured 2026-10-09: 50349 lost ids from a build that never made a venv were written as a linux FAIL."""
    outcomes = {'t::a': 'passed', 't::e': 'error', 't::x': unrun}
    with pytest.raises(platformparts.PartRefusal, match=r'INCONCLUSIVE: 1 of 3 .*t::x'):
        platformparts.run_part(_record(outcomes), log='r@d')
    with pytest.raises(platformparts.PartRefusal, match='covers no test'):
        platformparts.run_part(_record({'t::f': 'not-covered'}), log='r@d')


def test_every_id_is_assigned_to_exactly_one_part_by_one_rule() -> None:
    """The rule: linux if it can run there, else windows, else macos; nowhere is ``None``."""
    assert assign(['linux', 'windows', 'macos']) == 'linux'
    assert assign(['macos', 'windows']) == 'windows', 'the rule reads PLATFORMS order, not the list order'
    assert assign(['macos']) == 'macos'
    assert assign([]) is None
    can = {'t::a': ['linux', 'windows', 'macos'], 't::f': ['windows'], 't::m': ['windows', 'macos'], 't::n': []}
    for platform in ('linux', 'windows', 'macos'):
        mine, handed = platformparts.split(can, platform)
        assert set(mine).isdisjoint(handed), platform
        assert set(mine) | set(handed) == set(can), platform
    assert platformparts.split(can, 'windows') == (['t::f', 't::m'], {'t::a': can['t::a'], 't::n': []})
    assert platformparts.split(can, 'linux')[0] == ['t::a']


def test_a_part_selects_from_its_own_collection_without_reading_any_ledger(tmp_path: Path, monkeypatch) -> None:
    """No part is recorded anywhere, and windows still selects: the selection reads only table and ids."""
    monkeypatch.setattr(platformparts, 'table_at', lambda _root, _sha: read_table(PYPROJECT))
    collected = {'': ['t::a', 't::f', 't::m'], 'femm': ['t::f'], 'femm or matlab': ['t::f', 't::m']}
    mine, handed = platformparts.select(tmp_path, SHA, 'windows', collect=collected.__getitem__)
    assert mine == ['t::f']
    assert handed == {'t::a': ['linux', 'windows', 'macos'], 't::m': ['linux', 'windows']}
    assert runnable(['t::f'], {'linux': {'t::f'}}) == {'t::f': ['windows', 'macos']}
    with pytest.raises(ValueError, match='one of'):
        platformparts.select(tmp_path, SHA, 'win32', collect=collected.__getitem__)


def test_the_cli_writes_the_run_record_as_its_part_into_the_ledger(tmp_path: Path) -> None:
    source = write_record(_record({'t::a': 'passed'}), tmp_path / 'runs')
    ledger = tmp_path / 'ledger.jsonl'
    assert platformparts.main(['record', str(source), '--ledger', str(ledger)]) == 0
    run = entries(ledger)[0]
    assert (run.part, run.result, run.commit, run.tier) == ('linux', 'PASS', SHA, 'full')
    assert run.log.startswith(f'{source}@sha256:')
    empty = write_record({**_record({}), 'req': 't1'}, tmp_path / 'runs')
    assert platformparts.main(['record', str(empty), '--ledger', str(ledger)]) == 1
