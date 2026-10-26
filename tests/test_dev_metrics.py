"""THE BASELINE IS LOGGED, NOT REMEMBERED: one JSONL per kind through one writer, and one read of the plan's metrics."""

from __future__ import annotations

import dataclasses
import json
import subprocess
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
        subprocess.run(['git', '-C', str(main_tree), *argv], check=True)  # noqa: S607
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
    found = compute('git@forge.example:o/r.git', records, pulls, since=SINCE)
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
