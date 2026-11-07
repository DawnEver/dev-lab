"""THE ISSUER: the one holder of the TOTP seed and the Ed25519 private key, on the forge host.

User ruling 2026-11-07. :meth:`Issuer.issue` turns a request the registry admits (:mod:`.actions`) plus the user's
TOTP code into a signed credential; :meth:`Issuer.register` records an IRREVERSIBLE use of one -- a single credential
once, a campaign's spend debited against its cap. Both run under the role lock (:mod:`dev_lab.ops.statelock`), so the
TOTP step, the lockout and the ledger are read and written by one session at a time.

THE TOTP CHECK IS :func:`dev_lab.ops.totp.accept` (a code is accepted once: its step is recorded) under
:func:`dev_lab.ops.lockout.guarded` (consecutive wrong codes lock every code out). A request is validated BEFORE the
code is checked, so a refused request spends no step.

THE LEDGER (``<state>/ledger.jsonl``) is append-only and records ``event``, ``id``, ``action``, ``subject`` and, for
a use, its ``amount`` -- never a code, a param, a signature or a key.
"""

from __future__ import annotations

import json
import math
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, load_pem_private_key

from dev_lab.ops.consent.actions import ACTIONS, CAMPAIGN, Action
from dev_lab.ops.consent.credential import ConsentRefused, params_hash, sign, verify
from dev_lab.ops.lockout import guarded
from dev_lab.ops.statelock import exclusive
from dev_lab.ops.totp import TotpRefused, accept, write_private

__all__ = ['Issuer', 'keygen', 'requested']


def keygen(key_file: Path, *, force: bool = False) -> Ed25519PrivateKey:
    """A new Ed25519 private key at *key_file* (PEM, mode 600); refuse to replace one unless *force*."""
    if key_file.is_file() and not force:
        msg = f'{key_file} already holds a key; --force replaces it (every issued credential stops verifying)'
        raise ConsentRefused(msg)
    key = Ed25519PrivateKey.generate()
    write_private(key_file, key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()).decode())
    return key


def _typed(value: object, kind: type) -> bool:
    if isinstance(value, bool):
        return False
    if kind is float:
        return isinstance(value, int | float) and math.isfinite(value) and value >= 0
    return isinstance(value, kind) and (kind is not int or value >= 0)


def _params(row: Action, params: object) -> dict[str, Any]:
    if not isinstance(params, dict) or set(params) != set(row.params):
        msg = f'{row.name} params are exactly {sorted(row.params)}'
        raise ConsentRefused(msg)
    if bad := sorted(name for name, kind in row.params.items() if not _typed(params[name], kind)):
        msg = f'{row.name} params {bad} must be non-negative {", ".join(row.params[n].__name__ for n in bad)}'
        raise ConsentRefused(msg)
    return dict(params)


def requested(data: object) -> tuple[Action, str, dict[str, Any], int | None, float]:
    """``(row, subject, params, cap, ttl)`` of a grant request; :class:`ConsentRefused` names the first bad field."""
    if not isinstance(data, dict):
        msg = 'a request is a JSON object'
        raise ConsentRefused(msg)
    if unknown := sorted(set(data) - {'action', 'subject', 'params', 'scope', 'cap', 'ttl'}):
        msg = f'the request has unknown fields {unknown}'
        raise ConsentRefused(msg)
    row = ACTIONS.get(str(data.get('action')))
    if row is None:
        msg = f'action must be one of {sorted(ACTIONS)}'
        raise ConsentRefused(msg)
    subject = data.get('subject')
    if not isinstance(subject, str) or not subject.strip():
        msg = 'subject must be a non-empty string'
        raise ConsentRefused(msg)
    if data.get('scope', row.scope) != row.scope:
        msg = f'{row.name} is {row.scope} only'
        raise ConsentRefused(msg)
    params = _params(row, data.get('params', {}))
    cap = data.get('cap')
    if row.scope == CAMPAIGN and not (isinstance(cap, int) and not isinstance(cap, bool) and cap > 0):
        msg = f'{row.name} is a campaign: cap must be a positive integer'
        raise ConsentRefused(msg)
    if row.scope != CAMPAIGN and cap is not None:
        msg = f'{row.name} is single-use: it carries no cap'
        raise ConsentRefused(msg)
    ttl = data.get('ttl', row.default_ttl)
    if isinstance(ttl, bool) or not isinstance(ttl, int | float) or not 0 < ttl <= row.max_ttl:
        msg = f'ttl must be in (0, {row.max_ttl:g}] s for {row.name}; asked {ttl!r}'
        raise ConsentRefused(msg)
    return row, subject.strip(), params, cap, float(ttl)


@dataclass
class Issuer:
    """The issuer over its files; *now* is the clock, *on_lock* is told when the code lockout begins."""

    totp: Path
    key: Path
    state: Path
    name: str
    now: Callable[[], float]
    lockout_after: int = 5
    lockout_minutes: float = 15.0
    on_lock: Callable[[float], None] = lambda _until: None

    @property
    def ledger(self) -> Path:
        """The append-only ledger."""
        return self.state / 'ledger.jsonl'

    def _private(self) -> Ed25519PrivateKey:
        if not self.key.is_file():
            msg = f'no consent key at {self.key}: run the consent keygen verb first'
            raise ConsentRefused(msg)
        key = load_pem_private_key(self.key.read_bytes(), password=None)
        if not isinstance(key, Ed25519PrivateKey):
            msg = f'{self.key} is not an Ed25519 private key'
            raise ConsentRefused(msg)
        return key

    def public(self) -> Ed25519PublicKey:
        """The public half of the signing key: what a verifier on this host checks with."""
        return self._private().public_key()

    def _record(self, event: str, credential: Mapping[str, Any], amount: int | None = None) -> None:
        line = {'event': event, 'id': credential['id'], 'action': credential['action'],
                'subject': credential['subject']} | ({} if amount is None else {'amount': amount})  # fmt: skip
        self.ledger.parent.mkdir(parents=True, exist_ok=True)
        with self.ledger.open('a', encoding='utf-8') as out:
            out.write(json.dumps(line, sort_keys=True) + '\n')

    def _events(self, ident: str) -> list[dict[str, Any]]:
        if not self.ledger.is_file():
            return []
        lines = self.ledger.read_text(encoding='utf-8').splitlines()
        return [event for event in map(json.loads, filter(None, lines)) if event.get('id') == ident]

    def _code(self, code: str) -> None:
        def check() -> None:
            try:
                accept(self.totp, self.state / 'totp.step', code, self.now())
            except TotpRefused as refused:
                raise ConsentRefused(str(refused)) from refused

        guarded(self.state, check, now=self.now(), after=self.lockout_after, minutes=self.lockout_minutes,
                on_lock=self.on_lock, refused=ConsentRefused)  # fmt: skip

    def issue(self, request: object, code: str) -> dict[str, Any]:
        """The signed credential *request* asks for, paid for with the user's TOTP *code*."""
        row, subject, params, cap, ttl = requested(request)  # before the code: a refused request spends no step
        with exclusive(self.state):
            key = self._private()
            self._code(code)
            now = self.now()
            fields = {'id': str(uuid.uuid4()), 'action': row.name, 'subject': subject, 'params': params,
                      'params_hash': params_hash(params), 'scope': row.scope, 'cap': cap, 'issued': now,
                      'expires': now + ttl, 'issuer': self.name}  # fmt: skip
            credential = sign(fields, key)
            self._record('granted', credential)
            return credential

    def register(self, credential: object, amount: int = 1) -> int | None:
        """Record one irreversible use of *credential*; the campaign's remaining cap, ``None`` for a single one.

        Raises:
            ConsentRefused: the credential does not verify, a single one was already used, or the spend is over cap.

        """
        if isinstance(amount, bool) or not isinstance(amount, int) or amount < 1:
            msg = 'a use spends a positive integer amount'
            raise ConsentRefused(msg)
        with exclusive(self.state):
            found = verify(credential, self.public(), now=self.now())
            assert isinstance(credential, dict)  # noqa: S101 -- verify refused anything else
            uses = [event for event in self._events(found.id) if event.get('event') == 'used']
            if found.cap is None:
                if uses or amount != 1:
                    msg = f'single-use credential {found.id} was already used' if uses else 'a single use spends 1'
                    raise ConsentRefused(msg)
                self._record('used', credential, 1)
                return None
            spent = sum(int(event.get('amount', 0)) for event in uses)
            if spent + amount > found.cap:
                msg = f'campaign {found.id} has {found.cap - spent} of {found.cap} left; {amount} asked'
                raise ConsentRefused(msg)
            self._record('used', credential, amount)
            return found.cap - spent - amount
