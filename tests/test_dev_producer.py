"""THE PRODUCER EXIT CONTRACT: every code means one thing, and USAGE is argparse's own."""

from __future__ import annotations

import argparse

import pytest

from lab_commons.dev import verify
from lab_commons.dev.producer import RETRYABLE, ProducerExit, release_reason


def test_every_meaning_has_its_own_code() -> None:
    assert len({int(code) for code in ProducerExit}) == len(ProducerExit)
    assert {code.name for code in ProducerExit} == {'PASS', 'FAIL', 'USAGE', 'INCONCLUSIVE', 'UNREACHABLE'}


def test_usage_is_the_code_argparse_exits_with() -> None:
    """PLANTED: a real parser refusing a real argv -- the code serve reads as a broken contract."""
    parser = argparse.ArgumentParser()
    parser.add_argument('--sha', required=True)
    with pytest.raises(SystemExit) as refused:
        parser.parse_args(['--install', 'x'])
    assert refused.value.code == ProducerExit.USAGE
    assert refused.value.code != ProducerExit.INCONCLUSIVE, 'the live collision: INCONCLUSIVE must not be 2'


def test_verify_exits_by_the_contract() -> None:
    assert {outcome.name: code for outcome, code in verify.EXIT_CODES.items()} == {
        'PASS': ProducerExit.PASS,
        'FAIL': ProducerExit.FAIL,
        'INCONCLUSIVE': ProducerExit.INCONCLUSIVE,
    }


def test_only_unreachable_is_released_as_retryable() -> None:
    reasons = {code: release_reason(code) for code in (*ProducerExit, -9, 137)}
    retryable = {code for code, reason in reasons.items() if reason.startswith(RETRYABLE)}
    assert retryable == {ProducerExit.UNREACHABLE}
    assert len(set(reasons.values())) == len(reasons), 'every exit is released with a reason naming it'
    assert release_reason(-9) == 'released: producer crashed (exit -9)'
