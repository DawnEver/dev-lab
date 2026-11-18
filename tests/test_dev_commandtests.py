"""Verify measures a COMMAND-PART repo's script tests through its declared command, to a real verdict."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from lab_commons.hpc.testcells import TestCell
from lab_commons.outcomes import Cell, Conclusion, Status

from dev_lab.dev import verifysteps
from dev_lab.dev.commandtests import declared_command, script_paths, selected_command
from dev_lab.dev.jobparts import command_part
from dev_lab.dev.test_outcomes import OUTCOMES_DIR_VAR, CellRecorder

_NODE = ('node', '--test', '--test-concurrency=4', 'a/*.test.mjs', 'b/*.test.mjs')
_PRODUCE = '[tool.lab_commons.tests]\nproduce = ["-m", "dev_lab.dev.commandpart", "{part}", "--", %s]\n'
_OUTPUT = '[tool.dev_lab.parts]\noutput = "out/logs"\n'


def _pyproject(command: tuple[str, ...] | None) -> str:
    return _OUTPUT + (_PRODUCE % ', '.join(json.dumps(word) for word in command) if command else '')


def test_the_declared_command_is_the_producer_line_after_its_separator() -> None:
    assert declared_command(_pyproject(_NODE)) == _NODE
    assert command_part(_pyproject(_NODE))
    assert declared_command(_pyproject(None)) is None
    assert not command_part(_pyproject(None))


def test_a_node_command_keeps_its_options_and_runs_exactly_the_selection(tmp_path: Path) -> None:
    assert selected_command(tmp_path, _NODE, ('a/x.test.mjs',)) == (
        'node',
        '--test',
        '--test-concurrency=4',
        'a/x.test.mjs',
    )


def test_npm_test_is_expanded_to_its_package_script_before_it_is_cut(tmp_path: Path) -> None:
    (tmp_path / 'package.json').write_text(json.dumps({'scripts': {'test': 'node --test s/*.test.mjs'}}), 'utf-8')
    assert selected_command(tmp_path, ('npm', 'test'), ('s/x.test.mjs',)) == ('node', '--test', 's/x.test.mjs')
    refused = selected_command(tmp_path, ('npm', 'run', 'absent'), ('s/x.test.mjs',))
    assert isinstance(refused, str)
    assert 'absent' in refused


def test_only_existing_script_paths_leave_the_pytest_arguments(tmp_path: Path) -> None:
    (tmp_path / 'x.test.mjs').write_text('', 'utf-8')
    assert script_paths(tmp_path, ('-x', 'x.test.mjs', 'gone.test.mjs', 'tests')) == (
        ('-x', 'gone.test.mjs', 'tests'),
        ('x.test.mjs',),
    )


_PASSING = "import test from 'node:test';\ntest('holds', () => {});\n"
_FAILING = "import test from 'node:test';\nimport assert from 'node:assert';\ntest('breaks', () => assert.ok(false));\n"


def _repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: str, *, declared: bool = True) -> str:
    (tmp_path / 't').mkdir()
    (tmp_path / 't' / 'one.test.mjs').write_text(body, 'utf-8')
    command = ('node', '--test', 't/*.test.mjs') if declared else None
    (tmp_path / 'pyproject.toml').write_text(_pyproject(command), 'utf-8')
    monkeypatch.setattr(verifysteps, 'RUFF_STEPS', ())
    return 't/one.test.mjs'


needs_node = pytest.mark.skipif(shutil.which('node') is None, reason='node is not on PATH')


@needs_node
@pytest.mark.parametrize(('body', 'outcome'), [(_PASSING, Conclusion.PASS), (_FAILING, Conclusion.FAIL)])
def test_a_selected_node_test_settles_by_its_own_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: str, outcome: Conclusion
) -> None:
    path = _repo(tmp_path, monkeypatch, body)
    verdict = verifysteps.run_verify(tmp_path, (path,), hooks=False)
    assert verdict.result.outcome is outcome, verdict.result
    assert (path in verdict.result.failures) is (outcome is Conclusion.FAIL)


def test_an_undeclared_command_measures_nothing_and_names_its_door(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _repo(tmp_path, monkeypatch, _PASSING, declared=False)
    verdict = verifysteps.run_verify(tmp_path, (path,), hooks=False)
    assert verdict.result.outcome is Conclusion.INCONCLUSIVE, verdict.result
    assert 'dev_lab.dev.commandpart' in str(verdict.result)


@needs_node
def test_a_mixed_selection_runs_both_and_either_red_fails_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = _repo(tmp_path, monkeypatch, _FAILING)
    (tmp_path / 'tests').mkdir()
    (tmp_path / 'tests' / 'test_one.py').write_text('def test_one():\n    pass\n', 'utf-8')
    real, ran = verifysteps._tee, []

    def step(command: list[str], *, handle, extra_env=None, **where: object) -> int:
        ran.append(command)
        if not extra_env:
            return real(command, handle=handle, **where)
        CellRecorder(Path(extra_env[OUTCOMES_DIR_VAR]) / 'cells.jsonl').record(
            'tests/test_one.py::test_one', TestCell(Cell(Status.OK))
        )
        handle.write('1 passed in 0.1s\n')
        return 0

    monkeypatch.setattr(verifysteps, 'boxed', lambda _root, argv, **_k: (argv, None))
    monkeypatch.setattr(verifysteps, '_tee', step)
    verdict = verifysteps.run_verify(tmp_path, (path, 'tests/test_one.py'), hooks=False)
    assert any('pytest' in command for command in ran), ran
    assert any(path in command for command in ran), ran
    assert verdict.result.outcome is Conclusion.FAIL, verdict.result
    assert verdict.result.failures == (path,)
