"""A stale consumer gets one branch and one pull request; a fresh one gets nothing.

The staleness reading is `lockcheck.stale` -- the same one the pre-push `lock` row makes -- so these cases
plant that reading rather than resolving anything.
"""

from __future__ import annotations

from pathlib import Path

from lab_commons.dev.relock import Relock, branch_for, decision, dist_of

_SHA = 'dca72b71758ee4c70fb991fbcb44c56a9e52498d'


def test_a_fresh_lock_needs_no_relock(tmp_path: Path) -> None:
    assert decision(tmp_path, _SHA, resolve=lambda _t: _Report()) is None


class _Report:
    """The shape ``stale`` reads: ok, its last attempt's output, and a remedy."""

    ok = True
    attempts: tuple[object, ...] = ()
    remedy = ''


def test_a_stale_lock_names_the_dist_its_branch_and_its_pull_request(tmp_path: Path) -> None:
    """PLANTED control: the same checkout with a fresh lock needs nothing (the test above)."""
    found = decision(tmp_path, _SHA, resolve=lambda _t: _stale('Update pint v0.26.1 -> v0.26.2'))
    assert isinstance(found, Relock)
    assert found.dist == 'pint'
    assert found.branch == f'pr/relock-pint-{_SHA[:12]}'
    assert found.title == 'build(deps): relock pint to the newest resolution'
    assert 'pint' in found.body
    assert found.branch in found.body


def test_the_dist_is_the_word_the_change_names() -> None:
    assert dist_of('uv.lock is not the newest resolution: Update pint v0.26.1 -> v0.26.2') == 'pint'
    assert dist_of('uv.lock is not the newest resolution: Add ruff v0.17.1') == 'ruff'
    assert dist_of('uv.lock is not the newest resolution: something else entirely') == 'lock'


def test_one_branch_per_dist_and_short_sha() -> None:
    assert branch_for('pint', _SHA) == f'pr/relock-pint-{_SHA[:12]}'
    assert branch_for('pint', _SHA) != branch_for('ruff', _SHA)


class _Attempt:
    def __init__(self, output: str) -> None:
        self.output = output


class _StaleReport(_Report):
    ok = True

    def __init__(self, output: str) -> None:
        self.attempts = (_Attempt(output),)


def _stale(change: str) -> _StaleReport:
    return _StaleReport(f'{change}\n')
