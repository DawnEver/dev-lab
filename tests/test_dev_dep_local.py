"""A LOCAL SIBLING IS A DECLARED OVERLAY ON THE LOCKED ENVIRONMENT -- and nothing else is.

User directive 2026-11-05: an environment is the LOCK by default; a family sibling's local checkout replaces
its locked version only when declared (the machine file's ``[dep] local``, or ``dep --local NAME``), and only
through this door. The overlay is installed after the sync inside the same seat, announced on every sync, and
folded into the key the door compares, because an editable checkout at the locked commit reports the same
version and would otherwise move nothing.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import pytest

from dev_lab.dev import dep
from dev_lab.dev._dep_local import STAMP_FILE, Overlay, OverlayRefused, declared, install_command, resolve

_GIT = shutil.which('git') or 'git'
_LOCK = '[[package]]\nname = "lab-commons"\nversion = "0.3"\n\n[[package]]\nname = "product"\nversion = "0"\n'


def _product(tmp_path: Path) -> Path:
    root = tmp_path / 'product'
    root.mkdir()
    (root / 'pyproject.toml').write_text('[project]\nname="product"\nversion="0"\n', encoding='utf-8')
    (root / 'uv.lock').write_text(_LOCK, encoding='utf-8')
    return root


def _sibling(tmp_path: Path, name: str = 'lab-commons', project: str | None = None) -> Path:
    path = tmp_path / name
    path.mkdir()
    (path / 'pyproject.toml').write_text(f'[project]\nname="{project or name}"\nversion="0"\n', encoding='utf-8')
    subprocess.run([_GIT, '-C', str(path), 'init', '-q'], check=True)
    return path


def test_the_declaration_is_the_machine_list_plus_the_run_list_once_each() -> None:
    assert declared(['ai-lab', 'lab-commons'], {'local': ['lab-commons']}) == ('lab-commons', 'ai-lab')
    assert declared([], {}) == ()


def test_a_declaration_that_is_not_a_list_of_names_is_refused() -> None:
    with pytest.raises(OverlayRefused, match=r'\[dep\] local'):
        declared([], {'local': 'lab-commons'})


def test_the_path_is_the_machine_repos_entry_else_beside_the_family(tmp_path: Path) -> None:
    root = _product(tmp_path)
    beside = _sibling(tmp_path)
    assert resolve(root, ('lab-commons',), repos={}, family=tmp_path) == (Overlay('lab-commons', beside),)
    (tmp_path / 'elsewhere').mkdir()
    elsewhere = _sibling(tmp_path / 'elsewhere')
    assert resolve(root, ('lab-commons',), repos={'lab-commons': str(elsewhere)}, family=tmp_path / 'none') == (
        Overlay('lab-commons', elsewhere),
    )


@pytest.mark.parametrize(
    ('name', 'setup', 'says'),
    [
        ('numpy-lab', lambda _tmp: None, 'not a package in'),  # PLANTED: not in the lock
        ('lab-commons', lambda _tmp: None, 'no checkout'),  # PLANTED: nothing beside the family
        ('lab-commons', lambda tmp: _sibling(tmp, project='other'), 'names other'),  # PLANTED: wrong distribution
    ],
)
def test_an_overlay_that_cannot_be_what_it_claims_is_refused_naming_the_fix(tmp_path, name, setup, says) -> None:
    root = _product(tmp_path)
    setup(tmp_path)
    with pytest.raises(OverlayRefused, match=says):
        resolve(root, (name,), repos={}, family=tmp_path)


def test_the_overlay_is_editable_and_never_resolves_a_dependency(tmp_path: Path) -> None:
    command = install_command('uv', 'py', (Overlay('lab-commons', tmp_path / 'lab-commons'),))
    assert command == ['uv', 'pip', 'install', '--python', 'py', '--no-deps', '-e', str(tmp_path / 'lab-commons')]


def _door(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, list[tuple[str, ...]]]:
    root = _product(tmp_path)
    _sibling(tmp_path)
    monkeypatch.setattr(dep, 'family_root', lambda _root: tmp_path)
    calls: list[tuple[str, ...]] = []
    return root, calls


def _runner(calls: list[tuple[str, ...]]) -> Callable[..., SimpleNamespace]:
    def run(argv: list[str], **_kwargs: object) -> SimpleNamespace:
        calls.append(tuple(argv))
        return SimpleNamespace(returncode=0, stdout='', stderr='')

    return run


def test_with_nothing_declared_the_door_installs_the_lock_alone(tmp_path, monkeypatch) -> None:
    root, calls = _door(tmp_path, monkeypatch)
    assert dep.main(['--sync'], cwd=root, run=_runner(calls), machine=lambda _name: {}) == 0
    assert not [c for c in calls if 'pip' in c]
    assert not (root / '.venv' / STAMP_FILE).exists()


def test_a_declared_sibling_is_overlaid_after_the_sync_and_announced(tmp_path, monkeypatch, capsys) -> None:
    root, calls = _door(tmp_path, monkeypatch)
    machine = {'dep': {'local': ['lab-commons']}, 'repos': {}}
    assert dep.main(['--sync'], cwd=root, run=_runner(calls), machine=lambda name: machine.get(name, {})) == 0
    syncs = [i for i, c in enumerate(calls) if 'sync' in c]
    overlays = [i for i, c in enumerate(calls) if 'pip' in c]
    assert syncs
    assert overlays
    assert syncs[0] < overlays[0], 'the overlay lands on the synced lock, never under it'
    assert str(tmp_path / 'lab-commons') in calls[overlays[0]]
    assert 'LOCAL OVERLAY: lab-commons ->' in capsys.readouterr().out
    assert (root / '.venv' / STAMP_FILE).is_file()


def test_the_run_flag_declares_an_overlay_for_one_run(tmp_path, monkeypatch) -> None:
    root, calls = _door(tmp_path, monkeypatch)
    assert dep.main(['--sync', '--local', 'lab-commons'], cwd=root, run=_runner(calls), machine=lambda _n: {}) == 0
    assert [c for c in calls if 'pip' in c]


def test_dropping_the_declaration_is_the_revert(tmp_path, monkeypatch) -> None:
    root, calls = _door(tmp_path, monkeypatch)
    assert dep.main(['--sync', '--local', 'lab-commons'], cwd=root, run=_runner(calls), machine=lambda _n: {}) == 0
    calls.clear()
    assert dep.main(['--sync'], cwd=root, run=_runner(calls), machine=lambda _n: {}) == 0
    assert not [c for c in calls if 'pip' in c]
    assert not (root / '.venv' / STAMP_FILE).exists(), 'the stamp goes with the overlay'


def test_the_key_the_door_compares_moves_with_the_overlay(tmp_path, monkeypatch) -> None:
    """PLANTED: the versions are identical, so only the overlay stamp can move the key."""
    root, calls = _door(tmp_path, monkeypatch)
    monkeypatch.setattr(dep, '_snapshot', lambda _python: ('', 'same-versions'))
    keys: list[tuple[str, str]] = []
    real = dep._change

    def spy(*args: object, **kwargs: object) -> dep.Report:
        report = real(*args, **kwargs)
        keys.append((report.before, report.after))
        return report

    monkeypatch.setattr(dep, '_change', spy)
    (root / '.venv').mkdir()
    (root / '.venv' / 'Scripts').mkdir()
    for python in ('Scripts/python.exe', 'bin/python'):
        (root / '.venv' / python).parent.mkdir(parents=True, exist_ok=True)
        (root / '.venv' / python).write_bytes(b'')
    monkeypatch.setattr(dep, '_snapshot', lambda _python: (str(root / '.venv'), 'same-versions'))
    assert dep.main(['--sync', '--local', 'lab-commons'], cwd=root, run=_runner(calls), machine=lambda _n: {}) == 0
    assert dep.main(['--sync'], cwd=root, run=_runner(calls), machine=lambda _n: {}) == 0
    (on_before, on_after), (off_before, off_after) = keys
    assert on_before != on_after, 'adding an overlay must move the key'
    assert off_before != off_after, 'removing it must move the key back'
    assert on_before == off_after
