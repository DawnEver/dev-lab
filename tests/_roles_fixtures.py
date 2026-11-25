"""Planted roles bindings for tests: the kinds a render would carry (:data:`dev_lab.dev.roles.ROLES_ENV`).

A test's machine file is empty (``conftest``), so no family layer binds anything: every test runs as a job that
carries the kinds below. The default is a CI-tested repo reviewed by a judge host (:data:`CI_REPO`); a test of an
HPC-served repo plants :data:`HPC_REPO` with :func:`carry`. Invented, never our hosts.
"""

from __future__ import annotations

import tomllib
from typing import Any, Final

import pytest

from dev_lab.dev.roles import CI, HOST, HPC, ROLES_ENV, Roles

__all__ = ['CI_REPO', 'EVERY_CI', 'HPC_REPO', 'HPC_REVIEWED', 'carry', 'seats_family']

#: Every role on the forge's CI but review, which a judge host performs.
CI_REPO: Final = Roles.of_kinds(tests=CI, review=HOST, merge=CI, promote=CI, prune=CI)
#: Every role on the forge's CI, its review too.
EVERY_CI: Final = Roles.of_kinds(tests=CI, review=CI, merge=CI, promote=CI, prune=CI)
#: Tests, merge and prune on an HPC executor, review on a judge host, promote on a forge host: no role on CI.
HPC_REPO: Final = Roles.of_kinds(tests=HPC, review=HOST, merge=HPC, promote=HOST, prune=HPC)
#: As :data:`HPC_REPO`, its review on the HPC executor too: the serve tick reviews it.
HPC_REVIEWED: Final = Roles.of_kinds(tests=HPC, review=HPC, merge=HPC, promote=HOST, prune=HPC)


def carry(monkeypatch: pytest.MonkeyPatch, roles: Roles) -> None:
    """Make *roles* the kinds this test's process carries."""
    monkeypatch.setenv(ROLES_ENV, roles.env())


#: A planted family layer (invented names): one cluster, the verification seat ``vera`` its gitea roles bind, and
#: ``rhea``, whose grant role :func:`seats_family` names.
_SEATS_FAMILY: Final = """
[hpc.clusters.alpha]
hosts = ["login.alpha.example"]
slurm_accounts = { free = { billed = false } }

[[hpc.grant]]
user = "vera"
cluster = "alpha"
slurm_account = "free"
role = "verification"

[[hpc.grant]]
user = "rhea"
cluster = "alpha"
slurm_account = "free"
role = "{rhea}"

[roles.gitea]
tests = { hpc = "alpha", role = "verification" }
review = { host = "judgehost" }
merge = { hpc = "alpha", role = "verification" }
promote = { host = "promotehost" }
prune = { hpc = "alpha", role = "verification" }
"""


def seats_family(rhea: str = 'research') -> dict[str, Any]:
    """The planted family layer, ``rhea`` holding a grant of role *rhea* (``research``: no role of a gitea repo)."""
    return tomllib.loads(_SEATS_FAMILY.replace('{rhea}', rhea))
