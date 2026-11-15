"""The ``serial`` marker's stage, driven through the REAL ``run_verify`` and a real pytest.

Each planted test appends the stage it ran in to a ledger. The control is the same pair with the mark
removed: then no serial stage runs at all, so the split is the marker's doing and not verify's habit.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from dev_lab.dev import reports, verifysteps
from dev_lab.dev._logdistil import distil
from dev_lab.dev.serialpass import SERIAL_MARK
from dev_lab.dev.verdict import Conclusion

if TYPE_CHECKING:
    from pathlib import Path

_PLANTED = """\
import os
from pathlib import Path

import pytest

LEDGER = Path({ledger!r})


def _ran(name):
    with LEDGER.open('a', encoding='utf-8') as handle:
        handle.write(f"{{name}} {{os.environ.get('DEV_LAB_VERIFY_STAGE')}}\\n")


{mark}
def test_alone() -> None:
    _ran('alone')


def test_shared() -> None:
    _ran('shared')
"""


def _unboxed(_root: Path, argv: list[str], **_k: object) -> tuple[list[str], Path | None]:
    return argv, None


def _ledger(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, marked: bool) -> tuple[list[str], Conclusion]:
    ledger = tmp_path / 'ledger.txt'
    (tmp_path / 'tests').mkdir()
    mark = f'@pytest.mark.{SERIAL_MARK}' if marked else ''
    (tmp_path / 'tests' / 'test_planted.py').write_text(
        _PLANTED.format(ledger=str(ledger), mark=mark), encoding='utf-8'
    )
    (tmp_path / 'pyproject.toml').write_text(
        '[tool.pytest.ini_options]\naddopts = "--strict-markers"\n[tool.dev_lab.parts]\noutput = "out/logs"\n',
        encoding='utf-8',
    )
    monkeypatch.setattr(verifysteps, 'boxed', _unboxed)
    monkeypatch.setattr(verifysteps, 'RUFF_STEPS', ())
    verdict = verifysteps.run_verify(tmp_path, ('tests',), hooks=False)
    return sorted(ledger.read_text(encoding='utf-8').splitlines()), verdict.result.outcome


def test_a_marked_test_runs_alone_after_the_parallel_stage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ran, outcome = _ledger(tmp_path, monkeypatch, marked=True)
    assert ran == ['alone serial', 'shared parallel']
    assert outcome is Conclusion.PASS


def test_control_an_unmarked_pair_runs_in_the_parallel_stage_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ran, outcome = _ledger(tmp_path, monkeypatch, marked=False)
    assert ran == ['alone parallel', 'shared parallel']
    assert outcome is Conclusion.PASS


def test_the_parallel_half_ends_where_the_serial_banner_opens() -> None:
    log = ['--- pytest ---\n', '1 passed in 0.1s\n', '--- pytest serial ---\n', '1 failed in 0.1s\n']
    assert distil(log, banner='--- pytest ---\n', until='--- pytest serial ---\n').text == '1 passed in 0.1s\n'
    assert distil(log, banner='--- pytest serial ---\n').text == '1 failed in 0.1s\n'


def test_a_stage_the_split_emptied_is_dropped_but_an_empty_selection_is_not() -> None:
    emptied = ('2 deselected in 0.1s\n', 5)
    ran = ('1 passed in 0.1s\n', 0)
    assert reports.read_stages((emptied, ran)).truncated == ()
    assert reports.read_stages((emptied, emptied)).truncated


def test_the_stale_skip_side_is_judged_over_both_stages() -> None:
    skipped = ('SKIPPED tests/test_a.py::test_x - vendor\n20 passed, 1 skipped in 0.1s\n', 0)
    ran = ('1 passed in 0.1s\n', 0)
    allowed = ('tests/test_a.py::test_x',)
    assert reports.read_stages((ran, skipped), allowed_skips=allowed).truncated == ()
    stale = reports.read_stages((ran, ran), allowed_skips=allowed).truncated
    assert any('NOT skipped' in reason for reason in stale)


def test_real_serial_and_parallel_failures_keep_their_whole_legal_parameter_identities(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / 'tests').mkdir()
    ids = ['same prefix - [left value]', 'same prefix - [right value]']
    (tmp_path / 'tests' / 'test_planted.py').write_text(
        'import pytest\n\n'
        f'@pytest.mark.parametrize("value", [0, 1], ids={ids!r})\n'
        'def test_shared(value):\n    assert value < 0\n\n'
        f'@pytest.mark.{SERIAL_MARK}\n'
        f'@pytest.mark.parametrize("value", [0, 1], ids={ids!r})\n'
        'def test_alone(value):\n    assert value < 0\n',
        encoding='utf-8',
    )
    (tmp_path / 'pyproject.toml').write_text(
        '[tool.pytest.ini_options]\naddopts = "--strict-markers"\n[tool.dev_lab.parts]\noutput = "out/logs"\n',
        encoding='utf-8',
    )
    monkeypatch.setattr(verifysteps, 'boxed', _unboxed)
    monkeypatch.setattr(verifysteps, 'RUFF_STEPS', ())
    verdict = verifysteps.run_verify(tmp_path, ('tests',), hooks=False)
    assert verdict.result.outcome is Conclusion.FAIL, verdict.result
    assert set(verdict.result.failures) == {
        f'tests/test_planted.py::{name}[{identity}]' for name in ('test_shared', 'test_alone') for identity in ids
    }


def test_real_nonstrict_xpass_is_a_recorded_failure_even_when_pytest_exits_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / 'test_planted.py').write_text(
        'import pytest\n\n@pytest.mark.xfail(reason="known residual", strict=False)\n'
        'def test_expected_to_reject():\n    assert True\n',
        encoding='utf-8',
    )
    (tmp_path / 'pyproject.toml').write_text('[tool.dev_lab.parts]\noutput = "out/logs"\n', encoding='utf-8')
    monkeypatch.setattr(verifysteps, 'boxed', _unboxed)
    monkeypatch.setattr(verifysteps, 'RUFF_STEPS', ())
    verdict = verifysteps.run_verify(tmp_path, ('test_planted.py',), hooks=False)
    assert verdict.result.outcome is Conclusion.FAIL, verdict.result
    assert verdict.result.failures == ('test_planted.py::test_expected_to_reject',)


@pytest.mark.parametrize('case', ['allowed-not-applicable', 'resource-retry', 'undeclared', 'stale'])
def test_real_whitespace_skip_identity_keeps_the_exact_allowance_and_semantic_cell(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    identity = 'same prefix - [skip value]'
    node = f'test_planted.py::test_skips[{identity}]'
    mark = 'femm' if case == 'resource-retry' else 'not_applicable'
    allowed = [] if case == 'undeclared' else [node]
    if case == 'stale':
        allowed.append('test_planted.py::test_skips[same prefix - [other value]]')
    (tmp_path / 'test_planted.py').write_text(
        'import pytest\n\n@pytest.mark.parametrize("value", range(10))\n'
        'def test_passes(value):\n    assert value >= 0\n\n'
        f'@pytest.mark.{mark}\n@pytest.mark.parametrize("value", [0], ids={[identity]!r})\n'
        'def test_skips(value):\n    pytest.skip("question does not apply or resource unavailable")\n',
        encoding='utf-8',
    )
    (tmp_path / 'pyproject.toml').write_text(
        '[tool.dev_lab.parts]\noutput = "out/logs"\n'
        f'[tool.dev_lab.verify]\nallowed_skips = {json.dumps(allowed)}\n'
        '[tool.lab_commons.tests]\nresources = ["femm"]\n'
        '[tool.pytest.ini_options]\nmarkers = ["femm: declared resource"]\n',
        encoding='utf-8',
    )
    monkeypatch.setattr(verifysteps, 'boxed', _unboxed)
    monkeypatch.setattr(verifysteps, 'RUFF_STEPS', ())
    verdict = verifysteps.run_verify(tmp_path, hooks=False)
    expected = Conclusion.PASS if case == 'allowed-not-applicable' else Conclusion.INCONCLUSIVE
    assert verdict.result.outcome is expected, verdict.result
