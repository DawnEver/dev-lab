"""THE FAMILY PYTHON (user ruling 2026-11-27, dev-lab #1045): declared once, rendered and judged everywhere it reaches.

Every arm is driven through the consumer body (:func:`~dev_lab.dev.famtests.pythontoolchain.assert_the_family_python`)
against a planted repo, each paired with the planted wrong truth it must report; the live arm judges this checkout.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Final

import pytest

from dev_lab.dev import ciworkflows
from dev_lab.dev.ciworkflowshape import BASE_PATH
from dev_lab.dev.famtests.pythontoolchain import ForeignPython, assert_the_family_python
from dev_lab.dev.hpcaccount.spec import DEFAULT_PYTHON
from dev_lab.dev.pythontoolchain import (
    REQUIRES_PYTHON,
    RUFF_TARGET,
    SYNC_FLAGS,
    VERSION,
    drift,
    main,
    unpinned_syncs,
    write,
)

ROOT: Final = Path(__file__).resolve().parents[1]

#: A consumer's manifest before the ruling: its own floor and ruff target, plus keys and a comment the render keeps.
_BEFORE: Final = (
    '[project]\nname = "consumer"\n# why this floor\nrequires-python = ">=3.12"\ndependencies = ["numpy"]\n\n'
    '[tool.ruff]\nline-length = 120\ntarget-version = "py312"\n'
)


def _repo(root: Path, manifest: str = _BEFORE) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / 'pyproject.toml').write_text(manifest, encoding='utf-8')
    return root


def _workflow(root: Path, sync: str) -> Path:
    """A rendered workflow (the stamp, then JSON) whose one job syncs with *sync*."""
    path = root / '.github' / 'workflows' / 'ci.yml'
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {'jobs': {'part': {'steps': [{'name': 'Sync', 'run': sync}]}}}
    path.write_text(f'{ciworkflows.STAMP}\n{json.dumps(body, indent=2)}\n', encoding='utf-8')
    return path


def test_every_derived_fact_reads_the_one_version() -> None:
    major, minor = VERSION.split('.')
    assert f'>={VERSION},<{major}.{int(minor) + 1}' == REQUIRES_PYTHON
    assert f'py{major}{minor}' == RUFF_TARGET
    assert f'--python {VERSION} --managed-python' == SYNC_FLAGS
    assert DEFAULT_PYTHON == VERSION, 'a cluster venv on another minor would install no family repo'


def test_the_ci_base_types_no_python_version() -> None:
    """The workflows reach the version only through the placeholder; a literal there would be a second source."""
    base = BASE_PATH.read_text(encoding='utf-8')
    assert ciworkflows.PYTHON_PLACEHOLDER in base
    assert '--python 3' not in base
    assert VERSION not in base


def test_this_repo_runs_the_family_python() -> None:
    """The live arm: this checkout's manifest and every workflow it renders."""
    assert_the_family_python(root=ROOT)


def test_a_consumer_left_on_its_own_python_is_named_key_by_key(tmp_path: Path) -> None:
    root = _repo(tmp_path / 'consumer')
    with pytest.raises(ForeignPython) as refused:
        assert_the_family_python(root=root)
    said = str(refused.value)
    assert "requires-python: the file says '>=3.12'" in said
    assert "target-version: the file says 'py312'" in said
    assert 'python -m dev_lab.dev.pythontoolchain render' in said


def test_the_render_writes_only_the_family_keys_and_the_body_then_passes(tmp_path: Path) -> None:
    """Planted control for the arm above: the same repo, rendered, is the family's; the rest of it is untouched."""
    root = _repo(tmp_path / 'consumer')
    assert write(root) == 'pyproject.toml: rendered'
    assert_the_family_python(root=root)
    text = (root / 'pyproject.toml').read_text(encoding='utf-8')
    assert '# why this floor' in text
    assert 'dependencies = ["numpy"]' in text
    assert 'line-length = 120' in text
    assert write(root) == 'pyproject.toml: current'


def test_a_repo_with_no_ruff_table_gets_one(tmp_path: Path) -> None:
    root = _repo(tmp_path / 'consumer', '[project]\nname = "consumer"\n')
    assert drift(root), 'an absent key is not agreement'
    write(root)
    assert drift(root) == []


def test_a_rendered_sync_without_the_family_interpreter_is_named(tmp_path: Path) -> None:
    root = _repo(tmp_path / 'consumer')
    write(root)
    workflow = _workflow(root, 'uv sync --frozen --extra test')
    with pytest.raises(ForeignPython, match=r'\.github/workflows/ci\.yml: `uv sync --frozen --extra test`'):
        assert_the_family_python(root=root)
    workflow.write_text(workflow.read_text(encoding='utf-8').replace('--frozen', f'--frozen {SYNC_FLAGS}'))
    assert_the_family_python(root=root)


def test_a_hand_written_workflow_is_not_this_bodys_to_parse(tmp_path: Path) -> None:
    """ciworkflows.drift refuses a hand-written file; this body reads only what a render stamped."""
    root = _repo(tmp_path / 'consumer')
    write(root)
    path = root / '.github' / 'workflows' / 'own.yml'
    path.parent.mkdir(parents=True)
    path.write_text('on: push\njobs: {}\n', encoding='utf-8')
    assert drift(root) == []


@pytest.mark.parametrize(
    ('workflow', 'unpinned'),
    [
        ({'run': f'uv sync --frozen {SYNC_FLAGS}'}, []),
        ({'steps': [{'run': 'echo hi\nuv sync --frozen'}]}, ['uv sync --frozen']),
        ([{'run': 'uv run --no-sync python -m x'}], []),
    ],
)
def test_every_sync_line_is_read_at_any_depth(workflow: object, unpinned: list[str]) -> None:
    assert unpinned_syncs(workflow) == unpinned


def test_the_check_door_exits_by_its_verdict(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _repo(tmp_path / 'consumer')
    assert main(['check', '--repo', str(root)]) == 1
    assert 'requires-python' in capsys.readouterr().out
    assert main(['render', '--repo', str(root)]) == 0
    assert main(['check', '--repo', str(root)]) == 0
