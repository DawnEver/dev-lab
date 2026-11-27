"""``dep --sync`` installs exactly the committed ``uv.lock`` and never writes it (user ruling 2026-11-27).

Before: ``--sync`` was an unfrozen ``uv sync`` adding ``--upgrade-package`` for every floating family requirement,
so every sync relocked -- agents running it to "match the env" left unexplained ``uv.lock`` diffs in lanes. Moving
a family kit is a relock: ``--lock-upgrade ROOT --upgrade-package <kit>``, whose seated sync then builds it.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import pytest

from dev_lab.dev import _dep_project, dep
from dev_lab.dev.lockcheck import uv_version

_LOCK = 'version = 1\n[[package]]\nname = "dev-lab"\nversion = "1"\nsource = { git = "https://x/dev-lab?rev=aaa" }\n'


def _project(root: Path) -> bytes:
    (root / 'pyproject.toml').write_text(
        '[project]\nname="empty"\nversion="0"\ndependencies=["dev-lab @ git+https://x/dev-lab"]\n'
        '[tool.dev_lab.dep]\nextras=[]\n[project.optional-dependencies]\ndev=[]\n',
        encoding='utf-8',
    )
    (root / 'uv.lock').write_text(_LOCK, encoding='utf-8')
    return (root / 'uv.lock').read_bytes()


def _runner(calls: list[tuple[str, ...]], *, sync: int = 0, check: int = 0) -> Callable[..., SimpleNamespace]:
    def run(argv, **_kwargs: object) -> SimpleNamespace:
        calls.append(tuple(argv))
        code = check if argv[1:3] == ['lock', '--check'] else sync if argv[1] == 'sync' else 0
        return SimpleNamespace(returncode=code, stdout='', stderr='')

    return run


def _verb(calls: list[tuple[str, ...]], verb: str) -> list[tuple[str, ...]]:
    return [call for call in calls if call[1:2] == (verb,)]


def test_a_sync_installs_the_committed_lock_and_leaves_it_byte_identical(tmp_path: Path) -> None:
    lock = _project(tmp_path)
    calls: list[tuple[str, ...]] = []
    assert dep.main(['--sync'], cwd=tmp_path, run=_runner(calls)) == 0
    (sync,) = _verb(calls, 'sync')
    assert '--locked' in sync
    assert '--upgrade-package' not in sync, 'a sync moves no floating family requirement'
    assert not _verb(calls, 'lock'), 'a sync never relocks'
    assert (tmp_path / 'uv.lock').read_bytes() == lock


def test_planted_control_a_relock_does_move_the_lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """PLANTED CONTROL: the instrument above can say no -- the relock door does write, under the pinned uv."""
    _project(tmp_path)
    monkeypatch.setattr(_dep_project, 'installed_uv_version', lambda _uv: uv_version())
    calls: list[tuple[str, ...]] = []
    assert dep.main(['--lock-upgrade', '--upgrade-package', 'dev-lab'], cwd=tmp_path, run=_runner(calls)) == 0
    (lock,) = _verb(calls, 'lock')
    assert '--check' not in lock


def test_a_stale_lock_is_refused_by_name_with_the_relock_door(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    lock = _project(tmp_path)
    calls: list[tuple[str, ...]] = []
    assert dep.main(['--sync'], cwd=tmp_path, run=_runner(calls, sync=2, check=1)) != 0
    out = capsys.readouterr().out
    assert 'REFUSED' in out
    assert f'--lock-upgrade {tmp_path}' in out
    assert ('lock', '--check') in {call[1:3] for call in calls}
    assert (tmp_path / 'uv.lock').read_bytes() == lock


def test_planted_control_a_sync_failing_for_another_cause_names_no_relock(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """PLANTED CONTROL: a sync that fails while its lock still matches is not blamed on the lock."""
    _project(tmp_path)
    assert dep.main(['--sync'], cwd=tmp_path, run=_runner([], sync=2, check=0)) != 0
    assert '--lock-upgrade' not in capsys.readouterr().out


def test_the_family_path_moves_the_kit_and_its_floor_then_builds_the_new_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _project(tmp_path)
    monkeypatch.setattr(_dep_project, 'installed_uv_version', lambda _uv: uv_version())
    calls: list[tuple[str, ...]] = []
    assert dep.main(['--lock-upgrade', '--upgrade-package', 'dev-lab'], cwd=tmp_path, run=_runner(calls)) == 0
    (lock,) = _verb(calls, 'lock')
    moved = {lock[i + 1] for i, word in enumerate(lock) if word == '--upgrade-package'}
    assert moved == {'dev-lab', 'lab-commons'}
    (sync,) = _verb(calls, 'sync')
    assert '--frozen' in sync
    assert calls.index(lock) < calls.index(sync)


@pytest.mark.parametrize(
    'argv', [['--sync', '--upgrade-package', 'dev-lab'], ['--bootstrap', '.', '--upgrade-package', 'x']]
)
def test_a_sync_naming_a_package_to_move_is_refused_naming_the_relock(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], argv: list[str]
) -> None:
    _project(tmp_path)
    with pytest.raises(SystemExit):
        dep.main(argv, cwd=tmp_path, run=_runner([]))
    assert '--lock-upgrade' in capsys.readouterr().err
