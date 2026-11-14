"""``[ops.status]``: the host publishes its status card, served read-only behind its allowlist (2026-11-13).

The declaration is the whole switch: install renders the supervisor's ``--card`` (and the auto-upgrade audit it
quotes) and a managed route in the declared Caddy site that serves that ONE file to the ``[ops.caddy] allow`` list
only. Undeclared, the route is removed -- never left serving a card nobody writes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dev_lab.ops.caddy import status_routed
from dev_lab.ops.config import load
from dev_lab.ops.install import install

_CADDYFILE = """gitea.example {
\t@campus remote_ip 128.243.0.0/16
\thandle @campus {
\t\treverse_proxy 127.0.0.1:3000
\t}
\trespond "Forbidden (campus-only)" 403
}
"""

_HOST = (
    '[ops]\nhome = "/srv/ops"\npython = "/opt/ops/bin/python"\nrepos = []\n'
    '[ops.supervise]\nproject = "/srv/ops"\n'
    '[ops.caddy]\nfile = "/etc/caddy/Caddyfile"\nallow = ["128.243.0.0/16", "192.0.2.7/32"]\n'
)
_STATUS = '[ops.status]\nfile = "/var/lib/dev-lab-status/card.json"\nsite = "gitea.example"\n'


def _host(tmp_path: Path, text: str) -> tuple[Path, Path]:
    path = tmp_path / 'supervise.toml'
    path.write_text(text, encoding='utf-8')
    root = tmp_path / 'root'
    (root / 'etc/caddy').mkdir(parents=True, exist_ok=True)
    (root / 'etc/caddy/Caddyfile').write_text(_CADDYFILE, encoding='utf-8')
    return path, root


def test_a_declared_card_is_written_by_the_supervisor_and_served_only_to_the_allowlist(tmp_path: Path) -> None:
    path, root = _host(tmp_path, _HOST + _STATUS)
    done = install(load(path), root)
    unit = (root / 'etc/systemd/system/dev-lab-supervise.service').read_text(encoding='utf-8')
    assert '--card /var/lib/dev-lab-status/card.json' in unit
    assert '--card-audit /srv/ops/upgrade-follow/audit.jsonl' in unit
    caddy = (root / 'etc/caddy/Caddyfile').read_text(encoding='utf-8')
    assert '\t\tpath /dev-lab/status.json\n\t\tremote_ip 128.243.0.0/16 192.0.2.7/32\n' in caddy
    assert '\t\troot * /var/lib/dev-lab-status\n\t\trewrite * /card.json\n' in caddy
    assert caddy.index('@dev_lab_status') < caddy.index('@campus'), 'the card route is matched before the proxy'
    assert any('install -d -m 0755 -o root /var/lib/dev-lab-status' in step for step in done.next_steps)
    assert install(load(path), root).paths['etc/caddy/Caddyfile'] == 'unchanged', 'idempotent'


def test_an_undeclared_card_removes_the_route_and_the_flags(tmp_path: Path) -> None:
    """PLANTED CONTROL: the route a previous declaration rendered goes when the declaration goes."""
    path, root = _host(tmp_path, _HOST + _STATUS)
    install(load(path), root)
    path.write_text(_HOST, encoding='utf-8')
    install(load(path), root)
    assert (root / 'etc/caddy/Caddyfile').read_text(encoding='utf-8') == _CADDYFILE.replace(
        '128.243.0.0/16\n', '128.243.0.0/16 192.0.2.7/32\n'
    )
    assert '--card' not in (root / 'etc/systemd/system/dev-lab-supervise.service').read_text(encoding='utf-8')


@pytest.mark.parametrize(
    ('text', 'match'),
    [
        (_HOST.replace('[ops.caddy]', '[ops.caddy_off]').split('[ops.caddy_off]')[0] + _STATUS, r'\[ops.caddy\]'),
        (_HOST.replace('[ops.supervise]\nproject = "/srv/ops"\n', '') + _STATUS, r'\[ops.supervise\]'),
        (_HOST + _STATUS.replace('/var/lib/dev-lab-status/card.json', 'card.json'), 'absolute'),
        (_HOST + _STATUS + 'path = "/x; respond 200"\n', 'path'),
    ],
)
def test_a_card_with_no_allowlist_no_supervisor_or_an_unsafe_path_is_refused(
    tmp_path: Path, text: str, match: str
) -> None:
    """PLANTED CONTROLS: a card served to everyone, written by nobody, or a value that widens the Caddyfile."""
    path, _ = _host(tmp_path, text)
    with pytest.raises(ValueError, match=match):
        load(path)


def test_a_route_in_a_site_the_caddyfile_does_not_hold_is_refused() -> None:
    with pytest.raises(ValueError, match=r'nowhere\.example'):
        status_routed(_CADDYFILE, site='nowhere.example', path='/s.json', file='/v/card.json', allow=('1.2.3.4',))
