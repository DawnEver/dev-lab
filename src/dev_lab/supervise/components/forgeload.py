"""How busy the forge is: concurrent requests and postgres connections, for the status card's history (2026-11-20).

Two samplers, each declared, neither naming a host:

* ``scrape``: Prometheus text pages (a reverse proxy's or Gitea's ``/metrics``), each declared series summed across
  its labels and published under the card name the declaration gives it -- ``caddy_http_requests_in_flight`` is the
  requests the forge is serving right now. A ``token_file`` is sent as a Bearer header and never repeated.
* ``postgres``: an argv (``psql -X -At -d <db>``, run through the process manager's ceiling) that this component
  hands ONE read-only query of ``pg_stat_activity`` -- client backends by state, their total, and
  ``max_connections`` -- as ``pg_connections_<state>``, ``pg_connections_total`` and ``pg_connections_max``.

A VALUE NOT READ IS ABSENT, NEVER 0. A refused scrape, a missing series or a failed query publishes no metric (the
card's history says ``unknown``) and one ``sample_failed`` warning naming what failed -- a 0 would read as an idle
forge exactly when it is too busy to answer.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

from dev_lab.supervise.component import CheckContext, Component
from dev_lab.supervise.transport import OK_CEILING, OK_FLOOR, Transport, fetch_text, scheme_transport
from dev_lab.supervise.verdict import Anomaly, CheckResult, Severity

__all__ = ['PG_QUERY', 'SCRAPE_CAP', 'ForgeLoad', 'prometheus_sum']

#: Client backends by state (a NULL state is a backend between states), then the server's ceiling.
PG_QUERY: Final = (
    "SELECT coalesce(state, 'unknown'), count(*) FROM pg_stat_activity WHERE backend_type = 'client backend' "
    "GROUP BY 1 UNION ALL SELECT 'max', setting::int FROM pg_settings WHERE name = 'max_connections'"
)

#: A metrics page is larger than a health reply; bounded all the same.
SCRAPE_CAP: Final = 1024 * 1024

_SAMPLE: Final = re.compile(r'^(?P<name>[A-Za-z_:][A-Za-z0-9_:]*)(?:\{[^}]*\})?\s+(?P<value>\S+)')
_STATE: Final = re.compile(r'[^a-z0-9]+')


def prometheus_sum(text: str, series: str) -> float | None:
    """The sum of every sample of *series* in a Prometheus text page, or None when it has none."""
    values = [
        float(found['value'])
        for line in text.splitlines()
        if (found := _SAMPLE.match(line)) and found['name'] == series
    ]
    return sum(values) if values else None


class ForgeLoad(Component):
    """Concurrent requests (Prometheus scrapes) and postgres connections by state.

    Config::

        [components.forge_load]
        postgres = ["psql", "-X", "-At", "-d", "gitea"]
        [[components.forge_load.scrape]]
        url = "http://127.0.0.1:2019/metrics"
        series = { caddy_http_requests_in_flight = "forge_requests" }
        # token_file = "/etc/dev-lab/metrics-token"

    """

    name = 'forge_load'
    description = 'Concurrent requests and database connections, sampled for the status card history'

    def __init__(self, transport: Transport | None = None) -> None:
        """Take the transport, so a test reads the request rather than makes it."""
        self._transport = transport or scheme_transport

    def check(self, ctx: CheckContext) -> CheckResult:
        """Sample every declared scrape and the postgres query; each failure absent and said, never 0."""
        result = CheckResult()
        failed = [problem for scrape in ctx.config.get('scrape', ()) for problem in self._scrape(scrape, result)]
        if argv := [str(part) for part in ctx.config.get('postgres', ())]:
            failed += self._postgres(ctx, argv, result)
        if failed:
            result.anomalies.append(
                Anomaly(
                    kind='sample_failed',
                    severity=Severity.WARNING,
                    message='forge load not read (shown unknown): ' + '; '.join(failed),
                    signature='forge_load:' + ','.join(sorted(problem.split(': ', 1)[0] for problem in failed)),
                )
            )
        return result

    def _scrape(self, scrape: Mapping[str, Any], result: CheckResult) -> list[str]:
        url = str(scrape.get('url', ''))
        headers: dict[str, str] = {}
        if token_file := scrape.get('token_file'):
            try:
                headers['Authorization'] = 'Bearer ' + Path(str(token_file)).read_text(encoding='utf-8').strip()
            except OSError as exc:
                return [f'{url}: token file unreadable ({type(exc).__name__})']
        status, body, detail = fetch_text(
            self._transport, url, float(scrape.get('timeout', 5)), headers, cap=SCRAPE_CAP
        )
        if not OK_FLOOR <= status < OK_CEILING:
            said = detail.splitlines()[0][:120] if detail.strip() else 'no reply'
            return [f'{url}: answered {status} ({said})']
        missing = []
        for series, key in dict(scrape.get('series', {})).items():
            value = prometheus_sum(body, str(series))
            if value is None:
                missing.append(f'{url}: no {series} series')
            else:
                result.metrics[str(key)] = value
        return missing

    @staticmethod
    def _postgres(ctx: CheckContext, argv: list[str], result: CheckResult) -> list[str]:
        ran = ctx.manager.run_capped(
            [*argv, '-c', PG_QUERY],
            memory_max=str(ctx.shared.get('cycle', {}).get('command_ceiling', '400M')),
            timeout=int(ctx.config.get('timeout', 10)),
        )
        if not ran.ok:
            return [f'postgres: {ran.detail()}']
        counts: dict[str, float] = {}
        for line in ran.out.splitlines():
            state, _, count = line.rpartition('|')
            try:
                counts[_STATE.sub('_', state.strip().lower()).strip('_')] = float(count)
            except ValueError:
                return [f'postgres: unparsed row {line[:80]!r}']
        if 'max' not in counts:
            return ['postgres: no max_connections row']
        ceiling = counts.pop('max')
        result.metrics.update({f'pg_connections_{state}': value for state, value in counts.items()})
        result.metrics['pg_connections_total'] = sum(counts.values())
        result.metrics['pg_connections_max'] = ceiling
        return []
