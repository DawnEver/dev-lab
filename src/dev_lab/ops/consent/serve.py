"""THE ISSUER'S SSH FORCECOMMAND: one JSON line in, the answer out (``python -m dev_lab.ops --config X consent serve``).

A line is ``{"verb": "issue", "request": {...}, "code": "..."}``, ``{"verb": "issue-plan", "plan": {...}, "code":
"..."}``, ``{"verb": "register", "credential": {...}, "amount": n}``, ``{"verb": "spent", "ids": [...]}`` or
``{"verb": "fetch-unspent", "plan": "<digest>"}``, ``{"verb": "hello"}`` or ``{"verb": "subject", "action": A,
"argv": [...]}``.
``subject`` is a READ, no code: this host derives *A*'s subject by running its ops verb with ``--subject``
(:func:`~dev_lab.ops.consent.door.read_argv` admits only the registry's read form; an acting flag is refused) and
answers the digest.
``hello`` answers the field set and registry actions this issuer speaks (:func:`~dev_lab.ops.consent.door.hello`):
the version handshake a client runs before it asks the user for a code.
``issue`` answers the credential's JSON, ``issue-plan`` the JSON list of one credential per grant; ``register`` the
campaign's remaining cap (empty for a single credential); ``spent`` the JSON list of those ids whose use the ledger
records; ``fetch-unspent`` the JSON list of the plan's granted, never-used, live credentials, as issued
(:meth:`~dev_lab.ops.consent.issuer.Issuer.unspent`: no code, never a new grant). A refusal raises
:class:`~dev_lab.ops.consent.credential.ConsentRefused`; its message never carries the code.

OVER HTTPS (``serve --https``, :mod:`dev_lab.ops.httpsdoor`; user ruling 2026-11-21) no ssh key admits the caller,
so each verb stands on its own authorization: ``hello`` and ``subject`` are reads, ``spent`` answers which of the ids
it is GIVEN were used, ``register`` spends a credential only its holder has (signed), ``issue`` / ``issue-plan`` pay a
TOTP code -- and ``fetch-unspent``, which re-delivers live credentials to whoever names a plan digest, pays one too
(over ssh the consent key admitted it). Every code-taking request strikes the peer's throttle first (rate limit +
lockout + alert), on top of the issuer's own wrong-code lockout.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence

from dev_lab.ops.consent.credential import ConsentRefused
from dev_lab.ops.consent.door import hello, read_argv
from dev_lab.ops.consent.issuer import Issuer
from dev_lab.ops.httpsdoor import Throttle

__all__ = ['CODE_VERBS', 'Derive', 'handle']

#: Runs this host's ``dev_lab.ops`` with argv words, read-only (the ``subject`` verb's); ``(exit status, output)``.
type Derive = Callable[[Sequence[str]], tuple[int, str]]


def _subject(data: dict, derive: Derive | None) -> str:
    argv = read_argv(str(data.get('action')), data.get('argv'))
    if derive is None:
        msg = 'this issuer derives no subjects'
        raise ConsentRefused(msg)
    status, said = derive(argv)
    lines = [line.strip() for line in said.splitlines() if line.strip()]
    if status or not lines:
        msg = f'the subject could not be derived here ({status}): {lines[-1] if lines else "no output"}'
        raise ConsentRefused(msg)
    return lines[-1]


#: The verbs that take the user's code over HTTPS: each strikes the peer's throttle before the code is checked.
CODE_VERBS = frozenset({'issue', 'issue-plan', 'fetch-unspent'})


def _code(data: dict, verb: str) -> str:
    code = data.get('code')
    if not isinstance(code, str):
        msg = f'{verb} carries the code as a string'
        raise ConsentRefused(msg)
    return code


def _admitted(issuer: Issuer, data: dict, verb: object, https: Throttle, peer: str) -> None:
    """The HTTPS door's own admission (see the module docstring): throttle, and a code for ``fetch-unspent``."""
    if verb == 'hello':
        return
    https.check(peer)
    if verb in CODE_VERBS:
        https.strike(peer)
    if verb == 'fetch-unspent':
        issuer.confirm(_code(data, str(verb)))


def handle(
    issuer: Issuer, line: str, *, derive: Derive | None = None, https: Throttle | None = None, peer: str = ''
) -> str:
    """Answer one request *line* (see the module docstring); *derive* runs a ``subject`` read on this host.

    *https* is set when the request came through the HTTPS door from *peer* (see the module docstring).
    """
    try:
        data = json.loads(line)
    except ValueError as bad:
        msg = 'not one JSON line'
        raise ConsentRefused(msg) from bad
    verb = data.get('verb') if isinstance(data, dict) else None
    if https is not None:
        _admitted(issuer, data, verb, https, peer)
    if verb in {'hello', 'subject'}:  # the two reads: no code, no state changed
        return json.dumps(hello(), sort_keys=True) if verb == 'hello' else _subject(data, derive)
    if verb in {'issue', 'issue-plan'}:
        code = _code(data, verb)
        if verb == 'issue-plan':
            return json.dumps(issuer.issue_plan(data.get('plan'), code), sort_keys=True)
        return json.dumps(issuer.issue(data.get('request'), code), sort_keys=True)
    if verb == 'register':
        amount = data.get('amount', 1)
        left = issuer.register(data.get('credential'), amount)
        return '' if left is None else str(left)
    if verb == 'fetch-unspent':
        return json.dumps(issuer.unspent(data.get('plan')), sort_keys=True)
    if verb == 'spent':
        return json.dumps(issuer.spent(data.get('ids')))
    msg = 'verb must be hello, subject, issue, issue-plan, register, spent or fetch-unspent'
    raise ConsentRefused(msg)
