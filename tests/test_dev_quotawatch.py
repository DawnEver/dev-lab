"""A QUOTA WARNS BEFORE IT FILLS (user ruling 2026-11-22): one declared pair of lines, files AND bytes stated.

Each warning has its PLANTED CONTROL beside it: an account well under both lines is never warned.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dev_lab.dev import quotawatch, retention
from dev_lab.dev.diskusage import Usage
from dev_lab.dev.retention import Freed
from dev_lab.dev.retentionplan import Plan, Policy

_GB = 1024**3
#: The incident's shape: files past the soft quota, bytes far from theirs.
FULL_FILES = Usage(43 * _GB, 1000 * _GB, 2_019_981, 2_000_000)
NEAR_FILES = Usage(43 * _GB, 1000 * _GB, 1_760_000, 2_000_000)
NEAR_BYTES = Usage(900 * _GB, 1000 * _GB, 100_000, 2_000_000)
CALM = Usage(43 * _GB, 1000 * _GB, 400_000, 2_000_000)


def test_the_lines_are_declared_once_with_warn_below_refuse() -> None:
    policy = quotawatch.declared_lines({})
    assert (policy.pressure, policy.refuse) == (0.85, 0.95)
    assert quotawatch.declared_lines({'pressure': 0.5, 'refuse': 0.6}).refuse == 0.6
    with pytest.raises(ValueError, match='no key'):
        quotawatch.declared_lines({'warn': 0.5})


@pytest.mark.parametrize(
    ('usage', 'name', 'binding'),
    [
        (FULL_FILES, quotawatch.FULL, 'files'),
        (NEAR_FILES, quotawatch.NEAR, 'files'),
        (NEAR_BYTES, quotawatch.NEAR, 'bytes'),
    ],
)
def test_a_line_reached_is_named_with_its_binding_ceiling_and_door(usage: Usage, name: str, binding: str) -> None:
    watch = quotawatch.judge(usage, Policy())
    assert (watch.name, watch.binding) == (name, binding)
    assert watch.text.startswith(f'{name}: {binding} at ')
    assert quotawatch.DOOR in watch.text


def test_planted_control_an_account_under_both_lines_is_not_warned() -> None:
    assert not quotawatch.judge(CALM, Policy()).near
    said = quotawatch.lines(CALM, Policy(), who='alice')
    assert len(said) == 1
    assert said[0].startswith('alice: usage files 400000/2000000 (20.0%), headroom 1600000 files; bytes ')


def test_the_usage_line_states_files_and_bytes_each_with_headroom() -> None:
    said = quotawatch.lines(FULL_FILES, Policy())
    assert 'headroom 0 files' in said[0]
    assert 'headroom 957.0 GB' in said[0]
    assert said[1].startswith('QUOTA-FULL: files')


def test_unread_usage_says_it_cannot_warn() -> None:
    assert quotawatch.lines(None, Policy()) == [quotawatch.UNREAD]
    assert not quotawatch.judge(None, Policy()).near


def test_retention_summary_judges_what_is_left_after_an_apply() -> None:
    done = Freed(0, 300_000, over=False)
    dry = retention.summary(done, NEAR_FILES, applied=False, policy=Policy())
    applied = retention.summary(done, NEAR_FILES, applied=True, policy=Policy())
    assert any('QUOTA-NEAR: files' in line for line in dry)
    assert not any('QUOTA-' in line for line in applied), 'freed below the line: no warning'


def test_the_serving_tick_states_usage_and_names_the_line_on_its_alarm(tmp_path: Path) -> None:
    said: list[str] = []
    done = retention.serve_pass(
        Path(), cluster=True, home=tmp_path, account=tmp_path / 'lab',
        lock=tmp_path / 'retention.lock', table={'uv_prune': False},
        usage=lambda: NEAR_FILES, live=set, say=said.append, run=lambda *_a, **_k: None,
        planner=lambda *_a, **_k: Plan(()),
    )  # fmt: skip
    assert done is not None
    assert done.watch == 'QUOTA-NEAR on files'
    assert done.alarm.startswith('QUOTA-NEAR: files')
    assert any(line.startswith('[retention] usage files 1760000/2000000') for line in said)


def test_planted_control_a_calm_tick_raises_no_alarm(tmp_path: Path) -> None:
    done = retention.serve_pass(
        Path(), cluster=True, home=tmp_path, account=tmp_path / 'lab',
        lock=tmp_path / 'retention.lock', table={'uv_prune': False},
        usage=lambda: CALM, live=set, say=lambda _: None, run=lambda *_a, **_k: None,
        planner=lambda *_a, **_k: Plan(()),
    )  # fmt: skip
    assert done is not None
    assert not done.over
    assert done.watch == ''
