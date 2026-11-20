"""``[ops.caddy] metrics``: the install door renders Caddy's global ``servers { metrics }`` (2026-11-20).

Requests in flight (``caddy_http_requests_in_flight``, read by the supervisor's ``forge_load``) exist only when the
global option is on. It used to be a hand edit of a root-owned file; now it is declared, rendered between markers,
and removed when the declaration goes. An unmanaged global ``servers`` block is refused, never merged into.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dev_lab.ops.caddy import Caddy, install_caddy, metrics_rendered

_SITE = 'gitea.example {\n\t@campus remote_ip 198.51.100.0/24\n\trespond "x" 403\n}\n'
_GLOBAL = '{\n\temail ops@example.org\n}\n\n' + _SITE


def test_a_caddyfile_without_a_global_block_gains_one_holding_only_metrics() -> None:
    found = metrics_rendered(_SITE, on=True)
    assert found.index('servers {\n') < found.index('gitea.example {')
    assert '\t\tmetrics\n' in found
    assert found.endswith(_SITE)


def test_an_existing_global_block_keeps_its_options_and_gains_metrics_inside_it() -> None:
    found = metrics_rendered(_GLOBAL, on=True)
    assert found.startswith('{\n')
    assert '\temail ops@example.org\n' in found
    assert found.index('metrics') < found.index('\n}\n')
    assert found.count('{\n') == _GLOBAL.count('{\n') + 1, 'no second global block'


@pytest.mark.parametrize('text', [_SITE, _GLOBAL])
def test_rendering_is_idempotent_and_undeclaring_restores_the_file(text: str) -> None:
    """PLANTED CONTROL: off removes exactly what on added -- byte for byte."""
    once = metrics_rendered(text, on=True)
    assert metrics_rendered(once, on=True) == once
    assert metrics_rendered(once, on=False) == text
    assert metrics_rendered(text, on=False) == text


def test_an_unmanaged_global_servers_block_is_refused_by_name() -> None:
    text = '{\n\tservers {\n\t\tprotocols h1\n\t}\n}\n' + _SITE
    with pytest.raises(ValueError, match=r'servers.*\[ops.caddy\] metrics'):
        metrics_rendered(text, on=True)


def test_install_renders_metrics_and_names_the_reload(tmp_path: Path) -> None:
    live = tmp_path / 'etc/caddy/Caddyfile'
    live.parent.mkdir(parents=True)
    live.write_text(_SITE, encoding='utf-8')
    rendered: dict[str, str] = {}
    steps = install_caddy(Caddy(allow=('198.51.100.0/24',), metrics=True), tmp_path, rendered)
    assert '\t\tmetrics\n' in rendered['etc/caddy/Caddyfile']
    assert any('systemctl reload caddy' in step for step in steps)
