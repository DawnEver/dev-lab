"""COMMAND-PART: a repo whose tests are not pytest (``npm test``) posts its part as ONE cell, its command."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from _forge_fake import make_repo, run_git
from lab_commons.outcomes import Conclusion

from dev_lab.dev import commandpart
from dev_lab.dev.cjk import CJK_RANGES
from dev_lab.dev.famtests.alwayson import required_ids
from dev_lab.dev.platformparts import part_context, part_of
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


def test_a_family_command_cannot_pass_with_a_malformed_layout_policy(tmp_path: Path, monkeypatch) -> None:
    run_git(tmp_path, 'init', '-q')
    (tmp_path / 'pyproject.toml').write_text(
        '[tool.lab_commons.tests]\nresources = []\n'
        '[tool.dev_lab.layout]\nmodule_unit = "guessed"\nmodule_limit = 300\n',
        encoding='utf-8',
    )
    posted = _wired(tmp_path, monkeypatch, code=0)
    started: list[list[str]] = []
    execute = commandpart._door.run

    def run(argv: list[str], **kwargs: object) -> object:
        started.append(list(argv))
        return execute(argv, **kwargs)

    monkeypatch.setattr(commandpart._door, 'run', run)
    assert commandpart.main(['--root', str(tmp_path), 'base', '--', 'npm', 'test']) == ProducerExit.FAIL
    assert not any('test' in argv for argv in started), 'the external command must not run past a failed guard'
    assert posted
    assert all(cell['status'] != 'ok' for record in posted for cell in record['cells'].values())


@pytest.mark.parametrize('violation', ['directory-width', 'cjk'])
def test_a_non_pytest_command_must_execute_the_same_family_guards(tmp_path: Path, monkeypatch, violation: str) -> None:
    root = make_repo(tmp_path, 'https://forge.example.org/team/app.git')
    (root / 'pyproject.toml').write_text(
        '[tool.lab_commons.tests]\nresources = []\n[tool.dev_lab.layout]\nmodule_unit = "raw"\nmodule_limit = 600\n',
        encoding='utf-8',
    )
    if violation == 'cjk':
        (root / 'subject.js').write_text('// ' + chr(CJK_RANGES[2][0]) + '\n', encoding='utf-8')
    else:
        (root / 'scripts').mkdir()
        for number in range(26):
            (root / 'scripts' / f'subject_{number}.py').write_text('value = 1\n', encoding='utf-8')
    run_git(root, 'add', '.')
    run_git(root, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.org', 'commit', '-qm', 'fixture')
    started: list[list[str]] = []
    posted: list[dict[str, Any]] = []
    execute = commandpart._door.run

    def run(argv: list[str], **kwargs: object) -> object:
        if argv[-1:] == ['test']:
            started.append(list(argv))
            return type('Done', (), {'returncode': 0})()
        return execute(argv, **kwargs)

    monkeypatch.setattr(commandpart._door, 'run', run)
    monkeypatch.setattr(commandpart, 'record_directory', lambda _root, _sha: root / 'records')
    monkeypatch.setattr(commandpart, 'post_local', lambda _root, record, _dir: posted.append(record) or 'posted')
    monkeypatch.setenv(PRODUCING_VAR, producing(part_context('base'), _SHA)[PRODUCING_VAR])
    assert commandpart.main(['--root', str(root), 'base', '--', 'npm', 'test']) == ProducerExit.FAIL
    assert started == [], 'a failed family guard must stop the external command'
    (record,) = posted
    assert set(record['cells']) == set(required_ids(root))
    assert {cell['status'] for cell in record['cells'].values()} == {'ok', 'rejected'}
    assert part_of(record).result is Conclusion.FAIL


def test_the_program_is_resolved_on_path_so_a_windows_cmd_shim_runs(tmp_path: Path, monkeypatch) -> None:
    """On Windows ``npm`` is ``npm.cmd``: a bare name cannot be started (WinError 2), so the door resolves it first.

    PLANTED: the launched argv[0] is the resolved path while the cell keeps the command as written.
    """
    started: list[list[str]] = []
    posted = _wired(tmp_path, monkeypatch, code=0)
    wired_run = commandpart._door.run

    def run(argv: list[str], **kwargs: object) -> object:
        started.append(list(argv))
        return wired_run(argv, **kwargs)

    monkeypatch.setattr(commandpart._door, 'run', run)
    monkeypatch.setattr(commandpart.shutil, 'which', lambda name: f'C:/node/{name}.cmd' if name == 'npm' else None)
    assert commandpart.main(['--root', str(tmp_path), 'base', '--', 'npm', 'test']) == ProducerExit.PASS
    assert started[-1] == ['C:/node/npm.cmd', 'test']
    assert list(posted[0]['cells']) == ['npm test']
