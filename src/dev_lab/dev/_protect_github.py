"""GitHub's rendering of a protection :class:`~dev_lab.dev.forgeprotect.Target`: one REPOSITORY RULESET per branch.

A ruleset, not classic protection: it is enforced on administrators unless one is a bypass actor, and it names its
bypass actors -- classic protection's ``enforce_admins`` is one switch for every admin at once. Classic protection
left beside a ruleset is a SECOND, undeclared rule (both apply, the stricter wins), so the plan deletes it.

A RULESET CANNOT NAME A USER. Its bypass actors are a repository role, a GitHub App or a team
(``role:admin|maintain|write``, ``app:<id>``, ``team:<id>``); on a personal repository the role is the only kind, so
the break-glass identity is the role it holds. Every bypass is ``pull_request`` mode: the actor may MERGE a pull
request past the rules -- break-glass merges one -- and may never push past them. Nor can a ruleset name the
approving login: the judge (``[tool.dev_lab.review] judge_login``) is enforced by the merge decision
(:func:`dev_lab.dev.reviewgate.judge_missing`) the required ``tests/merge-ready`` context carries, and the ruleset
counts approvals. The trunk is pushed by the promotion's job token, judged by the required contexts, so a GitHub
forge declares no ``promote`` identity.

Only rulesets named :data:`PREFIX` are this door's; a stray one is deleted, any other is left alone.
"""

from __future__ import annotations

import urllib.parse
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any, Final

from dev_lab.dev._protect_steps import UNREADABLE, Step, absent, created, differences
from dev_lab.dev.forgecontexts import JUDGE_CHECK
from dev_lab.dev.forgefailure import ForgeCallFailed

if TYPE_CHECKING:
    from dev_lab.dev.forgeprotect import Api, Target

__all__ = ['PREFIX', 'actor', 'facts', 'plan', 'ruleset']

#: Every ruleset this door owns is named ``<PREFIX><role>``.
PREFIX: Final = 'dev-lab '

#: GitHub's built-in repository roles, by the ids its rulesets API names them with.
_ROLES: Final = {'admin': 5, 'maintain': 2, 'write': 4}
_KINDS: Final = {'role': 'RepositoryRole', 'app': 'Integration', 'team': 'Team'}


def actor(spec: str) -> dict[str, Any]:
    """The bypass actor *spec* names (``role:admin``, ``app:<id>``, ``team:<id>``), in ``pull_request`` mode."""
    kind, _, value = spec.partition(':')
    if kind == 'role' and value in _ROLES:
        found = _ROLES[value]
    elif kind in {'app', 'team'} and value.isdigit():
        found = int(value)
    else:
        msg = (
            f'GitHub breakglass = {spec!r}: a ruleset bypass is role:<{"|".join(_ROLES)}>, app:<id> or team:<id> '
            '-- never a login, which no ruleset can name'
        )
        raise ValueError(msg)
    return {'actor_id': found, 'actor_type': _KINDS[kind], 'bypass_mode': 'pull_request'}


def ruleset(target: Target) -> dict[str, Any]:
    """The ruleset that makes *target* true. Pure, so ``plan`` can say it before ``apply`` sends it."""
    if target.pushers:
        msg = f'GitHub promote = {list(target.pushers)}: the trunk is pushed by the job token; declare no login'
        raise ValueError(msg)
    rules: list[dict[str, Any]] = [{'type': 'deletion'}, {'type': 'non_fast_forward'}]
    checks = [{'context': context} for context in target.contexts]
    checks += [{'context': JUDGE_CHECK, 'integration_id': target.judge_app}] if target.judge_app else []
    if checks:
        rules.append({'type': 'required_status_checks', 'parameters': {
            'strict_required_status_checks_policy': False, 'do_not_enforce_on_create': False,
            'required_status_checks': checks}})  # fmt: skip
    if target.via_pull_request:
        rules.append({'type': 'pull_request', 'parameters': {
            'required_approving_review_count': target.approvals, 'dismiss_stale_reviews_on_push': True,
            'require_code_owner_review': False, 'require_last_push_approval': False,
            'required_review_thread_resolution': False, 'allowed_merge_methods': ['merge']}})  # fmt: skip
    return {
        'name': f'{PREFIX}{target.role}',
        'target': 'branch',
        'enforcement': 'active',
        'conditions': {'ref_name': {'include': [f'refs/heads/{target.branch}'], 'exclude': []}},
        'bypass_actors': [actor(target.bypass)],
        'rules': rules,
    }


def facts(found: Mapping[str, Any]) -> dict[str, object]:
    """What a ruleset ENFORCES, flattened so a live one and a rendered one compare key by key."""
    rules = {rule['type']: rule.get('parameters', {}) for rule in found.get('rules', ())}
    checks = rules.get('required_status_checks', {}).get('required_status_checks', ())
    review = rules.get('pull_request')
    bypass = found.get('bypass_actors', UNREADABLE)
    return {
        'enforcement': found.get('enforcement', UNREADABLE),
        'branches': sorted(found.get('conditions', {}).get('ref_name', {}).get('include', ())),
        'bypass': bypass if bypass == UNREADABLE else sorted(
            f'{one["actor_type"]}:{one.get("actor_id")}:{one["bypass_mode"]}' for one in bypass),
        'rules': sorted(rules),
        'contexts': sorted(_source(check) for check in checks),
        'approvals': None if review is None else review.get('required_approving_review_count'),
        'dismiss_stale': None if review is None else review.get('dismiss_stale_reviews_on_push'),
        'merge_methods': None if review is None else sorted(review.get('allowed_merge_methods', ())),
    }  # fmt: skip


def _source(check: Mapping[str, Any]) -> str:
    """A required check as ``context``; :data:`JUDGE_CHECK` as ``context@<app id>``, the one App it is required from.

    GitHub answers every check with the ``integration_id`` it bound, Actions' for a bare context: only the judge's
    App is declared, so only it is compared.
    """
    return f'{JUDGE_CHECK}@{check.get("integration_id")}' if check['context'] == JUDGE_CHECK else check['context']


def _classic(api: Api, path: str) -> dict[str, Any] | None:
    try:
        return api.call('GET', path)
    except ForgeCallFailed as failed:
        if absent(failed):
            return None
        raise


def plan(api: Api, wanted: Sequence[Target]) -> list[Step]:
    """Every step that makes the repository's rulesets hold *wanted*, classic protection and strays deleted."""
    listed = api.call('GET', f'{api.repo}/rulesets?includes_parents=false') or []
    live = {one['name']: one['id'] for one in listed if one.get('source_type', 'Repository') == 'Repository'}
    steps = []
    for target in wanted:
        body, where = ruleset(target), f'{target.role} {target.branch}'
        name = body['name']
        if name not in live:
            steps.append(Step(f'{where}: ruleset "{name}" absent -> create', created(facts(body)),
                              lambda body=body: api.call('POST', f'{api.repo}/rulesets', body)))  # fmt: skip
        elif said := differences(facts(api.call('GET', f'{api.repo}/rulesets/{live[name]}')), facts(body)):
            path = f'{api.repo}/rulesets/{live[name]}'
            steps.append(Step(f'{where}: ruleset "{name}" differs -> update', said,
                              lambda path=path, body=body: api.call('PUT', path, body)))  # fmt: skip
        classic_path = f'{api.repo}/branches/{urllib.parse.quote(target.branch, safe="")}/protection'
        if (classic := _classic(api, classic_path)) is not None:
            admins = (classic.get('enforce_admins') or {}).get('enabled')
            contexts = sorted((classic.get('required_status_checks') or {}).get('contexts', ()))
            steps.append(Step(f'{where}: classic branch protection is a second, undeclared rule -> delete',
                              (f'live contexts={contexts} enforce_admins={admins}',),
                              lambda path=classic_path: api.call('DELETE', path)))  # fmt: skip
    ours = {f'{PREFIX}{target.role}' for target in wanted}
    for name, number in sorted(live.items()):
        if name.startswith(PREFIX) and name not in ours:
            path = f'{api.repo}/rulesets/{number}'
            steps.append(Step(f'ruleset "{name}" is declared by no role -> delete', (),
                              lambda path=path: api.call('DELETE', path)))  # fmt: skip
    return steps
