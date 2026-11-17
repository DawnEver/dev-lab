"""THE BINDER IS NAMED: an unbound push says which rem the session's harness runs, when that can be read.

The skew this closes (2026-11-16): a host whose rem plugin is absent, disabled or older than the release that binds
writes no binding, and the gate only said "none is bound". Each planted registry below must change the door; an
unreadable one keeps the plain door, never a crash.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest
from _rem_binding import plant_claude_rem, plant_codex_rem

from dev_lab.dev import remplugin, taskbinding, taskgate

_CLAUDE = {'CLAUDE_CODE_SESSION_ID': 'claude-session-1'}
_CODEX = {'CODEX_THREAD_ID': 'codex-thread-1'}
_GIT = shutil.which('git') or 'git'
#: Plants one harness registry under a home.
Plant = Callable[[Path], object]


def _codex_without_rem(home: Path) -> None:
    (home / '.codex').mkdir()
    (home / '.codex' / 'config.toml').write_text('model = "planted"\n', encoding='utf-8')


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / 'repo'
    task = root / '.claude' / 'tasks' / 'toolchain' / 'TASK.md'
    task.parent.mkdir(parents=True)
    task.write_text('---\nauthority: a1\nstatus: open\n---\n', encoding='utf-8')
    (root / 'pyproject.toml').write_text('[tool.dev_lab.task]\nrequired = true\n', encoding='utf-8')
    subprocess.run([_GIT, 'init', '-q', str(root)], check=True, capture_output=True)
    return root


@pytest.mark.parametrize(
    ('env', 'plant'),
    [(_CLAUDE, lambda home: plant_claude_rem(home, '2.6.0')), (_CODEX, lambda home: plant_codex_rem(home, '2.4.0'))],
)
def test_an_old_rem_names_the_update(tmp_path: Path, env: dict[str, str], plant: Plant) -> None:
    plant(tmp_path)
    said = remplugin.binder_door(env, tmp_path, tmp_path)
    assert said is not None
    assert 'update rem to >= 2.7.0' in said
    assert 'claude plugin update rem@cc-market' in said
    assert 'codex plugin add rem@cc-market' in said


@pytest.mark.parametrize(
    ('env', 'plant'),
    [(_CLAUDE, lambda home: plant_claude_rem(home, None)), (_CODEX, _codex_without_rem)],
)
def test_an_absent_rem_names_the_install(tmp_path: Path, env: dict[str, str], plant: Plant) -> None:
    plant(tmp_path)
    said = remplugin.binder_door(env, tmp_path, tmp_path)
    assert said is not None
    assert 'install rem@cc-market' in said
    assert 'claude plugin install rem@cc-market' in said


@pytest.mark.parametrize(
    ('env', 'plant'),
    [
        (_CLAUDE, lambda home: plant_claude_rem(home, '2.7.0', enabled=False)),
        (_CLAUDE, lambda home: plant_claude_rem(home, '2.7.0', enabled=None)),
        (_CODEX, lambda home: plant_codex_rem(home, '2.7.0', enabled=False)),
    ],
)
def test_a_disabled_rem_names_the_enable(tmp_path: Path, env: dict[str, str], plant: Plant) -> None:
    plant(tmp_path)
    said = remplugin.binder_door(env, tmp_path, tmp_path)
    assert said is not None
    assert 'enable rem@cc-market' in said


def test_the_project_settings_layer_overrides_the_users(tmp_path: Path) -> None:
    plant_claude_rem(tmp_path, '2.7.0', enabled=False)
    root = tmp_path / 'repo'
    (root / '.claude').mkdir(parents=True)
    (root / '.claude' / 'settings.local.json').write_text('{"enabledPlugins": {"rem@cc-market": true}}', 'utf-8')
    assert remplugin.binder_door(_CLAUDE, tmp_path, root) is None


@pytest.mark.parametrize(
    ('env', 'plant'),
    [
        (_CLAUDE, lambda home: plant_claude_rem(home, '2.7.0')),
        (_CODEX, lambda home: plant_codex_rem(home, '2.4.0', '2.10.1')),  # the newest cached release counts
    ],
)
def test_a_current_rem_leaves_the_task_prompt_door(tmp_path: Path, env: dict[str, str], plant: Plant) -> None:
    """PLANTED CONTROL: a binder new enough is not the cause, so the door is the user's `task:` prompt."""
    plant(tmp_path)
    assert remplugin.binder_door(env, tmp_path, tmp_path) is None


@pytest.mark.parametrize(
    ('env', 'plant'),
    [
        (_CLAUDE, lambda home: (home / '.claude' / 'plugins').mkdir(parents=True)),  # no registry file
        (_CLAUDE, lambda home: plant_claude_rem(home, 'not-a-version')),
        (_CODEX, lambda home: (home / '.codex').mkdir() or (home / '.codex' / 'config.toml').write_text('[[', 'utf-8')),
        ({}, lambda home: plant_claude_rem(home, '2.6.0')),  # no harness: an old rem it does not run is no cause
    ],
)
def test_an_unreadable_registry_keeps_the_plain_door(tmp_path: Path, env: dict[str, str], plant: Plant) -> None:
    plant(tmp_path)
    assert remplugin.binder_door(env, tmp_path, tmp_path) is None


def test_the_gate_names_the_skew_and_otherwise_the_task_prompt(tmp_path: Path) -> None:
    root, home = _repo(tmp_path), tmp_path / 'home'
    plant_claude_rem(home, '2.6.0')
    said = taskgate.refusal(root, env=_CLAUDE, branch='pr/toolchain/a', home=home) or ''
    assert taskgate.RULE in said
    assert 'none is bound' in said
    assert 'update rem to >= 2.7.0' in said
    plant_claude_rem(home, None)
    assert 'install rem@cc-market' in (taskgate.refusal(root, env=_CLAUDE, branch='pr/toolchain/a', home=home) or '')
    plant_claude_rem(home, '2.7.0')
    said = taskgate.refusal(root, env=_CLAUDE, branch='pr/toolchain/a', home=home) or ''
    assert taskbinding.DOOR in said, 'a current binder: the door is the `task:` prompt, as before'
    (home / '.claude' / 'plugins' / 'installed_plugins.json').write_text('{', encoding='utf-8')
    assert taskbinding.DOOR in (taskgate.refusal(root, env=_CLAUDE, branch='pr/toolchain/a', home=home) or '')


def test_the_gate_reads_and_never_writes_the_registries(tmp_path: Path) -> None:
    root, home = _repo(tmp_path), tmp_path / 'home'
    plant_claude_rem(home, '2.6.0')
    plant_codex_rem(home, '2.4.0')
    before = {path: path.read_bytes() for path in home.rglob('*') if path.is_file()}
    taskgate.refusal(root, env=_CLAUDE, branch='pr/toolchain/a', home=home)
    taskgate.refusal(root, env=_CODEX, branch='pr/toolchain/a', home=home)
    assert {path: path.read_bytes() for path in home.rglob('*') if path.is_file()} == before
