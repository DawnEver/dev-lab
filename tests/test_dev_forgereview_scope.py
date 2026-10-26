"""REVIEW-SCOPE: a PR review reads its own change in slices; a head it cannot read so is held, never skipped.

The branch's own change, minus generated files, since its last reviewed head, in slices under one lens each.

Real git repositories, the stateful fake forge and a fake review command, as in ``test_dev_forgereview.py``;
every refusal has its planted control.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from _branch_repos import advance, clone_pair
from _forge_fake import git_out, run_git
from _forge_state import StateForge

from dev_lab.dev.famfiles import GENERATED
from dev_lab.dev.forgepulls import Marker, comment_upsert
from dev_lab.dev.forgereview import (
    LENS_FIELD,
    PATHS_FIELD,
    RANGE_FIELD,
    REVIEW_CONTEXT,
    Review,
    review_tick,
)
from dev_lab.dev.forgereview_findings import merge_outputs, parse_findings
from dev_lab.dev.forgereview_scope import (
    FINDINGS_FIELD,
    ONLY_GENERATED,
    OVER_CAP_TAKEOVER,
    Budget,
    lens_of,
    own_base,
    plan,
    reviewed_heads,
)
from dev_lab.dev.forgestatus import status_list
from dev_lab.dev.platformparts import HOLD_CONTEXT

_SLICED = ('reviewer', '--range', RANGE_FIELD, '--lens', LENS_FIELD, '--paths', PATHS_FIELD)
_WIDE = Budget(slice_bytes=10**6, total_bytes=10**7)


def _doc(fid: str = 'SR-1', name: str = 'correctness') -> str:
    reviewer = {'name': name, 'provider': 'anthropic', 'status': 'ok', 'dropped_findings': 0}
    finding = {
        'id': fid, 'severity': 'LOW', 'security': False, 'rule': 'occams-razor', 'file': 'a.txt', 'anchor': 'a',
        'summary': 's', 'category': 'Bug', 'status': 'OPEN',
        'suggestion': '', 'detail': '', 'confidence': 'single', 'reviewers': [{'name': name, 'provider': 'anthropic'}],
    }  # fmt: skip
    return json.dumps({'schema_version': 3, 'range': 'a..b', 'profiles': [name], 'reviewers': [reviewer],
                       'findings': [finding]})  # fmt: skip


class Recorder:
    """A review command printing one findings document per run, recording each argv."""

    def __init__(self) -> None:
        """No run yet."""
        self.ran: list[list[str]] = []

    def __call__(self, argv: Sequence[str], _root: Path) -> str:
        self.ran.append(list(argv))
        return _doc(f'SR-{len(self.ran)}')


def _can(_argv: Sequence[str], _root: Path) -> str | None:
    return None


def _merge_integration(work: Path, branch: str) -> str:
    """Merge ``origin/integrate/main`` into *branch* and push it; the merge sha."""
    run_git(work, 'checkout', '-q', '-B', 'tmp-merge', f'origin/{branch}')
    run_git(work, '-c', 'user.name=t', '-c', 'user.email=t@t', 'merge', '-q', '--no-edit', 'origin/integrate/main')
    run_git(work, 'push', '-q', '--no-verify', 'origin', f'HEAD:refs/heads/{branch}')
    run_git(work, 'fetch', '-q', 'origin')
    return git_out(work, 'rev-parse', 'HEAD')


def _paths(work: Path, reviewed: str) -> list[str]:
    return git_out(work, 'diff', '--name-only', reviewed).splitlines()


# --- the range ---------------------------------------------------------------------------------------


def test_a_merge_of_the_integration_branch_is_not_the_branchs_own_change(tmp_path: Path) -> None:
    """PLANTED control: the branch's own file is read, the merged-in one is not."""
    _, work = clone_pair(tmp_path)
    advance(work, 'pr/x', 'own.txt', 'mine\n')
    advance(work, 'integrate/main', 'theirs.txt', 'theirs\n')
    head = _merge_integration(work, 'pr/x')
    scope = plan(work, 'origin/integrate/main', head, _WIDE)
    assert [path for one in scope.slices for path in one.paths] == ['own.txt']


def test_a_push_after_a_review_is_read_from_the_reviewed_head(tmp_path: Path) -> None:
    """Incremental; PLANTED control: an integration merge after the review reads the whole own change again."""
    _, work = clone_pair(tmp_path)
    first = advance(work, 'pr/x', 'one.txt', '1\n')
    second = advance(work, 'pr/x', 'two.txt', '2\n')
    assert own_base(work, 'origin/integrate/main', second, (first,)) == first
    assert _paths(work, plan(work, 'origin/integrate/main', second, _WIDE, (first,)).range) == ['two.txt']
    advance(work, 'integrate/main', 'theirs.txt', 'theirs\n')
    merged = _merge_integration(work, 'pr/x')
    base = git_out(work, 'merge-base', 'origin/integrate/main', merged)
    assert own_base(work, 'origin/integrate/main', merged, (first,)) == base


def test_the_reviewed_heads_are_read_from_the_review_comments() -> None:
    forge = StateForge()
    number = forge.add_pull('pr/x', 'integrate/main', sha='a' * 40)
    comment_upsert(forge, number, kind=Marker.REVIEW, key='b' * 40, text='reviewed')
    comment_upsert(forge, number, kind=Marker.LANDED, key='c' * 40, text='landed')
    assert reviewed_heads(one['body'] for one in forge.comments[number]) == ('b' * 40,)


# --- what is read ------------------------------------------------------------------------------------


def test_generated_files_are_not_read(tmp_path: Path) -> None:
    """The family's renders and the declared globs; PLANTED control: a hand-written file beside them is read."""
    assert 'uv.lock' in GENERATED
    _, work = clone_pair(tmp_path)
    advance(work, 'pr/x', 'uv.lock', 'lock\n')
    advance(work, 'pr/x', 'golden.json', '{}\n')
    head = advance(work, 'pr/x', 'code.py', 'x = 1\n')
    budget = Budget(slice_bytes=10**6, total_bytes=10**7, derived=('*.json',))
    assert [p for one in plan(work, 'origin/integrate/main', head, budget).slices for p in one.paths] == ['code.py']


def test_a_head_of_only_generated_files_is_posted_as_nothing_to_review(tmp_path: Path) -> None:
    _, work = clone_pair(tmp_path)
    head = advance(work, 'pr/x', 'uv.lock', 'lock\n')
    forge = StateForge()
    forge.add_pull('pr/x', 'integrate/main', sha=head)
    command = Recorder()
    review_tick(work, forge, Review(command=_SLICED), base='integrate/main', run=command, ready=_can, host='box')
    assert command.ran == []
    found = {(s.context, s.state, s.description) for s in status_list(forge, head)}
    assert found == {(c, 'success', ONLY_GENERATED) for c in (REVIEW_CONTEXT, HOLD_CONTEXT)}


def test_each_path_earns_its_lens() -> None:
    review = Review()
    for path, lens in (
        ('.claude/hooks/deny.js', 'strict'), ('tests/architecture/test_x.py', 'strict'),
        ('src/pkg/contracts/ir.py', 'strict'), ('.claude/rules/taste.md', 'strict'),
        ('docs-src/dev/x.md', 'light'), ('.claude/memory/2026/10/24/x.md', 'light'), ('README.md', 'light'),
        ('src/pkg/solver.py', 'standard'),
    ):  # fmt: skip
        assert lens_of(path, review.strict, review.light) == lens, path


# --- slices ------------------------------------------------------------------------------------------


def _many(tmp_path: Path) -> tuple[Path, str]:
    _, work = clone_pair(tmp_path)
    for name in ('a', 'b', 'c'):
        (work / name).mkdir(exist_ok=True)
        advance(work, 'pr/x', f'{name}/f.py', 'x = 1\n' * 40)
    (work / 'tests' / 'architecture').mkdir(parents=True, exist_ok=True)
    head = advance(work, 'pr/x', 'tests/architecture/test_t.py', 'x = 1\n')
    return work, head


def test_a_head_past_one_slice_is_read_in_slices_each_under_one_lens(tmp_path: Path) -> None:
    """Every slice runs the command once with its paths and lens; the outputs merge into one comment."""
    work, head = _many(tmp_path)
    forge = StateForge()
    number = forge.add_pull('pr/x', 'integrate/main', sha=head)
    command = Recorder()
    review = Review(command=_SLICED, max_diff_bytes=400)
    review_tick(work, forge, review, base='integrate/main', run=command, ready=_can, host='box')
    assert [argv[4] for argv in command.ran] == ['strict', 'standard', 'standard', 'standard']
    read = sorted(path for argv in command.ran for path in argv[6:])
    assert read == ['a/f.py', 'b/f.py', 'c/f.py', 'tests/architecture/test_t.py']
    (comment,) = forge.comments[number]
    assert all(f'SR-{n}' in comment['body'] for n in range(1, 5))
    assert next(s.state for s in status_list(forge, head) if s.context == REVIEW_CONTEXT) == 'success'


def test_a_synthesis_reads_the_merged_slices_once(tmp_path: Path) -> None:
    """PLANTED control: undeclared, no fifth run."""
    work, head = _many(tmp_path)
    for synthesis, runs in (((), 4), (('synth', '--findings', FINDINGS_FIELD, '--range', RANGE_FIELD), 5)):
        forge = StateForge()
        forge.add_pull('pr/x', 'integrate/main', sha=head)
        command = Recorder()
        review = Review(command=_SLICED, synthesis=synthesis, max_diff_bytes=400)
        review_tick(work, forge, review, base='integrate/main', run=command, ready=_can, host='box')
        assert len(command.ran) == runs
    assert command.ran[-1][0] == 'synth'
    assert command.ran[-1][2].endswith('findings.json')


def test_a_head_the_slices_cannot_hold_is_held_for_a_session(tmp_path: Path) -> None:
    """Over the total, one file over a slice, or several slices for a command without paths: OVER_CAP_TAKEOVER.

    PLANTED control: the same head under wide bounds is reviewed (the slices test).
    """
    work, head = _many(tmp_path)
    for review in (
        Review(command=_SLICED, max_diff_bytes=400, max_total_bytes=500),
        Review(command=_SLICED, max_diff_bytes=100),
        Review(command=('reviewer', '--range', RANGE_FIELD), max_diff_bytes=400),
    ):
        forge = StateForge()
        forge.add_pull('pr/x', 'integrate/main', sha=head)
        command = Recorder()
        review_tick(work, forge, review, base='integrate/main', run=command, ready=_can, host='box')
        assert command.ran == []
        statuses = status_list(forge, head)
        assert sorted(s.context for s in statuses) == [REVIEW_CONTEXT, HOLD_CONTEXT]
        assert all(s.state == 'pending' and s.description.startswith(OVER_CAP_TAKEOVER) for s in statuses)


def test_the_slice_outputs_merge_once_per_finding_id() -> None:
    merged = parse_findings(merge_outputs([_doc('SR-1', 'a'), _doc('SR-1', 'b'), _doc('SR-2', 'a')], 'x..y'))
    assert merged.range == 'x..y'
    assert [one.id for one in merged.findings] == ['SR-1', 'SR-2']
    assert merged.profiles == ('a', 'b')
    assert len(merged.reviewers) == 3
