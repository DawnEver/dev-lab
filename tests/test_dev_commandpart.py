"""COMMAND-PART: a repo whose tests are not pytest (``npm test``) posts its part as ONE cell, its command."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from dev_lab.dev import commandpart
from dev_lab.dev.platformparts import part_context
from dev_lab.dev.producer import PRODUCING_VAR, ProducerExit, producing

_SHA = 'a' * 40


def _wired(tmp_path: Path, monkeypatch, *, code: int | None, part: str = 'base') -> list[dict[str, Any]]:
    """The command exits *code* (``None``: it cannot be started) inside serve's producer of *part*; the posts."""
    posted: list[dict[str, Any]] = []

    def run(argv: list[str], **_kwargs: object) -> object:
        if argv[:2] == ['git', 'rev-parse']:
            return type('Done', (), {'returncode': 0, 'stdout': _SHA + '\n'})()
        if code is None:
            raise FileNotFoundError(2, 'not found', argv[0])
        return type('Done', (), {'returncode': code, 'stdout': ''})()

    monkeypatch.setattr(commandpart._door, 'run', run)
    monkeypatch.setattr(commandpart, 'record_directory', lambda _root, _sha: tmp_path)
    monkeypatch.setattr(commandpart, 'post_local', lambda _root, record, _dir: posted.append(record) or 'ok')
    monkeypatch.setenv(PRODUCING_VAR, producing(part_context(part), _SHA)[PRODUCING_VAR])
    return posted


@pytest.mark.parametrize(
    ('code', 'status', 'exit_code'),
    [(0, 'ok', ProducerExit.PASS), (1, 'rejected', ProducerExit.FAIL), (2, 'rejected', ProducerExit.FAIL),
     (3, 'rejected', ProducerExit.FAIL), (4, 'rejected', ProducerExit.FAIL), (137, 'rejected', ProducerExit.FAIL)],
)  # fmt: skip
def test_the_command_is_one_cell_and_its_exit_maps_to_the_producer_contract(
    tmp_path: Path, monkeypatch, code: int, status: str, exit_code: int
) -> None:
    """A command's 2/3/4 is its own failure, never the producer's USAGE/INCONCLUSIVE/UNREACHABLE (dev-lab #3 HIGH)."""
    posted = _wired(tmp_path, monkeypatch, code=code)
    assert commandpart.main(['--root', str(tmp_path), 'base', '--', 'npm', 'test']) == exit_code
    (record,) = posted
    assert record['platform'] == 'base'
    assert record['sha'] == _SHA
    assert record['cells']['npm test']['status'] == status
    assert record['handed'] == {}


def test_an_os_qualified_row_keeps_its_own_cell(tmp_path: Path, monkeypatch) -> None:
    """dev-lab #3 HIGH: ``base@windows`` handed its one cell away. PLANTED control: plain ``base`` (above)."""
    posted = _wired(tmp_path, monkeypatch, code=0, part='base@windows')
    assert commandpart.main(['--root', str(tmp_path), 'base@windows', '--', 'npm', 'test']) == ProducerExit.PASS
    (record,) = posted
    assert list(record['cells']) == ['npm test']
    assert record['handed'] == {}


def test_outside_a_serve_producer_the_command_is_refused(tmp_path: Path, monkeypatch, capsys) -> None:
    """Like verify's full suite: a verdict is the forge's to produce (PLANTED control: every test above runs)."""
    posted = _wired(tmp_path, monkeypatch, code=0)
    monkeypatch.delenv(PRODUCING_VAR)
    assert commandpart.main(['--root', str(tmp_path), 'base', '--', 'npm', 'test']) == ProducerExit.USAGE
    assert posted == []
    assert 'refused' in capsys.readouterr().err


def test_a_command_that_cannot_start_is_unreachable_in_one_line(tmp_path: Path, monkeypatch, capsys) -> None:
    """A host without ``npm`` says nothing about the code: UNREACHABLE (retried), no traceback, nothing posted."""
    posted = _wired(tmp_path, monkeypatch, code=None)
    assert commandpart.main(['--root', str(tmp_path), 'base', '--', 'npm', 'test']) == ProducerExit.UNREACHABLE
    assert posted == []
    err = capsys.readouterr().err
    assert 'npm' in err
    assert len(err.strip().splitlines()) == 1


def test_no_command_is_refused_naming_the_shape(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        commandpart.main(['--root', str(tmp_path), 'base', '--'])
