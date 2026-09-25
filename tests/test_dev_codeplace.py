"""``lab_commons.dev.codeplace``: the code-root allow-list and the scratch lifecycle, on planted trees."""

from __future__ import annotations

import datetime
import os
import time

import pytest

from lab_commons.dev.codeplace import archive_scratch, misplaced_code, overdue_scratch, pending_scratch

_ROOTS = ('src/', 'tests/', 'scratch/', '.claude/memory/')
_DAY = 86400.0


def _plant(root, rel: str, *, age_days: float = 0.0) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('x\n', encoding='utf-8')
    stamp = time.time() - age_days * _DAY
    os.utime(path, (stamp, stamp))


@pytest.mark.parametrize(
    ('path', 'misplaced'),
    [
        ('output/logs/26/09/25/probe.py', True),
        ('cases/x/drive.rs', True),
        ('run_me.ps1', True),
        ('docs-src/snippet.sh', True),
        ('src/pkg/x.py', False),
        ('scratch/try.py', False),
        ('.claude/memory/2026/09/25/attachments/probe.py', False),
        ('output/logs/26/09/25/table.csv', False),
    ],
)
def test_the_allow_list_refuses_and_admits_each_planted_shape(tmp_path, path, misplaced) -> None:
    _plant(tmp_path, path)
    assert (misplaced_code(tmp_path, code_roots=_ROOTS) == [path]) is misplaced


def test_pruned_directories_are_not_walked(tmp_path) -> None:
    for rel in ('.venv/Lib/site.py', 'rust/target/debug/build.rs', 'worktrees/lane/output/x.py'):
        _plant(tmp_path, rel)
    assert misplaced_code(tmp_path, code_roots=_ROOTS, pruned_paths=('worktrees',)) == []


def test_an_empty_allow_list_is_REFUSED_rather_than_refusing_everything(tmp_path) -> None:
    with pytest.raises(ValueError, match='code roots'):
        misplaced_code(tmp_path, code_roots=())


def test_only_a_file_older_than_the_limit_is_overdue(tmp_path) -> None:
    _plant(tmp_path, 'scratch/fresh.py', age_days=0.5)
    _plant(tmp_path, 'scratch/sub/old.py', age_days=4.0)
    scratch = tmp_path / 'scratch'
    assert overdue_scratch(scratch, root=tmp_path, max_age_days=3.0) == ['scratch/sub/old.py']
    assert [p for p, _ in pending_scratch(scratch, root=tmp_path)] == ['scratch/sub/old.py', 'scratch/fresh.py']
    assert pending_scratch(tmp_path / 'absent', root=tmp_path) == []


def test_an_archive_lands_beside_that_days_memory_and_records_why(tmp_path) -> None:
    _plant(tmp_path, 'scratch/probe.py')
    memory = tmp_path / '.claude' / 'memory'
    dest = archive_scratch(
        tmp_path / 'scratch/probe.py', why='read the card back', root=tmp_path, memory=memory,
        day=datetime.date(2026, 9, 25),
    )  # fmt: skip
    assert dest == memory / '2026/09/25/attachments/probe.py'
    assert not (tmp_path / 'scratch/probe.py').exists()
    assert '`probe.py` -- read the card back (from `scratch/probe.py`)' in (dest.parent / 'INDEX.md').read_text(
        encoding='utf-8'
    )


def test_an_archive_without_a_reason_is_REFUSED_and_moves_nothing(tmp_path) -> None:
    _plant(tmp_path, 'scratch/probe.py')
    with pytest.raises(ValueError, match='WHY'):
        archive_scratch(tmp_path / 'scratch/probe.py', why=' ', root=tmp_path, memory=tmp_path / 'm')
    assert (tmp_path / 'scratch/probe.py').exists()


def test_an_archive_never_overwrites(tmp_path) -> None:
    day = datetime.date(2026, 9, 25)
    _plant(tmp_path, 'scratch/a/probe.py')
    _plant(tmp_path, 'scratch/b/probe.py')
    memory = tmp_path / 'm'
    archive_scratch(tmp_path / 'scratch/a/probe.py', why='first', root=tmp_path, memory=memory, day=day)
    with pytest.raises(ValueError, match='already exists'):
        archive_scratch(tmp_path / 'scratch/b/probe.py', why='second', root=tmp_path, memory=memory, day=day)
    dest = archive_scratch(
        tmp_path / 'scratch/b/probe.py', why='second', root=tmp_path, memory=memory, day=day, name='b__probe.py'
    )
    assert dest.name == 'b__probe.py'
