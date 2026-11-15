"""In-memory GitHub and Gitea forges for the protection door and the ops probe: rules, runs and the declaration.

Each fake answers the REST shapes its forge answers -- GitHub's rulesets and classic protection, Gitea's branch
protections (with ``null`` for an empty list, as Gitea writes it), both forges' ``actions/runs`` and ``contents`` --
and records every write, so a test asserts on what the forge was asked to do.
"""

from __future__ import annotations

import base64
import urllib.parse
from dataclasses import dataclass, field
from typing import Any

from dev_lab.dev.forgefailure import ForgeCallFailed
from dev_lab.dev.netverb import Attempt, Diagnosis, Report

#: Integration on ``integrate/main``, trunk ``main``.
INTEGRATOR = '[tool.dev_lab.integrator]\nintegration = "integrate/main"\n'

#: A GitHub repository whose CI workflows post the merge decision and fan parts out per OS.
GITHUB_TEXT = (
    INTEGRATOR + '[tool.dev_lab.ci."ci.yml"]\n'
    '[tool.dev_lab.protection.forges."github.com"]\nbreakglass = "role:admin"\n'
)

#: A Gitea repository served by a host (no workflows), its break-glass and promote identities declared.
GITEA_TEXT = (
    INTEGRATOR + '[tool.dev_lab.protection.forges."gitea.example"]\n'
    'breakglass = "breakglass-bot"\npromote = ["promote-bot"]\n'
)


def refused(status: int, what: str) -> ForgeCallFailed:
    """The failure the client raises for an answered refusal *status*."""
    return ForgeCallFailed(Report(('GET', what), (Attempt(1, status, what, Diagnosis.FORGE_REFUSED),), 1))


@dataclass
class _Fake:
    """What both fakes share: the manifest, the runs and the write log."""

    repo: str
    manifest: dict[str, str] = field(default_factory=dict)
    runs: list[dict[str, Any]] = field(default_factory=list)
    writes: list[tuple[str, str, Any]] = field(default_factory=list)
    #: Set to make every call fail as an unreachable forge would.
    down: bool = False

    def _common(self, method: str, path: str) -> object:
        url = urllib.parse.urlsplit(path)
        query = dict(urllib.parse.parse_qsl(url.query))
        if method == 'GET' and url.path == self.repo:
            return {'default_branch': 'main'}
        if method == 'GET' and url.path == f'{self.repo}/contents/pyproject.toml':
            text = self.manifest.get(query.get('ref', ''))
            if text is None:
                raise refused(404, 'contents')
            return {'content': base64.b64encode(text.encode()).decode()}
        if method == 'GET' and url.path == f'{self.repo}/actions/runs':
            found = [run for run in self.runs if all(run.get(key) == value for key, value in query.items()
                                                      if key in {'event', 'branch', 'status'})]  # fmt: skip
            return {'workflow_runs': sorted(found, key=lambda run: -run['id']), 'total_count': len(found)}
        return NotImplemented

    def call(self, method: str, path: str, body: dict[str, Any] | None = None) -> object:
        """One REST call, as :meth:`dev_lab.dev.forgework.Client.call` makes it."""
        if self.down:
            raise refused(503, 'down')
        if (answer := self._common(method, path)) is not NotImplemented:
            return answer
        if method != 'GET':
            self.writes.append((method, path, body))
        return self.answer(method, path, body)

    def answer(self, method: str, path: str, body: dict[str, Any] | None) -> object:
        raise NotImplementedError


@dataclass
class FakeGitHub(_Fake):
    """GitHub: repository rulesets by id, classic protection by branch."""

    repo: str = '/repos/owner/alpha'
    rulesets: dict[int, dict[str, Any]] = field(default_factory=dict)
    classic: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: Whether the credential may read bypass actors (GitHub omits them for a non-admin).
    admin: bool = True

    def answer(self, method: str, path: str, body: dict[str, Any] | None) -> object:
        url = urllib.parse.urlsplit(path).path
        if url == f'{self.repo}/rulesets':
            if method == 'GET':
                return [
                    {'id': key, 'name': one['name'], 'source_type': 'Repository'} for key, one in self.rulesets.items()
                ]
            key = max(self.rulesets, default=0) + 1
            self.rulesets[key] = self._stored(body)
            return {'id': key}
        if url.startswith(f'{self.repo}/rulesets/'):
            key = int(url.rsplit('/', 1)[1])
            if method == 'GET':
                shown = dict(self.rulesets[key])
                return shown if self.admin else {k: v for k, v in shown.items() if k != 'bypass_actors'}
            if method == 'PUT':
                self.rulesets[key] = self._stored(body)
            else:
                del self.rulesets[key]
            return None
        if url.startswith(f'{self.repo}/branches/'):
            branch = urllib.parse.unquote(url.split('/branches/', 1)[1].removesuffix('/protection'))
            if branch not in self.classic:
                raise refused(404, 'Branch not protected')
            if method == 'DELETE':
                del self.classic[branch]
                return None
            return self.classic[branch]
        raise AssertionError(path)

    @staticmethod
    def _stored(body: dict[str, Any]) -> dict[str, Any]:
        """What GitHub keeps: the body, plus the defaults it adds that no declaration names."""
        stored = {**body, 'source_type': 'Repository', 'current_user_can_bypass': 'never'}
        rules = []
        for rule in body['rules']:
            kept = rule
            if rule['type'] == 'pull_request':
                kept = {**rule, 'parameters': {**rule['parameters'], 'required_reviewers': []}}
            if rule['type'] == 'required_status_checks':
                checks = [{'integration_id': 15368, **one} for one in rule['parameters']['required_status_checks']]
                kept = {**rule, 'parameters': {**rule['parameters'], 'required_status_checks': checks}}
            rules.append(kept)
        return stored | {'rules': rules}


@dataclass
class FakeGitea(_Fake):
    """Gitea: branch protections by rule name, every empty list answered as ``null``."""

    repo: str = '/api/v1/repos/owner/alpha'
    protections: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: Whether the credential is a repository admin: Gitea answers its protections list to an admin alone (403), and
    #: shows a read credential only a branch's protected flag, approvals count and status contexts.
    admin: bool = True

    def answer(self, method: str, path: str, body: dict[str, Any] | None) -> object:
        url = urllib.parse.urlsplit(path).path
        if not self.admin and (method != 'GET' or url == f'{self.repo}/branch_protections'):
            raise ForgeCallFailed(Report((method, url), (Attempt(1, 403, 'admin', Diagnosis.PERMISSION_REFUSED),), 1))
        if method == 'GET' and url.startswith(f'{self.repo}/branches/'):
            name = urllib.parse.unquote(url.split('/branches/', 1)[1])
            one = self.protections.get(name, {})
            return {'name': name, 'protected': name in self.protections,
                    'required_approvals': one.get('required_approvals', 0),
                    'enable_status_check': one.get('enable_status_check', False),
                    'status_check_contexts': one.get('status_check_contexts') or None}  # fmt: skip
        if url == f'{self.repo}/branch_protections':
            if method == 'GET':
                return [self._shown(name, one) for name, one in self.protections.items()]
            self.protections[body['rule_name']] = {k: v for k, v in body.items() if k != 'rule_name'}
            return None
        name = urllib.parse.unquote(url.rsplit('/', 1)[1])
        self.protections[name] = {**self.protections[name], **body}
        return None

    @staticmethod
    def _shown(name: str, one: dict[str, Any]) -> dict[str, Any]:
        return {'rule_name': name, 'branch_name': name, **{k: (v or None) if isinstance(v, list) else v
                                                            for k, v in one.items()}}  # fmt: skip
