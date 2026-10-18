"""PIN + FRESHNESS (user ruling 2026-10-17): a pushed commit commits ``uv.lock`` at the NEWEST resolution.

Driven on REAL planted repositories with the REAL ``uv``, read at the pushed sha and offline: the in-house git
dependency is a local repository, and the PyPI-shaped one a find-links directory of planted wheels. Each
refusal has a planted control that passes.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from lab_commons.dev.githooks.table import base_rows
from lab_commons.dev.lockcheck import REMEDY, lock_problems, main, pushed_shas, unreasoned_holds

_GIT = shutil.which('git') or 'git'
_UV = shutil.which('uv') or 'uv'


def _run(cwd: Path, *argv: str) -> str:
    done = subprocess.run(
        list(argv), cwd=cwd, check=False, capture_output=True, text=True, encoding='utf-8', timeout=300
    )  # fmt: skip
    assert done.returncode == 0, f'{argv} exited {done.returncode}: {done.stderr}'
    return done.stdout.strip()


def _git(root: Path, *argv: str) -> str:
    return _run(root, _GIT, '-c', 'user.name=t', '-c', 'user.email=t@t', *argv)


def _commit(root: Path, files: dict[str, str]) -> str:
    for name, text in files.items():
        (root / name).write_text(text, encoding='utf-8')
    _git(root, 'add', '-A')
    _git(root, 'commit', '-q', '--allow-empty', '-m', 'c')
    return _git(root, 'rev-parse', 'HEAD')


def _wheel(index: Path, version: str) -> None:
    info = f'dep-{version}.dist-info'
    with zipfile.ZipFile(index / f'dep-{version}-py3-none-any.whl', 'w') as wheel:
        wheel.writestr('dep/__init__.py', '')
        wheel.writestr(f'{info}/METADATA', f'Metadata-Version: 2.1\nName: dep\nVersion: {version}\n')
        wheel.writestr(f'{info}/WHEEL', 'Wheel-Version: 1.0\nGenerator: t\nRoot-Is-Purelib: true\nTag: py3-none-any\n')
        wheel.writestr(f'{info}/RECORD', '')


def _manifest(kit: Path, index: Path, dep: str) -> str:
    return f"""[project]
name = "planted"
version = "0"
requires-python = ">=3.12"
dependencies = [
    "kit @ git+{kit.as_uri()}",
    {dep}
]

[tool.uv]
no-index = true
find-links = ["{index.as_posix()}"]
"""


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, Path]:
    """``(consumer, kit, index)``: a consumer of an in-house git ``kit`` and a PyPI-shaped ``dep`` (1.0 only)."""
    monkeypatch.setenv('UV_CACHE_DIR', str(tmp_path / 'uv-cache'))
    monkeypatch.setenv('UV_PYTHON', sys.executable)
    kit, index, root = tmp_path / 'kit', tmp_path / 'index', tmp_path / 'consumer'
    for path in (kit, index, root):
        path.mkdir()
    _git(kit, 'init', '-q', '-b', 'main')
    _commit(kit, {'pyproject.toml': '[project]\nname = "kit"\nversion = "1.0"\n'})
    _wheel(index, '1.0')
    _git(root, 'init', '-q', '-b', 'main')
    return root, kit, index


def _locked(root: Path, manifest: str, *, upgrade: bool = False) -> str:
    (root / 'pyproject.toml').write_text(manifest, encoding='utf-8')
    _run(root, _UV, 'lock', *(['--upgrade'] if upgrade else []))
    return _commit(root, {})


def test_a_stale_in_house_pin_is_refused_and_the_newest_admitted(world: tuple[Path, Path, Path]) -> None:
    """PLANTED: the kit moves after the lock pinned it -- refused naming it; `uv lock --upgrade` admits."""
    root, kit, index = world
    pinned = _locked(root, _manifest(kit, index, '"dep",'))
    assert lock_problems(root, pinned) == (), 'CONTROL: a lock at the newest resolution is admitted'
    _commit(kit, {'README': 'moved'})
    (why,) = lock_problems(root, pinned)
    assert why.startswith('uv.lock is not the newest resolution: Update kit'), why
    assert lock_problems(root, _locked(root, _manifest(kit, index, '"dep",'), upgrade=True)) == ()


def test_pypi_is_held_at_latest_unless_a_declared_range_says_why(world: tuple[Path, Path, Path]) -> None:
    """PLANTED: dep 2.0 is published. Unheld -> refused; a reasoned `<2` -> admitted; an unreasoned one -> refused."""
    root, kit, index = world
    old = _locked(root, _manifest(kit, index, '"dep",'))
    _wheel(index, '2.0')
    (why,) = lock_problems(root, old)
    assert 'Update dep' in why, why
    reasoned = _locked(root, _manifest(kit, index, '"dep<2",  # planted: 2.0 breaks the ABI'))
    assert lock_problems(root, reasoned) == (), 'a reasoned range is admitted below latest'
    bare = _locked(root, _manifest(kit, index, '"dep<2",'))
    (why,) = lock_problems(root, bare)
    assert why == 'line 7: "dep<2" holds a requirement below the newest with no reason'


def test_a_resolution_that_cannot_reach_its_source_refuses_with_its_diagnosis(world: tuple[Path, Path, Path]) -> None:
    """PLANTED: the in-house source vanishes (the network is down) -- refused, never admitted unjudged."""
    root, kit, index = world
    sha = _locked(root, _manifest(kit, index, '"dep",'))
    shutil.rmtree(kit, onexc=lambda func, path, _: (Path(path).chmod(0o700), func(path)))
    (why,) = lock_problems(root, sha)
    assert why.startswith('the newest resolution could not run ('), why
    assert 'REFUSED' in why or 'gave up' in why, 'the netverb diagnosis is carried'


def test_a_pushed_sha_other_than_head_is_judged_at_that_sha(world: tuple[Path, Path, Path]) -> None:
    root, kit, index = world
    stale = _locked(root, _manifest(kit, index, '"dep",'))
    _commit(kit, {'README': 'moved'})
    fresh = _locked(root, _manifest(kit, index, '"dep",'), upgrade=True)
    _git(root, 'checkout', '-q', stale)
    assert lock_problems(root, fresh) == (), 'judged in a worktree at the pushed sha, not the checkout'
    assert not (Path(_git(root, 'rev-parse', '--git-common-dir')) / 'lockcheck' / fresh[:12]).exists()


def test_no_lock_is_refused_and_a_deletion_only_push_is_never_judged(tmp_path: Path, capsys) -> None:
    root = tmp_path / 'r'
    root.mkdir()
    _git(root, 'init', '-q', '-b', 'main')
    bare = _commit(root, {'pyproject.toml': '[project]\nname = "x"\nversion = "0"\n'})
    assert lock_problems(root, bare) == (
        f'{bare[:12]} commits no uv.lock: its environment would be whatever resolves on the day',
    )

    def never(_tree: Path) -> object:
        msg = 'a deletion must not resolve anything'
        raise AssertionError(msg)

    deletion = f'(delete) {"0" * 40} refs/heads/x {bare}'
    assert pushed_shas([deletion, f'refs/tags/t {bare} refs/tags/t {"0" * 40}']) == ()
    assert main([str(root)], lines=[deletion], resolve=never) == 0, 'a deletion-only push is exempt'
    assert main([str(root)], lines=[f'refs/heads/x {bare} refs/heads/x {"0" * 40}'], resolve=never) == 1
    assert REMEDY in capsys.readouterr().err
    assert REMEDY.count('uv lock --upgrade') == 1


def test_a_hold_names_its_reason_on_its_line_or_the_line_above() -> None:
    text = (
        'requires-python = ">=3.13,<3.14"\n'
        '# `<3.14`: the pyo3 ABI\n'
        'requires-python = ">=3.13,<3.14"\n'
        'dependencies = ["a>=1", "b==2", "c~=1.0  ; python_version < \'3.13\'", "d!=3"]\n'
        'x = ["lab @ git+https://h/o/lab.git@' + 'a' * 40 + '", "lab @ git+https://h/o/lab.git"]\n'
        'install = "uv sync --frozen --all-extras"  # a reason-free non-requirement\n'
        'y = ["e<2"]  # held: e 2 drops Windows\n'
    )
    assert unreasoned_holds(text) == (
        'line 1: ">=3.13,<3.14"',
        'line 4: "b==2"',
        'line 4: "c~=1.0  ; python_version < \'3.13\'"',
        f'line 5: "lab @ git+https://h/o/lab.git@{"a" * 40}"',
    )


def test_the_family_hook_base_runs_the_lock_check_at_push() -> None:
    rows = {row['id']: row for row in base_rows()['pre-push']}
    assert rows['lock']['run'] == ['python', '-m', 'lab_commons.dev.lockcheck']
