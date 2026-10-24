"""Four channels, one shape, and a broken one that does not silence the others."""

from __future__ import annotations

import http.client
import smtplib
from email.message import EmailMessage
from typing import Any, ClassVar, NoReturn, Self

import pytest

from dev_lab.supervise.alert import Delivery, Notice, Notifier, Transport
from dev_lab.supervise.verdict import Severity


class _FakeResponse:
    """A canned reply."""

    def __init__(self, status: int = 200, body: str = 'ok') -> None:
        self.status = status
        self._body = body
        #: What the reader asked for, so a test can tell a CAPPED read from a read to EOF. `None`
        #: here is `read()` with no argument, which reads until the channel stops talking.
        self.asked_for: int | None = None

    def read(self, amt: int | None = None) -> bytes:
        """Return the body, recording how much was asked for."""
        self.asked_for = amt
        return self._body.encode('utf-8')


class _FakeConnection(http.client.HTTPConnection):
    """Records what was sent, without a socket.

    A real subclass rather than a duck: the transport's contract NAMES ``HTTPConnection``, so a
    stand-in that is one lets a recorder be a ``Transport`` honestly rather than by annotation.
    ``HTTPConnection`` does not connect until a request is made, so this costs nothing.
    """

    def __init__(self, status: int = 200) -> None:
        super().__init__('fake.invalid', timeout=1)
        self.status = status
        self.sent: list[tuple[str, str, bytes, dict[str, str]]] = []
        self.closed = False
        self.reply: _FakeResponse | None = None

    def request(self, method: str, path: str, body: bytes, headers: dict[str, str]) -> None:
        """Record one request."""
        self.sent.append((method, path, body, headers))

    def getresponse(self) -> _FakeResponse:
        """Return the canned reply, keeping it so a test can see how it was read."""
        self.reply = _FakeResponse(self.status)
        return self.reply

    def close(self) -> None:
        """Record the close."""
        self.closed = True


class _Recorder:
    """A transport that hands out one connection and remembers what it was asked for."""

    def __init__(self, status: int = 200) -> None:
        self.hosts: list[str] = []
        self.schemes: list[str] = []
        self.connection = _FakeConnection(status)

    def __call__(self, scheme: str, host: str, timeout: float) -> _FakeConnection:
        """Record the scheme and the host, then hand back the connection."""
        self.schemes.append(scheme)
        self.hosts.append(host)
        return self.connection


class _FakeSMTP:
    """Stands in for smtplib.SMTP, recording what a relay would have been handed."""

    instances: ClassVar[list[_FakeSMTP]] = []

    def __init__(self, host: str, port: int, timeout: int) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.started_tls = False
        self.credentials: tuple[str, str] | None = None
        self.message: EmailMessage | None = None
        _FakeSMTP.instances.append(self)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def starttls(self) -> None:
        """Record the upgrade."""
        self.started_tls = True

    def login(self, user: str, password: str) -> None:
        """Record the credentials."""
        self.credentials = (user, password)

    def send_message(self, message: EmailMessage) -> None:
        """Record the message."""
        self.message = message


@pytest.fixture(autouse=True)
def _clean_smtp() -> None:
    """Let each test see only the relays it caused."""
    _FakeSMTP.instances = []


def _notifier(alerts: dict[str, Any], transport: Transport | None = None) -> Notifier:
    """Build a notifier over one alerts table."""
    config = {'alerts': alerts}
    return Notifier(config=config, transport=transport) if transport else Notifier(config=config)


def test_nothing_enabled_delivers_nothing() -> None:
    """An empty list is a configuration fact, not an error -- the caller decides whether to care."""
    assert _notifier({}).send(Notice(subject='s', body='b')) == []


def test_a_disabled_channel_is_not_contacted() -> None:
    """`enabled = false` means the channel is absent, not that it is tried and dropped."""
    recorder = _Recorder()
    alerts = {'telegram': {'enabled': False, 'token': 't', 'chat': 'c'}}
    assert _notifier(alerts, recorder).send(Notice(subject='s', body='b')) == []
    assert recorder.hosts == []


def test_telegram_posts_to_the_chat_with_the_notice_rendered() -> None:
    """A chat has no subject field, so the severity and subject travel in the text."""
    recorder = _Recorder()
    alerts = {'telegram': {'enabled': True, 'token': 'T0K', 'chat': '42'}}
    notice = Notice(subject='disk full', body='91%', severity=Severity.CRITICAL)
    assert _notifier(alerts, recorder).send(notice) == [Delivery(channel='telegram', ok=True, detail='ok')]
    assert recorder.hosts == ['api.telegram.org']
    _method, path, body, _headers = recorder.connection.sent[0]
    assert path == '/botT0K/sendMessage'
    assert '"chat_id": "42"' in body.decode('utf-8')
    assert 'CRITICAL' in body.decode('utf-8')
    assert 'disk full' in body.decode('utf-8')


def test_a_channel_reply_is_read_to_a_cap_and_not_to_eof() -> None:
    """A refusal explains itself in its first line, and the rest is someone else's HTML.

    `read()` with no argument reads until the channel stops talking, and this process is the
    supervisor -- whose own cgroup is 300M. The identical defect was fixed in
    `transport.fetch_json` and left standing here, because each call site held its own copy of the
    number instead of importing the one the package already had.
    """
    recorder = _Recorder()
    alerts = {'telegram': {'enabled': True, 'token': 'T0K', 'chat': '42'}}
    _notifier(alerts, recorder).send(Notice(subject='s', body='b'))
    reply = recorder.connection.reply
    assert reply is not None
    assert reply.asked_for is not None, 'the reply was read to EOF'


def test_a_webhook_splits_its_url_and_keeps_the_scheme() -> None:
    """The transport takes a scheme AND a host; a config writes a URL. The seam is here, once.

    The predecessor dropped the scheme here -- it stripped ``https://`` and ``http://`` and handed
    the transport a bare host, which is why the transport had to guess. Guessing HTTPS is right
    for a channel carrying a token and wrong for every endpoint that is not.
    """
    recorder = _Recorder()
    alerts = {'webhook': {'enabled': True, 'url': 'https://hooks.example.org/abc/def'}}
    _notifier(alerts, recorder).send(Notice(subject='s', body='b'))
    assert recorder.hosts == ['hooks.example.org']
    assert recorder.schemes == ['https']
    assert recorder.connection.sent[0][1] == '/abc/def'


def test_a_webhook_carries_its_configured_headers() -> None:
    """An endpoint that wants a shared secret gets one from the config, not from code."""
    recorder = _Recorder()
    alerts = {'webhook': {'enabled': True, 'url': 'https://h.example.org/x', 'headers': {'X-Token': 'abc'}}}
    _notifier(alerts, recorder).send(Notice(subject='s', body='b'))
    headers = recorder.connection.sent[0][3]
    assert headers['X-Token'] == 'abc'
    assert headers['Content-Type'] == 'application/json'


def test_resend_posts_to_its_api_with_the_key() -> None:
    """The second mail method is a different host and a bearer token, not a different code path."""
    recorder = _Recorder()
    email = {
        'enabled': True,
        'method': 'resend',
        'api_key': 're_123',
        'sender': 'ops@example.org',
        'recipients': ['me@example.org'],
    }
    _notifier({'email': email}, recorder).send(Notice(subject='s', body='b'))
    assert recorder.hosts == ['api.resend.com']
    _method, path, body, headers = recorder.connection.sent[0]
    assert path == '/emails'
    assert headers['Authorization'] == 'Bearer re_123'
    assert 'me@example.org' in body.decode('utf-8')


def test_smtp_hands_the_relay_a_real_message(monkeypatch: pytest.MonkeyPatch) -> None:
    """The default method, and the one whose envelope fields a relay actually refuses on."""
    monkeypatch.setattr(smtplib, 'SMTP', _FakeSMTP)
    email = {
        'enabled': True,
        'host': 'relay.example.org',
        'port': 587,
        'use_tls': True,
        'username': 'u',
        'password': 'p',
        'sender': 'ops@example.org',
        'recipients': ['a@example.org', 'b@example.org'],
        'subject_prefix': '[wdg] ',
    }
    sent = _notifier({'email': email}).send(Notice(subject='deployed', body='af42145c'))
    assert sent == [Delivery(channel='email', ok=True)]
    relay = _FakeSMTP.instances[0]
    assert (relay.host, relay.port) == ('relay.example.org', 587)
    assert relay.started_tls is True
    assert relay.credentials == ('u', 'p')
    assert relay.message is not None
    assert relay.message['Subject'] == '[wdg] deployed'
    assert relay.message['To'] == 'a@example.org, b@example.org'


def test_a_failing_channel_does_not_silence_the_others(monkeypatch: pytest.MonkeyPatch) -> None:
    """The predecessor's channels shared a failure path; one broken webhook took the mail with it."""
    monkeypatch.setattr(smtplib, 'SMTP', _FakeSMTP)
    recorder = _Recorder(status=500)
    alerts = {
        'email': {'enabled': True, 'sender': 'ops@example.org', 'recipients': ['a@example.org']},
        'webhook': {'enabled': True, 'url': 'https://h.example.org/x'},
    }
    deliveries = _notifier(alerts, recorder).send(Notice(subject='s', body='b'))
    assert {delivery.channel: delivery.ok for delivery in deliveries} == {'email': True, 'webhook': False}


def test_a_transport_that_cannot_connect_reports_rather_than_raises() -> None:
    """An alert that blocks is worse than an alert that fails: the cycle it holds is the retry."""

    def explode(_scheme: str, _host: str, _timeout: float) -> NoReturn:
        raise OSError(113, 'no route to host')

    alerts = {'webhook': {'enabled': True, 'url': 'https://h.example.org/x'}}
    deliveries = _notifier(alerts, explode).send(Notice(subject='s', body='b'))
    assert deliveries[0].ok is False
    assert 'no route to host' in deliveries[0].detail


def test_a_relay_that_refuses_is_a_delivery_not_an_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    """A refused relay is the ordinary case on a host whose credentials have rotated."""

    class _Refusing(_FakeSMTP):
        def send_message(self, message: EmailMessage) -> None:
            raise smtplib.SMTPRecipientsRefused({})

    monkeypatch.setattr(smtplib, 'SMTP', _Refusing)
    email = {'enabled': True, 'method': 'smtp', 'sender': 'o@example.org', 'recipients': ['a@example.org']}
    deliveries = _notifier({'email': email}).send(Notice(subject='s', body='b'))
    assert deliveries[0].ok is False
    assert 'smtp:' in deliveries[0].detail


def test_every_enabled_channel_is_reported_in_a_fixed_order() -> None:
    """A caller reading the list positionally gets the same order every time."""
    recorder = _Recorder()
    alerts = {
        'email': {'enabled': True, 'method': 'resend', 'sender': 'o@example.org', 'recipients': ['a@example.org']},
        'telegram': {'enabled': True, 'token': 't', 'chat': 'c'},
        'webhook': {'enabled': True, 'url': 'https://h.example.org/x'},
    }
    channels = [delivery.channel for delivery in _notifier(alerts, recorder).send(Notice(subject='s', body='b'))]
    assert channels == ['email', 'telegram', 'webhook']
