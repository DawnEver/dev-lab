"""PLATFORM PARTS: one declaration per marker, a strict linux part from the cluster, and the next part's selection."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lab_commons.dev import platformparts
from lab_commons.dev.verdictledger import entries
from lab_commons.hpc.platforms import cannot_run, host_platform, read_table

SHA = 'a' * 40

PYPROJECT = """
[tool.lab_commons.platforms]
femm = ["windows"]
matlab = ["windows", "linux"]
"""


def _record(outcomes: dict[str, str], left: dict[str, list[str]] | None = None) -> dict[str, object]:
    return {
        'sha': SHA,
        'platform': 'linux-x86_64/glibc2.28',
        'cluster': 'login.ada',
        'python': '3.13.1',
        'plan': {},
        'outcomes': outcomes,
        'left': left or {},
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


def test_the_linux_part_is_derived_strictly() -> None:
    passing = _record(
        {'t::a': 'passed', 't::b': 'skipped', 't::c': 'xfailed', 't::f': 'not-covered'}, {'t::f': ['windows']}
    )
    run, *tests = platformparts.linux_part(passing, tier='heavy', log='r@d')
    assert (run.result, run.part, run.commit, run.tier) == ('PASS', 'linux', SHA, 'heavy')
    assert run.env == 'hpc:login.ada:linux-x86_64/glibc2.28:python-3.13.1', 'the env names the cluster, not this box'
    assert run.left == {'t::f': ['windows']}
    assert {t.test for t in tests} == {'t::a', 't::c'}
    for bad in ('failed', 'error', 'lost', 'missing'):
        failing = platformparts.linux_part(_record({'t::a': 'passed', 't::x': bad}), tier='heavy', log='r@d')
        assert failing[0].result == 'FAIL', bad
    with pytest.raises(platformparts.PartRefusal, match='covers no test'):
        platformparts.linux_part(_record({'t::f': 'not-covered'}), tier='heavy', log='r@d')


def test_the_next_part_runs_what_its_platform_can_and_no_part_ran() -> None:
    left = {'t::f': ['windows'], 't::m': ['windows', 'macos'], 't::n': []}
    rows = platformparts.linux_part(
        _record({'t::a': 'passed', **dict.fromkeys(left, 'not-covered')}, left), tier='heavy', log='r'
    )
    ids, remaining = platformparts.to_run(rows, head=SHA, platform='windows', env='e', host='windows')
    assert ids == ['t::f', 't::m']
    assert platformparts.left_after(remaining, ids) == {'t::n': []}
    with pytest.raises(platformparts.PartRefusal, match='record the linux part first'):
        platformparts.to_run([], head=SHA, platform='windows', env='e', host='windows')


def test_the_cli_writes_the_linux_part_into_the_ledger(tmp_path: Path) -> None:
    source = tmp_path / 'record.json'
    source.write_text(json.dumps(_record({'t::a': 'passed'})), encoding='utf-8')
    ledger = tmp_path / 'ledger.jsonl'
    assert platformparts.main(['record-linux', str(source), '--tier', 'heavy', '--ledger', str(ledger)]) == 0
    run = entries(ledger)[0]
    assert (run.part, run.result, run.commit) == ('linux', 'PASS', SHA)
    assert run.log.startswith(f'{source}@sha256:')
    empty = tmp_path / 'empty.json'
    empty.write_text(json.dumps(_record({})), encoding='utf-8')
    assert platformparts.main(['record-linux', str(empty), '--tier', 'heavy', '--ledger', str(ledger)]) == 1
