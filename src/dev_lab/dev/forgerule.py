"""FORGE-BRANCH-PROTECTION: what the git host enforces on a branch, measured against a DECLARATION.

WHY A MECHANISM AND NOT A PAGE. The rule every repo in this family believes it has -- ``main`` takes
no direct push from an unnamed account, and no force-push ever -- lived as clicks in a web UI and a
paragraph describing them. Prose cannot fire: MEASURED 2026-08-27 on one forge, the rule everyone
believed was applied was NOT, and nobody could have noticed by reading the page. A second machine
joining the same forge needs the same settings, and a checklist re-typed by hand is how two machines
end up differently protected.

WHAT IS FAMILY AND WHAT IS ONE REPO'S ANSWER, and the split is the whole point of this module. The
API shape, the credential route, the clause vocabulary and -- the part that was paid for -- the
distinction between a rule that is UNAPPLIED and one that is INERT are true of every repo on a
Gitea-shaped forge. WHICH BRANCH, WHICH ACCOUNTS, whether force-push is permitted and which status
contexts are required are facts about ONE repository, so they arrive together in :class:`Protection`
and **every field of it is required**. A default here would judge every other repo against one
repo's trunk name and one repo's account list, and report the result as if it had been asked.

THE DECLARATION IS A TARGET, AND DRIFT IN EITHER DIRECTION IS DRIFT. :func:`assess` compares the live
rule to the declaration rather than to a floor, so a forge that is STRICTER than the declaration is
reported too. A repo that wants the stricter setting says so in its declaration; a difference nobody
declared is a difference nobody decided.

AN EMPTY ACCOUNT LIST IS REFUSED AT DECLARATION, and :meth:`Protection.__post_init__` says why: the
empty set is a subset of every whitelist, so a target naming nobody is met by every rule on every
forge -- the vacuous green in its arithmetic form.

AN ABSENT KEY IS NOT A FALSE AND AN INERT LIST IS NOT AN UNAPPLIED ONE. :data:`UNREADABLE` and
:data:`INERT` are their own standings because their REMEDIES differ, and each constant carries its
own measurement; a report that collapses either into ``NOT_APPLIED`` sends a reader to the wrong one.

A STATUS CONTEXT IS REPORTED AND, WHEN DECLARED EMPTY, NEVER WRITTEN -- ``status_contexts=()`` is a
declared absence :func:`protection_body` honours, because a branch protected against a status nobody
publishes is indistinguishable from a broken gate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from dev_lab.dev.forge import Forge, Transport, call, forge_transport

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    'APPLIED',
    'INERT',
    'NOT_APPLIED',
    'UNREADABLE',
    'Clause',
    'Protection',
    'apply_protection',
    'assess',
    'protection_body',
    'read_rule',
]

#: The clause matches the declaration.
APPLIED = 'applied'

#: The clause does not match the declaration, and the forge answered the question.
NOT_APPLIED = 'not applied'

#: The clause's DATA is right and the switch that enforces it is off. Its own standing because its
#: remedy is one flag, where ``NOT_APPLIED`` may need the whole rule rewritten -- and because the
#: state reads as success to anyone checking the data and not the switch, which is the 2026-08-27
#: miss exactly.
INERT = 'inert'

#: The forge did not answer this question. NEVER folded into ``NOT_APPLIED``: a missing key is a fact
#: about the forge's API, and re-applying a rule is the wrong remedy for it.
UNREADABLE = 'unreadable'


@dataclass(frozen=True)
class Protection:
    """ONE REPOSITORY'S TARGET STATE for one branch. Every field is required; see the module docstring.

    Attributes:
        branch: the branch the rule is about -- a repo's trunk name, never guessed.
        push_accounts: who may push it directly. At least one, and the floor is why.
        allow_force_push: whether the forge should permit rewriting it.
        status_contexts: required checks. ``()`` is a DECLARED absence and writes nothing.

    """

    branch: str
    push_accounts: tuple[str, ...]
    allow_force_push: bool
    status_contexts: tuple[str, ...] = field()

    def __post_init__(self) -> None:
        """Refuse a declaration that cannot mean anything, at the moment it is written."""
        if not self.branch.strip():
            msg = 'a protection names the branch it is about; the empty string is a branch no forge holds'
            raise ValueError(msg)
        if not self.push_accounts:
            msg = (
                'a push whitelist must name at least one account: the empty set is a subset of every '
                'whitelist, so a target naming nobody is met by every rule on every forge'
            )
            raise ValueError(msg)


@dataclass(frozen=True)
class Clause:
    """One question asked of the live rule, its standing, and what a reader needs to act."""

    name: str
    standing: str
    detail: str


def _read(rule: Mapping[str, Any], key: str) -> object:
    """The forge's answer, or :data:`UNREADABLE` when it did not give one."""
    return rule.get(key, UNREADABLE)


def _clause(name: str, *, live: object, wanted: object, detail: str) -> Clause:
    """One comparison, with the unreadable case kept out of the equality."""
    if live is UNREADABLE:
        return Clause(name, UNREADABLE, f'the forge did not answer {detail}')
    standing = APPLIED if live == wanted else NOT_APPLIED
    return Clause(name, standing, f'{detail}: live={live!r} declared={wanted!r}')


def assess(rule: Mapping[str, Any] | None, target: Protection) -> tuple[Clause, ...]:
    """Every clause of *target*, against the live *rule*; ``None`` means no rule exists at all."""
    if rule is None:
        detail = f'no protection rule for `{target.branch}` exists: any account may push anything'
        return tuple(Clause(name, NOT_APPLIED, detail) for name in ('push_whitelist', 'force_push', 'status_checks'))
    return (
        _push_clause(rule, target),
        _clause(
            'force_push',
            live=_read(rule, 'enable_force_push'),
            wanted=target.allow_force_push,
            detail='whether the branch may be rewritten',
        ),
        _status_clause(rule, target),
    )


def _push_clause(rule: Mapping[str, Any], target: Protection) -> Clause:
    """Who may push, and whether the switch that enforces the list is on."""
    enabled, switch = _read(rule, 'enable_push'), _read(rule, 'enable_push_whitelist')
    listed = _read(rule, 'push_whitelist_usernames')
    if UNREADABLE in (enabled, switch, listed):
        return Clause('push_whitelist', UNREADABLE, 'the forge did not answer the push whitelist clause')
    named = set(target.push_accounts) <= set(listed or ())
    if named and not switch:
        return Clause(
            'push_whitelist',
            INERT,
            'the whitelist names the declared accounts and enable_push_whitelist is off, so it is '
            'decorative: anyone with write access may push',
        )
    if enabled and switch and named:
        return Clause('push_whitelist', APPLIED, f'push restricted to {sorted(target.push_accounts)}')
    return Clause(
        'push_whitelist',
        NOT_APPLIED,
        f'declared {sorted(target.push_accounts)}, live enable_push={enabled!r} '
        f'enable_push_whitelist={switch!r} whitelist={sorted(listed or ())}',
    )


def _status_clause(rule: Mapping[str, Any], target: Protection) -> Clause:
    """Required status checks, against a declaration whose empty value is a measured absence."""
    enabled, contexts = _read(rule, 'enable_status_check'), _read(rule, 'status_check_contexts')
    if UNREADABLE in (enabled, contexts):
        return Clause('status_checks', UNREADABLE, 'the forge did not answer the status check clause')
    live = tuple(sorted(contexts or ())) if enabled else ()
    wanted = tuple(sorted(target.status_contexts))
    standing = APPLIED if live == wanted else NOT_APPLIED
    return Clause('status_checks', standing, f'required contexts: live={list(live)} declared={list(wanted)}')


def protection_body(target: Protection, *, with_branch: bool = False) -> dict[str, Any]:
    """The payload that makes *target* true. Pure, so a caller can read it before sending it.

    ``with_branch`` is for the CREATE call only: a PATCH addresses the branch in its path, and
    repeating it in the body is a second place to be wrong.
    """
    body: dict[str, Any] = {
        'enable_push': True,
        'enable_push_whitelist': True,
        'push_whitelist_usernames': list(target.push_accounts),
        'enable_force_push': target.allow_force_push,
    }
    if target.status_contexts:
        body |= {'enable_status_check': True, 'status_check_contexts': list(target.status_contexts)}
    return {'branch_name': target.branch, **body} if with_branch else body


def read_rule(forge: Forge, token: str, target: Protection, *, transport: Transport = forge_transport) -> dict | None:
    """The live rule for *target*'s branch, MATCHED rather than taken as the first rule.

    A repo with several protected branches would otherwise be reported on under the wrong one.
    """
    payload = call(forge, forge.protections, token, transport=transport)
    rules: list[dict[str, Any]] = payload if isinstance(payload, list) else []
    return next((rule for rule in rules if rule.get('branch_name') == target.branch), None)


def apply_protection(
    forge: Forge, token: str, target: Protection, *, transport: Transport = forge_transport
) -> tuple[Clause, ...]:
    """Make *target* true, and return the assessment of the state AFTER.

    A write the forge silently declined otherwise reports as applied, because the call returned 200.
    """
    existing = read_rule(forge, token, target, transport=transport)
    if existing is None:
        call(
            forge,
            forge.protections,
            token,
            method='POST',
            body=protection_body(target, with_branch=True),
            transport=transport,
        )
    else:
        call(
            forge,
            f'{forge.protections}/{target.branch}',
            token,
            method='PATCH',
            body=protection_body(target),
            transport=transport,
        )
    return assess(read_rule(forge, token, target, transport=transport), target)
