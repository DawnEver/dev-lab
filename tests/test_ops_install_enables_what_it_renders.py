"""An install run as root on the live host enables the units it rendered (issue #557).

Account, package and sshd steps stay the operator's; a follow timer rendered but left disabled died at reboot.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, cast

from dev_lab.ops import enableunits, hostverbs
from dev_lab.ops.install import Rendered

if TYPE_CHECKING:
    from dev_lab.ops.config import OpsConfig

STEPS = (
    'id dev-lab || useradd --system dev-lab',
    'systemctl daemon-reload',
    'systemctl enable --now dev-lab-ops-upgrade-follow.timer',
    'apt-get install -y libpam-oath',
    'sshd -t && systemctl reload ssh',
    'systemctl daemon-reload',
    'systemctl enable --now dev-lab-supervise.service',
)


def test_the_rendered_units_are_enabled_and_the_rest_is_left_to_the_operator() -> None:
    units, rest = enableunits.split(STEPS)
    assert units == ('dev-lab-ops-upgrade-follow.timer', 'dev-lab-supervise.service')
    # the planted control: account, package and auth-surface steps are never run by install
    assert rest == (
        'id dev-lab || useradd --system dev-lab',
        'apt-get install -y libpam-oath',
        'sshd -t && systemctl reload ssh',
    )


def test_enabling_reloads_once_then_enables_each_unit() -> None:
    ran: list[list[str]] = []
    failed = enableunits.enable(('a.timer', 'b.service'), run=lambda argv: ran.append(argv) or 0)
    assert failed == ()
    assert ran == [['systemctl', 'daemon-reload'],
                   ['systemctl', 'enable', '--now', 'a.timer'],
                   ['systemctl', 'enable', '--now', 'b.service']]  # fmt: skip


def test_a_unit_that_does_not_enable_is_named_not_swallowed() -> None:
    failed = enableunits.enable(('a.timer', 'b.service'), run=lambda argv: 1 if 'b.service' in argv else 0)
    assert failed == ('b.service',)


def _as_root_install(monkeypatch, root: Path) -> list[tuple[str, ...]]:
    enabled: list[tuple[str, ...]] = []
    monkeypatch.setattr(hostverbs.sys, 'platform', 'linux')
    monkeypatch.setattr(hostverbs.os, 'geteuid', lambda: 0, raising=False)
    monkeypatch.setattr(hostverbs.install, 'install', lambda *_a, **_k: Rendered({}, STEPS))
    monkeypatch.setattr(hostverbs.enableunits, 'enable', lambda units: enabled.append(tuple(units)) or ())
    assert hostverbs.install_verb(cast('OpsConfig', None), root) == 0
    return enabled


def test_install_as_root_on_the_live_host_enables_its_units(monkeypatch) -> None:
    assert _as_root_install(monkeypatch, Path('/')) == [
        ('dev-lab-ops-upgrade-follow.timer', 'dev-lab-supervise.service')
    ]


def test_install_into_a_staging_root_enables_nothing(monkeypatch, tmp_path: Path) -> None:
    assert _as_root_install(monkeypatch, tmp_path) == []
