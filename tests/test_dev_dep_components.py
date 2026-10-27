"""A COMPONENT WHOSE TREE MOVED IS REINSTALLED ON EVERY SYNC -- derived from evidence, never remembered.

INCIDENT (motronics, 2026-10-19): ``components/numerics-lab`` moved to a commit adding a symbol, its
``uv.lock`` source is ``{ directory = ... }`` installed non-editable at an unchanged version string, and
``dep --sync``, ``--upgrade-package`` and ``--bootstrap`` all exited 0 leaving the OLD module installed. The
door now stamps each ``[tool.dev_lab.components]`` package's tree (git HEAD, plus its diff when dirty)
into the venv after a sync, and passes ``--reinstall-package`` for exactly those whose stamp moved.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

from dev_lab.dev import dep
from dev_lab.dev._dep_components import changed, record

_GIT = shutil.which('git') or 'git'
_PYPROJECT = (
    '[project]\nname="product"\nversion="0"\n'
    '[tool.dev_lab.components.numerics-lab]\n'
    'url = "https://forge.invalid/o/numerics-lab.git"\nbranch = "main"\nparts = ["base"]\npackage = "numerics-lab"\n'
)


def _git(cwd: Path, *args: str) -> None:
    subprocess.run([_GIT, '-C', str(cwd), *args], check=True, capture_output=True)


def _commit(engine: Path, text: str) -> None:
    (engine / 'line_search.py').write_text(text, encoding='utf-8')
    _git(engine, 'add', '-A')
    _git(engine, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '-m', text)


def _product(tmp_path: Path) -> tuple[Path, Path]:
    (tmp_path / 'pyproject.toml').write_text(_PYPROJECT, encoding='utf-8')
    engine = tmp_path / 'components' / 'numerics-lab'
    engine.mkdir(parents=True)
    _git(engine, 'init', '-q')
    _commit(engine, 'old = 1\n')
    return tmp_path, engine


def test_a_moved_component_is_named_and_an_unmoved_one_is_not(tmp_path: Path) -> None:
    """PLANTED both ways, and dirty edits count as a move."""
    root, engine = _product(tmp_path)
    prefix = tmp_path / '.venv'
    prefix.mkdir()
    assert changed(root, prefix) == ('numerics-lab',), 'never stamped: reinstall'
    record(root, prefix)
    assert changed(root, prefix) == ()
    _commit(engine, 'old = 1\nclass TrialNotEvaluable(Exception): ...\n')
    assert changed(root, prefix) == ('numerics-lab',)
    record(root, prefix)
    assert changed(root, prefix) == ()
    (engine / 'line_search.py').write_text('edited = 2\n', encoding='utf-8')
    assert changed(root, prefix) == ('numerics-lab',)


def test_every_sync_reinstalls_exactly_the_moved_component(tmp_path: Path) -> None:
    """Through the door: --reinstall-package on the first sync and after a move, absent in between."""
    root, engine = _product(tmp_path)
    calls: list[tuple[str, ...]] = []

    def run(argv: list[str], **_kwargs: object) -> SimpleNamespace:
        calls.append(tuple(argv))
        return SimpleNamespace(returncode=0, stdout='', stderr='')

    def reinstalled() -> list[str]:
        command = next(c for c in reversed(calls) if 'sync' in c)  # the sync, not the auto-mode refresh after it
        return [command[i + 1] for i, flag in enumerate(command) if flag == '--reinstall-package']

    assert dep.main(['--sync'], cwd=root, run=run) == 0
    assert reinstalled() == ['numerics-lab']
    assert dep.main(['--sync'], cwd=root, run=run) == 0
    assert reinstalled() == []
    _commit(engine, 'new = 2\n')
    assert dep.main(['--sync'], cwd=root, run=run) == 0
    assert reinstalled() == ['numerics-lab']


def test_a_failed_sync_records_nothing_so_the_next_one_reinstalls_again(tmp_path: Path) -> None:
    root, _engine = _product(tmp_path)
    calls: list[tuple[str, ...]] = []

    def run(argv: list[str], **_kwargs: object) -> SimpleNamespace:
        calls.append(tuple(argv))
        return SimpleNamespace(returncode=0 if len(calls) > 3 else 2, stdout='', stderr='')

    assert dep.main(['--sync'], cwd=root, run=run) == 2
    assert changed(root, root / '.venv') == ('numerics-lab',)


def test_an_edit_to_an_untracked_file_moves_the_stamp(tmp_path: Path) -> None:
    """The stamp hashes an untracked file's CONTENT, not only its name."""
    root, engine = _product(tmp_path)
    prefix = tmp_path / '.venv'
    prefix.mkdir()
    (engine / 'probe.py').write_text('a = 1\n', encoding='utf-8')
    record(root, prefix)
    assert changed(root, prefix) == ()
    (engine / 'probe.py').write_text('a = 2\n', encoding='utf-8')
    assert changed(root, prefix) == ('numerics-lab',)
