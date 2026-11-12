"""HOW A FORGE ANSWER READS: an answer, a transient, a rate limit, a refusal of the call, or a refused credential.

RETRY, THEN REPORT, IN NETVERB'S VOCABULARY. Every call is bounded by
:data:`~dev_lab.dev.netverb.DEFAULT_ATTEMPTS` and its outcome is a
:class:`~dev_lab.dev.netverb.Report`, so an HTTP failure reads exactly like a failed ``git
push``. An ANSWERED 4xx is a refusal and is never repeated (408 and 429 stay retryable, as the table
says); a 5xx or a dropped connection is retried. A 401/403 is MEASURED before it is named: the same
credential is asked ``GET /user``; a refusal there is a credential refusal (not retried, the ``auth
login`` remedy), an answer there makes the 401/403 transient (retried, and never told to re-store).

A RATE LIMIT IS NAMED BEFORE ANY OF THAT (2026-11-05: GitHub's 403 "API rate limit exceeded" was measured
against ``GET /user``, rate limited too, and reported as a refused credential, never retried). A 429, or a 403
whose headers or body say rate limit, is :attr:`~dev_lab.dev.netverb.Diagnosis.RATE_LIMITED`: retried after the
wait the forge names (``Retry-After``, else ``X-RateLimit-Reset``), and reported without another attempt when
that wait is past :data:`RATE_WAIT_CAP_S` -- an attempt before the reset is refused by construction.

:func:`retried` IS THE ONE LOOP every forge HTTP exchange runs through: the client's JSON calls and raw reads
(:class:`~dev_lab.dev.forgework.Client`) and the Actions artifact protocol (:mod:`dev_lab.dev.actionsartifact`).
:class:`ForgeCallFailed` is what every caller of a forge verb catches.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from typing import TYPE_CHECKING, Final

from dev_lab.dev import forge as _forge
from dev_lab.dev.netverb import DEFAULT_ATTEMPTS, DEFAULT_BACKOFF_S, Attempt, Diagnosis, Report, classify

if TYPE_CHECKING:
    import http.client

    from dev_lab.dev.forge import Transport

__all__ = [
    'HTTP_ERROR_FLOOR',
    'RATE_HEADERS',
    'RATE_WAIT_CAP_S',
    'UNAUTHENTICATED',
    'Answer',
    'BudgetSpent',
    'ForgeCallFailed',
    'diagnose',
    'pause',
    'permission_refused',
    'rate_limited',
    'retried',
    'within',
]

#: Statuses below this are answers; at or above it the call failed.
HTTP_ERROR_FLOOR: Final = 400

#: The 5xx floor: a server error, which a later attempt may clear.
_HTTP_SERVER_FLOOR: Final = 500

#: The one status that says the credential did not authenticate (a 403 authenticated it and refused the act).
UNAUTHENTICATED: Final = 401

#: The status a forge answers a rate limit with when it does not answer 429 (GitHub's primary limit).
_FORBIDDEN: Final = 403

#: How a forge words a CREDENTIAL fault in a 401/403 body; a 403 without one, from an account ``GET /user``
#: authenticates, is the account lacking the right (2026-11-10: a push-only account read ``branch_protections``).
_CREDENTIAL_WORDS: Final = ('invalid username', 'password or token', 'failed to authenticate', 'bad credentials')

#: The remedy of a permission refusal: the account answered, so only another account or a grant changes it.
_PERMISSION_REMEDY: Final = (
    'the stored credential authenticates (GET /user answered), but this account lacks the right to this call -- '
    'retrying cannot change it; run it as an admin account, or grant this account that permission'
)


#: How much of a failed answer's body an :class:`~dev_lab.dev.netverb.Attempt` keeps: enough for GitHub's
#: ``errors`` list after its ``message`` (a 422's cause), so the JSON still parses and :func:`_reason` can read it.
_BODY_KEPT: Final = 2000


def _error(one: object) -> str:
    """One entry of a body's ``errors``: GitHub writes a string, or an object with a ``message`` or a ``code``."""
    if isinstance(one, dict):
        return str(one.get('message') or ' '.join(str(one[k]) for k in ('resource', 'field', 'code') if k in one))
    return str(one)


def _reason(output: str) -> str:
    """The forge's own ``message`` and every entry of its ``errors`` from an answered body, else the body as it came.

    The body is the forge's answer, never the request: no header or credential reaches it.
    """
    try:
        body = json.loads(output)
    except ValueError:
        return output.strip()
    if not isinstance(body, dict):
        return output.strip()
    errors = body.get('errors') or ()
    named = [_error(one) for one in (errors if isinstance(errors, list) else [errors])]
    return '; '.join([str(body.get('message', output)).strip(), *named])


def permission_refused(status: int, text: str) -> bool:
    """A 403 that names no credential fault -- asked only once ``GET /user`` has authenticated the credential."""
    lowered = text.lower()
    return status == _FORBIDDEN and not any(word in lowered for word in _CREDENTIAL_WORDS)


#: The status that is a rate limit whatever else the answer says.
_TOO_MANY: Final = 429

#: 4xx statuses that are NOT a refusal of the request itself: timeout and rate limit clear by waiting.
_HTTP_RETRYABLE_4XX: Final = frozenset({408, _TOO_MANY})

#: The answer headers a rate limit is read off, on both forges; an :class:`Answer` carries only these.
RATE_HEADERS: Final = ('Retry-After', 'X-RateLimit-Remaining', 'X-RateLimit-Reset')

#: The longest wait for a rate limit's reset inside one call. Past it the call is reported, not slept through:
#: GitHub's primary limit resets hourly, and a caller blocked for an hour is a hang, not a retry.
RATE_WAIT_CAP_S: Final = 60.0


@dataclass(frozen=True, slots=True)
class Answer:
    """One HTTP exchange: its status (``0``: no answer), its body, and whichever :data:`RATE_HEADERS` it sent."""

    status: int
    payload: bytes
    headers: Mapping[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        """Whether the forge answered below :data:`HTTP_ERROR_FLOOR`."""
        return 0 < self.status < HTTP_ERROR_FLOOR


class BudgetSpent(TimeoutError):
    """The caller's time budget ran out before a forge call could start: never retried, as waiting cannot clear it."""


def within(
    transport: Transport, deadline: float, what: str, budget_s: float, *, now: Callable[[], float] = time.monotonic
) -> Transport:
    """*transport*, each connection's wait cut to what is left before *deadline*; none opened past it.

    Past *deadline* (on *now*'s clock) the connection is never opened: :class:`BudgetSpent` names *what* spent its
    *budget_s*, and :func:`retried` re-raises it rather than retrying.
    """

    def opened(host: str, timeout: float) -> http.client.HTTPConnection:
        left = deadline - now()
        if left <= 0:
            msg = f'{what} spent its {budget_s:g} s read budget before asking {host}'
            raise BudgetSpent(msg)
        return transport(host, min(timeout, left))

    return opened


class ForgeCallFailed(OSError):
    """A forge call that did not succeed within the bound; :attr:`report` is netverb's report of it."""

    def __init__(self, report: Report, *, credential_gone: bool = False, credential_kept: bool = False) -> None:
        """Carry the report; on a 401/403 the message adds what the credential check and refresh MEASURED.

        *credential_gone*: the refresh left the store holding no credential -- retried and measured, never a re-login.
        *credential_kept*: the store cannot refresh, so the refused credential was kept -- retried and measured.
        A rate limit says nothing about the credential, so its message adds nothing.
        """
        attempt = report.attempts[-1] if report.attempts else None
        last = attempt.returncode if attempt else 0
        said = _forge.AUTH_TRANSIENT
        if attempt is not None and attempt.diagnosis is Diagnosis.PERMISSION_REFUSED:
            said = f'{_PERMISSION_REMEDY}; the forge said: {_reason(attempt.output)}'
        elif _credential_refused(report):
            said = _forge.AUTH_GONE if credential_gone else _forge.AUTH_KEPT if credential_kept else _forge.AUTH_REMEDY
        auth = last in _forge.AUTH_REFUSED and report.diagnosis is not Diagnosis.RATE_LIMITED
        message = f'{report.remedy}. {said}' if auth else report.remedy
        if attempt is not None and attempt.diagnosis is Diagnosis.FORGE_REFUSED and not auth:
            message += f'; the forge answered {last}: {_reason(attempt.output)}'
        super().__init__(message)
        self.report = report

    @property
    def credential_refused(self) -> bool:
        """Whether the forge refused the stored CREDENTIAL -- measured by ``GET /user``, never read off one status."""
        return _credential_refused(self.report)

    @property
    def permission(self) -> bool:
        """Whether the forge answered that this ACCOUNT lacks a grant (:attr:`Diagnosis.PERMISSION_REFUSED`)."""
        last = self.report.attempts[-1] if self.report.attempts else None
        return last is not None and last.diagnosis is Diagnosis.PERMISSION_REFUSED

    @property
    def final(self) -> int | None:
        """The HTTP status when the forge refused THIS CALL for good, else ``None`` (a later attempt may land).

        Final is an answered refusal (:attr:`~dev_lab.dev.netverb.Diagnosis.FORGE_REFUSED`, e.g. a 405 on
        merging a merged PR) that is not a refused CREDENTIAL: that one is the box's fault, not the call's.
        A PERMISSION refusal is not final either: the account lacks a grant, and the same call lands once it is
        granted, so a queued post stays queued for it (never dropped).
        """
        last = self.report.attempts[-1] if self.report.attempts else None
        if last is None or last.diagnosis is not Diagnosis.FORGE_REFUSED or self.credential_refused:
            return None
        return last.returncode


def _credential_refused(report: Report) -> bool:
    """The last attempt was a 401/403 diagnosed refused after asking ``GET /user`` (``Client._diagnosis``)."""
    last = report.attempts[-1] if report.attempts else None
    return last is not None and last.returncode in _forge.AUTH_REFUSED and last.diagnosis is Diagnosis.FORGE_REFUSED


def rate_limited(status: int, text: str, headers: Mapping[str, str]) -> bool:
    """A 429, or a 403 whose headers (no request left, a ``Retry-After``) or body say rate limit."""
    if status == _TOO_MANY:
        return True
    if status != _FORBIDDEN:
        return False
    spent = headers.get('X-RateLimit-Remaining') == '0' or bool(headers.get('Retry-After'))
    return spent or classify(text) is Diagnosis.RATE_LIMITED


def diagnose(status: int, text: str, headers: Mapping[str, str] | None = None) -> Diagnosis:
    """A rate limit first; then netverb's table; an answered 4xx it does not know is a refusal, never a transient.

    A 401/403 that is no rate limit never reaches here: :meth:`dev_lab.dev.forgework.Client._diagnosis` measures
    it against ``GET /user`` first.
    """
    if rate_limited(status, text, headers or {}):
        return Diagnosis.RATE_LIMITED
    found = classify(f'error: {status} {text}')
    answered = HTTP_ERROR_FLOOR <= status < _HTTP_SERVER_FLOOR and status not in _HTTP_RETRYABLE_4XX
    return Diagnosis.FORGE_REFUSED if found is Diagnosis.UNCLASSIFIED and answered else found


def pause(diagnosis: Diagnosis, headers: Mapping[str, str], now: float) -> float | None:
    """Seconds to wait before the next attempt; ``None`` when the forge's named wait is past :data:`RATE_WAIT_CAP_S`.

    A rate limit waits what ``Retry-After`` (seconds or an HTTP date) names, else until ``X-RateLimit-Reset`` (epoch
    seconds); a limit naming neither, and every other failure, waits :data:`~dev_lab.dev.netverb.DEFAULT_BACKOFF_S`.
    """
    if diagnosis is not Diagnosis.RATE_LIMITED:
        return DEFAULT_BACKOFF_S
    named = _seconds_until(headers.get('Retry-After', ''), headers.get('X-RateLimit-Reset', ''), now)
    wait = DEFAULT_BACKOFF_S if named is None else max(named, 0.0)
    return wait if wait <= RATE_WAIT_CAP_S else None


def _seconds_until(retry_after: str, reset: str, now: float) -> float | None:
    """The wait a ``Retry-After`` (delta seconds or HTTP date) or an ``X-RateLimit-Reset`` (epoch) names."""
    if retry_after.strip().isdigit():
        return float(retry_after)
    if retry_after:
        try:
            return parsedate_to_datetime(retry_after).timestamp() - now
        except (TypeError, ValueError):
            pass
    return float(reset) - now if reset.strip().isdigit() else None


def retried(
    label: tuple[str, ...],
    once: Callable[[], Answer],
    *,
    diagnosis: Callable[[Answer, str], Diagnosis] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.time,
    landed: Callable[[], object] | None = None,
    failed: Callable[[Report], Exception] = ForgeCallFailed,
) -> object:
    """*once* until it answers below :data:`HTTP_ERROR_FLOOR`, is refused, or the attempts run out.

    The answering :class:`Answer` (or what *landed* found) is returned; otherwise ``failed(report)`` is raised
    after at most :data:`~dev_lab.dev.netverb.DEFAULT_ATTEMPTS`. *diagnosis* reads a failed answer (default
    :func:`diagnose`); a dropped connection (``OSError``) is status 0 and transient. Before each retry the loop
    waits :func:`pause`, then asks *landed* whether the lost attempt landed: what it returns, unless ``None``, is
    the result, and a :class:`ForgeCallFailed` from it stops the loop -- whether a write landed is then unknowable,
    and a blind retry may duplicate it. A :class:`BudgetSpent` is re-raised naming *label*, never retried.
    """
    read = diagnosis or (lambda answer, text: diagnose(answer.status, text, answer.headers))
    made: list[Attempt] = []
    for index in range(1, DEFAULT_ATTEMPTS + 1):
        try:
            answer = once()
        except BudgetSpent as spent:
            msg = f'{" ".join(label)}: {spent}'
            raise BudgetSpent(msg) from spent
        except OSError as exc:
            answer = Answer(0, str(exc).encode())
        if answer.ok:
            return answer
        text = answer.payload.decode(errors='replace')[:_BODY_KEPT]
        made.append(Attempt(index, answer.status or 1, text, read(answer, text)))
        wait = pause(made[-1].diagnosis, answer.headers, now())
        if not made[-1].retryable or wait is None or index == DEFAULT_ATTEMPTS:
            break
        sleep(wait)
        if landed is not None:
            try:
                found = landed()
            except ForgeCallFailed:
                break
            if found is not None:
                return found
    raise failed(Report(label, tuple(made), DEFAULT_ATTEMPTS))
