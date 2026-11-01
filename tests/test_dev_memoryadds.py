"""MEMORY-SHAPE, the merge half: memory is ADDED to, never edited or deleted, and a merged entry cites.

Driven over real temporary git repos (the planted controls) and over the pure classifier.
"""

from __future__ import annotations

import io
import shutil
import subprocess
from pathlib import Path

import pytest

from dev_lab.dev import memoryadds

_GIT = shutil.which('git') or 'git'
ENTRY = '.claude/memory/2026/10/01/an-entry.md'
SOURCES = ('.claude/memory/2026/10/01/a.md', '.claude/memory/2026/10/02/b.md')


def _git(root: Path, *args: str) -> str:
    done = subprocess.run([_GIT, '-C', str(root), *args], capture_output=True, text=True, encoding='utf-8', check=True)
    return done.stdout.strip()


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


def _commit(root: Path, message: str, *paths: str) -> str:
    _git(root, 'add', '--', *paths)
    _git(root, 'commit', '-q', '-m', message)
    return _git(root, 'rev-parse', 'HEAD')


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, 'init', '-q', '-b', 'integrate/main')
    _git(tmp_path, 'config', 'user.email', 't@t')
    _git(tmp_path, 'config', 'user.name', 't')
    _write(tmp_path, ENTRY, '---\nname: an-entry\ndescription: d\naccessed: 2026-10-02\n---\n\nBody.\n')
    _write(tmp_path, 'pyproject.toml', "[tool.dev_lab.integrator]\nintegration = 'integrate/main'\n")
    for rel in SOURCES:
        _write(tmp_path, rel, '---\nname: s\ndescription: d\n---\n\nS.\n')
    _commit(tmp_path, 'base', ENTRY, 'pyproject.toml', *SOURCES)
    _git(tmp_path, 'update-ref', 'refs/remotes/origin/integrate/main', 'HEAD')
    return tmp_path


def _lane(repo: Path) -> str:
    _git(repo, 'switch', '-q', '-c', 'lane')
    return _git(repo, 'rev-parse', 'integrate/main')


def test_a_lane_that_only_adds_memory_passes(repo: Path) -> None:
    base = _lane(repo)
    _write(repo, '.claude/memory/2026/10/31/new.md', '---\nname: new\ndescription: d\n---\n\nNew.\n')
    _commit(repo, 'add', '.claude/memory/2026/10/31/new.md')
    assert memoryadds.problems_between(repo, base, 'HEAD') == ()


@pytest.mark.parametrize('change', ['edit', 'delete', 'rename'])
def test_a_lane_that_edits_deletes_or_moves_an_entry_is_refused(repo: Path, change: str) -> None:
    base = _lane(repo)
    if change == 'edit':
        _write(repo, ENTRY, '---\nname: an-entry\ndescription: d\n---\n\nRewritten.\n')
        _commit(repo, 'edit', ENTRY)
    elif change == 'delete':
        _git(repo, 'rm', '-q', ENTRY)
        _git(repo, 'commit', '-q', '-m', 'delete')
    else:
        _git(repo, 'mv', ENTRY, '.claude/memory/2026/10/01/moved.md')
        _git(repo, 'commit', '-q', '-m', 'move')
    found = memoryadds.problems_between(repo, base, 'HEAD')
    assert len(found) == 1, found
    assert ENTRY in found[0]


def test_a_task_moved_into_memory_is_the_one_allowed_move(repo: Path) -> None:
    _write(repo, '.claude/tasks/integrator/JOURNAL.md', 'D1 a decision\n')
    _commit(repo, 'task', '.claude/tasks/integrator/JOURNAL.md')
    base = _lane(repo)
    (repo / '.claude/memory/2026/10/31').mkdir(parents=True)
    _git(repo, 'mv', '.claude/tasks/integrator', '.claude/memory/2026/10/31/task-integrator')
    _git(repo, 'commit', '-q', '-m', 'archive the task')
    assert memoryadds.problems_between(repo, base, 'HEAD') == ()


def test_the_migration_strip_of_volatile_frontmatter_is_not_an_edit(repo: Path) -> None:
    base = _lane(repo)
    _write(repo, ENTRY, '---\nname: an-entry\ndescription: d\n---\n\nBody.\n')
    _commit(repo, 'strip', ENTRY)
    assert memoryadds.problems_between(repo, base, 'HEAD') == ()


def test_planted_a_merge_that_edits_an_existing_entry_is_refused(repo: Path) -> None:
    """PLANTED CONTROL: the lane adds only; the RESOLUTION rewrites an entry -- the merge reds."""
    _lane(repo)
    _write(repo, '.claude/memory/2026/10/31/lane.md', '---\nname: lane\ndescription: d\n---\n\nLane.\n')
    _commit(repo, 'lane adds', '.claude/memory/2026/10/31/lane.md')
    _git(repo, 'switch', '-q', 'integrate/main')
    _git(repo, 'merge', '-q', '--no-ff', '--no-commit', 'lane')
    _write(repo, ENTRY, '---\nname: an-entry\ndescription: d\n---\n\nEdited in the merge.\n')
    _git(repo, 'add', '--', ENTRY)
    found = memoryadds.pending(repo)
    assert len(found) == 1, found
    assert ENTRY in found[0]


def test_a_clean_merge_of_an_adding_lane_passes(repo: Path) -> None:
    _lane(repo)
    _write(repo, '.claude/memory/2026/10/31/lane.md', '---\nname: lane\ndescription: d\n---\n\nLane.\n')
    _commit(repo, 'lane adds', '.claude/memory/2026/10/31/lane.md')
    _git(repo, 'switch', '-q', 'integrate/main')
    _git(repo, 'merge', '-q', '--no-ff', '--no-commit', 'lane')
    assert memoryadds.pending(repo) == ()


def test_nothing_staged_judges_nothing(repo: Path) -> None:
    assert memoryadds.pending(repo) == ()


CITED = (
    '---\nname: m\ndescription: d\nmerged_from: [2026/10/01/a.md, 2026/10/02/b.md]\n---\n\n'
    '# Title\n\nThe first finding (2026/10/01/a.md).\n\nThe second, from `2026/10/02/b.md`.\n'
)


def test_a_merged_entry_that_cites_every_paragraph_in_one_scope_passes() -> None:
    assert memoryadds.merged_entry_problems('src/x/.claude/memory/2026/10/31/m.md', CITED) == ()


def test_a_merged_entry_with_an_uncited_paragraph_is_refused() -> None:
    text = CITED + '\nA claim with no source.\n'
    found = memoryadds.merged_entry_problems('.claude/memory/2026/10/31/m.md', text)
    assert len(found) == 1
    assert 'A claim with no source' in found[0]


def test_a_merged_entry_reaching_into_another_scope_is_refused() -> None:
    text = CITED.replace('2026/10/02/b.md]', 'src/y/.claude/memory/2026/10/02/b.md]')
    found = memoryadds.merged_entry_problems('src/x/.claude/memory/2026/10/31/m.md', text)
    assert any('src/y/.claude/memory/2026/10/02/b.md' in line for line in found), found


def test_a_lane_adding_an_uncited_merged_entry_is_refused(repo: Path) -> None:
    base = _lane(repo)
    rel = '.claude/memory/2026/10/31/m.md'
    _write(repo, rel, CITED + '\nUncited.\n')
    _commit(repo, 'merge entries', rel)
    found = memoryadds.problems_between(repo, base, 'HEAD')
    assert len(found) == 1, found
    assert 'Uncited' in found[0]


def test_the_commit_msg_hook_refuses_the_planted_merge(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The planted merge again, through the hook git runs: ``mergeaudit.main`` refuses it."""
    _lane(repo)
    _write(repo, '.claude/memory/2026/10/31/lane.md', '---\nname: lane\ndescription: d\n---\n\nLane.\n')
    _commit(repo, 'lane adds', '.claude/memory/2026/10/31/lane.md')
    _git(repo, 'switch', '-q', 'integrate/main')
    _git(repo, 'merge', '-q', '--no-ff', '--no-commit', 'lane')
    _write(repo, ENTRY, 'rewritten\n')
    _git(repo, 'add', '--', ENTRY)
    monkeypatch.chdir(repo)
    assert memoryadds.main(['commit', 'MSG']) == 1


def test_planted_a_plain_commit_editing_an_entry_is_refused(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """PLANTED CONTROL: no merge at all -- the commit-msg row still reds an edited entry."""
    _write(repo, ENTRY, '---\nname: an-entry\ndescription: d\n---\n\nQuietly rewritten.\n')
    _git(repo, 'add', '--', ENTRY)
    found = memoryadds.pending(repo)
    assert len(found) == 1, found
    assert ENTRY in found[0]
    monkeypatch.chdir(repo)
    assert memoryadds.main(['commit', 'MSG']) == 1


def test_planted_a_pushed_range_holding_an_edit_is_refused(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """PLANTED CONTROL: the edit was committed past the hook; the pre-push row reds the pushed range."""
    _lane(repo)
    _write(repo, ENTRY, 'rewritten\n')
    _commit(repo, 'edit past the hook', ENTRY)
    _write(repo, '.claude/memory/2026/10/31/later.md', '---\nname: later\ndescription: d\n---\n\nL.\n')
    head = _commit(repo, 'a clean commit on top', '.claude/memory/2026/10/31/later.md')
    lines = f'refs/heads/lane {head} refs/heads/lane {"0" * 40}\n'
    found = memoryadds.pushed(repo, lines)
    assert len(found) == 1, found
    assert ENTRY in found[0]
    monkeypatch.chdir(repo)
    monkeypatch.setattr('sys.stdin', io.StringIO(lines))
    assert memoryadds.main(['push']) == 1


def test_a_crlf_entry_stripped_to_lf_is_still_only_the_strip(repo: Path) -> None:
    _lane(repo)
    (repo / ENTRY).write_bytes(b'---\r\nname: an-entry\r\ndescription: d\r\naccessed: x\r\n---\r\n\r\nBody.\r\n')
    base = _commit(repo, 'crlf', ENTRY)
    _write(repo, ENTRY, '---\nname: an-entry\ndescription: d\n---\n\nBody.\n')
    _commit(repo, 'strip', ENTRY)
    assert memoryadds.problems_between(repo, base, 'HEAD') == ()


def test_a_merged_source_missing_at_the_base_is_refused() -> None:
    found = memoryadds.merged_entry_problems('.claude/memory/2026/10/31/m.md', CITED, exists=lambda p: 'a.md' in p)
    assert found == (
        (
            '.claude/memory/2026/10/31/m.md: merged_from 2026/10/02/b.md does not exist at the base '
            '(.claude/memory/2026/10/02/b.md)'
        ),
    )


def test_a_copied_entry_is_judged_like_an_added_one(repo: Path) -> None:
    """A ``C`` row is an addition: a copy carrying an uncited merge reds like a new file would."""
    rel = '.claude/memory/2026/10/31/m.md'
    _write(repo, rel, CITED + '\nUncited.\n')
    head = _commit(repo, 'm', rel)
    found = memoryadds._judge(repo, f'{head}~1', head, [('C', ENTRY, rel)])
    assert any('Uncited' in line for line in found), found


def _downstream_merge_of_an_upstream_edit(repo: Path) -> None:
    """integrate/main edits ENTRY after the lane branched; the LANE merges integrate/main in (a sync)."""
    _lane(repo)
    _write(repo, '.claude/memory/2026/10/31/lane.md', '---\nname: lane\ndescription: d\n---\n\nLane.\n')
    _commit(repo, 'lane adds', '.claude/memory/2026/10/31/lane.md')
    _git(repo, 'switch', '-q', 'integrate/main')
    _write(repo, ENTRY, '---\nname: an-entry\ndescription: d\n---\n\nBody, redacted upstream.\n')
    _commit(repo, 'upstream edits its entry', ENTRY)
    _git(repo, 'switch', '-q', 'lane')
    _git(repo, 'merge', '-q', '--no-ff', '--no-commit', 'integrate/main')


def test_a_sync_taking_upstreams_own_memory_edit_verbatim_passes(repo: Path) -> None:
    """A downstream merge staging an entry EXACTLY as MERGE_HEAD holds it is not an edit by this merge.

    It is the integration line's own change, judged where it was made. MEASURED 2026-11-01: a motronics lane
    syncing 2454 commits was refused on 255 such entries, and the hook's remedy (restore them) would have reverted
    upstream inside the merge.
    """
    _downstream_merge_of_an_upstream_edit(repo)
    assert memoryadds.pending(repo) == ()


def test_planted_a_sync_whose_resolution_rewrites_an_upstream_edit_is_refused(repo: Path) -> None:
    """PLANTED CONTROL: the same sync, but the resolution stages a THIRD text for the upstream-edited entry."""
    _downstream_merge_of_an_upstream_edit(repo)
    _write(repo, ENTRY, '---\nname: an-entry\ndescription: d\n---\n\nNeither side wrote this.\n')
    _git(repo, 'add', '--', ENTRY)
    found = memoryadds.pending(repo)
    assert len(found) == 1, found
    assert ENTRY in found[0]
