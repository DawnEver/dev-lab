"""COMMAND-PART: a repo whose tests are not pytest (``npm test``) posts its part as ONE cell, its command."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from dev_lab.dev import commandpart


@pytest.mark.parametrize(('code', 'status'), [(0, 'ok'), (1, 'rejected')])
def test_the_command_is_one_cell_of_its_part_judged_by_its_exit_code(
    tmp_path: Path, monkeypatch, code: int, status: str
) -> None:
    posted: list[dict[str, Any]] = []
    ran: list[list[str]] = []

    def run(argv: list[str], **_kwargs: object) -> object:
        ran.append(argv)
        return type('Done', (), {'returncode': code, 'stdout': 'a' * 40 + '\n'})()

    monkeypatch.setattr(commandpart._door, 'run', run)
    monkeypatch.setattr(commandpart, 'record_directory', lambda _root, _sha: tmp_path)
    monkeypatch.setattr(commandpart, 'post_local', lambda _root, record, _dir: posted.append(record) or 'ok')

    assert commandpart.main(['--root', str(tmp_path), 'base', '--', 'npm', 'test']) == code
    assert ['npm', 'test'] in ran
    (record,) = posted
    assert record['platform'] == 'base'
    assert record['sha'] == 'a' * 40
    assert list(record['cells']) == ['npm test']
    assert record['cells']['npm test']['status'] == status
    assert record['handed'] == {}


def test_no_command_is_refused_naming_the_shape(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        commandpart.main(['--root', str(tmp_path), 'base', '--'])
