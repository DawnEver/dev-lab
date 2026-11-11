"""A pre-#311 ``[ops.breakglass]`` is UPGRADED ON READ (FORMATS-UPGRADE-ON-READ), never refused.

forge-a1, 2026-11-08: ``ops upgrade`` self-checks the host's CURRENT config with the NEW code. #311 moved the wave
window, the merge cap and the code lockout out of ``[ops.breakglass]`` into the consent credential and the issuer, so
the new reader refused the host's file and the old reader refused the new one: no order upgraded the host. The shape
below is the host's own (redacted): its TOTP seed is the one the issuer now holds.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dev_lab.ops.config import load
from dev_lab.ops.configupgrade import BREAKGLASS_MOVED

#: The host's values for the keys #311 moved; the keys themselves are named once, by the loader that upgrades them.
_MOVED_VALUES = ('"/etc/breakglass/totp"', '24.0', '20', '5', '15.0')
_MOVED = ''.join(f'{key} = {value}\n' for key, value in zip(BREAKGLASS_MOVED, _MOVED_VALUES, strict=True))

_OLD = """
[ops]
home = "{home}"
python = "/opt/dev-lab/.venv/bin/python"
repos = []
[ops.breakglass]
account = "breakglass"
keys = ["ssh-ed25519 AAAA agent"]
repos = ["https://gitea.example/owner/alpha.git"]
state = "/var/lib/forge-breakglass"
log = "/var/log/forge-breakglass/audit.log"
{moved}wave_hours_max = 24.0
max_merges_max = 100
[ops.breakglass.tokens]
"gitea.example" = "/etc/forge-breakglass/gitea-token"
"""


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / 'supervise.toml'
    path.write_text(text.format(home=(tmp_path / 'home').as_posix(), moved=_MOVED), encoding='utf-8')
    return path


def test_the_pre_consent_breakglass_shape_loads_with_its_issuer_derived(tmp_path: Path) -> None:
    config = load(_write(tmp_path, _OLD), environ={})
    assert config.breakglass is not None
    assert (config.breakglass.wave_hours_max, config.breakglass.max_merges_max) == (24.0, 100)
    assert config.consent is not None
    assert config.consent.totp == '/etc/breakglass/totp'
    assert (config.consent.account, config.consent.key) == ('consent', '/etc/dev-lab/consent/issuer.key')
    assert config.consent.state == '/var/lib/dev-lab-ops/consent'
    assert config.consent.keys == ('ssh-ed25519 AAAA agent',)
    assert (config.consent.lockout_after, config.consent.lockout_minutes) == (5, 15.0)


def test_a_declared_issuer_wins_over_the_derived_one(tmp_path: Path) -> None:
    declared = _OLD + '[ops.consent]\naccount = "issuer"\ntotp = "/x/totp"\nkey = "/x/key"\nstate = "/x/state"\n'
    config = load(_write(tmp_path, declared), environ={})
    assert config.consent is not None
    assert (config.consent.account, config.consent.totp) == ('issuer', '/x/totp')


def test_an_unknown_breakglass_key_is_still_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match='unknown keys'):
        load(_write(tmp_path, _OLD.replace('wave_hours_max', 'wave_hourz_max')), environ={})
