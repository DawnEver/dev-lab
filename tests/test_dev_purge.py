"""``dev_lab.dev.purge`` -- one door deletes one git-ignored, untracked path (user rulings 2026-11-23).

PLANTED CONTROLS: every refusal has a path built to trip it, beside a path built to pass, so a door that refused
everything (or nothing) reds here: outside the checkout, the checkout itself, missing, tracked, untracked but not
ignored, a declared read_only path (and its parent), a declared store (and a path inside one), an undeclared
placement, an unclassified/unlanded bundle or patch, and an over-limit tree.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from dev_lab.dev import purge

_PYPROJECT = """
[tool.dev_lab.parts]
output = "output/logs"
[tool.dev_lab.placement]
read_only = ["temp", "attic"]
stores = ["output/cas"]
scratch = "scratch/"
"""


def _git(root: Path, *args: str) -> None:
    subprocess.run(['git', '-C', str(root), *args], check=True, capture_output=True)  # noqa: S607


def _write(path: Path, text: str = 'x') -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')
    return path


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A checkout with a tracked file, an ignored copy, a store, read-only input and parked work."""
    monkeypatch.setattr(purge.datedlog, 'dated_base', lambda root, base, **_: root / base)
    root = tmp_path / 'repo'
    root.mkdir()
    _git(root, 'init', '-q')
    _write(root / 'pyproject.toml', _PYPROJECT)
    _write(root / '.gitignore', 'output/\ntemp/\nwip-ignored/\n')
    _write(root / 'attic' / 'old.py')
    _write(root / 'output' / 'tracked.txt')
    _git(root, 'add', 'pyproject.toml', '.gitignore', 'attic/old.py')
    _git(root, 'add', '-f', 'output/tracked.txt')
    _git(root, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '-m', 'init')
    _write(root / 'output' / 'copy' / 'a' / 'b.txt', 'hello')
    _write(root / 'output' / 'copy' / 'c.txt', 'abc')
    _write(root / 'output' / 'cas' / 'k' / 'blob')
    _write(root / 'temp' / 'input.csv')
    _write(root / 'wip' / 'draft.py')
    _write(root / 'output' / 'parked' / 'lane.bundle')
    _write(root / 'output' / 'parked' / 'fix.patch')
    return root


def _record(root: Path, rows: dict[str, str]) -> None:
    lines = '\n'.join(json.dumps({'path': p, 'cls': c}) for p, c in rows.items())
    _write(root / 'output' / 'logs' / '26' / '11' / '24' / 'merge-check' / 'table.jsonl', lines + '\n')


def test_an_ignored_untracked_copy_is_counted_and_removed(repo: Path) -> None:
    plan = purge.plan(repo, 'output/copy')
    assert (len(plan.leaves), len(plan.dirs), plan.size) == (2, 2, 8)
    assert (repo / 'output' / 'copy').exists()  # the plan is a dry run
    assert purge.apply(plan) == []
    assert not (repo / 'output' / 'copy').exists()
    assert (repo / 'output' / 'tracked.txt').exists()
    log = next((repo / 'output' / 'logs').rglob('purge/*.jsonl'))
    assert json.loads(log.read_text(encoding='utf-8').splitlines()[-1])['files'] == 2


@pytest.mark.parametrize(
    ('rel', 'cause'),
    [
        ('../outside', 'outside the checkout'),
        ('.', 'outside the checkout'),
        ('output/nothing-here', 'does not exist'),
        ('output', 'tracked'),
        ('attic', 'tracked'),
        ('wip', 'not git-ignored'),
        ('temp', 'read_only'),
        ('temp/input.csv', 'read_only'),
        ('output/cas', 'stores'),
        ('output/cas/k', 'stores'),
    ],
)
def test_every_refusal_names_its_cause_and_door(repo: Path, rel: str, cause: str) -> None:
    (repo.parent / 'outside').mkdir(exist_ok=True)
    with pytest.raises(purge.PurgeRefused, match=cause) as refused:
        purge.plan(repo, rel)
    assert 'Door' in str(refused.value)


def test_a_parent_of_a_store_is_refused(repo: Path) -> None:
    _write(repo / '.gitignore', 'output/\ntemp/\n')
    (repo / 'output' / 'tracked.txt').unlink()
    _git(repo, 'rm', '-q', '--cached', 'output/tracked.txt')
    with pytest.raises(purge.PurgeRefused, match='stores'):
        purge.plan(repo, 'output')


def test_an_undeclared_placement_is_refused(repo: Path) -> None:
    _write(repo / 'pyproject.toml', '[tool.dev_lab.parts]\noutput = "output/logs"\n')
    with pytest.raises(purge.PurgeRefused, match='declares no'):
        purge.plan(repo, 'output/copy')


@pytest.mark.parametrize(
    ('rows', 'still_open'),
    [
        ({}, 'no record'),
        ({'output/parked/lane.bundle': 'landed'}, 'fix.patch (no record)'),
        ({'output/parked/lane.bundle': 'landed', 'output/parked/fix.patch': 'unlanded'}, 'fix.patch (unlanded)'),
        ({'output/parked/lane.bundle': 'error', 'output/parked/fix.patch': 'superseded'}, 'lane.bundle (error)'),
    ],
)
def test_parked_work_no_merge_check_cleared_is_refused(repo: Path, rows: dict[str, str], still_open: str) -> None:
    _record(repo, rows)
    with pytest.raises(purge.PurgeRefused, match='no merge check cleared') as refused:
        purge.plan(repo, 'output/parked')
    assert still_open in str(refused.value)


def test_parked_work_cleared_by_the_record_goes(repo: Path) -> None:
    _record(repo, {'output/parked/lane.bundle': 'landed', 'output/parked/fix.patch': 'superseded'})
    assert len(purge.plan(repo, 'output/parked').leaves) == 2


def test_the_removal_is_bounded(repo: Path) -> None:
    with pytest.raises(purge.PurgeRefused, match='--limit'):
        purge.plan(repo, 'output/copy', limit=2)
    assert len(purge.plan(repo, 'output/copy', limit=4).leaves) == 2


def test_a_junction_or_link_inside_is_unlinked_never_followed(repo: Path, tmp_path: Path) -> None:
    keep = _write(tmp_path / 'elsewhere' / 'keep.txt')
    link = repo / 'output' / 'copy' / 'link'
    try:
        link.symlink_to(keep.parent, target_is_directory=True)
    except OSError:
        subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(keep.parent)], check=True, capture_output=True)  # noqa: S607
    plan = purge.plan(repo, 'output/copy')
    assert link in plan.leaves
    assert purge.apply(plan) == []
    assert keep.exists()


def test_the_declared_scratch_is_purgeable_though_not_ignored(repo: Path) -> None:
    """Scratch is declared never-tracked (SCRATCH-IS-NEVER-COMMITTED); unignored ``wip/`` stays refused above."""
    _write(repo / 'scratch' / 'mirror.git' / 'HEAD')
    assert len(purge.plan(repo, 'scratch/mirror.git').leaves) == 1
    with pytest.raises(purge.PurgeRefused, match='outside the checkout'):
        purge.plan(repo, 'scratch/../..')


def test_the_cli_dry_run_prints_counts_and_deletes_nothing(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert purge.main(['--root', str(repo), '--path', 'output/copy']) == 0
    assert 'would purge output/copy: 2 files, 2 directories, 8 bytes' in capsys.readouterr().out
    assert (repo / 'output' / 'copy').exists()
    assert purge.main(['--root', str(repo), '--path', 'wip']) == 1
    assert 'not git-ignored' in capsys.readouterr().err
