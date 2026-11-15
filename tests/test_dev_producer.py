"""THE PRODUCER EXIT CONTRACT: every code means one thing, and USAGE is argparse's own."""

from __future__ import annotations

import argparse

import pytest
from _box_fake import ended
from lab_commons.box import Refused

from dev_lab.dev import verify
from dev_lab.dev.producer import (
    PRODUCING_VAR,
    RETRYABLE,
    Owner,
    ProducerExit,
    box_release_reason,
    declared_outage,
    full_suite_refusal,
    licence_outage,
    outage_env,
    owned,
    owner_of,
    producing,
    release_reason,
    unreachable,
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


def test_only_a_declared_unreachable_is_released_as_retryable() -> None:
    reasons = {code: release_reason(code, outage=Owner.NETWORK) for code in (*ProducerExit, -9, 137)}
    retryable = {code for code, reason in reasons.items() if reason.startswith(RETRYABLE)}
    assert retryable == {ProducerExit.UNREACHABLE}
    assert not release_reason(ProducerExit.UNREACHABLE, outage=None).startswith(RETRYABLE), (
        'a command exiting 4 on its own is not an outage: it would be re-claimed every tick'
    )
    assert len(set(reasons.values())) == len(reasons), 'every exit is released with a reason naming it'
    assert release_reason(-9, outage=None) == 'released: producer crashed (exit -9) class=environment'


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


def test_an_outage_is_declared_in_the_outcome_record_never_read_from_the_exit_code(tmp_path, monkeypatch) -> None:
    """The producer SAYS unreachable where serve named; exit 4 alone says nothing (sharp-review 10-15 #2)."""
    record = tmp_path / 'run.outcome.json'
    assert declared_outage(record) is None, 'PLANTED CONTROL: nothing declared, no outage'
    monkeypatch.setenv(*next(iter(outage_env(record).items())))
    assert unreachable('npm missing') == ProducerExit.UNREACHABLE
    assert declared_outage(record) is Owner.NETWORK
    assert declared_outage(record) is None, 'the declaration is consumed: a later run of the tree starts clean'
    monkeypatch.delenv(next(iter(outage_env(record))))
    assert unreachable('outside serve') == ProducerExit.UNREACHABLE, 'outside serve it only exits 4'


def test_every_owner_class_of_contract_6_is_one_enum() -> None:
    assert {str(one) for one in Owner} == {
        'code',
        'environment',
        'scheduling',
        'vendor-licence',
        'network',
        'status-publishing',
    }


def test_a_licence_outage_is_class_vendor_licence_and_retried_not_a_fail(tmp_path, monkeypatch) -> None:
    """PLANTED: the producer declares the licence outage; serve releases it RETRYABLE under its own class."""
    record = tmp_path / 'run.outcome.json'
    monkeypatch.setenv(*next(iter(outage_env(record).items())))
    assert licence_outage('JMAG: no seat free') == ProducerExit.UNREACHABLE
    said = declared_outage(record)
    assert said is Owner.VENDOR_LICENCE
    released = release_reason(ProducerExit.UNREACHABLE, outage=said)
    assert released.startswith(RETRYABLE), 'retried next tick, never settled'
    assert owner_of('error', released) is Owner.VENDOR_LICENCE
    assert owner_of('error', released) is not Owner.CODE, 'not the author red'
    control = release_reason(ProducerExit.UNREACHABLE, outage=Owner.NETWORK)
    assert owner_of('error', control) is Owner.NETWORK, 'CONTROL: a network outage keeps its own class'


def test_a_producer_cannot_declare_the_code_its_outage() -> None:
    with pytest.raises(ValueError, match='never code'):
        unreachable('blame the author', Owner.CODE)


def test_every_release_names_a_class_and_none_is_the_code() -> None:
    """A producer ending without a part, or the box ending it, is never the author's red."""
    releases = [release_reason(code, outage=None) for code in (*ProducerExit, -9)]
    releases += [box_release_reason(Refused('cpu')), box_release_reason(ended(-9, 'wall')), box_release_reason(None)]
    owners = {owner_of('error', one) for one in releases}
    assert None not in owners, releases
    assert Owner.CODE not in owners
    assert owner_of('error', box_release_reason(Refused('cpu'))) is Owner.SCHEDULING


def test_the_class_field_is_read_tolerantly_and_survives_the_cut() -> None:
    assert owner_of('failure', 'scope=full ran=3 hands=-') is Owner.CODE, 'a judged FAIL is the code'
    assert owner_of('success', 'class=code') is None
    assert owner_of('error', 'env=abc class=network policy=p') is Owner.NETWORK, 'other fields around it'
    assert owner_of('error', 'released: something') is None, 'PLANTED: no class is unowned, not code'
    assert owner_of('error', 'class=bogus') is None
    assert owner_of('error', 'subclass=code') is None, 'PLANTED: a longer key is not the field'
    long = owned(Owner.ENVIRONMENT, 'x' * 500)
    assert len(long) == 140
    assert owner_of('error', long) is Owner.ENVIRONMENT
