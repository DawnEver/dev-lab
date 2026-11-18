"""A desktop act's consent: the ``desktop.open`` / ``desktop.focus`` rows and the HELD-credential verifier.

A product that drives a vendor GUI never imports the dev kit; it finds :func:`dev_lab.ops.consent.client.verify_held`
through an entry point and hands it the credential id the user's grant wrote. Every refusal has its planted control:
the same call with the one fault removed passes -- and a refused call leaves the credential unspent.
"""

from __future__ import annotations

import json
import tomllib
from importlib import import_module
from pathlib import Path
from typing import Any

import pytest
from _ops_fixtures import NOW, RFC_KEY, code

from dev_lab.dev.consentguard import state_dir
from dev_lab.ops.consent.actions import ACTIONS, SINGLE
from dev_lab.ops.consent.client import verify_held
from dev_lab.ops.consent.credential import ConsentRefused, public_text
from dev_lab.ops.consent.issuer import Issuer, keygen
from dev_lab.ops.totp import STEP

#: The entry-point group a desktop-driving product looks its consent verifier up in.
GROUP = 'dev_lab.desktop.consent'
SUBJECT = 'a' * 64
_ROOT = Path(__file__).resolve().parents[1]


class Host:
    """An issuer on disk, and a client home holding what it granted."""

    def __init__(self, tmp: Path) -> None:
        """Enrol the TOTP secret, make the signing key, and name the client's machine-file table."""
        self.tmp = tmp
        self.steps = 0
        (tmp / 'totp').write_text(RFC_KEY + '\n', encoding='utf-8')
        keygen(tmp / 'consent.key')
        self.issuer = Issuer(tmp / 'totp', tmp / 'consent.key', tmp / 'state', 'test issuer', self.clock)
        self.table = {'endpoint': 'issuer@host', 'public_key': public_text(self.issuer.public())}

    def clock(self) -> float:
        return NOW + self.steps * STEP

    def held(self, action: str, subject: str = SUBJECT) -> str:
        """Grant *action* on *subject* and write it where the grant writes; its id."""
        credential = self.issuer.issue({'action': action, 'subject': subject, 'params': {}}, code(self.steps))
        self.steps += 1  # the next code is a fresh step
        folder = state_dir(self.tmp / 'home')
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f'{credential["id"]}.json').write_text(json.dumps(credential), encoding='utf-8')
        return str(credential['id'])

    def verify(self, ident: str, *, action: str, subject: str = SUBJECT, table: dict[str, Any] | None = None) -> None:
        verify_held(ident, action=action, subject=subject, home=self.tmp / 'home', table=table or self.table,
                    register=self.issuer.register, now=self.clock)  # fmt: skip


@pytest.fixture
def host(tmp_path: Path) -> Host:
    return Host(tmp_path)


@pytest.mark.parametrize(('name', 'max_ttl'), [('desktop.open', 3600.0), ('desktop.focus', 900.0)])
def test_the_desktop_rows_are_single_use_short_lived_and_not_a_boundary(name: str, max_ttl: float) -> None:
    row = ACTIONS[name]
    assert (row.params, row.scope, row.default_ttl, row.max_ttl, row.boundary) == ({}, SINGLE, 900.0, max_ttl, False)


@pytest.mark.parametrize('action', ['desktop.open', 'desktop.focus'])
def test_a_held_credential_verifies_once_for_its_action_and_subject(host: Host, action: str) -> None:
    """The planted control of every refusal below."""
    host.verify(host.held(action), action=action)


def test_planted_a_credential_for_another_subject_is_refused_unspent(host: Host) -> None:
    ident = host.held('desktop.open')
    with pytest.raises(ConsentRefused, match='another request'):
        host.verify(ident, action='desktop.open', subject='b' * 64)
    host.verify(ident, action='desktop.open')  # unspent: the right request still takes it


def test_planted_a_credential_for_another_action_is_refused_unspent(host: Host) -> None:
    ident = host.held('desktop.open')
    with pytest.raises(ConsentRefused, match=r'consents to desktop\.open, not desktop\.focus'):
        host.verify(ident, action='desktop.focus')
    host.verify(ident, action='desktop.open')


def test_planted_a_credential_another_key_signed_is_refused(host: Host) -> None:
    ident = host.held('desktop.open')
    other = {**host.table, 'public_key': public_text(keygen(host.tmp / 'other.key').public_key())}
    with pytest.raises(ConsentRefused, match='signature does not verify'):
        host.verify(ident, action='desktop.open', table=other)
    host.verify(ident, action='desktop.open')


def test_planted_a_changed_field_breaks_the_signature(host: Host) -> None:
    ident = host.held('desktop.open', subject='b' * 64)
    path = state_dir(host.tmp / 'home') / f'{ident}.json'
    path.write_text(json.dumps(json.loads(path.read_text(encoding='utf-8')) | {'subject': SUBJECT}), encoding='utf-8')
    with pytest.raises(ConsentRefused, match='signature does not verify'):
        host.verify(ident, action='desktop.open')


def test_planted_a_reused_credential_is_refused(host: Host) -> None:
    ident = host.held('desktop.focus')
    host.verify(ident, action='desktop.focus')
    with pytest.raises(ConsentRefused, match='already used'):
        host.verify(ident, action='desktop.focus')


def test_a_credential_not_held_or_not_an_id_is_refused_by_name(host: Host) -> None:
    with pytest.raises(ConsentRefused, match='no credential 0123abcd-0000 is held'):
        host.verify('0123abcd-0000', action='desktop.open')
    with pytest.raises(ConsentRefused, match='is not a credential id'):
        host.verify('../../secret', action='desktop.open')


def test_a_client_with_no_endpoint_or_no_key_refuses_before_any_use(host: Host) -> None:
    ident = host.held('desktop.open')
    with pytest.raises(ConsentRefused, match='no consent public key'):
        verify_held(ident, action='desktop.open', subject=SUBJECT, home=host.tmp / 'home', table={'endpoint': 'x@y'},
                    now=host.clock)  # fmt: skip
    with pytest.raises(ConsentRefused, match=r'no \[consent\] endpoint'):
        verify_held(ident, action='desktop.open', subject=SUBJECT, home=host.tmp / 'home',
                    table={'public_key': host.table['public_key']}, now=host.clock)  # fmt: skip
    host.verify(ident, action='desktop.open')  # neither spent it


def test_the_verifier_is_declared_in_the_group_the_product_reads() -> None:
    """Declared in pyproject, and the declaration resolves to the verifier (installed metadata follows a sync)."""
    declared = tomllib.loads((_ROOT / 'pyproject.toml').read_text(encoding='utf-8'))['project']['entry-points']
    (spec,) = declared[GROUP].values()
    module, attribute = spec.split(':')
    assert getattr(import_module(module), attribute) is verify_held
