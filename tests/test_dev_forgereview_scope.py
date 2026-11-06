"""REVIEW-SCOPE: a PR review reads its own change in diff slices; a head is never held, never read path-less.

The branch's own change since its merge base, minus generated files, in slices under one lens each; past the total
budget the rest is listed as unread, strictest lens first.

Real git repositories, the stateful fake forge and a fake review command, as in ``test_dev_forgereview.py``;
every refusal has its planted control.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from _branch_repos import advance, clone_pair
from _forge_fake import git_out, run_git
from _forge_state import StateForge, called_due

from dev_lab.dev.famfiles import GENERATED
from dev_lab.dev.forgereview import review_tick
from dev_lab.dev.forgereview_declared import LENS_FIELD, PATHS_FIELD, RANGE_FIELD, Review, review_from
from dev_lab.dev.forgereview_findings import merge_outputs, parse_findings
from dev_lab.dev.forgereview_scope import (
    FINDINGS_FIELD,
    Budget,
    Slice,
    lens_of,
    plan,
    reviewable,
)
from dev_lab.dev.forgestatus import status_list
from dev_lab.dev.platformparts import REVIEW_CONTEXT
from dev_lab.dev.reviewcode import CODE, NOT_CODE, ONLY_GENERATED, is_code

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
    called_due(forge, head)  # the merge decision called its review due
    command = Recorder()
    review_tick(work, forge, Review(command=_SLICED), base='integrate/main', run=command, ready=_can, host='box')
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
    called_due(forge, head)  # the merge decision called its review due
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
        called_due(forge, head)  # the merge decision called its review due
        command = Recorder()
        review = Review(command=_SLICED, synthesis=synthesis, max_diff_bytes=400)
        review_tick(work, forge, review, base='integrate/main', run=command, ready=_can, host='box')
        assert len(command.ran) == runs
    assert command.ran[-1][0] == 'synth'
    assert command.ran[-1][2].endswith('findings.json')


def test_an_oversize_head_is_read_in_diff_slices_and_the_rest_is_listed(tmp_path: Path) -> None:
    """D123 and the 2026-11-06 fix: an oversize head is never held and never one path-less review.

    The path-less "structure" slice was rendered by ai-lab as an ``agent`` call the forge's headless run mode
    refuses, so every reviewer was ``unsupported`` (motronics #5490). Now: past the total, slices run strictest lens
    first and the code left out is listed in the comment; one file over a slice is a slice of its own.

    PLANTED control: the same head under wide bounds reads every path and lists nothing.
    """
    work, head = _many(tmp_path)
    for review, unread in (
        (Review(command=_SLICED, max_diff_bytes=400, max_total_bytes=500), True),
        (Review(command=_SLICED, max_diff_bytes=100), False),
    ):
        forge = StateForge()
        number = forge.add_pull('pr/x', 'integrate/main', sha=head)
        called_due(forge, head)  # the merge decision called its review due
        command = Recorder()
        review_tick(work, forge, review, base='integrate/main', run=command, ready=_can, host='box')
        runs = [one for one in command.ran if one[0] == 'reviewer']
        assert runs, 'reviewed'
        assert all(any(arg.endswith('.py') for arg in argv) for argv in runs), 'every call names its paths'
        assert runs[0][4] == 'strict', 'the strictest lens is read first'
        statuses = status_list(forge, head)
        assert next(s for s in statuses if s.context == REVIEW_CONTEXT).state == 'success'
        (comment,) = forge.comments[number]
        assert ('Past the review budget, not read' in comment['body']) is unread
    wide = plan(work, 'origin/integrate/main', head, _WIDE)
    assert all(one.paths for one in wide.slices)
    assert wide.unread == ()


def test_a_command_without_paths_runs_once_over_every_path(tmp_path: Path) -> None:
    work, head = _many(tmp_path)
    scope = plan(work, 'origin/integrate/main', head, Budget(slice_bytes=100, total_bytes=200), sliceable=False)
    (whole,) = scope.slices
    assert len(whole.paths) == 4
    assert scope.unread == ()


def _diff_call(one: Slice) -> bool:
    """Whether *one* renders as a diff ``review`` call, the one call mode the headless run mode allows.

    A slice naming no paths was rendered as an ``agent`` call (ai-lab ``method.json``, headless ``call_modes``).
    """
    return bool(one.paths)


def test_every_slice_the_scope_emits_is_a_call_the_headless_run_mode_allows(tmp_path: Path) -> None:
    """PLANTED CONTROL: a path-less slice -- the retired whole-range one -- is refused by the same predicate."""
    assert not _diff_call(Slice('standard', (), 0))
    work, head = _many(tmp_path)
    for budget in (_WIDE, Budget(slice_bytes=100, total_bytes=10**7), Budget(slice_bytes=400, total_bytes=500),
                   Review().budget):  # fmt: skip
        scope = plan(work, 'origin/integrate/main', head, budget)
        assert scope.slices
        assert all(_diff_call(one) for one in scope.slices), budget


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
    scope = plan(work, first, head, Budget(slice_bytes=600, total_bytes=10**6))
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
    """A head whose bulk is prose fits the cap; PLANTED control: code past the same cap is left unread."""
    work, head = _mixed(tmp_path, 'x = 1\n' * 50)
    code_bytes = sum(s.size for s in plan(work, 'origin/integrate/main', head, _WIDE).slices)
    tight = Budget(slice_bytes=10**6, total_bytes=code_bytes)
    assert all(one.paths for one in plan(work, 'origin/integrate/main', head, tight).slices)
    everything = Budget(slice_bytes=200, total_bytes=code_bytes, code=('**',), not_code=())
    over = plan(work, 'origin/integrate/main', head, everything)
    assert all(one.paths for one in over.slices)
    assert over.unread, 'past the cap: the rest is listed, never a path-less review'


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
    called_due(forge, head)  # the merge decision called its review due
    review_tick(work, forge, Review(command=_SLICED), base='integrate/main', run=Recorder(), ready=_can, host='box')
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
    scope = plan(work, first, head, _WIDE)
    (one,) = scope.slices
    assert set(one.paths) == {'a/old.py', 'z/new.py'}
    assert one.size < 200 < len(_BODY)
    assert scope.moved == ('z/new.py',)


def test_a_rename_with_an_edit_costs_its_hunk(tmp_path: Path) -> None:
    """The edited move costs about its hunk; it is not listed as a pure move."""
    work, first, head = _moved(tmp_path, 'added = 1\n')
    scope = plan(work, first, head, _WIDE)
    (one,) = scope.slices
    assert 0 < one.size < 600 < len(_BODY)
    assert scope.moved == ()


def test_a_delete_and_an_unrelated_add_cost_both(tmp_path: Path) -> None:
    """PLANTED control: no rename is detected between unrelated files, so both full diffs count."""
    work, first, head = _moved(tmp_path, unrelated=True)
    scope = plan(work, first, head, _WIDE)
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


def test_a_large_head_is_read_strictest_first_up_to_the_family_total_and_the_rest_listed(tmp_path: Path) -> None:
    """Review spend 2026-11-03 and 2026-11-06: past ``max_total_bytes``, slices up to the total, the rest listed.

    A head past the total reads slices up to it, never a
    path-less review, and lists what it left out. PLANTED CONTROL: the old 4 MB total reads every directory.
    """
    _, work = clone_pair(tmp_path)
    head = ''
    for at in range(12):  # 12 directories of ~150 kB code each: ~1.8 MB, under the old 4 MB total
        (work / f'd{at}').mkdir()
        head = advance(work, 'pr/x', f'd{at}/m.py', ''.join(f'v{n} = {n}\n' for n in range(11_000)))
    old = plan(work, 'origin/integrate/main', head, Budget(slice_bytes=200_000, total_bytes=4_000_000))
    new = plan(work, 'origin/integrate/main', head, Review().budget)
    assert (len(old.slices), old.unread) == (12, ()), 'before: one slice per directory, nothing left out'
    assert new.slices
    assert all(one.paths for one in new.slices)
    assert sum(one.size for one in new.slices) <= Review().budget.total_bytes
    assert len(new.unread) + sum(len(one.paths) for one in new.slices) == 12


def test_the_family_budget_packs_a_mid_size_head_into_fewer_larger_slices(tmp_path: Path) -> None:
    """Under ``max_total_bytes`` a head packs into slices of the raised ``max_diff_bytes``: fewer fixed prompts.

    PLANTED CONTROL: the same head under the old 200 kB slice needs twice the slices.
    """
    _, work = clone_pair(tmp_path)
    head = ''
    for at in range(4):  # 4 directories of ~150 kB code: ~600 kB
        (work / f'd{at}').mkdir()
        head = advance(work, 'pr/x', f'd{at}/m.py', ''.join(f'v{n} = {n}\n' for n in range(11_000)))
    old = plan(work, 'origin/integrate/main', head, Budget(slice_bytes=200_000, total_bytes=4_000_000))
    new = plan(work, 'origin/integrate/main', head, Review().budget)
    assert (len(old.slices), len(new.slices)) == (4, 2)
    assert new.unread == ()
    assert all(one.paths for one in new.slices)
