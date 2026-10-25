"""The scheme decides the connection, and one default cannot serve both callers."""

from __future__ import annotations

import http.client
import http.server
import threading

import pytest

from dev_lab.supervise.transport import fetch_json, https_only, scheme_transport, split_url


class _Connection(http.client.HTTPConnection):
    """A transport's product, recording what it was asked instead of connecting.

    Subclassing the real class is deliberate: it makes a recorder a ``Transport`` honestly rather
    than by annotation. ``HTTPConnection`` does not connect until a request is made.
    """

    def __init__(self, status: int = 200, body: str = '{}') -> None:
        """Build a recorder that answers with one canned reply."""
        super().__init__('fake.invalid', timeout=1)
        self.status = status
        self._body = body
        self.sent: list[str] = []
        self.closed = False

    def request(self, method: str, url: str, body: object = None, headers: object = None) -> None:
        """Record one request."""
        self.sent.append(url)

    def getresponse(self) -> http.client.HTTPResponse:
        """Answer from the canned reply."""
        return _Reply(self.status, self._body)

    def close(self) -> None:
        """Record the close."""
        self.closed = True


class _Reply:
    """A canned HTTP reply."""

    def __init__(self, status: int, body: str) -> None:
        """Hold the status and the body."""
        self.status = status
        self._body = body

    def read(self, amt: int | None = None) -> bytes:
        """Return the body."""
        return self._body.encode('utf-8')


def test_the_scheme_reaches_the_transport() -> None:
    """THE REGRESSION. The transport was handed a bare host, so it could not know the scheme.

    The predecessor stripped ``http://`` off the URL and then called a transport whose only
    parameter was the host. A health probe against ``http://127.0.0.1:7001/`` therefore arrived as
    an HTTPS request, the TLS handshake read plain HTTP, and the endpoint was reported unreachable
    while it was answering 200 to everything else on the box.
    """
    seen: dict[str, str] = {}

    def transport(scheme: str, host: str, _timeout: float) -> http.client.HTTPConnection:
        seen['scheme'] = scheme
        seen['host'] = host
        return _Connection()

    fetch_json(transport, 'http://127.0.0.1:7001/health/', 5)
    assert seen == {'scheme': 'http', 'host': '127.0.0.1:7001'}


def test_a_plain_url_gets_a_plain_connection() -> None:
    """Loopback speaks HTTP because the service behind the proxy holds no certificate."""
    assert isinstance(scheme_transport('http', '127.0.0.1:7001', 5), http.client.HTTPConnection)
    assert not isinstance(scheme_transport('http', '127.0.0.1:7001', 5), http.client.HTTPSConnection)


def test_a_secure_url_gets_a_secure_connection() -> None:
    """The same transport must still do TLS when the URL asks for it."""
    assert isinstance(scheme_transport('https', 'api.resend.com', 5), http.client.HTTPSConnection)


def test_a_probe_on_plain_http_completes_against_a_real_server() -> None:
    """THE POINT OF THE WHOLE MODULE: a real round trip, not a recorded one.

    A double would have agreed with whichever connection class it was handed. Only a socket can
    tell TLS from plain text, and telling them apart is the entire defect.
    """
    server = http.server.HTTPServer(('127.0.0.1', 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        status, body, _detail = fetch_json(scheme_transport, f'http://127.0.0.1:{port}/health/', 5)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    assert status == 200
    assert body == {'status': 'healthy'}


class _Handler(http.server.BaseHTTPRequestHandler):
    """Answer every GET with a fixed JSON health payload."""

    def do_GET(self) -> None:
        """Write the canned answer."""
        payload = b'{"status": "healthy"}'
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt: str, *args: object) -> None:
        """Stay silent: a test's server has no business writing to the console."""
        return


def test_the_credential_channel_refuses_to_be_talked_down_to_plain_http() -> None:
    """An API key in clear text is the failure this family refuses to ship.

    The stance belongs to the channel that carries the secret. It was applied to every caller
    instead, which is how a probe against loopback was made to speak TLS at a plain socket.
    """
    with pytest.raises(ValueError, match='plain HTTP'):
        https_only('http', 'api.resend.com', 5)


def test_the_credential_channel_still_connects_over_https() -> None:
    """Refusing plain HTTP must not refuse the case it exists for."""
    assert isinstance(https_only('https', 'api.resend.com', 5), http.client.HTTPSConnection)


def test_a_url_is_split_into_the_three_parts_a_request_needs() -> None:
    """Parsing the URL happens once. Twice is how the two copies drift."""
    assert split_url('https://api.resend.com/emails') == ('https', 'api.resend.com', '/emails')


def test_a_url_with_no_scheme_is_refused() -> None:
    """A bare host reads as a relative path, and guessing the scheme is how the defect began."""
    with pytest.raises(ValueError, match='scheme'):
        split_url('api.resend.com/emails')


def test_a_connection_that_fails_is_reported_rather_than_raised() -> None:
    """An endpoint being down is the ordinary case here; it must not end the cycle."""
    status, body, detail = fetch_json(scheme_transport, 'http://127.0.0.1:1/health/', 2)
    assert status == 0
    assert body is None
    assert detail
