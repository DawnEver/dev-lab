"""THE PRODUCER EXIT CONTRACT: every code means one thing, and USAGE is argparse's own."""

from __future__ import annotations

import argparse

import pytest
from _box_fake import ended

from lab_commons.box import Refused
from lab_commons.dev import verify
from lab_commons.dev.producer import (
    PRODUCING_VAR,
    RETRYABLE,
    ProducerExit,
    box_release_reason,
    full_suite_refusal,
    producing,
    release_reason,
)


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


def test_the_box_record_decides_the_release_never_the_exit_code() -> None:
    """A refusal is retryable, a kill and a crash are released naming them; the producer's own exit is its code's."""
    assert box_release_reason(Refused('cpu: wants 4 of 3')).startswith(RETRYABLE)
    assert 'killed it past its declared wall' in box_release_reason(ended(-9, 'wall'))
    assert 'box crashed' in box_release_reason(None)
    assert box_release_reason(ended(69)) is None, 'PLANTED: a producer exiting 69 itself is judged by its code'
    assert box_release_reason(ended(137)) is None, 'PLANTED: a producer exiting 137 itself is judged by its code'


def test_the_door_is_open_only_to_the_producer_forge_serve_spawned() -> None:
    """VERDICTS-FROM-THE-FORGE: a full suite runs only under the claim ``forge serve`` hands its producer."""
    sha = 'a' * 40
    assert producing('tests/windows', sha) == {PRODUCING_VAR: f'tests/windows@{sha}'}
    assert full_suite_refusal('verify', producing('tests/windows', sha), 'tests/windows') is None, 'the control'
    refused = full_suite_refusal('verify', {}, 'tests/windows')
    assert refused is not None
    assert 'push; the forge produces the part' in refused
    assert 'forge status list <sha>' in refused
    assert 'verify -- <paths>' in refused


def test_a_claim_for_another_platform_does_not_open_this_one() -> None:
    """PLANTED: a linux claim leaked into a windows shell is not this box's part."""
    assert full_suite_refusal('verify', producing('tests/linux', 'a' * 40), 'tests/windows') is not None
