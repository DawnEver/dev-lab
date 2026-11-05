"""THE FORGE PROBE: per declared repository, on either forge, protection drift and a failed CI run -- alerted once.

Parity gap 7 (2026-11-04): a failed scheduled run on either forge alerted nobody (dev-lab's nightly CI had failed
that morning), and nothing compared a forge's branch rules to anything. A timer (``[ops.probe] schedule``) runs
``python -m dev_lab.ops --config <toml> probe``; for each repository in ``[ops.probe] repos``, as that forge's probe
identity (``[ops.probe.tokens]``, one read-only token per forge host):

* PROTECTION: the repository's declaration at its integration branch -- as the forge holds it, never a clone --
  rendered by :func:`dev_lab.dev.forgeprotect.plan`; any difference is drift (``forge protect check``'s reading);
* CI RUNS: the latest completed run of each workflow among the ``schedule`` runs and the ``push`` runs of the
  integration branch; a ``failure``, ``timed_out`` or ``startup_failure`` is a failed run;
* a repository the probe cannot read is a finding too: a probe that cannot see is not a clean one.

ONE ALERT PER NEW FINDING, through the configuration's ``[alerts]``. ``<state>/probe.json`` keeps each standing
finding's key and mark: a finding alerts when its key is new or its mark moved (a different drift; a workflow
failing again after a pass), never again while it stands, and its key is dropped when it clears -- so a nightly
that keeps failing alerts once, and fails anew after a green night. A finding whose alert no channel delivered is
not recorded, so the next tick sends it again.

The probe identity only READS: GitHub needs ``Administration: read`` (a ruleset's bypass actors and classic
protection are admin reads); Gitea an administrator's token scoped ``read:repository``. ``apply`` stays an
administrator's verb, never this role's.
"""

from __future__ import annotations

import hashlib
import json
import urllib.parse
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from dev_lab.dev import forgeprotect
from dev_lab.dev._forgebackends import backend_for
from dev_lab.dev.forge import Forge, forge_of_url
from dev_lab.dev.forgefailure import ForgeCallFailed
from dev_lab.dev.lanepolicy import policy_from
from dev_lab.dev.reviewgate import DeclarationUnread, manifest_at
from dev_lab.ops.config import OpsConfig
from dev_lab.ops.statelock import exclusive

__all__ = ['FAILED', 'Finding', 'findings', 'run']

#: The run conclusions that are a failure on both forges.
FAILED: Final = frozenset({'failure', 'timed_out', 'startup_failure'})

#: How many of the newest completed runs per query are read for each workflow's latest.
_PAGE: Final = 50

_STATE: Final = 'probe.json'


@dataclass(frozen=True)
class Finding:
    """One standing problem: its dedup ``key``, the ``mark`` that makes it new, and what the alert says."""

    key: str
    mark: str
    title: str
    detail: str


def _fingerprint(lines: Iterable[str]) -> str:
    return hashlib.sha256('\n'.join(lines).encode()).hexdigest()[:16]


def _declaration(api: forgeprotect.Api) -> tuple[str, str]:
    """The integration branch and the pyproject text the forge holds there (read from the default branch first)."""
    default = str(api.call('GET', api.repo)['default_branch'])
    integration = policy_from(manifest_at(api, default), f'{default}:pyproject.toml').integration
    return integration, manifest_at(api, integration)


def _runs(api: forgeprotect.Api, forge: Forge, integration: str) -> list[Finding]:
    """A finding per workflow whose latest completed scheduled or integration-push run failed."""
    page = f'{backend_for(forge).page_param}={_PAGE}'
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    branch = urllib.parse.quote(integration, safe='')
    for query in ('event=schedule&status=completed', f'event=push&branch={branch}&status=completed'):
        answer = api.call('GET', f'{api.repo}/actions/runs?{query}&{page}') or {}
        for found in sorted(answer.get('workflow_runs', ()), key=lambda one: -int(one['id'])):
            latest.setdefault((str(found['event']), str(found.get('path') or found.get('name'))), found)
    return [
        Finding(f'{forge.identity}|run|{event}|{workflow}', 'failed', f'CI {event} run FAILED: {forge.identity}',
                f'{workflow} run {found["id"]} at {str(found.get("head_sha", ""))[:12]} concluded '
                f'{found["conclusion"]}: {found.get("html_url", "")}')
        for (event, workflow), found in sorted(latest.items()) if found.get('conclusion') in FAILED
    ]  # fmt: skip


def findings(url: str, api: forgeprotect.Api) -> list[Finding]:
    """Every standing finding of the repository at *url*, read through *api*."""
    forge = forge_of_url(url)
    try:
        integration, text = _declaration(api)
        wanted = forgeprotect.targets(text, f'{integration}:pyproject.toml', forge)
        steps = forgeprotect.plan(api, forge, wanted)
        out = _runs(api, forge, integration)
    except (ForgeCallFailed, DeclarationUnread, ValueError, KeyError, TypeError) as unread:
        said = f'{type(unread).__name__}: {unread}'
        return [Finding(f'{forge.identity}|unread', 'unread', f'probe cannot read {forge.identity}', said)]
    if steps:
        lines = forgeprotect.render(steps)
        title = f'protection drift: {forge.identity} (run `forge protect apply` as an administrator)'
        out.insert(0, Finding(f'{forge.identity}|protection', _fingerprint(lines), title, '\n'.join(lines)))
    return out


def _load(path: Path) -> dict[str, str]:
    try:
        return dict(json.loads(path.read_text(encoding='utf-8')))
    except FileNotFoundError:
        return {}


def _save(path: Path, state: dict[str, str]) -> None:
    partial = path.with_suffix('.partial')
    partial.write_text(json.dumps(state, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    partial.replace(path)


def run(config: OpsConfig, api_for: Callable[[str], forgeprotect.Api], alert: Callable[[str, str], bool]) -> list[str]:
    """Probe every declared repository; alert each NEW finding once (see the module docstring); the lines said."""
    role = config.probe
    if role is None:
        msg = f'{config.path} enables no [ops.probe]'
        raise ValueError(msg)
    state_dir = Path(role.state)
    with exclusive(state_dir):
        before = _load(state_dir / _STATE)
        after: dict[str, str] = {}
        said = []
        for url in role.repos:
            for found in findings(url, api_for(url)):
                if before.get(found.key) == found.mark:
                    after[found.key] = found.mark
                    continue
                delivered = alert(found.title, found.detail)
                said.append(f'{"alerted" if delivered else "UNDELIVERED"} {found.key}')
                if delivered:
                    after[found.key] = found.mark
                elif found.key in before:  # the old mark stands, so the new one is sent again next tick
                    after[found.key] = before[found.key]
        said += [f'cleared {key}' for key in sorted(set(before) - set(after))]
        _save(state_dir / _STATE, after)
    return said
