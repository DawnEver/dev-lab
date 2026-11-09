"""``[ops.caddy]``: the forge's Caddy allowlist is configuration, rewritten by the install door (2026-11-09).

The user ruling: the Aliyun Actions test host and the Cirrus research account reach Gitea, which the campus-only
allowlist refused with 403. Before this, the allowlist was a hand-edited Caddyfile line that only root could change,
and after the lockdown nobody holds root -- so the allowlist moves through the ops door like every other knob.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dev_lab.ops.caddy import allowlisted
from dev_lab.ops.config import load
from dev_lab.ops.install import install

_CADDYFILE = """gitea.example {
\t@campus remote_ip 128.243.0.0/16
\thandle @campus {
\t\treverse_proxy 127.0.0.1:3000
\t}
\trespond "Forbidden (campus-only)" 403
}
api.example {
\t@campus remote_ip 128.243.0.0/16
\trespond "Forbidden (campus-only)" 403
}
"""

_ALLOW = ('128.243.0.0/16', '8.208.22.233/32', '129.215.62.178/32')


def test_every_remote_ip_matcher_takes_the_declared_list() -> None:
    out = allowlisted(_CADDYFILE, _ALLOW)
    assert out.count('\t@campus remote_ip 128.243.0.0/16 8.208.22.233/32 129.215.62.178/32\n') == 2
    assert out.replace(' 8.208.22.233/32 129.215.62.178/32', '') == _CADDYFILE, 'nothing else moves'
    assert allowlisted(out, _ALLOW) == out, 'idempotent'


def test_a_site_list_rewrites_only_the_named_sites() -> None:
    out = allowlisted(_CADDYFILE, _ALLOW, sites=('gitea.example',))
    gitea, api = out.split('api.example {')
    assert '8.208.22.233/32' in gitea
    assert '8.208.22.233/32' not in api


def test_a_caddyfile_with_no_matcher_or_a_bad_address_is_refused() -> None:
    """PLANTED CONTROLS: nothing to rewrite, a named site that is absent, and a value that is not an address."""
    with pytest.raises(ValueError, match='remote_ip'):
        allowlisted('gitea.example {\n\treverse_proxy 127.0.0.1:3000\n}\n', _ALLOW)
    with pytest.raises(ValueError, match=r'nowhere.example'):
        allowlisted(_CADDYFILE, _ALLOW, sites=('nowhere.example',))
    with pytest.raises(ValueError, match='not an address'):
        allowlisted(_CADDYFILE, ('128.243.0.0/16', 'evil; respond 200'))
    with pytest.raises(ValueError, match='empty'):
        allowlisted(_CADDYFILE, ())


def test_install_rewrites_the_caddyfile_keeps_a_backup_and_names_the_reload(tmp_path: Path) -> None:
    path = tmp_path / 'supervise.toml'
    path.write_text(
        '[ops]\nhome = "/h"\npython = "/opt/ops/bin/python"\nrepos = []\n'
        '[ops.caddy]\nfile = "/etc/caddy/Caddyfile"\nsites = ["gitea.example"]\n'
        'allow = ["128.243.0.0/16", "8.208.22.233/32"]\n',
        encoding='utf-8',
    )
    config = load(path)
    root = tmp_path / 'root'
    live = root / 'etc/caddy/Caddyfile'
    live.parent.mkdir(parents=True)
    live.write_text(_CADDYFILE, encoding='utf-8')
    done = install(config, root)
    assert done.paths['etc/caddy/Caddyfile'] == 'written'
    assert '128.243.0.0/16 8.208.22.233/32' in live.read_text(encoding='utf-8')
    assert (root / 'etc/caddy/Caddyfile.bak-dev-lab').read_text(encoding='utf-8') == _CADDYFILE
    assert 'caddy validate --config /etc/caddy/Caddyfile && systemctl reload caddy' in done.next_steps
    again = install(config, root)
    assert again.paths['etc/caddy/Caddyfile'] == 'unchanged'
    assert not any('caddy' in step for step in again.next_steps), 'nothing changed, nothing to reload'
