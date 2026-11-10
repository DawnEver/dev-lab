"""THE ONE FORGE RETRY DOOR, one planted answer per class: what is retried, after how long, and what is not.

Every exchange goes through an injected transport, so the REAL loop (:func:`dev_lab.dev.forgefailure.retried`)
runs with only the clock substituted. The classes: a rate limit (403 with its headers or body, 429) is retried
after the wait the forge names, and reported without another attempt when that wait is past the cap; a 5xx and a
dropped connection are retried after the backoff; a not-found and a refused credential are answered once.
"""

from __future__ import annotations

import functools
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from dev_lab.dev import forgesecrets
from dev_lab.dev.actionsartifact import retrying
from dev_lab.dev.forge import Forge
from dev_lab.dev.forgefailure import RATE_WAIT_CAP_S, Answer, ForgeCallFailed, pause
from dev_lab.dev.forgesecrets import Target
from dev_lab.dev.forgework import Client
from dev_lab.dev.netverb import DEFAULT_ATTEMPTS, DEFAULT_BACKOFF_S, Diagnosis, Disposition, classify, run_network_verb

_GITHUB = Forge('github.com', 'o', 'r')
_ISSUE = '/repos/o/r/issues/1'
_LIMITED = b'{"message": "API rate limit exceeded for user ID 1."}'


@dataclass
class _Response:
    status: int
    body: bytes
    headers: dict[str, str]

    def getheader(self, name: str) -> str | None:
        return self.headers.get(name)

    def read(self) -> bytes:
        return self.body


@dataclass
class _Wire:
    """A transport answering each path from its own queue of ``(status, body, headers)`` -- or an ``OSError``."""

    answers: dict[str, list[Any]]
    asked: list[str] = field(default_factory=list)

    def __call__(self, _host: str, _timeout: float) -> _Wire:
        return self

    def request(self, _method: str, path: str, **_: object) -> None:
        self.asked.append(path)

    def getresponse(self) -> _Response:
        queue = self.answers[self.asked[-1]]
        planted = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(planted, OSError):
            raise planted
        status, body, headers = planted
        return _Response(status, body, headers)

    def close(self) -> None:
        pass


def _client(wire: _Wire, slept: list[float]) -> Client:
    return Client(_GITHUB, 'tok', transport=wire, sleep=slept.append)


def test_a_403_rate_limit_is_retried_after_its_reset_and_never_measured_as_a_credential() -> None:
    """THE INCIDENT (2026-11-05): this answer was read as a refused credential and never retried."""
    reset = str(int(time.time()) + 2)
    limited = (403, _LIMITED, {'X-RateLimit-Remaining': '0', 'X-RateLimit-Reset': reset})
    wire, slept = _Wire({_ISSUE: [limited, (200, b'{"number": 1}', {})]}), []
    assert _client(wire, slept).call('GET', _ISSUE) == {'number': 1}
    assert wire.asked == [_ISSUE, _ISSUE], 'GET /user is never asked: it is rate limited too'
    assert len(slept) == 1
    assert 0 < slept[0] <= 2


def test_a_403_whose_only_evidence_is_its_body_is_a_rate_limit_too() -> None:
    wire, slept = _Wire({_ISSUE: [(403, _LIMITED, {}), (200, b'{}', {})]}), []
    assert _client(wire, slept).call('GET', _ISSUE) == {}
    assert slept == [DEFAULT_BACKOFF_S], 'no wait named: the backoff'


def test_a_429_waits_its_retry_after() -> None:
    wire, slept = _Wire({_ISSUE: [(429, b'', {'Retry-After': '7'}), (200, b'{}', {})]}), []
    _client(wire, slept).call('GET', _ISSUE)
    assert slept == [7.0]


def test_a_reset_past_the_cap_is_reported_at_once_and_names_no_credential() -> None:
    reset = str(int(time.time() + RATE_WAIT_CAP_S) + 600)
    wire, slept = _Wire({_ISSUE: [(403, _LIMITED, {'X-RateLimit-Remaining': '0', 'X-RateLimit-Reset': reset})]}), []
    with pytest.raises(ForgeCallFailed) as failed:
        _client(wire, slept).call('GET', _ISSUE)
    assert (failed.value.report.diagnosis, failed.value.report.disposition) == (
        Diagnosis.RATE_LIMITED,
        Disposition.EXHAUSTED,
    )
    assert (wire.asked, slept) == ([_ISSUE], [])
    assert not failed.value.credential_refused
    assert failed.value.final is None, 'a rate limit is never a final refusal: the outbox keeps the write'
    assert 're-store' not in str(failed.value)
    assert 'credential' not in str(failed.value)


@pytest.mark.parametrize('planted', [(502, b'bad gateway', {}), ConnectionResetError('connection reset by peer')])
def test_a_5xx_and_a_dropped_connection_are_retried_after_the_backoff(planted: object) -> None:
    wire, slept = _Wire({_ISSUE: [planted, (200, b'{"ok": true}', {})]}), []
    assert _client(wire, slept).call('GET', _ISSUE) == {'ok': True}
    assert slept == [DEFAULT_BACKOFF_S]


def test_a_5xx_that_never_clears_spends_the_bound_and_no_more() -> None:
    wire, slept = _Wire({_ISSUE: [(503, b'service unavailable', {})]}), []
    with pytest.raises(ForgeCallFailed) as failed:
        _client(wire, slept).call('GET', _ISSUE)
    assert len(wire.asked) == DEFAULT_ATTEMPTS
    assert failed.value.report.disposition is Disposition.EXHAUSTED


def test_a_not_found_is_answered_once_and_final() -> None:
    wire, slept = _Wire({_ISSUE: [(404, b'{"message": "Not Found"}', {})]}), []
    with pytest.raises(ForgeCallFailed) as failed:
        _client(wire, slept).call('GET', _ISSUE)
    assert (wire.asked, slept, failed.value.final) == ([_ISSUE], [], 404)


def test_a_refused_credential_is_measured_once_and_not_retried() -> None:
    """PLANTED CONTROL for the rate-limit rows: a 401 with no rate-limit evidence still reaches GET /user."""
    bad = (401, b'{"message": "Bad credentials"}', {})
    wire, slept = _Wire({_ISSUE: [bad], '/user': [bad]}), []
    with pytest.raises(ForgeCallFailed) as failed:
        _client(wire, slept).call('GET', _ISSUE)
    assert (wire.asked, slept) == ([_ISSUE, '/user'], [])
    assert failed.value.credential_refused


def test_a_raw_download_is_retried_as_every_call_is() -> None:
    """It bypassed the loop: one 503 on an artifact zip failed the review pointer outright."""
    path = '/repos/o/r/actions/artifacts/5/zip'
    wire, slept = _Wire({path: [(503, b'', {}), (200, b'zip', {})]}), []
    assert _client(wire, slept).download(path) == b'zip'
    assert slept == [DEFAULT_BACKOFF_S]


def test_the_pause_reads_an_http_date_and_caps_the_wait() -> None:
    limited = Diagnosis.RATE_LIMITED
    assert pause(limited, {'Retry-After': 'Thu, 01 Jan 1970 00:00:30 GMT'}, now=10.0) == 20.0
    assert pause(limited, {'X-RateLimit-Reset': str(10 + int(RATE_WAIT_CAP_S) + 1)}, now=10.0) is None
    assert pause(limited, {'X-RateLimit-Reset': '5'}, now=10.0) == 0.0, 'a reset already past waits nothing'
    assert pause(Diagnosis.TRANSIENT, {'Retry-After': '999'}, now=0.0) == DEFAULT_BACKOFF_S


def test_the_artifact_protocol_goes_through_the_same_door() -> None:
    planted = [Answer(503, b''), Answer(200, b'{"ok": true}')]
    sent: list[str] = []

    def exchange(method: str, url: str, _body: bytes, _headers: object) -> Answer:
        sent.append(f'{method} {url}')
        return planted.pop(0)

    slept: list[float] = []
    assert retrying(exchange, sleep=slept.append)('POST', 'https://r.example/twirp/x', b'', {}) == b'{"ok": true}'
    assert (len(sent), slept) == (2, [DEFAULT_BACKOFF_S])


def test_a_refused_artifact_call_is_not_repeated_and_its_report_holds_no_signed_query() -> None:
    sent: list[str] = []

    def exchange(_method: str, url: str, _body: bytes, _headers: object) -> Answer:
        sent.append(url)
        return Answer(409, b'already exists')

    with pytest.raises(ForgeCallFailed) as failed:
        retrying(exchange, sleep=lambda _: None)('PUT', 'https://blob.example/a?sig=SECRET', b'', {})
    assert len(sent) == 1
    assert 'SECRET' not in str(failed.value)


@pytest.mark.parametrize(
    ('said', 'diagnosis'),
    [
        ('HTTP 403: API rate limit exceeded for installation ID 1.', Diagnosis.RATE_LIMITED),
        ('You have exceeded a secondary rate limit.', Diagnosis.RATE_LIMITED),
        ('HTTP 401: Bad credentials (https://api.github.com/...)', Diagnosis.FORGE_REFUSED),
        ('HTTP 404: Not Found (https://api.github.com/repos/o/r/...)', Diagnosis.REMOTE_ABSENT),
    ],
)
def test_gh_s_own_spellings_are_classified(said: str, diagnosis: Diagnosis) -> None:
    assert classify(said) is diagnosis


def test_a_gh_secret_set_is_retried_through_netverb_and_its_output_never_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []
    codes = [1, 0]

    def run(argv: list[str], **kw: object) -> subprocess.CompletedProcess[str]:
        calls.append(kw)
        return subprocess.CompletedProcess(argv, codes.pop(0), stdout='', stderr='HTTP 502: Bad Gateway')

    monkeypatch.setattr(forgesecrets._door, 'run', run)
    monkeypatch.setattr(forgesecrets, 'run_network_verb', functools.partial(run_network_verb, sleep=lambda _: None))
    forgesecrets.set_secret(Target('hub', Path(), _GITHUB), 'AI_LAB_KEYS_LIVE', 'bundle')
    assert [call['input'] for call in calls] == ['bundle', 'bundle']
