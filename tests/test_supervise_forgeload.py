"""``forge_load``: how busy the forge is -- concurrent requests from a Prometheus scrape, postgres connections by state.

User, 2026-11-20: the status card shows Gitea's concurrent requests and postgres's connection count, with a history.
A sampler that could not read a value reports it ABSENT (the card says ``unknown``), never 0: a zero on a busy forge
is the reading that would let an overload pass unnoticed.
"""

from __future__ import annotations

import http.client
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from _box_fake import boxed_as_run

from dev_lab.supervise.component import CheckContext
from dev_lab.supervise.components import COMPONENTS
from dev_lab.supervise.components.forgeload import ForgeLoad, prometheus_sum
from dev_lab.supervise.process import SystemdProcessManager
from dev_lab.supervise.process.base import Ran
from dev_lab.supervise.transport import Transport

_NOW = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)

_METRICS = """# HELP caddy_http_requests_in_flight Number of requests currently handled by this server.
# TYPE caddy_http_requests_in_flight gauge
caddy_http_requests_in_flight{handler="reverse_proxy",server="srv0"} 7
caddy_http_requests_in_flight{handler="file_server",server="srv0"} 2
caddy_http_requests_in_flight_total 99
go_goroutines 143
"""


class _Reply:
    def __init__(self, status: int, body: str) -> None:
        self.status = status
        self._body = body

    def read(self, amt: int | None = None) -> bytes:
        return self._body.encode('utf-8')


class _Connection(http.client.HTTPConnection):
    def __init__(self, status: int, body: str, seen: list[dict[str, str]]) -> None:
        super().__init__('fake.invalid', timeout=1)
        self._status, self._body, self._seen = status, body, seen

    def request(self, method: str, url: str, headers: dict[str, str] | None = None) -> None:
        self._seen.append(dict(headers or {}))

    def getresponse(self) -> _Reply:
        return _Reply(self._status, self._body)

    def close(self) -> None:
        """Nothing to close."""


def _transport(status: int = 200, body: str = _METRICS, seen: list[dict[str, str]] | None = None) -> Transport:
    record = seen if seen is not None else []

    def make(_scheme: str, _host: str, _timeout: float) -> _Connection:
        return _Connection(status, body, record)

    return make


def _ctx(config: dict[str, Any], ran: Ran | None = None) -> CheckContext:
    def run(argv: list[str], _timeout: int, _cwd: str | None) -> Ran:
        return boxed_as_run(argv, ran if ran is not None else Ran(code=0, out=''))

    return CheckContext(
        config=config,
        shared={},
        state={},
        project=Path('/srv/target'),
        manager=SystemdProcessManager(runner=run),
        timeline={'now': _NOW.isoformat()},
    )


_SCRAPE = {'url': 'http://127.0.0.1:2019/metrics', 'series': {'caddy_http_requests_in_flight': 'forge_requests'}}


def test_the_roster_ships_forge_load() -> None:
    assert 'forge_load' in [component.name for component in COMPONENTS]


def test_a_series_is_summed_across_its_labels_and_a_longer_name_is_not_it() -> None:
    assert prometheus_sum(_METRICS, 'caddy_http_requests_in_flight') == 9.0
    assert prometheus_sum(_METRICS, 'go_goroutines') == 143.0
    assert prometheus_sum(_METRICS, 'absent_series') is None


def test_a_scrape_publishes_each_declared_series_under_its_card_name() -> None:
    found = ForgeLoad(transport=_transport()).check(_ctx({'scrape': [_SCRAPE]}))
    assert found.metrics == {'forge_requests': 9.0}
    assert not found.anomalies


def test_a_token_file_is_sent_as_a_bearer_header_and_never_said(tmp_path: Path) -> None:
    token = 'T' * 40
    (tmp_path / 'token').write_text(token + '\n', encoding='utf-8')
    seen: list[dict[str, str]] = []
    scrape = {**_SCRAPE, 'token_file': str(tmp_path / 'token')}
    found = ForgeLoad(transport=_transport(status=401, body='unauthorized', seen=seen)).check(
        _ctx({'scrape': [scrape]})
    )
    assert seen == [{'Accept': 'text/plain', 'Authorization': f'Bearer {token}'}]
    assert found.anomalies, 'a refused scrape is said'
    assert token not in found.anomalies[0].message


def test_a_failed_scrape_reports_the_value_absent_never_zero() -> None:
    """PLANTED CONTROL: the sampler can say "I do not know"; a 0 here would read as an idle forge."""
    for transport in (_transport(status=503, body='down'), _transport(body='other_series 1\n')):
        found = ForgeLoad(transport=transport).check(_ctx({'scrape': [_SCRAPE]}))
        assert 'forge_requests' not in found.metrics
        assert [anomaly.kind for anomaly in found.anomalies] == ['sample_failed']


def test_postgres_connections_are_counted_by_state_with_their_total_and_ceiling() -> None:
    ran = Ran(code=0, out='active|3\nidle|7\nidle in transaction|1\nmax|100\n')
    found = ForgeLoad(transport=_transport()).check(_ctx({'postgres': ['psql', '-X', '-At', '-d', 'gitea']}, ran))
    assert found.metrics == {
        'pg_connections_active': 3.0,
        'pg_connections_idle': 7.0,
        'pg_connections_idle_in_transaction': 1.0,
        'pg_connections_total': 11.0,
        'pg_connections_max': 100.0,
    }


def test_a_failed_postgres_query_reports_every_connection_count_absent() -> None:
    found = ForgeLoad(transport=_transport()).check(_ctx({'postgres': ['psql']}, Ran(code=2, err='peer auth failed')))
    assert not [key for key in found.metrics if key.startswith('pg_')]
    assert [anomaly.kind for anomaly in found.anomalies] == ['sample_failed']
    assert 'peer auth failed' in found.anomalies[0].message
