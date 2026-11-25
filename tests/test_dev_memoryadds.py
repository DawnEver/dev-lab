"""MEMORY-SHAPE, the change half: memory is ADDED to, never edited or deleted, and a merged entry cites.

Driven over real temporary git repos (the planted controls) and over the pure classifier. The one row is pre-push:
what a push would publish is judged net, since its merge-base with ``origin/<integration>``.
"""

from __future__ import annotations

import io
import shutil
import subprocess
from pathlib import Path

import pytest

from dev_lab.dev import memoryadds, memoryentry

_GIT = shutil.which('git') or 'git'
ENTRY = '.claude/memory/2026/10/01/an-entry.md'
SOURCES = ('.claude/memory/2026/10/01/a.md', '.claude/memory/2026/10/02/b.md')
MANUAL = '.claude/memory/2026/11/05/manual.md'
# The retired rem todo list's shape: once exempt, now an entry like any other.
MANUAL_HEAD = (
    '---\nname: manual-2026-11-05\ndescription: Manual tasks created on 2026-11-05\nmetadata:\n  type: project\n---\n\n'
)
MANUAL_FIRST = (
    '- [ ] MANUAL-20261105-694 [HIGH] Deferred heavy acceptance; keep its evidence bar. (2026-11-05)\n'
    '      module: acceptance\n'
)


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


def _publish(repo: Path) -> None:
    """HEAD is on ``origin/<integration>``: what it holds is published from here on."""
    _git(repo, 'update-ref', 'refs/remotes/origin/integrate/main', 'HEAD')


def _push(repo: Path, head: str) -> tuple[str, ...]:
    return memoryadds.pushed(repo, f'refs/heads/lane {head} refs/heads/lane {"0" * 40}\n')


def _judged(repo: Path) -> tuple[str, ...]:
    """The pre-push row's verdict on HEAD, after committing what is staged (a merge in flight included)."""
    in_merge = (repo / '.git' / 'MERGE_HEAD').is_file()
    if in_merge or _git(repo, 'diff', '--cached', '--name-only'):
        _git(repo, 'commit', '-q', '--no-edit', '-m', 'staged')
    return _push(repo, _git(repo, 'rev-parse', 'HEAD'))


def test_a_lane_that_only_adds_memory_passes(repo: Path) -> None:
    base = _lane(repo)
    _write(repo, '.claude/memory/2026/10/31/new.md', '---\nname: new\ndescription: d\n---\n\nNew.\n')
    _commit(repo, 'add', '.claude/memory/2026/10/31/new.md')
    assert memoryadds.problems_between(repo, base, 'HEAD') == ()


def test_a_retired_rem_manual_list_is_immutable_like_any_entry(repo: Path) -> None:
    """REM-RETIRED (2026-11-23): rem's todo list lost its exemption; a toggled checkbox is an edit, refused."""
    _write(repo, MANUAL, MANUAL_HEAD + MANUAL_FIRST)
    _commit(repo, 'original manual tasks', MANUAL)
    base = _lane(repo)
    _write(repo, MANUAL, MANUAL_HEAD + MANUAL_FIRST.replace('- [ ]', '- [x]'))
    _commit(repo, 'task state', MANUAL)
    assert 'immutable' in ' '.join(memoryadds.problems_between(repo, base, 'HEAD'))


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


SUMMARY = '.claude/memory/2026/10/SUMMARY-2026-10.md'


@pytest.mark.parametrize('change', ['delete', 'move'])
def test_a_retired_month_summary_may_leave_memory(repo: Path, change: str) -> None:
    """User ruling 2026-11-24: SUMMARY-*.md retires -- its deletion, or its move into a dated entry, is admitted.

    PLANTED CONTROL: the same deletion of a dated entry in that change is still refused, naming the summary door.
    """
    _write(repo, SUMMARY, '# October\n\nWhat happened.\n')
    _commit(repo, 'summary', SUMMARY)
    base = _lane(repo)
    if change == 'delete':
        _git(repo, 'rm', '-q', SUMMARY)
    else:
        moved = '.claude/memory/2026/10/31/october-summary.md'
        (repo / moved).parent.mkdir(parents=True, exist_ok=True)
        _git(repo, 'mv', SUMMARY, moved)
        _write(repo, moved, '---\nname: october-summary\ndescription: d\n---\n\nWhat happened.\n')
        _git(repo, 'add', moved)
    _git(repo, 'commit', '-q', '-m', 'retire the month summary')
    assert memoryadds.problems_between(repo, base, 'HEAD') == ()
    _git(repo, 'rm', '-q', ENTRY)
    _git(repo, 'commit', '-q', '-m', 'and an entry')
    found = memoryadds.problems_between(repo, base, 'HEAD')
    assert len(found) == 1, found
    assert ENTRY in found[0]
    assert 'SUMMARY-' in found[0], 'the refusal names the one deletion memory admits'


def test_nothing_moves_into_memory_not_even_a_task(repo: Path) -> None:
    """A closed task is archived in the global tasks repo by rem (2026-11-23), never moved into a checkout's memory."""
    _write(repo, 'notes/integrator/JOURNAL.md', 'D1 a decision\n')
    _commit(repo, 'task', 'notes/integrator/JOURNAL.md')
    base = _lane(repo)
    assert memoryadds.problems_between(repo, base, 'HEAD') == (), 'planted control: nothing moved yet'
    (repo / '.claude/memory/2026/10/31').mkdir(parents=True)
    _git(repo, 'mv', 'notes/integrator', '.claude/memory/2026/10/31/task-integrator')
    _git(repo, 'commit', '-q', '-m', 'archive the task')
    [found] = memoryadds.problems_between(repo, base, 'HEAD')
    assert 'tasks repo' in found


def test_the_migration_strip_of_volatile_frontmatter_is_not_an_edit(repo: Path) -> None:
    base = _lane(repo)
    _write(repo, ENTRY, '---\nname: an-entry\ndescription: d\n---\n\nBody.\n')
    _commit(repo, 'strip', ENTRY)
    assert memoryadds.problems_between(repo, base, 'HEAD') == ()


_SITE = '---\nname: an-entry\ndescription: d\n---\n\nThe forge is at 192.0.2.7 on host box-7.\nBody.\n'


def test_a_privacy_redaction_of_a_published_entry_is_not_an_edit(repo: Path) -> None:
    """A published repo must be able to remove a site marker: each changed line only swaps spans for placeholders."""
    _write(repo, ENTRY, _SITE)
    _commit(repo, 'site', ENTRY)
    _git(repo, 'update-ref', 'refs/remotes/origin/integrate/main', 'HEAD')
    base = _lane(repo)
    _write(
        repo,
        ENTRY,
        '---\nname: an-entry\ndescription: d\n---\n\n> '
        + memoryentry.REDACTION_NOTE.format(day='2026-11-09')
        + '\n\nThe forge is at <ip> on host <host>.\nBody.\n',
    )
    _commit(repo, 'redact', ENTRY)
    assert memoryadds.problems_between(repo, base, 'HEAD') == ()


@pytest.mark.parametrize(
    'body',
    [
        'The forge is at <ip> on host <host>.\nBody, and a new claim.\n',  # a narrative change rides along
        'Rewritten entirely.\n',  # no placeholder: a rewrite
    ],
)
def test_planted_a_redaction_note_never_admits_a_narrative_edit(repo: Path, body: str) -> None:
    """PLANTED CONTROL: the note alone admits nothing; every other changed line must be a placeholder swap."""
    _write(repo, ENTRY, _SITE)
    _commit(repo, 'site', ENTRY)
    _git(repo, 'update-ref', 'refs/remotes/origin/integrate/main', 'HEAD')
    base = _lane(repo)
    note = '> ' + memoryentry.REDACTION_NOTE.format(day='2026-11-09')
    _write(repo, ENTRY, f'---\nname: an-entry\ndescription: d\n---\n\n{note}\n\n{body}')
    _commit(repo, 'redact and rewrite', ENTRY)
    found = memoryadds.problems_between(repo, base, 'HEAD')
    assert len(found) == 1, found


def test_planted_a_merge_that_edits_an_existing_entry_is_refused(repo: Path) -> None:
    """PLANTED CONTROL: the lane adds only; the RESOLUTION rewrites an entry -- the merge reds."""
    _lane(repo)
    _write(repo, '.claude/memory/2026/10/31/lane.md', '---\nname: lane\ndescription: d\n---\n\nLane.\n')
    _commit(repo, 'lane adds', '.claude/memory/2026/10/31/lane.md')
    _git(repo, 'switch', '-q', 'integrate/main')
    _git(repo, 'merge', '-q', '--no-ff', '--no-commit', 'lane')
    _write(repo, ENTRY, '---\nname: an-entry\ndescription: d\n---\n\nEdited in the merge.\n')
    _git(repo, 'add', '--', ENTRY)
    found = _judged(repo)
    assert len(found) == 1, found
    assert ENTRY in found[0]


def test_a_clean_merge_of_an_adding_lane_passes(repo: Path) -> None:
    _lane(repo)
    _write(repo, '.claude/memory/2026/10/31/lane.md', '---\nname: lane\ndescription: d\n---\n\nLane.\n')
    _commit(repo, 'lane adds', '.claude/memory/2026/10/31/lane.md')
    _git(repo, 'switch', '-q', 'integrate/main')
    _git(repo, 'merge', '-q', '--no-ff', '--no-commit', 'lane')
    assert _judged(repo) == ()


def test_a_push_publishing_nothing_new_judges_nothing(repo: Path) -> None:
    assert _judged(repo) == ()


CITED = (
    '---\nname: m\ndescription: d\nmerged_from: [2026/10/01/a.md, 2026/10/02/b.md]\n---\n\n'
    '# Title\n\nThe first finding (2026/10/01/a.md).\n\nThe second, from `2026/10/02/b.md`.\n'
)


def test_a_merged_entry_that_cites_every_paragraph_in_one_scope_passes() -> None:
    assert memoryentry.merged_entry_problems('src/x/.claude/memory/2026/10/31/m.md', CITED) == ()


def test_a_merged_entry_with_an_uncited_paragraph_is_refused() -> None:
    text = CITED + '\nA claim with no source.\n'
    found = memoryentry.merged_entry_problems('.claude/memory/2026/10/31/m.md', text)
    assert len(found) == 1
    assert 'A claim with no source' in found[0]


def test_a_merged_entry_reaching_into_another_scope_is_refused() -> None:
    text = CITED.replace('2026/10/02/b.md]', 'src/y/.claude/memory/2026/10/02/b.md]')
    found = memoryentry.merged_entry_problems('src/x/.claude/memory/2026/10/31/m.md', text)
    assert any('src/y/.claude/memory/2026/10/02/b.md' in line for line in found), found


def test_a_lane_adding_an_uncited_merged_entry_is_refused(repo: Path) -> None:
    base = _lane(repo)
    rel = '.claude/memory/2026/10/31/m.md'
    _write(repo, rel, CITED + '\nUncited.\n')
    _commit(repo, 'merge entries', rel)
    found = memoryadds.problems_between(repo, base, 'HEAD')
    assert len(found) == 1, found
    assert 'Uncited' in found[0]


def test_the_pre_push_hook_refuses_the_planted_merge(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The planted merge again, through the hook git runs: ``memoryadds.main`` refuses its push."""
    _lane(repo)
    _write(repo, '.claude/memory/2026/10/31/lane.md', '---\nname: lane\ndescription: d\n---\n\nLane.\n')
    _commit(repo, 'lane adds', '.claude/memory/2026/10/31/lane.md')
    _git(repo, 'switch', '-q', 'integrate/main')
    _git(repo, 'merge', '-q', '--no-ff', '--no-commit', 'lane')
    _write(repo, ENTRY, 'rewritten\n')
    _commit(repo, 'merge', ENTRY)
    monkeypatch.chdir(repo)
    head = _git(repo, 'rev-parse', 'HEAD')
    monkeypatch.setattr(
        'sys.stdin', io.StringIO(f'refs/heads/integrate/main {head} refs/heads/integrate/main {"1" * 40}\n')
    )
    assert memoryadds.main([]) == 1


def test_planted_a_plain_commit_editing_an_entry_is_refused(repo: Path) -> None:
    """PLANTED CONTROL: no merge at all -- the pushed range still reds an edited entry."""
    _write(repo, ENTRY, '---\nname: an-entry\ndescription: d\n---\n\nQuietly rewritten.\n')
    _git(repo, 'add', '--', ENTRY)
    found = _judged(repo)
    assert len(found) == 1, found
    assert ENTRY in found[0]


def test_planted_a_pushed_range_holding_an_edit_is_refused(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """PLANTED CONTROL: a clean commit on top of the edit does not hide it; the pushed range is judged whole."""
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
    assert memoryadds.main([]) == 1


def test_a_crlf_entry_stripped_to_lf_is_still_only_the_strip(repo: Path) -> None:
    _lane(repo)
    (repo / ENTRY).write_bytes(b'---\r\nname: an-entry\r\ndescription: d\r\naccessed: x\r\n---\r\n\r\nBody.\r\n')
    base = _commit(repo, 'crlf', ENTRY)
    _write(repo, ENTRY, '---\nname: an-entry\ndescription: d\n---\n\nBody.\n')
    _commit(repo, 'strip', ENTRY)
    assert memoryadds.problems_between(repo, base, 'HEAD') == ()


def test_a_merged_source_missing_at_the_base_is_refused() -> None:
    found = memoryentry.merged_entry_problems('.claude/memory/2026/10/31/m.md', CITED, exists=lambda p: 'a.md' in p)
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
    _publish(repo)
    _git(repo, 'switch', '-q', 'lane')
    _git(repo, 'merge', '-q', '--no-ff', '--no-commit', 'integrate/main')


def test_a_sync_taking_upstreams_own_memory_edit_verbatim_passes(repo: Path) -> None:
    """A downstream merge taking an entry EXACTLY as the integration line holds it is not an edit by this push.

    It is the integration line's own change, judged where it was made: the sync moves the merge-base past it.
    MEASURED 2026-11-01: a consumer lane syncing 2454 commits was refused on 255 such entries by a commit-time
    reading, and its remedy (restore them) would have reverted upstream inside the merge.
    """
    _downstream_merge_of_an_upstream_edit(repo)
    assert _judged(repo) == ()


def test_planted_a_sync_whose_resolution_rewrites_an_upstream_edit_is_refused(repo: Path) -> None:
    """PLANTED CONTROL: the same sync, but the resolution stages a THIRD text for the upstream-edited entry."""
    _downstream_merge_of_an_upstream_edit(repo)
    _write(repo, ENTRY, '---\nname: an-entry\ndescription: d\n---\n\nNeither side wrote this.\n')
    _git(repo, 'add', '--', ENTRY)
    found = _judged(repo)
    assert len(found) == 1, found
    assert ENTRY in found[0]


def test_restoring_an_entry_the_lane_edited_to_the_integration_lines_text_passes(repo: Path) -> None:
    """The remedy the refusal prints -- commit the entry back to the integration line's text -- must pass.

    MEASURED 2026-11-01: a lane holding three old in-place edits restored them to origin/integrate/main's text and
    a commit-time reading refused the restore, a change against HEAD. Judged net over the pushed range, the entry is
    unchanged.
    """
    _lane(repo)
    _write(repo, ENTRY, '---\nname: an-entry\ndescription: d\naccessed: 2026-10-02\n---\n\nEdited in place.\n')
    _commit(repo, 'lane edits in place (before the rule)', ENTRY)
    _git(repo, 'checkout', 'origin/integrate/main', '--', ENTRY)
    assert _judged(repo) == ()


def test_planted_a_lane_rewriting_an_entry_to_neither_text_is_still_refused(repo: Path) -> None:
    """PLANTED CONTROL: the lane's second edit matches neither HEAD nor the integration line -- an edit."""
    _lane(repo)
    _write(repo, ENTRY, '---\nname: an-entry\ndescription: d\naccessed: 2026-10-02\n---\n\nEdited in place.\n')
    _commit(repo, 'lane edits in place (before the rule)', ENTRY)
    _write(repo, ENTRY, '---\nname: an-entry\ndescription: d\naccessed: 2026-10-02\n---\n\nEdited again.\n')
    _git(repo, 'add', '--', ENTRY)
    found = _judged(repo)
    assert len(found) == 1, found
    assert ENTRY in found[0]


SAME_PUSH = (
    '---\nname: m\ndescription: d\nmerged_from: [2026/11/04/x.md, 2026/11/04/y.md]\n---\n\n'
    'The first finding (2026/11/04/x.md).\n\nThe second, from `2026/11/04/y.md`.\n'
)


def _add_sources(repo: Path, *names: str) -> None:
    rels = [f'.claude/memory/2026/11/04/{name}' for name in names]
    for rel in rels:
        _write(repo, rel, '---\nname: s\ndescription: d\n---\n\nS.\n')
    _commit(repo, 'sources', *rels)


def test_merged_sources_added_in_the_same_pushed_range_are_accepted(repo: Path) -> None:
    """The 2026-11-04 incident: a merge entry and the sources it names arrive in ONE push."""
    base = _lane(repo)
    _add_sources(repo, 'x.md', 'y.md')
    rel = '.claude/memory/2026/11/04/m.md'
    _write(repo, rel, SAME_PUSH)
    _commit(repo, 'merge entry', rel)
    assert memoryadds.problems_between(repo, base, 'HEAD') == ()


def test_merged_sources_added_in_the_same_commit_are_accepted(repo: Path) -> None:
    """Entry and sources in ONE commit are one addition."""
    rels = ['.claude/memory/2026/11/04/x.md', '.claude/memory/2026/11/04/y.md']
    for rel in rels:
        _write(repo, rel, '---\nname: s\ndescription: d\n---\n\nS.\n')
    _write(repo, '.claude/memory/2026/11/04/m.md', SAME_PUSH)
    _git(repo, 'add', '--', *rels, '.claude/memory/2026/11/04/m.md')
    assert _judged(repo) == ()


def test_planted_a_merged_source_absent_from_base_and_range_is_still_refused(repo: Path) -> None:
    """PLANTED CONTROL: only x.md is added; y.md exists in neither the base nor the range."""
    base = _lane(repo)
    _add_sources(repo, 'x.md')
    rel = '.claude/memory/2026/11/04/m.md'
    _write(repo, rel, SAME_PUSH)
    _commit(repo, 'merge entry', rel)
    assert memoryadds.problems_between(repo, base, 'HEAD') == (
        f'{rel}: merged_from 2026/11/04/y.md does not exist at the base (.claude/memory/2026/11/04/y.md)',
    )


def test_an_unpublished_entry_may_still_be_edited_or_deleted(repo: Path) -> None:
    """Immutability starts at publication: an entry the pushed range adds, then edits or drops, is a draft."""
    _lane(repo)
    rel = '.claude/memory/2026/11/04/draft.md'
    _write(repo, rel, '---\nname: draft\ndescription: d\n---\n\nUncited claim.\n')
    _commit(repo, 'draft', rel)
    _write(repo, rel, '---\nname: draft\ndescription: d\n---\n\nCited claim (2026/10/01/a.md).\n')
    _git(repo, 'add', '--', rel)
    assert _judged(repo) == ()
    _git(repo, 'rm', '-q', '--', rel)
    assert _judged(repo) == ()


def test_planted_an_edit_to_a_published_entry_is_still_refused(repo: Path) -> None:
    """PLANTED CONTROL: ENTRY is on origin/integrate/main, so editing it stays refused."""
    _lane(repo)
    _write(repo, ENTRY, '---\nname: an-entry\ndescription: d\n---\n\nRewritten.\n')
    _git(repo, 'add', '--', ENTRY)
    found = _judged(repo)
    assert len(found) == 1, found
    assert ENTRY in found[0]


def _fresh_origin(repo: Path, *, uncited: bool) -> str:
    """A repo whose origin holds NO integration ref yet: the push that founds the repo creates it."""
    _git(repo, 'update-ref', '-d', 'refs/remotes/origin/integrate/main')
    rel = '.claude/memory/2026/10/31/m.md'
    _write(repo, rel, CITED + ('\nUncited.\n' if uncited else ''))
    head = _commit(repo, 'founding memory', rel)
    return f'refs/heads/integrate/main {head} refs/heads/integrate/main {"0" * 40}\n'


def test_the_push_that_founds_a_repo_is_judged_from_the_empty_tree(repo: Path) -> None:
    """No published entry exists before the first push, so the whole pushed history is adds -- judged as adds."""
    assert memoryadds.pushed(repo, _fresh_origin(repo, uncited=False)) == ()


def test_planted_a_founding_push_adding_an_uncited_merged_entry_is_still_refused(repo: Path) -> None:
    """PLANTED CONTROL: with no integration ref the adds are still judged, never waved through."""
    found = memoryadds.pushed(repo, _fresh_origin(repo, uncited=True))
    assert len(found) == 1, found
    assert 'Uncited' in found[0]


_WRONG = '---\nname: an-entry\ndescription: d\n---\n\nThe user said: D31 decide it NOT yourself.\nBody.\n'


def _amend_note(reason: str = 'the quote was mistranslated', approved: str = 'fix that line') -> str:
    return '> ' + memoryentry.AMENDMENT_NOTE.format(day='2026-11-13', reason=reason, approved=approved)


def test_an_approved_amendment_corrects_a_published_entry_in_place(repo: Path) -> None:
    """The exceptional case: a published line is WRONG (a fact, a mistranslation, a forbidden character).

    It is corrected in place when the entry carries the amendment note -- its reason and the user's words
    approving it -- and every other change replaces a line one-for-one: nothing is added or removed.
    """
    _write(repo, ENTRY, _WRONG)
    _commit(repo, 'wrong', ENTRY)
    _git(repo, 'update-ref', 'refs/remotes/origin/integrate/main', 'HEAD')
    base = _lane(repo)
    _write(
        repo,
        ENTRY,
        f'---\nname: an-entry\ndescription: d\n---\n\n{_amend_note()}\n\n'
        'The user said: D31 decide it yourself.\nBody.\n',
    )
    _commit(repo, 'amend', ENTRY)
    assert memoryadds.problems_between(repo, base, 'HEAD') == ()


@pytest.mark.parametrize(
    ('note', 'body'),
    [
        (None, 'The user said: D31 decide it yourself.\nBody.\n'),  # no note: an edit
        ('reason-only', 'The user said: D31 decide it yourself.\nBody.\n'),  # no approval quoted
        ('full', 'The user said: D31 decide it yourself.\n'),  # a line removed
        ('full', 'The user said: D31 decide it yourself.\nBody.\nA new claim.\n'),  # a line added
    ],
)
def test_planted_an_amendment_needs_its_note_its_approval_and_one_for_one_lines(
    repo: Path, note: str | None, body: str
) -> None:
    """PLANTED CONTROL: without the note, without the user's words, or with lines added/removed, it is an edit."""
    _write(repo, ENTRY, _WRONG)
    _commit(repo, 'wrong', ENTRY)
    _git(repo, 'update-ref', 'refs/remotes/origin/integrate/main', 'HEAD')
    base = _lane(repo)
    head = {None: '', 'reason-only': _amend_note(approved='') + '\n\n', 'full': _amend_note() + '\n\n'}[note]
    _write(repo, ENTRY, f'---\nname: an-entry\ndescription: d\n---\n\n{head}{body}')
    _commit(repo, 'amend badly', ENTRY)
    found = memoryadds.problems_between(repo, base, 'HEAD')
    assert len(found) == 1, found


_HEAD = '---\nname: an-entry\ndescription: d\n---\n\n'
_NOTED = _HEAD + '> Amended 2026-11-13: a typo -- approved: "\u540c\u610f\u8865\u5168"\n\nBody.\n'
_TRANSLATED = '> Amended 2026-11-13: a typo -- approved: "agreed, complete it" (user, translated)'
_D26 = '> Amended 2026-11-17: translated to English (D26) -- approved: "translate memory to English"'


@pytest.mark.parametrize(
    ('after', 'accepted'),
    [
        (f'{_TRANSLATED}\n{_D26}\n\nBody.\n', True),  # the quote translated in place, beside the D26 note
        (f'{_TRANSLATED}\n\nBody.\n', False),  # the same note edit without a new approved note
        (f'{_D26}\n\nBody.\n', False),  # the existing note deleted
        (f'{_TRANSLATED.replace("11-13", "11-14")}\n{_D26}\n\nBody.\n', False),  # its date changed
        (f'> Revised 2026-11-13: a typo\n{_D26}\n\nBody.\n', False),  # its Amended prefix dropped
    ],
)
def test_planted_a_quote_inside_an_existing_note_is_translated_only_beside_a_new_note(
    *, after: str, accepted: bool
) -> None:
    """D26 (2026-11-17): an existing note keeps its date and prefix; only a NEW approved note admits its rewrite."""
    assert memoryentry.only_amended(_NOTED, _HEAD + after) is accepted


# --- a first adoption: origin holds no integration ref yet ---------------------------------------------------


def _bare(tmp_path: Path) -> Path:
    _git(tmp_path, 'init', '-q', '-b', 'integrate/main')
    _git(tmp_path, 'config', 'user.email', 't@t')
    _git(tmp_path, 'config', 'user.name', 't')
    _write(tmp_path, 'README.md', 'r\n')
    _commit(tmp_path, 'before the family', 'README.md')
    return tmp_path


def test_a_first_adoption_is_judged_by_its_own_manifest(tmp_path: Path) -> None:
    """The adopting commit's own manifest names the integration branch; nothing is published yet, so all adds."""
    repo = _bare(tmp_path)
    _write(repo, 'pyproject.toml', "[tool.dev_lab.integrator]\nintegration = 'integrate/main'\n")
    _write(repo, '.claude/memory/2026/11/13/adopted.md', '---\nname: adopted\ndescription: d\n---\n\nA.\n')
    _git(repo, 'add', '--', 'pyproject.toml', '.claude/memory/2026/11/13/adopted.md')
    assert _judged(repo) == ()


def test_a_manifest_naming_no_integration_branch_is_still_refused(tmp_path: Path) -> None:
    """PLANTED control: the pushed tip's manifest must name the branch whose origin ref bounds the range."""
    repo = _bare(tmp_path)
    _write(repo, 'pyproject.toml', "[project]\nname = 'x'\n")
    head = _commit(repo, 'a manifest without the table', 'pyproject.toml')
    with pytest.raises(ValueError, match='names no integration branch'):
        _push(repo, head)


# --- the shape of an added entry, and the amendment that completes a published one -----------------------------


@pytest.mark.parametrize(
    ('text', 'missing'),
    [
        ('---\ncreated: 2026-11-13\n---\n# X\n', 'name, description'),  # 2026-11-13: committed, caught only later
        ('---\nname: x\n---\n# X\n', 'description'),
        ('# no frontmatter at all\n', 'name, description'),
    ],
)
def test_planted_an_added_entry_without_name_or_description_is_refused_at_push(
    repo: Path, monkeypatch: pytest.MonkeyPatch, text: str, missing: str
) -> None:
    """PLANTED CONTROL: the shape the dated-memory test reads, refused when the entry is ADDED, not later.

    The clean twin (name and description declared) is ``test_a_lane_that_only_adds_memory_passes``.
    """
    rel = '.claude/memory/2026/11/13/half.md'
    _write(repo, rel, text)
    _git(repo, 'add', '--', rel)
    monkeypatch.chdir(repo)
    found = _judged(repo)
    assert len(found) == 1, found
    assert rel in found[0], found
    assert f'declares no {missing}' in found[0], found
    head = _git(repo, 'rev-parse', 'HEAD')
    monkeypatch.setattr('sys.stdin', io.StringIO(f'refs/heads/lane {head} refs/heads/lane {"0" * 40}\n'))
    assert memoryadds.main([]) == 1


_HEADLESS = '---\ncreated: 2026-11-13\n---\n# Title\n\nBody line.\n'


def _published(repo: Path) -> str:
    _write(repo, ENTRY, _HEADLESS)
    _commit(repo, 'headless', ENTRY)
    _git(repo, 'update-ref', 'refs/remotes/origin/integrate/main', 'HEAD')
    return _lane(repo)


def test_an_approved_amendment_may_add_the_missing_required_frontmatter(repo: Path) -> None:
    """2026-11-13: the user approved completing a published entry's frontmatter; one-for-one could not add a key."""
    base = _published(repo)
    note = _amend_note('added the name/description frontmatter the memory shape requires', '\u540c\u610f\u8865\u5168')
    _write(
        repo, ENTRY, f'---\nname: an-entry\ndescription: d\ncreated: 2026-11-13\n---\n# Title\n\nBody line.\n{note}\n'
    )
    _commit(repo, 'complete', ENTRY)
    assert memoryadds.problems_between(repo, base, 'HEAD') == ()


@pytest.mark.parametrize(
    ('note', 'head', 'body'),
    [
        ('approved', 'name: an-entry\ndescription: d\n', 'Body line.\nA new claim.\n'),  # a key AND a body line added
        ('approved', 'name: an-entry\ndescription: d\n', 'Body line changed.\n'),  # a key AND a body line rewritten
        ('approved', 'name: an-entry\ndescription: d\nowner: me\n', 'Body line.\n'),  # a key nothing requires
        ('', 'name: an-entry\ndescription: d\n', 'Body line.\n'),  # no approved note
    ],
)
def test_planted_a_frontmatter_completion_admits_nothing_else(repo: Path, note: str, head: str, body: str) -> None:
    """PLANTED CONTROL: beside the added required keys, every other line stays exactly as published."""
    base = _published(repo)
    tail = f'{_amend_note()}\n' if note else ''
    _write(repo, ENTRY, f'---\n{head}created: 2026-11-13\n---\n# Title\n\n{body}{tail}')
    _commit(repo, 'complete badly', ENTRY)
    assert len(memoryadds.problems_between(repo, base, 'HEAD')) == 1


# --- an approved redacting rename: an account-like token leaves a published entry's FILE NAME -----------------

_ACCOUNT = '.claude/memory/2026/10/01/what-jdoe7-measured.md'
_RENAMED = '.claude/memory/2026/10/01/what-user-measured.md'
_RENAME_NOTE = _amend_note('renamed to drop an account name from the file name', 'rename them')
_KEPT = 'The user said: D31 decide it NOT yourself.\nBody.\n'


def _published_account_entry(repo: Path, text: str = _WRONG) -> str:
    _write(repo, _ACCOUNT, text)
    _commit(repo, 'account', _ACCOUNT)
    _git(repo, 'update-ref', 'refs/remotes/origin/integrate/main', 'HEAD')
    return _lane(repo)


def _rename(repo: Path, old: str, new: str, text: str) -> None:
    (repo / new).parent.mkdir(parents=True, exist_ok=True)
    _git(repo, 'mv', old, new)
    _write(repo, new, text)
    _commit(repo, 'rename', new)


def _entry(head: str, body: str) -> str:
    return f'---\nname: an-entry\ndescription: d\n---\n\n{head}{body}'


@pytest.mark.parametrize(
    ('new', 'body'),
    [
        (_RENAMED, _KEPT),  # content kept: git sees R
        ('.claude/memory/2026/10/01/what-measured.md', _KEPT),  # the token run dropped
        (_RENAMED, 'The user said: D31 decide it yourself.\nBody.\n'),  # a line amended one-for-one
    ],
)
def test_an_approved_redacting_rename_of_a_published_entry_passes(repo: Path, new: str, body: str) -> None:
    """REDACTING-RENAME: the token run is replaced by ``user`` or dropped, and the entry carries the rename note."""
    base = _published_account_entry(repo)
    _rename(repo, _ACCOUNT, new, _entry(f'{_RENAME_NOTE}\n\n', body))
    assert memoryadds.problems_between(repo, base, 'HEAD') == ()


def test_a_redacting_rename_git_reads_as_delete_plus_add_passes(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A short entry whose content also changes falls under git's similarity bar: D + A, judged as the rename."""
    base = _published_account_entry(repo, '---\nname: what-jdoe7-measured\ndescription: d\n---\n\nAt 192.0.2.7.\n')
    redact = '> ' + memoryentry.REDACTION_NOTE.format(day='2026-11-14')
    text = f'---\nname: what-jdoe7-measured\ndescription: d\n---\n\n{_RENAME_NOTE}\n{redact}\n\nAt <ip>.\n'
    _rename(repo, _ACCOUNT, _RENAMED, text)
    assert 'D\x00' + _ACCOUNT in _git(repo, 'diff', '-M', '-C', '--name-status', '-z', base, 'HEAD')
    assert memoryadds.problems_between(repo, base, 'HEAD') == ()
    monkeypatch.setattr('sys.stdin', io.StringIO(f'refs/heads/lane {_git(repo, "rev-parse", "HEAD")} x {"0" * 40}\n'))
    monkeypatch.chdir(repo)
    assert memoryadds.main(['push']) == 0


@pytest.mark.parametrize(
    ('new', 'note'),
    [
        ('.claude/memory/2026/10/02/what-user-measured.md', _RENAME_NOTE),  # another directory
        ('.claude/memory/2026/10/01/what-user-found.md', _RENAME_NOTE),  # other words of the name changed
        ('.claude/memory/2026/10/01/what-someone-measured.md', _RENAME_NOTE),  # not the neutral placeholder
        ('.claude/memory/2026/10/01/what-jdoe7-measured.txt', _RENAME_NOTE),  # the suffix changed
        (_RENAMED, ''),  # no approval note
        (_RENAMED, _amend_note('the quote was mistranslated', 'fix that line')),  # a note not stating the rename
        (_RENAMED, _amend_note('renamed to drop an account name', '')),  # no user's words
    ],
)
def test_planted_a_rename_outside_the_redacting_rule_is_still_refused(repo: Path, new: str, note: str) -> None:
    """PLANTED CONTROL: each leg of REDACTING-RENAME is necessary; missing one, the move is refused as before."""
    base = _published_account_entry(repo)
    _rename(repo, _ACCOUNT, new, _entry(f'{note}\n\n' if note else '', _KEPT))
    found = memoryadds.problems_between(repo, base, 'HEAD')
    assert any('never deleted or moved' in line for line in found), found


def test_planted_a_redacting_rename_never_admits_a_narrative_edit(repo: Path) -> None:
    """PLANTED CONTROL: a valid name and note, but a line added -- the content leg refuses it."""
    base = _published_account_entry(repo)
    _rename(repo, _ACCOUNT, _RENAMED, _entry(f'{_RENAME_NOTE}\n\n', _KEPT + 'A new claim.\n'))
    found = memoryadds.problems_between(repo, base, 'HEAD')
    assert any('never deleted or moved' in line for line in found), found


_JOURNAL = '.claude/memory/2026/11/14/task-landed/JOURNAL.md'
_TASK_MD = '.claude/memory/2026/11/14/task-landed/TASK.md'
_TASK_TEXT = '---\nname: task-landed\ndescription: d\nkind: task\n---\n\nT.\n'


def _published_elsewhere(repo: Path, *files: tuple[str, str]) -> str:
    """Upstream takes *files* by a merge commit; the lane carries the same blobs without that tip (#6602)."""
    base = _git(repo, 'rev-parse', 'HEAD')
    _git(repo, 'switch', '-q', '-c', 'pr', base)
    for rel, text in files:
        _write(repo, rel, text)
    _commit(repo, 'pr adds', *(rel for rel, _ in files))
    _git(repo, 'switch', '-q', 'integrate/main')
    _git(repo, 'merge', '-q', '--no-ff', '-m', 'take pr', 'pr')
    _git(repo, 'update-ref', 'refs/remotes/origin/integrate/main', 'HEAD')
    _git(repo, 'switch', '-q', '-c', 'lane', base)
    for rel, text in files:
        _write(repo, rel, text)
    return _commit(repo, 'lane carries the same blobs', *(rel for rel, _ in files))


def test_a_byte_identical_published_entry_in_the_pushed_range_is_not_judged_again(repo: Path) -> None:
    """#6602: the merge-base fell back past a merge commit; a blob origin already holds is published, not added."""
    head = _published_elsewhere(repo, ('.claude/memory/2026/11/14/headless.md', _HEADLESS))
    assert _push(repo, head) == ()


def test_planted_a_new_misshapen_entry_beside_a_published_one_is_still_refused(repo: Path) -> None:
    """PLANTED CONTROL: the published blob passes; a genuinely new headless entry in the same range does not."""
    _published_elsewhere(repo, ('.claude/memory/2026/11/14/headless.md', _HEADLESS))
    rel = '.claude/memory/2026/11/14/new.md'
    _write(repo, rel, _HEADLESS)
    found = _push(repo, _commit(repo, 'new headless', rel))
    assert len(found) == 1, found
    assert rel in found[0], found


def test_planted_a_published_path_whose_blob_differs_is_still_judged(repo: Path) -> None:
    """PLANTED CONTROL: same path, other bytes -- not what origin holds, so it is this range's add."""
    rel = '.claude/memory/2026/11/14/headless.md'
    _published_elsewhere(repo, (rel, '---\nname: h\ndescription: d\n---\n\nH.\n'))
    _write(repo, rel, _HEADLESS)
    found = _push(repo, _commit(repo, 'rewrite', rel))
    assert len(found) == 1, found
    assert rel in found[0], found


def test_the_issue_6602_journal_published_by_a_merge_commit_passes(repo: Path) -> None:
    head = _published_elsewhere(repo, (_TASK_MD, _TASK_TEXT), (_JOURNAL, '# J\n'))
    assert _push(repo, head) == ()


@pytest.mark.parametrize('task', [_TASK_TEXT, '---\nname: t\ndescription: d\n---\n\nT.\n', None])
def test_a_journal_added_to_memory_is_an_entry_of_its_own_even_beside_a_task_md(repo: Path, task: str | None) -> None:
    """No archived-task exemption survives the global ledger (2026-11-23): each added file is an entry."""
    _lane(repo)
    paths = [_JOURNAL]
    _write(repo, _JOURNAL, '# Journal\n')
    if task is not None:
        _write(repo, _TASK_MD, task)
        paths.append(_TASK_MD)
    found = _push(repo, _commit(repo, 'no task', *paths))
    assert len(found) == 1, found
    assert _JOURNAL in found[0], found


ATTACHMENT = '.claude/memory/2026/10/01/attachments/manifest.toml'
_CITING = _HEAD + 'Its manifest: attachments/manifest.toml.\nBody.\n'
_CITED = _HEAD + 'Its manifest: cases/x/manifest.toml@abc1234.\nBody.\n'


def _deletion_note(names: str = '2026/10/01/attachments/manifest.toml', approved: str = 'delete the duplicate') -> str:
    return _amend_note(reason=f'deleted {names}, a duplicate of a case file', approved=approved)


def _published_attachment(repo: Path) -> str:
    _write(repo, ENTRY, _CITING)
    _write(repo, ATTACHMENT, "[case]\nname = 'x'\n")
    _commit(repo, 'attach', ENTRY, ATTACHMENT)
    _publish(repo)
    return _lane(repo)


def test_an_approved_attachment_deletion_passes(repo: Path) -> None:
    """ATTACHMENT-DELETE (user ruling 2026-11-24): an entry's note names the deleted attachment and the approval."""
    base = _published_attachment(repo)
    _git(repo, 'rm', '-q', ATTACHMENT)
    _write(repo, ENTRY, _CITED.replace(_HEAD, f'{_HEAD}{_deletion_note()}\n\n'))
    _commit(repo, 'cite instead', ENTRY)
    assert memoryadds.problems_between(repo, base, 'HEAD') == ()


@pytest.mark.parametrize(
    'note',
    [
        None,  # no note at all
        'approved-empty',  # the reason without the user's words
        'other-path',  # the note names a different attachment
        'not-deleted',  # an amendment that does not say deleted
        'published-note',  # a note the base already held approves nothing new
    ],
)
def test_planted_an_attachment_deletion_without_its_approval_is_refused_by_name(repo: Path, note: str | None) -> None:
    """PLANTED CONTROL: a deletion is refused, naming the attachment and its door, unless a NEW note approves it."""
    if note == 'published-note':
        _write(repo, ENTRY, _CITING.replace(_HEAD, f'{_HEAD}{_deletion_note()}\n\n'))
        _write(repo, ATTACHMENT, "[case]\nname = 'x'\n")
        _commit(repo, 'attach', ENTRY, ATTACHMENT)
        _publish(repo)
        base = _lane(repo)
        _git(repo, 'rm', '-q', ATTACHMENT)
        _git(repo, 'commit', '-q', '-m', 'drop')
    else:
        base = _published_attachment(repo)
        _git(repo, 'rm', '-q', ATTACHMENT)
        line = {
            None: '',
            'approved-empty': _deletion_note(approved=''),
            'other-path': _deletion_note(names='2026/10/01/attachments/other.toml'),
            'not-deleted': _amend_note(reason='2026/10/01/attachments/manifest.toml was cited'),
        }[note]
        _write(repo, ENTRY, _CITED.replace(_HEAD, f'{_HEAD}{line}\n\n' if line else _HEAD))
        _commit(repo, 'cite instead', ENTRY)
    found = memoryadds.problems_between(repo, base, 'HEAD')
    refusal = [line for line in found if ATTACHMENT in line]
    assert len(refusal) == 1, found
    assert 'ATTACHMENT-DELETE' in refusal[0]
    assert 'deleted <attachment>' in refusal[0]


def test_planted_an_approval_note_never_admits_deleting_an_entry(repo: Path) -> None:
    """PLANTED CONTROL: the door is for attachments -- an entry (``.md`` outside attachments/) stays undeletable."""
    base = _lane(repo)
    _git(repo, 'rm', '-q', SOURCES[0])
    _write(repo, ENTRY, _HEAD + _deletion_note(names='2026/10/01/a.md') + '\n\nBody.\n')
    _commit(repo, 'drop an entry', ENTRY)
    found = memoryadds.problems_between(repo, base, 'HEAD')
    assert any(SOURCES[0] in line and 'never deleted' in line for line in found), found


@pytest.mark.parametrize(
    ('path', 'attachment'),
    [
        ('.claude/memory/2026/10/01/attachments/INDEX.md', True),
        ('.claude/memory/2026/10/01/probe.py', True),
        ('.claude/memory/2026/10/01/an-entry.md', False),
        ('.claude/memory/2026/08/30/.archive/handoff.md', True),
        ('.claude/memory/2026/09/27/.archive/skills/git-tidy/SKILL.md', True),
        ('docs/attachments/x.toml', False),
    ],
)
def test_an_attachment_is_a_memory_file_that_is_not_an_entry(path: str, *, attachment: bool) -> None:
    assert memoryentry.is_attachment(path) is attachment


# ROOT-MOVE (user ruling R7 2026-11-23): a nested scope's entry moves into the root dated tree, text byte-identical,
# approved by an amendment note the same range adds naming old -> new. Each admit below has its planted refusal.
SCOPED = 'pkg/.claude/memory/2026/10/01/scoped.md'
ROOTED = '.claude/memory/2026/10/01/scoped.md'
_SCOPED_TEXT = '---\nname: scoped\ndescription: d\n---\n\nScoped body.\n'
_NOTE_ENTRY = '.claude/memory/2026/11/23/scoped-memory-moves-to-the-root.md'


def _move_note(
    pair: str = f'{SCOPED} -> {ROOTED}', reason: str = 'moved', approved: str = 'user ruling R7 2026-11-23'
) -> str:
    return '> ' + memoryentry.AMENDMENT_NOTE.format(day='2026-11-23', reason=f'{reason} {pair}', approved=approved)


def _moved(repo: Path, *, new: str = ROOTED, text: str = _SCOPED_TEXT, note: str | None = None) -> tuple[str, ...]:
    _write(repo, SCOPED, _SCOPED_TEXT)
    _commit(repo, 'scoped entry', SCOPED)
    _publish(repo)
    _lane(repo)
    _git(repo, 'rm', '-q', SCOPED)
    _write(repo, new, text)
    paths = [new]
    if note is not None:
        _write(repo, _NOTE_ENTRY, f'---\nname: r7\ndescription: d\n---\n\n{note}\n')
        paths.append(_NOTE_ENTRY)
    _commit(repo, 'move', *paths)
    return _push(repo, _git(repo, 'rev-parse', 'HEAD'))


def test_an_approved_byte_identical_move_into_the_root_passes(repo: Path) -> None:
    assert _moved(repo, note=_move_note()) == ()


def test_one_note_naming_both_memory_directories_carries_a_whole_scope(repo: Path) -> None:
    assert _moved(repo, note=_move_note('pkg/.claude/memory/ -> .claude/memory/')) == ()


def test_planted_a_move_without_its_note_is_refused_and_names_the_door(repo: Path) -> None:
    found = _moved(repo)
    assert len(found) == 1, found
    assert SCOPED in found[0]
    assert 'ROOT-MOVE' in found[0]


@pytest.mark.parametrize(
    ('change', 'kwargs'),
    [
        ('text changed', {'text': _SCOPED_TEXT.replace('Scoped body', 'Rewritten'), 'note': _move_note()}),
        (
            'another dated dir',
            {
                'new': '.claude/memory/2026/10/02/scoped.md',
                'note': _move_note(f'{SCOPED} -> .claude/memory/2026/10/02/scoped.md'),
            },
        ),
        ('note names other paths', {'note': _move_note(f'{SCOPED} -> .claude/memory/2026/10/01/other.md')}),
        ('reason does not say moved', {'note': _move_note(reason='relocated')}),
        ('no user words', {'note': _move_note(approved=' ')}),
    ],
)
def test_planted_a_move_breaking_one_condition_is_refused(repo: Path, change: str, kwargs: dict) -> None:
    assert _moved(repo, **kwargs), change


def test_planted_a_move_between_two_nested_scopes_is_refused() -> None:
    other = 'other/.claude/memory/2026/10/01/scoped.md'
    assert not memoryentry.move_approved(SCOPED, other, [_move_note(f'{SCOPED} -> {other}')])
    assert memoryentry.move_approved(SCOPED, ROOTED, [_move_note()])  # control: the root admits it
