"""How a connection is made, and the one fact the caller holds that a transport cannot.

THE SCHEME IS PASSED, AND THAT IS WHY THIS MODULE EXISTS. The predecessor handed a transport a
bare ``host:port``, having already stripped the scheme off the URL. A transport given only a host
cannot tell ``https://example.org`` from ``http://example.org``, so the one that shipped assumed
TLS -- correct for an alert channel carrying a credential, and wrong for a health probe against
``http://127.0.0.1:7001/``. That probe failed with ``SSLError: WRONG_VERSION_NUMBER``, reported a
service that was answering every other caller as unreachable, and would have refused every release
the deployment gate was asked to prove. The scheme is known exactly once, where the URL is parsed,
and it is carried from there.

TWO TRANSPORTS, BECAUSE THE TWO CALLERS WANT OPPOSITE THINGS. A channel that carries a credential
must never be talked down to plain HTTP: an API key in clear text is a failure this family refuses
to ship. A probe against loopback carries nothing and speaks plain HTTP on purpose, because the
service behind the reverse proxy holds no certificate. One default cannot serve both, and sharing
one is exactly how the second case silently became the first.
"""

from __future__ import annotations

import http.client
import json
from collections.abc import Callable
from typing import Final

__all__ = [
    'BODY_CAP',
    'OK_CEILING',
    'OK_FLOOR',
    'REPLY_KEPT',
    'Transport',
    'fetch_json',
    'https_only',
    'scheme_transport',
    'split_url',
]

#: What counts as an endpoint having answered, as a half-open range. Named rather than written into
#: a comparison because a bare 200 in an expression is a number, and a rule someone can find and
#: change is a policy.
#:
#: THESE LIVED IN TWO MODULES UNTIL 2026-10-03 -- `components.health` judged an endpoint healthy by
#: them and `alert` judged a channel to have taken a notice by a private second pair of the same two
#: numbers -- and they are ONE fact, so they are one definition now. HTTP is what this module is
#: about; a component is a thing that USES the answer.
OK_FLOOR: Final = 200
OK_CEILING: Final = 300

#: How much of a reply is kept for the anomaly message.
REPLY_KEPT: Final = 200

#: How much of a reply is READ, and it is not the same number as the one above because truncating
#: what is stored does not bound what is allocated. `response.read()` with no argument reads to
#: EOF, so an endpoint that answers with a large body -- a misconfigured one returning an HTML
#: error page, or one that is simply not the API it was believed to be -- makes the SUPERVISOR
#: allocate whatever that body is. On a 1.6 GB host the supervisor's whole job is to survive the
#: service behaving badly, and the 2026-10-01 incident on this machine was exactly a process that
#: took the box with it. Generous for a health payload and bounded regardless.
BODY_CAP: Final = 64 * 1024

#: The read is bounded in SIZE; a peer that dribbles one byte at a time defeats the socket timeout,
#: which applies per operation rather than to the whole reply. Bounding the size bounds that case
#: too -- a deliberate dribble is capped at :data:`BODY_CAP` bytes rather than running forever --
#: at the cost of hours rather than seconds in the worst case. Recorded rather than solved:
#: `http.client` offers no wall-clock deadline for a whole response.

#: Make a connection from a scheme, a host and a timeout. The scheme is the first parameter
#: because it is the one the transport cannot recover and the one that decides the class.
type Transport = Callable[[str, str, float], http.client.HTTPConnection]


def split_url(url: str) -> tuple[str, str, str]:
    """Split a URL into the scheme, the authority and the path a request needs.

    Parsed here and nowhere else. Two copies of this is how a webhook's scheme came to be dropped
    by the sender while the probe kept it, and neither copy could see the other.

    Args:
        url: the full URL, scheme included.

    Returns:
        The lower-cased scheme, the authority (host and port), and a path that always starts
        with a slash.

    Raises:
        ValueError: the URL carries no scheme, so the connection class cannot be chosen.

    """
    scheme, separator, rest = url.partition('://')
    if not separator:
        msg = f'{url!r} names no scheme; write https:// or http:// in front of it'
        raise ValueError(msg)
    authority, _, path = rest.partition('/')
    return scheme.lower(), authority, '/' + path


def https_only(scheme: str, host: str, timeout: float) -> http.client.HTTPSConnection:
    """Return the transport for a channel that carries a credential.

    It refuses plain HTTP rather than upgrading it, because a silent upgrade and a silent
    downgrade look the same to the caller and only one of them is safe.

    Args:
        scheme: the URL's scheme.
        host: the host to connect to.
        timeout: seconds to allow.

    Returns:
        A connection that cannot be talked down to plain HTTP.

    Raises:
        ValueError: the URL is not HTTPS.

    """
    if scheme != 'https':
        msg = f'{scheme}:// carries a credential and will not be sent over plain HTTP'
        raise ValueError(msg)
    return http.client.HTTPSConnection(host, timeout=timeout)


def scheme_transport(scheme: str, host: str, timeout: float) -> http.client.HTTPConnection:
    """Return the transport for a probe, which carries nothing secret.

    The scheme decides the connection class. A health endpoint on loopback is plain HTTP because
    the reverse proxy terminates TLS at the edge; an endpoint reached directly may not be.

    Args:
        scheme: the URL's scheme.
        host: the host to connect to.
        timeout: seconds to allow.

    Returns:
        A TLS connection for ``https``, a plain one otherwise.

    """
    if scheme == 'https':
        return http.client.HTTPSConnection(host, timeout=timeout)
    return http.client.HTTPConnection(host, timeout=timeout)


def fetch_json(transport: Transport, url: str, timeout: float) -> tuple[int, object, str]:
    """GET *url* and parse the body as JSON.

    Args:
        transport: how the connection is made, given the scheme the URL supplies.
        url: the full URL.
        timeout: seconds to allow.

    Returns:
        The status, the parsed body or None, and a one-line detail. A connection that failed
        returns status 0 rather than raising: an endpoint being down is the ordinary case here,
        and one malformed URL in a config must not end the cycle that reads it.

    """
    try:
        scheme, host, path = split_url(url)
    except ValueError as exc:
        return 0, None, str(exc)
    try:
        connection = transport(scheme, host, timeout)
        try:
            connection.request('GET', path, headers={'Accept': 'application/json'})
            response = connection.getresponse()
            raw = response.read(BODY_CAP).decode('utf-8', 'replace')
            try:
                body: object = json.loads(raw)
            except ValueError:
                body = None
            return response.status, body, raw[:REPLY_KEPT]
        finally:
            connection.close()
    except (OSError, ValueError, http.client.HTTPException) as exc:
        return 0, None, f'{type(exc).__name__}: {exc}'
