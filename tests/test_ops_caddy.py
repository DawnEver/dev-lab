"""``[ops.caddy]``: the forge's Caddy allowlist is configuration, rewritten by the install door (2026-11-09).

The user ruling: the Aliyun Actions test host and the Cirrus research account reach Gitea, which the campus-only
allowlist refused with 403. Before this, the allowlist was a hand-edited Caddyfile line that only root could change,
and after the lockdown nobody holds root -- so the allowlist moves through the ops door like every other knob.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from dev_lab.ops.caddy import allowlisted
from dev_lab.ops.config import load
from dev_lab.ops.install import install

_CADDYFILE = """gitea.example {
\t@campus remote_ip 198.51.100.0/24
\thandle @campus {
\t\treverse_proxy 127.0.0.1:3000
\t}
\trespond "Forbidden (campus-only)" 403
}
api.example {
\t@campus remote_ip 198.51.100.0/24
\trespond "Forbidden (campus-only)" 403
}
"""

_ALLOW = ('198.51.100.0/24', '203.0.113.7/32', '203.0.113.9/32')


def test_every_remote_ip_matcher_takes_the_declared_list() -> None:
    out = allowlisted(_CADDYFILE, _ALLOW)
    assert out.count('\t@campus remote_ip 198.51.100.0/24 203.0.113.7/32 203.0.113.9/32\n') == 2
    assert out.replace(' 203.0.113.7/32 203.0.113.9/32', '') == _CADDYFILE, 'nothing else moves'
    assert allowlisted(out, _ALLOW) == out, 'idempotent'


def test_a_site_list_rewrites_only_the_named_sites() -> None:
    out = allowlisted(_CADDYFILE, _ALLOW, sites=('gitea.example',))
    gitea, api = out.split('api.example {')
    assert '203.0.113.7/32' in gitea
    assert '203.0.113.7/32' not in api


def test_a_caddyfile_with_no_matcher_or_a_bad_address_is_refused() -> None:
    """PLANTED CONTROLS: nothing to rewrite, a named site that is absent, and a value that is not an address."""
    with pytest.raises(ValueError, match='remote_ip'):
        allowlisted('gitea.example {\n\treverse_proxy 127.0.0.1:3000\n}\n', _ALLOW)
    with pytest.raises(ValueError, match=r'nowhere.example'):
        allowlisted(_CADDYFILE, _ALLOW, sites=('nowhere.example',))
    with pytest.raises(ValueError, match='not an address'):
        allowlisted(_CADDYFILE, ('198.51.100.0/24', 'evil; respond 200'))
    with pytest.raises(ValueError, match='empty'):
        allowlisted(_CADDYFILE, ())


def test_install_rewrites_the_caddyfile_keeps_a_backup_and_names_the_reload(tmp_path: Path) -> None:
    path = tmp_path / 'supervise.toml'
    path.write_text(
        '[ops]\nhome = "/h"\npython = "/opt/ops/bin/python"\nrepos = []\n'
        '[ops.caddy]\nfile = "/etc/caddy/Caddyfile"\nsites = ["gitea.example"]\n'
        'allow = ["198.51.100.0/24", "203.0.113.7/32"]\n',
        encoding='utf-8',
    )
    config = load(path)
    root = tmp_path / 'root'
    live = root / 'etc/caddy/Caddyfile'
    live.parent.mkdir(parents=True)
    live.write_text(_CADDYFILE, encoding='utf-8')
    done = install(config, root)
    assert done.paths['etc/caddy/Caddyfile'] == 'written'
    assert '198.51.100.0/24 203.0.113.7/32' in live.read_text(encoding='utf-8')
    assert (root / 'etc/caddy/Caddyfile.bak-dev-lab').read_text(encoding='utf-8') == _CADDYFILE
    reload = [step for step in done.next_steps if 'systemctl reload caddy' in step]
    step = (
        'caddy validate --config /etc/caddy/Caddyfile && systemctl reload caddy && '
        'sha256sum /etc/caddy/Caddyfile > /etc/caddy/Caddyfile.reloaded-sha256'
    )
    assert reload == [step]
    # PLANTED CONTROL (forge-a1, 2026-11-10): the file is already right but the reload never ran -- the running
    # Caddy still served the old allowlist. An unchanged file is NOT a live config; install names the reload again.
    again = install(config, root)
    assert again.paths['etc/caddy/Caddyfile'] == 'unchanged'
    assert again.next_steps.count(reload[0]) == 1, 'the file is unchanged but no reload was stamped'
    # the reload ran (its stamp records the digest it loaded): only now does install have nothing to reload
    stamp = root / 'etc/caddy/Caddyfile.reloaded-sha256'
    stamp.write_text(f'{hashlib.sha256(live.read_bytes()).hexdigest()}  /etc/caddy/Caddyfile\n', encoding='utf-8')
    settled = install(config, root)
    assert not any('caddy' in step for step in settled.next_steps), 'the live config is the file, nothing to reload'
    # a later hand edit (or `config apply`) that did not reload: the stamp no longer matches, install reloads
    live.write_text(live.read_text(encoding='utf-8') + '# edited\n', encoding='utf-8')
    drifted = install(config, root)
    assert reload[0] in drifted.next_steps
