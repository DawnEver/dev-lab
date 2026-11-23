"""The bootstrap door names an interpreter whose version satisfies the target checkout's ``requires-python``.

Measured 2026-11-23: cc-market (``>=3.13``) was refused at pre-commit naming a borrowed 3.12 interpreter as its
door. PLANTED controls: a spec the running interpreter satisfies names the running one; a spec nothing satisfies
names none.
"""

from __future__ import annotations

import platform
import sys
from pathlib import Path

import pytest

from dev_lab.dev.githooks import fitting
from dev_lab.dev.githooks.runner import run_stage
from dev_lab.dev.githooks.table import Hook

_RUNNING = platform.python_version()


def _checkout(tmp_path: Path, spec: str) -> Path:
    (tmp_path / 'pyproject.toml').write_text(f'[project]\nname = "x"\nrequires-python = "{spec}"\n', encoding='utf-8')
    return tmp_path


def test_a_borrowed_interpreter_older_than_requires_python_is_passed_over(tmp_path: Path) -> None:
    root = _checkout(tmp_path, f'>{_RUNNING}')
    versions = {'old/python': '3.0.0', 'new/python': '99.0.0'}
    chosen = fitting.bootstrap_interpreter(root, others=list(versions), version_of=versions.get)
    assert chosen == 'new/python'


def test_planted_control_a_fitting_running_interpreter_is_named(tmp_path: Path) -> None:
    root = _checkout(tmp_path, f'>={_RUNNING}')
    chosen = fitting.bootstrap_interpreter(root, others=['new/python'], version_of=lambda _p: '99.0.0')
    assert chosen == Path(sys.executable).as_posix()


def test_planted_control_nothing_fitting_names_nothing(tmp_path: Path) -> None:
    root = _checkout(tmp_path, '>=99')
    probed = {'a/python': '3.0.0', 'b/python': None}
    assert fitting.bootstrap_interpreter(root, others=list(probed), version_of=probed.get) is None


@pytest.mark.parametrize(
    ('version', 'spec', 'ok'), [('3.12.4', '>=3.13', False), ('3.13.1', '>=3.13', True), ('3.12.4', None, True)]
)
def test_fits_reads_the_specifier(version: str, spec: str | None, ok: bool) -> None:  # noqa: FBT001 -- a parametrized case
    assert fitting.fits(version, spec) is ok


def test_the_refusal_names_the_fitting_interpreter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _checkout(tmp_path, f'>{_RUNNING}')
    monkeypatch.setattr(fitting, 'candidates', lambda _root: ['new/python'])
    monkeypatch.setattr(fitting, 'probe', lambda _p: '99.0.0')
    row = Hook(stage='pre-commit', id='x', run=('python', '-m', 'x'), always_run=True)
    assert run_stage('pre-commit', root=root, hooks=(row,), runner=lambda *_a, **_k: (0, ''), borrowed=True) == 1
    said = capsys.readouterr().err
    assert f'new/python -m dev_lab.dev.dep --bootstrap {root.as_posix()}' in said
    assert Path(sys.executable).as_posix() not in said, 'the unfit running interpreter is never the door'


def test_with_nothing_fitting_the_refusal_names_the_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _checkout(tmp_path, '>=99')
    monkeypatch.setattr(fitting, 'candidates', lambda _root: [])
    row = Hook(stage='pre-commit', id='x', run=('python', '-m', 'x'), always_run=True)
    assert run_stage('pre-commit', root=root, hooks=(row,), runner=lambda *_a, **_k: (0, ''), borrowed=True) == 1
    assert "requires-python '>=99'" in capsys.readouterr().err
