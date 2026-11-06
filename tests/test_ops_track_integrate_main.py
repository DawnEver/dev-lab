"""Every host installs and releases from ``integrate/main`` (user ruling 2026-11-06): nothing waits for ``main``."""

from __future__ import annotations

import inspect

from dev_lab.ops.config import INTEGRATION_REF, Upgrade
from dev_lab.supervise.deploy import fetch


def test_an_upgrade_takes_the_integration_tip_by_default() -> None:
    assert INTEGRATION_REF == 'integrate/main'
    assert Upgrade(source='https://example.invalid/dev-lab.git').ref == INTEGRATION_REF


def test_a_release_is_fetched_from_the_integration_branch_by_default() -> None:
    assert inspect.signature(fetch).parameters['branch'].default == INTEGRATION_REF


def test_a_declared_ref_is_still_honoured() -> None:
    """PLANTED CONTROL: a host that names another ref gets it."""
    assert Upgrade(source='https://example.invalid/dev-lab.git', ref='release').ref == 'release'
