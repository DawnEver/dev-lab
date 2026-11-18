"""Planted roles bindings for tests: the kinds a render would carry (:data:`dev_lab.dev.roles.ROLES_ENV`).

A test's machine file is empty (``conftest``), so no family layer binds anything: every test runs as a job that
carries the kinds below. The default is a CI-tested repo reviewed by a judge host (:data:`CI_REPO`); a test of an
HPC-served repo plants :data:`HPC_REPO` with :func:`carry`. Invented, never our hosts.
"""

from __future__ import annotations

from typing import Final

import pytest

from dev_lab.dev.roles import CI, HOST, HPC, ROLES_ENV, Roles

__all__ = ['CI_REPO', 'EVERY_CI', 'HPC_REPO', 'carry']

#: Every role on the forge's CI but review, which a judge host performs.
CI_REPO: Final = Roles.of_kinds(tests=CI, review=HOST, merge=CI, promote=CI, prune=CI)
#: Every role on the forge's CI, its review too.
EVERY_CI: Final = Roles.of_kinds(tests=CI, review=CI, merge=CI, promote=CI, prune=CI)
#: Tests, merge and prune on an HPC executor, review on a judge host, promote on a forge host: no role on CI.
HPC_REPO: Final = Roles.of_kinds(tests=HPC, review=HOST, merge=HPC, promote=HOST, prune=HPC)


def carry(monkeypatch: pytest.MonkeyPatch, roles: Roles) -> None:
    """Make *roles* the kinds this test's process carries."""
    monkeypatch.setenv(ROLES_ENV, roles.env())
