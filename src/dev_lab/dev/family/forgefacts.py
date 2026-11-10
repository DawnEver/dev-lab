"""One member's :class:`~dev_lab.dev.family.members.Facts`, read from its forge through the family client.

Read only: Pull Requests on (:func:`~dev_lab.dev.famtests.onboarding.assert_the_forge_takes_pull_requests`), each
branch by ``GET <repo>/branches/<name>``, protection as :mod:`dev_lab.dev.forgeprotect` plans it from the manifest
``origin/<integration>`` holds, the Actions secrets by NAME (``GET <repo>/actions/secrets``: Gitea answers a list,
GitHub ``{"secrets": [...]}``; no value is ever returned by either), and the open PRs' ``created_at``. A read the
forge refuses is named in ``unread``.
"""

from __future__ import annotations

import urllib.parse
from datetime import datetime

from dev_lab.dev import forgeprotect
from dev_lab.dev._forgebackends import GITHUB, backend_for
from dev_lab.dev.family.members import Facts
from dev_lab.dev.family.origin import Snapshot
from dev_lab.dev.famtests.onboarding import OnboardingViolation, assert_the_forge_takes_pull_requests
from dev_lab.dev.forgefailure import ForgeCallFailed
from dev_lab.dev.forgeprotect import INTEGRATION, TRUNK
from dev_lab.dev.forgework import Client

__all__ = ['ClientFacts', 'contexts_of', 'secret_names']


def secret_names(answer: object) -> frozenset[str]:
    """The secret names of an Actions-secrets answer of either forge."""
    rows = answer.get('secrets', []) if isinstance(answer, dict) else answer if isinstance(answer, list) else []
    return frozenset(str(row.get('name', '')) for row in rows if isinstance(row, dict))


def contexts_of(answer: object, branch: str) -> tuple[str, ...]:
    """The required contexts a protection answer holds for *branch*: GitHub's one rule, or Gitea's list of rules."""
    if isinstance(answer, dict):
        checks = answer.get('required_status_checks') or {}
        return tuple(sorted(checks.get('contexts', ()))) if isinstance(checks, dict) else ()
    rows = [r for r in answer or () if isinstance(r, dict) and branch in {r.get('rule_name'), r.get('branch_name')}]
    return tuple(sorted(c for r in rows for c in r.get('status_check_contexts') or ()))


class ClientFacts:
    """:class:`~dev_lab.dev.family.members.ForgeFacts` over one member's :class:`~dev_lab.dev.forgework.Client`."""

    def __init__(self, client: Client) -> None:
        """Read through *client*."""
        self.client = client
        self.unread: list[str] = []

    def _get(self, path: str, what: str) -> object:
        """One read; a refusal is named in ``unread`` and reads as ``None``."""
        try:
            return self.client.call('GET', f'{self.client.repo}{path}')
        except ForgeCallFailed as why:
            self.unread.append(f'{what} ({why})'.splitlines()[0])
            return None

    def _exists(self, branch: str) -> bool:
        try:
            self.client.call('GET', f'{self.client.repo}/branches/{urllib.parse.quote(branch, safe="")}')
        except ForgeCallFailed:
            return False
        return True

    def _drift(self, held: Snapshot) -> tuple[str, ...]:
        client = self.client
        try:
            wanted = forgeprotect.targets(held.manifest, f'{held.rev}:pyproject.toml', client.forge)
            return tuple(forgeprotect.render(forgeprotect.plan(client, client.forge, wanted)))
        except (ValueError, ForgeCallFailed) as why:
            return (str(why).splitlines()[0],)

    def _contexts(self, roles: dict[str, str]) -> dict[str, tuple[str, ...]]:
        if backend_for(self.client.forge) is GITHUB:
            found = {}
            for role, branch in roles.items():
                try:
                    answer = self.client.call('GET', f'{self.client.repo}/branches/{branch}/protection')
                except ForgeCallFailed:
                    answer = {}  # unprotected: no rule, no context
                found[role] = contexts_of(answer, branch)
            return found
        rules = self._get('/branch_protections', 'protection')
        return {role: contexts_of(rules if isinstance(rules, list) else [], branch) for role, branch in roles.items()}

    def facts(self, held: Snapshot, trunk: str, integration: str) -> Facts:
        """The member's forge facts; see the module docstring."""
        try:
            assert_the_forge_takes_pull_requests(self.client)
            pulls = True
        except OnboardingViolation:
            pulls = False
        missing = tuple(branch for branch in (trunk, integration) if not self._exists(branch))
        secrets = self._get('/actions/secrets', 'secrets')
        opened = self._get('/pulls?state=open', 'pulls')
        ages = [(int(p['number']), datetime.fromisoformat(str(p['created_at']))) for p in opened or ()]
        contexts = self._contexts({INTEGRATION: integration, TRUNK: trunk})
        return Facts(pulls, missing, self._drift(held), secret_names(secrets),
                     min(ages, key=lambda pair: pair[1]) if ages else None, tuple(self.unread), contexts,
                     self.client.forge.host)  # fmt: skip
