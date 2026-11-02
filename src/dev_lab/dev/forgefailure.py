"""HOW A FORGE ANSWER READS: an answer, a transient failure, a refusal of the call, or a refused credential.

RETRY, THEN REPORT, IN NETVERB'S VOCABULARY. Every call is bounded by
:data:`~dev_lab.dev.netverb.DEFAULT_ATTEMPTS` and its outcome is a
:class:`~dev_lab.dev.netverb.Report`, so an HTTP failure reads exactly like a failed ``git
push``. An ANSWERED 4xx is a refusal and is never repeated (408 and 429 stay retryable, as the table
says); a 5xx or a dropped connection is retried. A 401/403 is MEASURED before it is named: the same
credential is asked ``GET /user``; a refusal there is a credential refusal (not retried, the ``auth
login`` remedy), an answer there makes the 401/403 transient (retried, and never told to re-store).

:mod:`dev_lab.dev.forgework`'s :class:`~dev_lab.dev.forgework.Client` makes the calls and measures a 401/403;
this module names the outcome, and :class:`ForgeCallFailed` is what every caller of a forge verb catches.
"""

from __future__ import annotations

from typing import Final

from dev_lab.dev import forge as _forge
from dev_lab.dev.netverb import Diagnosis, Report, classify

__all__ = ['HTTP_ERROR_FLOOR', 'UNAUTHENTICATED', 'ForgeCallFailed', 'diagnose']

#: Statuses below this are answers; at or above it the call failed.
HTTP_ERROR_FLOOR: Final = 400

#: The 5xx floor: a server error, which a later attempt may clear.
_HTTP_SERVER_FLOOR: Final = 500

#: The one status that says the credential did not authenticate (a 403 authenticated it and refused the act).
UNAUTHENTICATED: Final = 401

#: 4xx statuses that are NOT a refusal of the request itself: timeout and rate limit clear by waiting.
_HTTP_RETRYABLE_4XX: Final = frozenset({408, 429})


class ForgeCallFailed(OSError):
    """A forge call that did not succeed within the bound; :attr:`report` is netverb's report of it."""

    def __init__(self, report: Report, *, credential_gone: bool = False, credential_kept: bool = False) -> None:
        """Carry the report; on a 401/403 the message adds what the credential check and refresh MEASURED.

        *credential_gone*: the refresh left the store holding no credential -- a re-login fixes it.
        *credential_kept*: the store cannot refresh, so the refused credential was kept -- a re-login may fix it.
        """
        last = report.attempts[-1].returncode if report.attempts else 0
        said = _forge.AUTH_TRANSIENT
        if _credential_refused(report):
            said = _forge.AUTH_GONE if credential_gone else _forge.AUTH_KEPT if credential_kept else _forge.AUTH_REMEDY
        super().__init__(f'{report.remedy}. {said}' if last in _forge.AUTH_REFUSED else report.remedy)
        self.report = report

    @property
    def credential_refused(self) -> bool:
        """Whether the forge refused the stored CREDENTIAL -- measured by ``GET /user``, never read off one status."""
        return _credential_refused(self.report)

    @property
    def final(self) -> int | None:
        """The HTTP status when the forge refused THIS CALL for good, else ``None`` (a later attempt may land).

        Final is an answered refusal (:attr:`~dev_lab.dev.netverb.Diagnosis.FORGE_REFUSED`, e.g. a 405 on
        merging a merged PR) that is not a refused CREDENTIAL: that one is the box's fault, not the call's.
        """
        last = self.report.attempts[-1] if self.report.attempts else None
        if last is None or last.diagnosis is not Diagnosis.FORGE_REFUSED or self.credential_refused:
            return None
        return last.returncode


def _credential_refused(report: Report) -> bool:
    """The last attempt was a 401/403 diagnosed refused after asking ``GET /user`` (``Client._diagnosis``)."""
    last = report.attempts[-1] if report.attempts else None
    return last is not None and last.returncode in _forge.AUTH_REFUSED and last.diagnosis is Diagnosis.FORGE_REFUSED


def diagnose(status: int, text: str) -> Diagnosis:
    """Read through netverb's table first; an answered 4xx it does not know is a refusal, never a transient.

    A 401/403 never reaches here: :meth:`dev_lab.dev.forgework.Client._diagnosis` measures it against ``GET /user``
    first.
    """
    found = classify(f'error: {status} {text}')
    answered = HTTP_ERROR_FLOOR <= status < _HTTP_SERVER_FLOOR and status not in _HTTP_RETRYABLE_4XX
    return Diagnosis.FORGE_REFUSED if found is Diagnosis.UNCLASSIFIED and answered else found
