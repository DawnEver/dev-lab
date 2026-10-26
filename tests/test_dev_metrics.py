"""THE BASELINE IS LOGGED, NOT REMEMBERED: one JSONL per kind through one writer, and one read of the plan's metrics."""

from __future__ import annotations

import dataclasses
import json
import os
import shutil
import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from lab_commons.config import config_path

from dev_lab.dev import forgecli, integrate, metrics
from dev_lab.dev.datedlog import date_parts
from dev_lab.dev.metrics import BYPASS, HAND_ACTION, HOST_FAILURE, PUSH, REFUSAL, compute, read, record

REPO = 'https://forge.example/o/r.git'
SINCE = datetime(2026, 10, 1, tzinfo=UTC)
UNTIL = datetime(2026, 11, 1, tzinfo=UTC)
OCT_06 = datetime(2026, 10, 6, tzinfo=UTC)


def _line(kind: str, time: str, **fields: str) -> dict[str, str]:
    return {'time': time, 'event.name': f'lab.{kind}', 'vcs.repository.url.full': REPO, **fields}


def test_a_record_is_dated_program_output_under_the_checkout_never_beside_the_machine_file(tmp_path: Path) -> None:
    """The defect: ``<config dir>/metrics/`` put ``tests/metrics/`` into a repo whose tests point the config there."""
    yy, mm, dd = date_parts()
    path = record(REFUSAL, root=tmp_path, repo=REPO)
    assert path == metrics.log_file(tmp_path, REFUSAL)
    assert path == tmp_path / 'output' / 'logs' / yy / mm / dd / 'metrics' / 'refusal.jsonl'
    assert not (config_path().parent / 'metrics').exists()


def test_every_worktree_of_one_repository_logs_into_its_main_checkout(tmp_path: Path) -> None:
    main_tree, lane = tmp_path / 'main', tmp_path / 'lane'
    main_tree.mkdir()
    ident = ['-c', 'user.name=t', '-c', 'user.email=t@x.invalid']
    for argv in (['init', '-q', '-b', 'main'], [*ident, 'commit', '-q', '--allow-empty', '-m', 'c'],
                 ['worktree', 'add', '-q', str(lane)]):  # fmt: skip
        subprocess.run([shutil.which('git') or 'git', '-C', str(main_tree), *argv], check=True)
    record(PUSH, root=lane, repo=REPO)
    assert len(read(PUSH, root=main_tree)) == 1
    assert not (lane / 'output').exists()


def test_a_record_is_one_otel_named_line_in_its_kinds_file(tmp_path: Path) -> None:
    path = record(
        REFUSAL, root=tmp_path, repo=REPO, rule='session-branch', reason='pre-push', vcs_ref_head_revision='abc1234'
    )
    assert path.name == 'refusal.jsonl'
    record(REFUSAL, root=tmp_path, repo=REPO, rule='ruff', reason='pre-commit')
    lines = read(REFUSAL, root=tmp_path)
    assert [line['lab.rule.id'] for line in lines] == ['session-branch', 'ruff']
    assert lines[0]['event.name'] == 'lab.refusal'
    assert lines[0]['vcs.ref.head.revision'] == 'abc1234'
    assert lines[0]['error.type'] == 'pre-push'
    assert read(PUSH, root=tmp_path) == []


def test_an_unknown_kind_raises_and_a_torn_tail_is_skipped(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match='unknown metrics kind'):
        record('mystery', root=tmp_path, repo=REPO)
    path = record(PUSH, root=tmp_path, repo=REPO)
    with path.open('a', encoding='utf-8') as handle:
        handle.write('{"time": "2026-')
    assert len(read(PUSH, root=tmp_path)) == 1


def test_a_hand_verb_is_recorded_and_a_read_verb_is_not(tmp_path: Path) -> None:
    assert metrics.hand_action(tmp_path, ['status', 'list', 'abcdef1']) is None
    metrics.hand_action(tmp_path, ['status', 'post', 'abcdef1', '--context', 'tests/base', '--state', 'success'])
    metrics.hand_action(tmp_path, ['pr', 'create', '--title', 't', '--head', 'pr/x', '--base', 'integrate/main'])
    metrics.hand_action(tmp_path, ['cancel-stuck', 'abcdef2'])
    lines = read(HAND_ACTION, root=tmp_path)
    assert [line['lab.action'] for line in lines] == ['status post', 'pr create', 'cancel-stuck']
    assert lines[0]['vcs.ref.head.revision'] == 'abcdef1'
    assert lines[1]['vcs.ref.head.name'] == 'pr/x'


def test_the_cli_record_arm_is_what_the_guard_engine_calls(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert metrics.main(['record', REFUSAL, '--repo', REPO, '--rule', 'RECURSIVE-GREP', '--reason', 'agent-guard']) == 0
    assert read(REFUSAL, root=tmp_path)[0]['lab.rule.id'] == 'RECURSIVE-GREP'


def test_the_read_computes_every_metric_of_the_plan() -> None:
    pulls = [
        {'number': 1, 'state': 'closed', 'created_at': '2026-10-02T00:00:00Z', 'merged_at': '2026-10-02T02:00:00Z',
         'head': {'sha': 'aaaa1111', 'ref': 'pr/a'}},
        {'number': 2, 'state': 'closed', 'created_at': '2026-10-03T00:00:00Z', 'merged_at': '2026-10-03T06:00:00Z',
         'head': {'sha': 'bbbb2222', 'ref': 'pr/b'}},
        {'number': 3, 'state': 'open', 'created_at': '2026-10-04T00:00:00Z', 'merged_at': None, 'head': {}},
        {'number': 4, 'state': 'closed', 'created_at': '2026-09-01T00:00:00Z', 'merged_at': '2026-09-02T00:00:00Z',
         'head': {'sha': 'cccc', 'ref': 'pr/c'}},
    ]  # fmt: skip
    records = {
        HAND_ACTION: [
            _line(HAND_ACTION, '2026-10-02T01:00:00+00:00', **{'lab.action': 'pr create', 'vcs.ref.head.name': 'pr/a'}),
            _line(
                HAND_ACTION, '2026-10-03T01:00:00+00:00', **{'lab.action': 'status post', 'vcs.ref.head.revision': 'bb'}
            ),
            _line(HAND_ACTION, '2026-10-03T02:00:00+00:00', **{'lab.action': 'pr close-landed', 'vcs.change.id': '2'}),
        ],
        REFUSAL: [
            _line(REFUSAL, '2026-10-02T00:10:00+00:00', **{'lab.rule.id': 'session-branch'}),
            _line(REFUSAL, '2026-10-02T00:20:00+00:00', **{'lab.rule.id': 'ruff'}),
            _line(REFUSAL, '2026-09-02T00:20:00+00:00', **{'lab.rule.id': 'ruff'}),
            {**_line(REFUSAL, '2026-10-02T00:20:00+00:00'), 'vcs.repository.url.full': 'git@x:o/other.git'},
        ],
        BYPASS: [_line(BYPASS, '2026-10-02T00:30:00+00:00', **{'lab.rule.id': 'session-branch'})],
        PUSH: [_line(PUSH, '2026-10-02T00:00:00+00:00') for _ in range(4)],
        HOST_FAILURE: [_line(HOST_FAILURE, '2026-10-05T00:00:00+00:00')],
    }  # fmt: skip
    found = compute('git@forge.example:o/r.git', records, pulls, since=SINCE, until=UNTIL)
    assert found.median_edit_to_merged_h == 4.0
    assert found.hand_actions_per_pr == 1.0, 'two touches on #2; #1 only opened its own PR'
    assert found.share_merged_untouched == 0.5
    assert (found.refusals, found.pushes, found.refusals_per_push) == (2, 4, 0.5)
    assert (found.candidate_false_positives, found.false_positive_share) == (1, 0.5)
    assert found.open_prs == 1
    assert found.host_failures_without_status == 1
    assert json.dumps(dataclasses.asdict(found))


def test_the_forge_cli_logs_a_hand_verb_only_when_it_succeeded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    codes = iter((1, 0, 0))
    monkeypatch.setitem(forgecli.NOUNS, 'status', lambda _argv: next(codes))
    assert forgecli.main(['status', 'post', 'abcdef1', '--context', 'c', '--state', 'failure']) == 1
    assert forgecli.main(['status', 'post', 'abcdef1', '--context', 'c', '--state', 'success']) == 0
    assert forgecli.main(['status', 'list', 'abcdef1']) == 0
    assert [line['lab.action'] for line in read(HAND_ACTION, root=tmp_path)] == ['status post']


def test_a_promotion_is_a_hand_action_and_its_refusal_a_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    answers = iter(('promote', 'refused'))
    monkeypatch.setattr(integrate, 'promote', lambda _r, _c, sha: integrate.Promotion(next(answers), sha, ('red',)))
    monkeypatch.setattr(integrate, '_policy', lambda _r, _s: SimpleNamespace(trunk='main'))
    run = {'cwd': tmp_path, 'client': object(), 'fetch': lambda _root: None}
    assert integrate.main(['promote', 'abcdef1'], **run) == 0
    assert integrate.main(['promote', 'abcdef2'], **run) == 2
    assert [(a['lab.action'], a['vcs.ref.head.revision']) for a in read(HAND_ACTION, root=tmp_path)] == [
        ('integrate promote', 'abcdef1')
    ]
    assert [(r['lab.rule.id'], r['vcs.ref.head.revision']) for r in read(REFUSAL, root=tmp_path)] == [
        ('integrate-promote', 'abcdef2')
    ]


def _git(root: Path, *argv: str, when: str = '') -> str:
    stamp = {'GIT_AUTHOR_DATE': when, 'GIT_COMMITTER_DATE': when} if when else {}
    done = subprocess.run(
        [shutil.which('git') or 'git', '-C', str(root), '-c', 'user.name=t', '-c', 'user.email=t@x.invalid', *argv],
        check=True, capture_output=True, text=True, encoding='utf-8', env={**os.environ, **stamp},
    )  # fmt: skip
    return done.stdout.strip()


@pytest.fixture
def integration(tmp_path: Path) -> Path:
    """A repository whose ``int`` branch took ``pr/glass`` by a Break-Glass merge, then ``pr/forge`` by a plain one."""
    root = tmp_path / 'repo'
    root.mkdir()
    _git(root, 'init', '-q', '-b', 'int')
    _git(root, 'commit', '-q', '--allow-empty', '-m', 'seed')
    for branch in ('pr/glass', 'pr/forge'):
        _git(root, 'checkout', '-q', '-b', branch, 'int')
        _git(root, 'commit', '-q', '--allow-empty', '-m', f'feat: {branch}')
        _git(root, 'checkout', '-q', 'int')
    glass = 'chore(merge): pr/glass\n\nMerged-Branch: pr/glass\nBreak-Glass: forge down'
    _git(root, 'merge', '--no-ff', '-q', '-m', glass, 'pr/glass', when='2026-10-05T10:00:00+00:00')
    plain = 'chore(merge): pr/forge\n\nMerged-Branch: pr/forge'
    _git(root, 'merge', '--no-ff', '-q', '-m', plain, 'pr/forge', when='2026-10-06T10:00:00+00:00')
    return root


def test_landings_are_the_integration_branchs_named_merges_in_the_window(integration: Path) -> None:
    """The integration branch's first-parent ``Merged-Branch:`` merges, each with its Break-Glass reason or none."""
    found = metrics.landings(integration, 'int', since=SINCE, until=OCT_06)
    assert [(one.branch, one.break_glass, one.time.isoformat()) for one in found] == [
        ('pr/glass', 'forge down', '2026-10-05T10:00:00+00:00')
    ], 'the window has an upper bound: the 10-06 merge is outside it'
    every = metrics.landings(integration, 'int', since=SINCE, until=UNTIL)
    assert [(one.branch, one.break_glass) for one in every] == [('pr/glass', 'forge down'), ('pr/forge', '')]
    assert all(len(one.sha) == 40 for one in every)


def _pull(number: int, ref: str, *, created: str, merged: str | None) -> dict[str, object]:
    return {'number': number, 'state': 'closed', 'created_at': created, 'merged_at': merged,
            'head': {'sha': f'{number:04d}abcd', 'ref': ref}}  # fmt: skip


GLASS = metrics.Landing('a' * 40, datetime(2026, 10, 5, 10, tzinfo=UTC), 'pr/glass', 'forge down')


def test_a_pr_landed_by_a_local_merge_is_merged_and_its_break_glass_is_a_hand_action() -> None:
    """The defect: a PR closed by ``pr close-landed`` after a local merge counted as neither merged nor touched."""
    plain = metrics.Landing('b' * 40, datetime(2026, 10, 6, 10, tzinfo=UTC), 'pr/plain', '')
    pulls = [
        _pull(1, 'pr/glass', created='2026-10-05T04:00:00Z', merged=None),
        _pull(2, 'pr/plain', created='2026-10-06T08:00:00Z', merged=None),
        _pull(3, 'pr/never', created='2026-10-06T08:00:00Z', merged=None),  # PLANTED: closed, named nowhere
    ]
    found = compute(REPO, {}, pulls, since=SINCE, until=UNTIL, landings=[GLASS, plain])
    assert found.merged_prs == 2, 'a head named in a Merged-Branch trailer is a merged PR; #3 is not'
    assert found.median_edit_to_merged_h == 4.0, 'merged at the landing commit: 6 h and 2 h'
    assert found.hand_actions_per_pr == 0.5, 'the Break-Glass merge is a hand action on the PR it carries'
    assert found.share_merged_untouched == 0.5


def test_a_logged_break_glass_and_its_landing_are_one_hand_action() -> None:
    """The log line and the git commit describe one act: counted once, by its sha (a retried push logs twice)."""
    logged = _line(HAND_ACTION, '2026-10-05T10:01:00+00:00', **{
        'lab.action': 'break-glass', 'vcs.ref.head.name': 'pr/glass', 'vcs.ref.head.revision': 'a' * 40,
    })  # fmt: skip
    pulls = [_pull(1, 'pr/glass', created='2026-10-05T04:00:00Z', merged=None)]
    found = compute(REPO, {HAND_ACTION: [logged, logged]}, pulls, since=SINCE, until=UNTIL, landings=[GLASS])
    assert found.hand_actions_per_pr == 1.0


def test_an_edit_starts_at_the_first_push_of_its_branch() -> None:
    """Edit->merged runs from the first push naming the head branch, when that precedes the PR's opening."""
    pulls = [_pull(1, 'pr/a', created='2026-10-02T04:00:00Z', merged='2026-10-02T06:00:00Z')]
    pushes = [
        _line(PUSH, '2026-10-02T03:00:00+00:00', **{'vcs.ref.head.name': 'pr/a'}),
        _line(PUSH, '2026-10-02T00:00:00+00:00', **{'vcs.ref.head.name': 'pr/a'}),
        _line(PUSH, '2026-10-01T00:00:00+00:00', **{'vcs.ref.head.name': 'pr/other'}),  # PLANTED: another branch
    ]
    assert compute(REPO, {PUSH: pushes}, pulls, since=SINCE, until=UNTIL).median_edit_to_merged_h == 6.0


def test_the_window_has_both_bounds() -> None:
    early = _line(REFUSAL, '2026-10-02T00:00:00+00:00', **{'lab.rule.id': 'ruff'})
    late = _line(REFUSAL, '2026-11-02T00:00:00+00:00', **{'lab.rule.id': 'ruff'})
    pulls = [_pull(1, 'pr/a', created='2026-10-30T00:00:00Z', merged='2026-11-02T00:00:00Z')]
    found = compute(REPO, {REFUSAL: [early, late]}, pulls, since=SINCE, until=UNTIL)
    assert (found.refusals, found.merged_prs, found.until) == (1, 0, UNTIL.isoformat())


def test_break_glass_writes_one_hand_action_naming_branch_sha_and_reason(tmp_path: Path) -> None:
    metrics.break_glass(tmp_path, repo=REPO, sha='c' * 40, branch='pr/x', reason='forge down')
    [line] = read(HAND_ACTION, root=tmp_path)
    assert (line['lab.action'], line['vcs.ref.head.name'], line['vcs.ref.head.revision'], line['lab.reason']) == (
        'break-glass',
        'pr/x',
        'c' * 40,
        'forge down',
    )


def test_the_family_is_the_machine_files_served_repos(tmp_path: Path) -> None:
    """ONE declared source: ``[serve] repos`` under ``root``, the list the serving host itself walks."""
    table = {'repos': ['lab-commons', 'dev-lab'], 'root': str(tmp_path)}
    assert metrics.family(table) == [tmp_path / 'lab-commons', tmp_path / 'dev-lab']
    with pytest.raises(ValueError, match=r'\[serve\] repos'):
        metrics.family({})


def test_the_retired_config_dir_lines_are_not_read(tmp_path: Path) -> None:
    """No compat: a line under ``<config dir>/metrics/`` (the writer's old home) is never part of the read."""
    old = config_path().parent / 'metrics' / 'push.jsonl'
    old.parent.mkdir(parents=True, exist_ok=True)
    old.write_text(json.dumps(_line(PUSH, '2026-10-02T00:00:00+00:00')) + '\n', encoding='utf-8')
    assert read(PUSH, root=tmp_path) == []


def test_a_test_run_never_writes_the_real_log(tmp_path: Path) -> None:
    """PLANTED CONTROL for the conftest's isolation: a record aimed at THIS checkout lands in the test's own tree.

    Unisolated, *here* resolves to the repository's main checkout -- the live log every session appends to.
    """
    here = Path(__file__).resolve().parent
    real = Path(_git(here, 'rev-parse', '--path-format=absolute', '--git-common-dir')).parent
    real_file = real.joinpath(metrics.BASE, *date_parts(), metrics.LOG_KIND, 'push.jsonl')
    marker = f'https://forge.example/planted/{uuid.uuid4().hex}.git'
    path = record(PUSH, root=here, repo=marker)
    assert path.is_relative_to(tmp_path), f'a test wrote {path}, outside its own tree'
    assert marker not in (real_file.read_text(encoding='utf-8') if real_file.is_file() else '')
