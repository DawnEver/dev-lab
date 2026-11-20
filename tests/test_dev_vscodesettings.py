"""``vscodesettings``: the editor excludes derive from the storage kinds, and only managed keys are written."""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

import pytest
from _venv_fake import current_env

from dev_lab.dev import venvpointer
from dev_lab.dev import vscodesettings as vs
from dev_lab.dev.venvpath import VENV_LAYOUTS

if TYPE_CHECKING:
    from pathlib import Path


def _repo(tmp_path: Path, pyproject: str = '') -> Path:
    (tmp_path / 'pyproject.toml').write_text(pyproject, encoding='utf-8')
    return tmp_path


def _settings(root: Path) -> dict:
    return json.loads((root / vs.RELATIVE).read_text(encoding='utf-8'))


def test_the_excludes_are_the_storage_kinds(tmp_path: Path) -> None:
    dirs = vs.excluded(_repo(tmp_path))
    assert set(dirs) == {'output', '.venvs', '.claude/worktrees', 'target'}
    assert 'output/temp' not in dirs, 'a nested kind is covered by its parent'


def test_the_editor_is_handed_the_environment_the_pointer_names(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    tail = VENV_LAYOUTS[os.name][1:]
    unset = vs.managed(root)['python.defaultInterpreterPath']
    assert unset == root.joinpath(venvpointer.POINTER, *tail).as_posix(), 'PLANTED CONTROL: no pointer names none'
    env = current_env(root, 'e1')
    assert vs.managed(root)['python.defaultInterpreterPath'] == env.joinpath(*tail).as_posix()


def test_a_repo_declares_its_own_extra_directory(tmp_path: Path) -> None:
    root = _repo(tmp_path, '[tool.dev_lab.vscode]\nexclude = ["attic"]\n')
    assert '**/attic' in vs.managed(root)['search.exclude']
    assert '**/attic/**' in vs.managed(root)['files.watcherExclude']


def test_an_undeclared_extra_is_not_added(tmp_path: Path) -> None:
    """PLANTED CONTROL: without a declaration, attic is not excluded."""
    assert '**/attic' not in vs.managed(_repo(tmp_path))['search.exclude']


def test_render_keeps_every_user_key(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    (root / '.vscode').mkdir()
    (root / vs.RELATIVE).write_text(json.dumps({'editor.fontSize': 15, 'python.analysis.typeCheckingMode': 'strict'}))
    vs.render(root)
    data = _settings(root)
    assert data['editor.fontSize'] == 15
    assert data['python.analysis.typeCheckingMode'] == 'strict'
    assert data['npm.autoDetect'] == 'off'
    assert data['search.followSymlinks'] is False


def test_a_stale_managed_key_is_rewritten_and_check_reports_it(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    (root / '.vscode').mkdir()
    (root / vs.RELATIVE).write_text(json.dumps({'search.exclude': {'**/old': True}, 'npm.autoDetect': 'on'}))
    assert set(vs.drift(root)) >= {'search.exclude', 'npm.autoDetect'}
    assert vs.check(root) == 1
    vs.render(root)
    assert vs.drift(root) == ()
    assert vs.check(root) == 0
    assert '**/old' not in _settings(root)['search.exclude']


def test_a_current_file_is_not_rewritten(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    vs.render(root)
    before = (root / vs.RELATIVE).stat().st_mtime_ns
    assert vs.render(root) == ()
    assert (root / vs.RELATIVE).stat().st_mtime_ns == before


def test_a_file_with_comments_is_refused_by_name_and_left_untouched(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    (root / '.vscode').mkdir()
    text = '{\n  // mine\n  "editor.fontSize": 15\n}\n'
    (root / vs.RELATIVE).write_text(text, encoding='utf-8')
    with pytest.raises(vs.SettingsError, match='strict JSON'):
        vs.render(root)
    assert (root / vs.RELATIVE).read_text(encoding='utf-8') == text
    assert 'not rendered' in vs.follow(root)


def test_a_bad_declaration_is_refused_by_name(tmp_path: Path) -> None:
    root = _repo(tmp_path, '[tool.dev_lab.vscode]\nexclude = "attic"\n')
    with pytest.raises(vs.SettingsError, match=r'\[tool\.dev_lab\.vscode\] exclude'):
        vs.managed(root)
