"""Gitea's rendering of a protection :class:`~dev_lab.dev.forgeprotect.Target`: one branch protection per branch.

Every identity is a LOGIN: the break-glass account is the protection's only bypass-allowlist entry; the trunk's push
whitelist is the promote identities and nobody else; the integration branch takes no direct push at all (a pull
request merge only), and the trunk no pull-request merge (its merge whitelist is enabled and empty); the approving
login is the approvals whitelist; ``block_admin_merge_override`` holds an administrator to the same rule.

Rules for branches the declaration does not name are not this door's and are left alone.
"""

from __future__ import annotations

import urllib.parse
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any, Final

from dev_lab.dev._protect_steps import UNREADABLE, Step, created, differences

if TYPE_CHECKING:
    from dev_lab.dev.forgeprotect import Api, Target

__all__ = ['body', 'facts', 'plan']

#: The keys whose value is a list Gitea answers ``null`` for when it is empty.
_LISTS: Final = ('_usernames', '_contexts', '_username')


def body(target: Target) -> dict[str, Any]:
    """The protection that makes *target* true. Pure, so ``plan`` can say it before ``apply`` sends it."""
    if ':' in target.bypass:
        msg = f'Gitea breakglass = {target.bypass!r}: a Gitea bypass allowlist names a login'
        raise ValueError(msg)
    if target.judge_app:
        msg = f'judge_app = {target.judge_app}: a Gitea forge has no GitHub App; declare judge_login'
        raise ValueError(msg)
    pushed = bool(target.pushers)
    return {
        'rule_name': target.branch,
        'enable_push': pushed,
        'enable_push_whitelist': pushed,
        'push_whitelist_usernames': sorted(target.pushers),
        'enable_force_push': False,
        'enable_merge_whitelist': not target.via_pull_request,
        'merge_whitelist_usernames': [],
        'enable_status_check': bool(target.contexts),
        'status_check_contexts': sorted(target.contexts),
        'required_approvals': target.approvals,
        'enable_approvals_whitelist': bool(target.approvals),
        'approvals_whitelist_username': [target.approver] if target.approvals else [],
        'dismiss_stale_approvals': True,
        'block_on_rejected_reviews': True,
        'enable_bypass_allowlist': True,
        'bypass_allowlist_usernames': [target.bypass],
        'block_admin_merge_override': True,
    }


def facts(found: Mapping[str, Any], keys: Sequence[str]) -> dict[str, object]:
    """*found*'s value of each of *keys*: a list sorted, Gitea's ``null`` for an empty list read as one."""
    out: dict[str, object] = {}
    for key in keys:
        value = found.get(key, UNREADABLE)
        listed = isinstance(value, list) or (value is None and key.endswith(_LISTS))
        out[key] = sorted(value or ()) if listed else value
    return out


def plan(api: Api, wanted: Sequence[Target]) -> list[Step]:
    """Every step that makes the repository's branch protections hold *wanted*."""
    listed = api.call('GET', f'{api.repo}/branch_protections') or []
    live = {one.get('rule_name') or one.get('branch_name'): one for one in listed}
    steps = []
    for target in wanted:
        rendered, where = body(target), f'{target.role} {target.branch}'
        keys = [key for key in rendered if key != 'rule_name']
        declared = facts(rendered, keys)
        if target.branch not in live:
            steps.append(
                Step(
                    f'{where}: branch protection absent -> create',
                    created(declared),
                    lambda rendered=rendered: api.call('POST', f'{api.repo}/branch_protections', rendered),
                )
            )
        elif said := differences(facts(live[target.branch], keys), declared):
            path = f'{api.repo}/branch_protections/{urllib.parse.quote(target.branch, safe="")}'
            patch = {key: rendered[key] for key in keys}
            steps.append(Step(f'{where}: branch protection differs -> update', said,
                              lambda path=path, patch=patch: api.call('PATCH', path, patch)))  # fmt: skip
    return steps
