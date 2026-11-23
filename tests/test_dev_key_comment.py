"""A workstation's ssh client key comment is ``<key_account>@<hostname>``, both declared; anything else is refused."""

from __future__ import annotations

import pytest

from dev_lab.dev import devschema

KEY = 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIA1dtjiBuQjg+mT4+rUmSfSrdgiwtUSw9TlircWVvVC0'
FAMILY = {'dev': {'ref': 'main', 'key_account': 'acct'}}


def _host(comment: str, **dev: str) -> dict:
    return {'dev': {'client_keys': [f'{KEY} {comment}'], 'hostname': 'box1', **dev}}


def test_a_comment_naming_the_declared_account_and_host_passes() -> None:
    assert devschema.check(_host('acct@box1'), FAMILY) == []


@pytest.mark.parametrize('comment', ['old@BOX1', 'mislabel', 'acct@BOX1', 'other@box1', ''])
def test_a_mislabelled_key_is_refused_naming_both_comments_and_its_door(comment: str) -> None:
    """Planted control beside the passing case: the same key with any other comment must be refused."""
    host = _host(comment) if comment else {'dev': {'client_keys': [KEY], 'hostname': 'box1'}}
    found = [line for line in devschema.check(host, FAMILY) if 'client_keys[0] comment' in line]
    assert found, devschema.check(host, FAMILY)
    assert f'{comment!r}' in found[0]
    assert "expected 'acct@box1'" in found[0]
    assert 'this host file' in found[0]


def test_a_keyed_host_without_a_hostname_or_account_is_refused() -> None:
    host = {'dev': {'client_keys': [f'{KEY} acct@box1']}}
    assert [line for line in devschema.check(host, FAMILY) if 'hostname' in line]
    assert [line for line in devschema.check(_host('acct@box1'), {'dev': {'ref': 'main'}}) if 'key_account' in line]


def test_a_host_overrides_the_family_account_but_never_restates_it() -> None:
    assert devschema.check(_host('own@box1', key_account='own'), FAMILY) == []
    restated = devschema.check(_host('acct@box1', key_account='acct'), FAMILY)
    assert [line for line in restated if 'key_account restates' in line], restated


def test_the_hostname_is_a_host_fact_and_a_name_holds_no_at() -> None:
    assert [line for line in devschema.check_family({'dev': {'hostname': 'box1'}}) if 'hostname' in line]
    assert [line for line in devschema.check(_host('acct@x@y', hostname='x@y'), FAMILY) if 'hostname must' in line]
