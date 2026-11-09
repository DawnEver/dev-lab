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
MANUAL = '.claude/memory/2026/11/05/manual.md'
# rem 2.2 task-engine.js handleAdd's exact dedicated task-list shape, not a generic memory entry.
MANUAL_HEAD = (
    '---\nname: manual-2026-11-05\ndescription: Manual tasks created on 2026-11-05\nmetadata:\n  type: project\n---\n\n'
)
MANUAL_FIRST = (
    '- [ ] MANUAL-20261105-694 [HIGH] Deferred heavy acceptance; keep its evidence bar. (2026-11-05)\n'
    '      module: acceptance\n'
)
MANUAL_NEXT = (
    '- [ ] MANUAL-20261105-695 [HIGH] Measure the exact unmeasured geometry identities. (2026-11-05)\n'
    '      module: euclid.geometry\n'
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


def test_a_lane_that_only_adds_memory_passes(repo: Path) -> None:
    base = _lane(repo)
    _write(repo, '.claude/memory/2026/10/31/new.md', '---\nname: new\ndescription: d\n---\n\nNew.\n')
    _commit(repo, 'add', '.claude/memory/2026/10/31/new.md')
    assert memoryadds.problems_between(repo, base, 'HEAD') == ()


@pytest.mark.parametrize('operation', ['append', 'append_closed', 'close', 'reopen'])
def test_rem_manual_task_operations_pass_both_index_and_push(repo: Path, operation: str) -> None:
    before = MANUAL_HEAD + MANUAL_FIRST
    if operation == 'reopen':
        before = before.replace('- [ ]', '- [x]')
    _write(repo, MANUAL, before)
    _commit(repo, 'original manual tasks', MANUAL)
    base = _lane(repo)
    after = (
        before + '\n' + MANUAL_NEXT
        if operation.startswith('append')
        else before.replace(
            '- [x]' if operation == 'reopen' else '- [ ]', '- [ ]' if operation == 'reopen' else '- [x]'
        )
    )
    if operation == 'append_closed':
        after = before + '\n' + MANUAL_NEXT.replace('- [ ]', '- [x]')
    _write(repo, MANUAL, after)
    _git(repo, 'add', '--', MANUAL)
    assert memoryadds.pending(repo) == ()
    _commit(repo, 'task state', MANUAL)
    assert memoryadds.problems_between(repo, base, 'HEAD') == ()


@pytest.mark.parametrize(
    'after',
    [
        MANUAL_HEAD + MANUAL_FIRST.replace('evidence bar', 'new claim'),
        MANUAL_HEAD + MANUAL_FIRST.replace('acceptance\n', 'geometry\n'),
        MANUAL_HEAD + MANUAL_FIRST.replace('[HIGH]', '[LOW]'),
        MANUAL_HEAD,
        MANUAL_HEAD + MANUAL_FIRST + '\nA historical claim rewritten in a task file.\n',
        MANUAL_HEAD + MANUAL_FIRST + '\n' + MANUAL_FIRST,
        MANUAL_HEAD + MANUAL_FIRST + '\n' + MANUAL_NEXT.replace('20261105', '20261106'),
        MANUAL_HEAD + MANUAL_FIRST + '\n' + MANUAL_NEXT.replace('(2026-11-05)', '(2026-11-06)'),
        MANUAL_HEAD + MANUAL_NEXT + '\n' + MANUAL_FIRST,
        (MANUAL_HEAD + MANUAL_FIRST).replace('type: project', 'type: bypass'),
    ],
)
def test_manual_filename_never_allows_task_content_rewrites_or_memory_injection(repo: Path, after: str) -> None:
    _write(repo, MANUAL, MANUAL_HEAD + MANUAL_FIRST)
    _commit(repo, 'original manual tasks', MANUAL)
    base = _lane(repo)
    _write(repo, MANUAL, after)
    _git(repo, 'add', '--', MANUAL)
    assert memoryadds.pending(repo)
    _commit(repo, 'planted bypass', MANUAL)
    assert memoryadds.problems_between(repo, base, 'HEAD')


@pytest.mark.parametrize('path', [MANUAL, ENTRY, 'src/x/' + MANUAL])
def test_ordinary_memory_cannot_turn_into_a_mutable_manual_list(repo: Path, path: str) -> None:
    _write(repo, path, '---\nname: manual-2026-11-05\n---\n\nImmutable prose.\n')
    _commit(repo, 'ordinary entry', path)
    _write(repo, path, MANUAL_HEAD + MANUAL_FIRST)
    _git(repo, 'add', '--', path)
    assert memoryadds.pending(repo)


def test_manual_refusal_names_the_versioned_task_format_and_remedy(repo: Path) -> None:
    _write(repo, MANUAL, MANUAL_HEAD + MANUAL_FIRST)
    _commit(repo, 'original task', MANUAL)
    _write(repo, MANUAL, MANUAL_HEAD + MANUAL_FIRST.replace('evidence bar', 'rewritten history'))
    _git(repo, 'add', '--', MANUAL)
    refusal = '\n'.join(memoryadds.pending(repo))
    assert 'rem 2.2.0' in refusal
    assert 'append tasks or toggle checkboxes' in refusal
    assert 'immutable' in refusal


@pytest.mark.parametrize('prefix', ['', 'src/x/'])
def test_scoped_manual_task_format_preserves_crlf_operations(prefix: str) -> None:
    before = MANUAL_HEAD + MANUAL_FIRST
    after = before.replace('- [ ]', '- [x]') + '\n' + MANUAL_NEXT
    assert memoryadds._only_manual_tasks_updated(prefix + MANUAL, before.replace('\n', '\r\n'), after)


@pytest.mark.parametrize('path', [ENTRY, MANUAL.replace('manual.md', 'narrative.md'), MANUAL.replace('/11/', '/99/')])
def test_a_task_shaped_body_cannot_make_another_memory_path_mutable(path: str) -> None:
    before = MANUAL_HEAD + MANUAL_FIRST
    assert not memoryadds._only_manual_tasks_updated(path, before, before + '\n' + MANUAL_NEXT)


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
        + memoryadds.REDACTION_NOTE.format(day='2026-11-09')
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
    note = '> ' + memoryadds.REDACTION_NOTE.format(day='2026-11-09')
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

    It is the integration line's own change, judged where it was made. MEASURED 2026-11-01: a consumer lane
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


def test_restoring_an_entry_the_lane_edited_to_the_integration_lines_text_passes(repo: Path) -> None:
    """The remedy the refusal prints -- restore the entry -- must itself be committable.

    MEASURED 2026-11-01: a lane holding three old in-place edits restored them to origin/integrate/main's text and
    the commit was refused, because the restore is a change against HEAD. An entry staged exactly as the integration
    line holds it is not an edit by this commit.
    """
    _lane(repo)
    _write(repo, ENTRY, '---\nname: an-entry\ndescription: d\naccessed: 2026-10-02\n---\n\nEdited in place.\n')
    _commit(repo, 'lane edits in place (before the rule)', ENTRY)
    _git(repo, 'checkout', 'origin/integrate/main', '--', ENTRY)
    assert memoryadds.pending(repo) == ()


def test_planted_a_lane_rewriting_an_entry_to_neither_text_is_still_refused(repo: Path) -> None:
    """PLANTED CONTROL: the lane's second edit matches neither HEAD nor the integration line -- an edit."""
    _lane(repo)
    _write(repo, ENTRY, '---\nname: an-entry\ndescription: d\naccessed: 2026-10-02\n---\n\nEdited in place.\n')
    _commit(repo, 'lane edits in place (before the rule)', ENTRY)
    _write(repo, ENTRY, '---\nname: an-entry\ndescription: d\naccessed: 2026-10-02\n---\n\nEdited again.\n')
    _git(repo, 'add', '--', ENTRY)
    found = memoryadds.pending(repo)
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
    """The commit-msg row: entry and sources staged together are one addition."""
    rels = ['.claude/memory/2026/11/04/x.md', '.claude/memory/2026/11/04/y.md']
    for rel in rels:
        _write(repo, rel, '---\nname: s\ndescription: d\n---\n\nS.\n')
    _write(repo, '.claude/memory/2026/11/04/m.md', SAME_PUSH)
    _git(repo, 'add', '--', *rels, '.claude/memory/2026/11/04/m.md')
    assert memoryadds.pending(repo) == ()


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
    """Immutability starts at publication: an entry absent from origin/<integration> is a draft."""
    _lane(repo)
    rel = '.claude/memory/2026/11/04/draft.md'
    _write(repo, rel, '---\nname: draft\ndescription: d\n---\n\nUncited claim.\n')
    _commit(repo, 'draft', rel)
    _write(repo, rel, '---\nname: draft\ndescription: d\n---\n\nCited claim (2026/10/01/a.md).\n')
    _git(repo, 'add', '--', rel)
    assert memoryadds.pending(repo) == ()
    _commit(repo, 'cite', rel)
    _git(repo, 'rm', '-q', '--', rel)
    assert memoryadds.pending(repo) == ()


def test_planted_an_edit_to_a_published_entry_is_still_refused(repo: Path) -> None:
    """PLANTED CONTROL: ENTRY is on origin/integrate/main, so editing it stays refused."""
    _lane(repo)
    _write(repo, ENTRY, '---\nname: an-entry\ndescription: d\n---\n\nRewritten.\n')
    _git(repo, 'add', '--', ENTRY)
    found = memoryadds.pending(repo)
    assert len(found) == 1, found
    assert ENTRY in found[0]


def test_planted_a_draft_entry_turning_into_a_task_list_is_still_refused(repo: Path) -> None:
    """PLANTED CONTROL: the draft exemption is the immutability rule only, never the task-format rule."""
    _lane(repo)
    rel = '.claude/memory/2026/11/04/draft.md'
    _write(repo, rel, '---\nname: draft\ndescription: d\n---\n\nImmutable prose.\n')
    _commit(repo, 'draft', rel)
    _write(repo, rel, MANUAL_HEAD + MANUAL_FIRST)
    _git(repo, 'add', '--', rel)
    assert memoryadds.pending(repo)
