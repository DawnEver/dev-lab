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
from test_dev_forgereview import JUDGE

from dev_lab.dev.famfiles import GENERATED
from dev_lab.dev.forgepulls import Marker, comment_upsert
from dev_lab.dev.forgereview import (
    LENS_FIELD,
    PATHS_FIELD,
    RANGE_FIELD,
    REVIEW_CONTEXT,
    Review,
    review_from,
    review_tick,
)
from dev_lab.dev.forgereview_findings import merge_outputs, parse_findings
from dev_lab.dev.forgereview_scope import (
    CODE,
    FINDINGS_FIELD,
    NOT_CODE,
    ONLY_GENERATED,
    Budget,
    is_code,
    lens_of,
    own_base,
    plan,
    reviewable,
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
    advance(work, 'pr/x', 'own.py', 'mine\n')
    advance(work, 'integrate/main', 'theirs.py', 'theirs\n')
    head = _merge_integration(work, 'pr/x')
    scope = plan(work, 'origin/integrate/main', head, _WIDE)
    assert [path for one in scope.slices for path in one.paths] == ['own.py']


def test_a_push_after_a_review_is_read_from_the_reviewed_head(tmp_path: Path) -> None:
    """Incremental; PLANTED control: an integration merge after the review reads the whole own change again."""
    _, work = clone_pair(tmp_path)
    first = advance(work, 'pr/x', 'one.py', '1\n')
    second = advance(work, 'pr/x', 'two.py', '2\n')
    assert own_base(work, 'origin/integrate/main', second, (first,)) == first
    assert _paths(work, plan(work, 'origin/integrate/main', second, _WIDE, (first,)).range) == ['two.py']
    advance(work, 'integrate/main', 'theirs.py', 'theirs\n')
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
    review_tick(
        work, forge, Review(judge=JUDGE, command=_SLICED), base='integrate/main', run=command, ready=_can, host='box'
    )
    assert command.ran == []
    found = {(s.context, s.state, s.description) for s in status_list(forge, head)}
    assert found == {(REVIEW_CONTEXT, 'success', ONLY_GENERATED)}, 'nothing to read is no hold to release'


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
    review = Review(judge=JUDGE, command=_SLICED, max_diff_bytes=400)
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
        review = Review(judge=JUDGE, command=_SLICED, synthesis=synthesis, max_diff_bytes=400)
        review_tick(work, forge, review, base='integrate/main', run=command, ready=_can, host='box')
        assert len(command.ran) == runs
    assert command.ran[-1][0] == 'synth'
    assert command.ran[-1][2].endswith('findings.json')


def test_an_oversize_head_gets_one_structure_level_review_over_the_whole_range(tmp_path: Path) -> None:
    """D123: an oversize head gets one whole-range review from the directory level, never a hold.

    User ruling 2026-10-31, superseding the 2026-10-26 hold-on-oversize: too many files means read the
    directories, never hold. Over the total, one file over a slice, or several slices for a command without paths:
    ONE reviewer over the whole range, no paths (ai-lab maps it at directory level), success posted, no hold.

    PLANTED control: the same head under wide bounds is cut into its per-path slices (the slices test).
    """
    work, head = _many(tmp_path)
    for review in (
        Review(judge=JUDGE, command=_SLICED, max_diff_bytes=400, max_total_bytes=500),
        Review(judge=JUDGE, command=_SLICED, max_diff_bytes=100),
        Review(judge=JUDGE, command=('reviewer', '--range', RANGE_FIELD), max_diff_bytes=400),
    ):
        forge = StateForge()
        forge.add_pull('pr/x', 'integrate/main', sha=head)
        command = Recorder()
        review_tick(work, forge, review, base='integrate/main', run=command, ready=_can, host='box')
        (argv,) = [one for one in command.ran if one[0] == 'reviewer']
        assert not any(arg.endswith('.py') for arg in argv), 'no path list: the whole range'
        statuses = status_list(forge, head)
        assert HOLD_CONTEXT not in {s.context for s in statuses}, 'an oversize head is reviewed, never held'
        assert next(s for s in statuses if s.context == REVIEW_CONTEXT).state == 'success'
    wide = plan(work, 'origin/integrate/main', head, _WIDE)
    assert all(one.paths for one in wide.slices)


def test_the_slice_outputs_merge_once_per_finding_id() -> None:
    merged = parse_findings(merge_outputs([_doc('SR-1', 'a'), _doc('SR-1', 'b'), _doc('SR-2', 'a')], 'x..y'))
    assert merged.range == 'x..y'
    assert [one.id for one in merged.findings] == ['SR-1', 'SR-2']
    assert merged.profiles == ('a', 'b')
    assert len(merged.reviewers) == 3


def test_the_merge_carries_the_one_summary_and_every_disposed_id() -> None:
    """The summary is the one call's that printed it; the disposed ids are every call's, once each."""
    summary = {'changes': [{'claim': 'adds a', 'cites': ['abc1234']}], 'open_items': []}

    def doc(**top: object) -> str:
        return json.dumps({**json.loads(_doc()), **top})

    texts = [doc(summary=summary, disposed=[{'id': 'F-1', 'reason': 'r'}]),
             doc(disposed=[{'id': 'F-1', 'reason': 'r'}, {'id': 'F-2', 'reason': 's'}])]  # fmt: skip
    text = merge_outputs(texts, 'x..y')
    assert next(iter(json.loads(text))) == 'summary', 'the summary is the first key, as the engine prints it'
    merged = parse_findings(text)
    assert merged.summary == summary
    assert merged.disposed == (('F-1', 'r'), ('F-2', 's'))
    assert parse_findings(merge_outputs([_doc()], 'x..y')).summary is None, 'PLANTED control: none printed, none'


def test_a_moved_file_is_read_whole_in_one_slice(tmp_path: Path) -> None:
    """PLANTED control: a move across directories puts both paths in one slice, so no reviewer reads a lone delete."""
    _, work = clone_pair(tmp_path)
    body = ''.join(f'x{n} = {n}\n' for n in range(40))
    for name in ('a', 'b', 'c', 'z'):
        (work / name).mkdir()
    first = advance(work, 'pr/x', 'a/old.py', body)
    advance(work, 'pr/x', 'b/pad.py', body.replace('x', 'y'))
    advance(work, 'pr/x', 'c/pad.py', body.replace('x', 'w'))
    run_git(work, 'mv', 'a/old.py', 'z/new.py')
    run_git(work, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qm', 'move')
    run_git(work, 'push', '-q', '--no-verify', 'origin', 'HEAD:refs/heads/pr/x')
    head = git_out(work, 'rev-parse', 'HEAD')
    scope = plan(work, 'origin/integrate/main', head, Budget(slice_bytes=600, total_bytes=10**6), reviewed=[first])
    assert len(scope.slices) > 1, 'the budget must cut the head into slices, else the control is vacuous'
    (holder,) = [one for one in scope.slices if 'a/old.py' in one.paths]
    assert 'z/new.py' in holder.paths


# --- code only (user ruling 2026-10-29) ---------------------------------------------------------------

_NOT_CODE = (
    '.claude/memory/2026/10/29/x.md', 'attic/old/legacy.py', 'docs-src/dev/x.md', 'README.md', 'Cargo.lock',
    'cases/a/golden.npz', 'cases/a/golden_jmag_ring.toml', 'tests/fixtures/f.json', 'data/t.csv', 'output/logs/run.log',
)  # fmt: skip
_CODE = ('src/pkg/a.py', 'rust/Cargo.toml', '.forgejo/workflows/ci.yml', 'scripts/x.sh', 'web/app.mjs')


def _mixed(tmp_path: Path, body: str = 'x = 1\n') -> tuple[Path, str]:
    _, work = clone_pair(tmp_path)
    head = ''
    for path in (*_NOT_CODE, *_CODE):
        (work / path).parent.mkdir(parents=True, exist_ok=True)
        head = advance(work, 'pr/x', path, body)
    return work, head


def test_only_code_is_reviewed_and_the_rest_is_counted(tmp_path: Path) -> None:
    """Prose, data, locks, memory, attic and docs are outside; PLANTED control: every code file is read."""
    work, head = _mixed(tmp_path)
    scope = plan(work, 'origin/integrate/main', head, _WIDE)
    assert sorted(p for one in scope.slices for p in one.paths) == sorted(_CODE)
    assert scope.outside == len(_NOT_CODE)


def test_the_cap_counts_code_bytes_only(tmp_path: Path) -> None:
    """A head whose bulk is prose fits the cap; PLANTED control: the same cap holds it when code is the bulk."""
    work, head = _mixed(tmp_path, 'x = 1\n' * 50)
    code_bytes = sum(s.size for s in plan(work, 'origin/integrate/main', head, _WIDE).slices)
    tight = Budget(slice_bytes=10**6, total_bytes=code_bytes)
    assert all(one.paths for one in plan(work, 'origin/integrate/main', head, tight).slices)
    everything = Budget(slice_bytes=10**6, total_bytes=code_bytes, code=('**',), not_code=())
    (whole,) = plan(work, 'origin/integrate/main', head, everything).slices
    assert whole.paths == (), 'past the cap: one structure-level review of the whole range'


def test_a_head_of_only_prose_is_nothing_to_review(tmp_path: Path) -> None:
    _, work = clone_pair(tmp_path)
    (work / 'docs-src').mkdir()
    head = advance(work, 'pr/x', 'docs-src/a.md', 'prose\n')
    assert plan(work, 'origin/integrate/main', head, _WIDE).slices == ()


def test_a_repo_may_declare_its_own_code_globs() -> None:
    review = review_from('[tool.dev_lab.review]\ncode = ["**/*.md"]\nnot_code = []\n', 'pyproject.toml')
    assert review.budget.code == ('**/*.md',)
    assert review.budget.not_code == ()
    assert Review().budget.code == CODE
    assert Review().budget.not_code == NOT_CODE


def test_the_review_comment_names_the_files_outside_scope(tmp_path: Path) -> None:
    work, head = _mixed(tmp_path)
    forge = StateForge()
    number = forge.add_pull('pr/x', 'integrate/main', sha=head)
    review_tick(
        work, forge, Review(judge=JUDGE, command=_SLICED), base='integrate/main', run=Recorder(), ready=_can, host='box'
    )
    (comment,) = forge.comments[number]
    assert f'{len(_NOT_CODE)} non-code file(s) outside the review scope' in comment['body']


def test_a_not_code_glob_never_hides_code_by_its_name() -> None:
    """Hooks, a ``logs`` package and a ``golden_*`` module execute; PLANTED control: memory and golden data do not."""
    for path in ('.claude/hooks/guard.py', '.claude/hooks/x.sh', 'src/pkg/logs/handler.py', 'tests/golden_helpers.py',
                 'src/pkg/golden_section.py', 'tests/golden_utils/loader.py'):  # fmt: skip
        assert is_code(path, CODE, NOT_CODE), path
    for path in ('.claude/memory/2026/10/29/x.toml', 'cases/a/golden_jmag_ring.toml', 'attic/old/legacy.py'):
        assert not is_code(path, CODE, NOT_CODE), path


# --- a rename is sized by what it changed (D85) -------------------------------------------------------

_BODY = ''.join(f'value_{n} = {n} * {n}\n' for n in range(400))


def _moved(tmp_path: Path, edit: str = '', *, unrelated: bool = False) -> tuple[Path, str, str]:
    """``a/old.py`` reviewed, then moved to ``z/new.py`` (plus *edit*); *unrelated*: a delete and an add."""
    _, work = clone_pair(tmp_path)
    for name in ('a', 'z'):
        (work / name).mkdir()
    first = advance(work, 'pr/x', 'a/old.py', _BODY)
    run_git(work, 'rm', '-q', 'a/old.py')
    other = ''.join(f'other_{n} = "{n}"\n' for n in range(400))
    (work / 'z/new.py').write_text(other if unrelated else _BODY + edit, encoding='utf-8')
    run_git(work, 'add', 'z/new.py')
    run_git(work, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qm', 'move')
    run_git(work, 'push', '-q', '--no-verify', 'origin', 'HEAD:refs/heads/pr/x')
    return work, first, git_out(work, 'rev-parse', 'HEAD')


def test_a_pure_rename_costs_nothing_and_is_listed_as_moved(tmp_path: Path) -> None:
    """A move is still read (both paths, one slice) but its bytes are the rename header, not the file twice."""
    work, first, head = _moved(tmp_path)
    scope = plan(work, 'origin/integrate/main', head, _WIDE, reviewed=[first])
    (one,) = scope.slices
    assert set(one.paths) == {'a/old.py', 'z/new.py'}
    assert one.size < 200 < len(_BODY)
    assert scope.moved == ('z/new.py',)


def test_a_rename_with_an_edit_costs_its_hunk(tmp_path: Path) -> None:
    """The edited move costs about its hunk; it is not listed as a pure move."""
    work, first, head = _moved(tmp_path, 'added = 1\n')
    scope = plan(work, 'origin/integrate/main', head, _WIDE, reviewed=[first])
    (one,) = scope.slices
    assert 0 < one.size < 600 < len(_BODY)
    assert scope.moved == ()


def test_a_delete_and_an_unrelated_add_cost_both(tmp_path: Path) -> None:
    """PLANTED control: no rename is detected between unrelated files, so both full diffs count."""
    work, first, head = _moved(tmp_path, unrelated=True)
    scope = plan(work, 'origin/integrate/main', head, _WIDE, reviewed=[first])
    assert sum(one.size for one in scope.slices) > 2 * len(_BODY) * 0.9
    assert scope.moved == ()


def test_a_derived_glob_matches_whole_paths_on_the_declared_minimum_python() -> None:
    """``*`` stays in one segment, ``**`` spans any; no 3.13-only ``PurePath.full_match`` (CI row ran 3.12)."""
    derived = ('docs/**/*.json', '*.lock')
    assert not reviewable('docs/a/b/c.json', derived)
    assert not reviewable('docs/c.json', derived)
    assert not reviewable('uv.lock', derived)
    assert reviewable('sub/uv.lock', derived)
    assert reviewable('docs/a/c.py', derived)
