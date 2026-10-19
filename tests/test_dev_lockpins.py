"""LOCK PINS: an env is stale against the checkout's OWN uv.lock, never against a dependency's remote tip."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from lab_commons.dev import lockpins, verify
from lab_commons.dev.lockpins import (
    DEFAULT_DOOR,
    Installed,
    installed_git,
    lock_freshness,
    locked_git,
    mismatches,
    refusal,
    sync_door,
)
from lab_commons.dev.platformparts import BASE, part_context
from lab_commons.dev.producer import PRODUCING_VAR
from lab_commons.outcomes import Conclusion

_X, _Y = 'a' * 40, 'b' * 40
_URL = 'https://gitea.example.org/Team/lab-commons.git'


def _dist(name: str, direct_url: dict[str, object] | None) -> SimpleNamespace:
    text = None if direct_url is None else json.dumps(direct_url)
    return SimpleNamespace(metadata={'Name': name}, read_text=lambda _name: text)


def _lock(root: Path, commit: str) -> None:
    (root / 'uv.lock').write_text(
        'version = 1\n\n[[package]]\nname = "lab-commons"\nversion = "0.3"\n'
        f'source = {{ git = "{_URL}?rev={commit}#{commit}" }}\n\n'
        '[[package]]\nname = "numpy"\nversion = "2.0"\nsource = { registry = "https://pypi.org/simple" }\n',
        encoding='utf-8',
    )


def test_only_distributions_installed_from_git_are_read() -> None:
    vcs = {'url': _URL, 'vcs_info': {'vcs': 'git', 'commit_id': _X}}
    found = installed_git(
        lambda: [
            _dist('lab_commons', vcs),
            _dist('numpy', {'url': 'https://files/numpy.whl', 'archive_info': {}}),
            _dist('dep-b', {'url': 'file:///x', 'dir_info': {'editable': True}}),
            _dist('dep-c', None),
        ]
    )
    assert found == (Installed('lab-commons', _X),)


def test_the_lock_pins_git_packages_by_commit(tmp_path: Path) -> None:
    _lock(tmp_path, _X)
    assert locked_git(tmp_path / 'uv.lock') == {'lab-commons': _X}
    assert locked_git(tmp_path / 'absent.lock') == {}


def test_an_env_built_from_the_lock_is_fresh_whatever_the_tip(tmp_path: Path, monkeypatch) -> None:
    """THE DEFECT: the lock pins X, the env holds X, the dependency's tip is Y -- that is NOT stale."""
    _lock(tmp_path, _X)
    monkeypatch.setattr(lockpins, 'installed_git', lambda: (Installed('lab-commons', _X),))
    assert lock_freshness(tmp_path) is None


def test_an_env_that_differs_from_the_lock_is_stale(tmp_path: Path, monkeypatch) -> None:
    """PLANTED CONTROL: the lock pins Y, the env holds X."""
    _lock(tmp_path, _Y)
    monkeypatch.setattr(lockpins, 'installed_git', lambda: (Installed('lab-commons', _X),))
    text = lock_freshness(tmp_path)
    assert text is not None
    assert 'STALE' in text
    assert DEFAULT_DOOR in text
    assert f'uv.lock pins {_Y[:12]}' in text


def test_a_package_the_lock_does_not_pin_by_git_is_not_judged() -> None:
    assert mismatches([Installed('dep-b', _X)], {'lab-commons': _Y}) == ()
    assert refusal((), door='d') is None


def test_the_sync_door_is_the_repos_declaration_else_the_shared_one(tmp_path: Path) -> None:
    assert sync_door(tmp_path) == DEFAULT_DOOR
    (tmp_path / 'pyproject.toml').write_text(
        '[tool.lab_commons.doors]\nENV-MUTATION-THROUGH-THE-DOOR = "python scripts/gate/dep_sync.py --sync"\n',
        encoding='utf-8',
    )
    assert sync_door(tmp_path) == 'python scripts/gate/dep_sync.py --sync'


def test_verify_refuses_a_stale_environment_before_anything_runs(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setenv(PRODUCING_VAR, f'{part_context(BASE)}@planted')  # the full suite is the producer's
    monkeypatch.setattr(verify, 'project_root', lambda: tmp_path)
    monkeypatch.setattr(verify, 'run_verify', lambda *_a, **_k: pytest.fail('a stale environment ran'))
    _lock(tmp_path, _Y)
    monkeypatch.setattr(lockpins, 'installed_git', lambda: (Installed('lab-commons', _X),))
    monkeypatch.setenv('LAB_COMMONS_RESOURCE_DIR', str(tmp_path))
    assert verify.main([]) == verify.EXIT_CODES[Conclusion.INCONCLUSIVE]
    assert 'STALE' in capsys.readouterr().err
