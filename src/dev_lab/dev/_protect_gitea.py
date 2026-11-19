"""Gitea's rendering of a protection :class:`~dev_lab.dev.forgeprotect.Target`: one branch protection per branch.

Every identity is a LOGIN: the break-glass account is the protection's only bypass-allowlist entry; the trunk's push
whitelist is the promote identities and nobody else; the integration branch takes no direct push at all (a pull
request merge only), and the trunk no pull-request merge (its merge whitelist is enabled and empty); the approving
login is the approvals whitelist. A review only ADVISES, so a rejected review never blocks a merge, and an
administrator may still merge by hand to rescue a stuck branch (user rulings 2026-11-11, 2026-11-13).

Rules for branches the declaration does not name are not this door's and are left alone.

Gitea lists a repository's protections to a repository ADMIN alone (403 otherwise). A read credential still sees, per
branch (``GET /branches/{b}``), whether it is protected, its approvals count and its status contexts
(:data:`READABLE`): ``plan`` then compares those and says every other fact unanswered -- so a reader is never told
"as declared" -- and every step's write refuses, naming the forge host's consent-gated door that applies it.
"""

from __future__ import annotations

import urllib.parse
from collections.abc import Callable, Mapping, Sequence
from typing import TYPE_CHECKING, Any, Final

from dev_lab.dev._protect_steps import UNREADABLE, Step, created, differences
from dev_lab.dev.forgefailure import ForgeCallFailed

if TYPE_CHECKING:
    from dev_lab.dev.forgeprotect import Api, Target

__all__ = ['READABLE', 'READ_IN_PART', 'body', 'facts', 'plan']

#: The keys whose value is a list Gitea answers ``null`` for when it is empty.
_LISTS: Final = ('_usernames', '_contexts', '_username')
#: What Gitea shows a READ credential of a branch's protection; every other fact is the repository admin's to read.
READABLE: Final = ('enable_status_check', 'status_check_contexts', 'required_approvals')
#: Said in every step a read credential's plan holds.
READ_IN_PART: Final = 'read without a repository admin'


def body(target: Target) -> dict[str, Any]:
    """The protection that makes *target* true. Pure, so ``plan`` can say it before ``apply`` sends it."""
    if len(target.bypass) != 1:
        msg = f'Gitea breakglass = {list(target.bypass)!r}: a Gitea forge names one login, its one bypass identity'
        raise ValueError(msg)
    (login,) = target.bypass
    if ':' in login:
        msg = f'Gitea breakglass = {login!r}: a Gitea bypass allowlist names a login'
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
        'block_on_rejected_reviews': False,  # a review advises; it never gates (user ruling 2026-11-11)
        'enable_bypass_allowlist': True,
        'bypass_allowlist_usernames': [login],
        'block_admin_merge_override': False,  # the admin keeps a hand rescue (user ruling 2026-11-13)
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
    try:
        listed = api.call('GET', f'{api.repo}/branch_protections') or []
    except ForgeCallFailed as failed:
        if not failed.permission:  # the account lacks the admin grant; anything else is no answer at all
            raise
        return _read_in_part(api, wanted)
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


def _read_in_part(api: Api, wanted: Sequence[Target]) -> list[Step]:
    """:func:`plan` for a read credential: :data:`READABLE` compared, the rest unanswered; no step writes."""
    repo = api.repo.rsplit('/repos/', 1)[-1]
    steps = []
    for target in wanted:
        rendered, where = body(target), f'{target.role} {target.branch}'
        declared = facts(rendered, [key for key in rendered if key != 'rule_name'])
        found = api.call('GET', f'{api.repo}/branches/{urllib.parse.quote(target.branch, safe="")}') or {}
        refuse = _host_applies(repo)
        if not found.get('protected'):
            steps.append(Step(f'{where}: branch protection absent ({READ_IN_PART})', created(declared), refuse))
        elif said := differences(facts(found, READABLE), declared):
            subject = f'{where}: branch protection {READ_IN_PART}: {len(declared) - len(READABLE)} fact(s) unanswered'
            steps.append(Step(subject, said, refuse))
    return steps


def _host_applies(repo: str) -> Callable[[], object]:
    def refuse() -> object:
        msg = (
            f'{repo}: writing branch protection needs a repository admin, and this credential is not one; the forge '
            f'host applies the declaration: python -m dev_lab.ops --config <supervise.toml> forge protect apply '
            f'--repo {repo} --ref <sha> (a single-use ops.forge.protect consent)'
        )
        raise PermissionError(msg)

    return refuse
