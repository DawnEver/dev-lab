"""THE PLAN: one code from the user opens a host session AND consents to a listed, closed set of actions.

User ruling 2026-11-10 ("one code, not two"). A plan file is JSON::

    {"host": "<user>@<host>", "grants": [{"action": "...", "subject": "..."}, ...]}

each grant a request the issuer checks against the registry as it checks a lone one. Its DIGEST
(:func:`digest`, SHA-256 of the canonical JSON) is what the user is shown (:func:`show`) before they give the code,
and what every grant command names: a plan changed after it was shown has another digest and is refused
(:func:`load`). The issuer turns the plan and the code into one single-use credential per grant
(:meth:`~dev_lab.ops.consent.issuer.Issuer.issue_plan`), each bound to its own subject exactly as a lone grant is;
a request outside the plan has no credential, and a credential shown to another request is refused before its use
is registered (:func:`dev_lab.ops.consent.client.redeem`).

WHY ONE CODE IS ENOUGH (the shaping assumption): a host has ONE TOTP secret (:mod:`dev_lab.ops.access`, user ruling
2026-11-04) that pam_oath and the consent issuer both verify, each recording the step it accepted. So one code is
accepted once by each verifier -- never twice by either -- and nothing here verifies a code itself.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from dev_lab.ops.consent.actions import ACTIONS
from dev_lab.ops.consent.credential import ConsentRefused, canonical

__all__ = ['DIGEST_SHOWN', 'STALE_CLIENT', 'Plan', 'digest', 'load', 'parsed', 'show', 'stale_client']

#: Hex characters of the digest the user is shown and every grant command names.
DIGEST_SHOWN: Final = 12


#: What a plan naming an action this client's registry lacks means, and the one thing to do about it.
STALE_CLIENT: Final = 'local dev-lab is older than the plan; update it'


@dataclass(frozen=True)
class Plan:
    """A parsed plan: its host, its grant requests in order, and its full digest."""

    host: str
    grants: tuple[Mapping[str, Any], ...]
    digest: str


def digest(data: Mapping[str, Any]) -> str:
    """SHA-256 (hex) of *data*'s canonical JSON: what the user is shown, and what the issuer records."""
    return hashlib.sha256(canonical(dict(data))).hexdigest()


def parsed(data: object) -> Plan:
    """*data* as a :class:`Plan`; :class:`ConsentRefused` names the first bad field (no code is spent on it)."""
    if not isinstance(data, dict) or set(data) != {'host', 'grants'}:
        msg = 'a plan is a JSON object with exactly host and grants'
        raise ConsentRefused(msg)
    host, grants = data['host'], data['grants']
    if not isinstance(host, str) or '@' not in host:
        msg = 'plan host is "<user>@<host>", the session it opens'
        raise ConsentRefused(msg)
    if not isinstance(grants, list) or not grants:
        msg = 'plan grants is a non-empty list of requests (the issuer bounds it by [ops.consent] max_grants)'
        raise ConsentRefused(msg)
    for index, grant in enumerate(grants):
        if not isinstance(grant, dict) or not all(isinstance(grant.get(key), str) for key in ('action', 'subject')):
            msg = f'plan grant {index} is a request object naming an action and a subject'
            raise ConsentRefused(msg)
    pairs = [(grant['action'], grant['subject']) for grant in grants]
    if twice := sorted({pair for pair in pairs if pairs.count(pair) > 1}):
        msg = f'plan grants {twice} twice'
        raise ConsentRefused(msg)
    return Plan(host, tuple(grants), digest(data))


def stale_client(plan: Plan) -> list[str]:
    """The actions of *plan* THIS client's registry lacks, sorted; empty when it knows them all.

    Checked before a code is asked for or sent: a plan written against a newer registry is refused locally by
    the grant anyway, but only after the user has given the code (2026-11-12).
    """
    return sorted({grant['action'] for grant in plan.grants} - set(ACTIONS))


def load(path: Path, shown: str) -> Plan:
    """The plan at *path*, refused unless its digest starts with *shown* -- the digest the user was shown."""
    plan = parsed(json.loads(path.read_text(encoding='utf-8')))
    if len(shown) < DIGEST_SHOWN or not plan.digest.startswith(shown.lower()):
        msg = (f'the plan at {path} is not the one shown (its digest {plan.digest[:DIGEST_SHOWN]}, named '
               f'{shown[:DIGEST_SHOWN]!r}): show it again and ask the user for a code for that one')  # fmt: skip
        raise ConsentRefused(msg)
    return plan


def show(path: Path) -> str:
    """What the user reads before a code: the digest, the boundary summary, every grant by host and action.

    Grouped so a large plan stays readable at a glance.

    A boundary action is a registry row's ``boundary`` (:mod:`.actions`); an action this client does not know is
    counted as one (it cannot say otherwise).
    """
    plan = parsed(json.loads(path.read_text(encoding='utf-8')))
    by_action: dict[str, list[str]] = {}
    for grant in plan.grants:
        by_action.setdefault(grant['action'], []).append(grant['subject'])
    crossing = [f'{action} x{len(subjects)}' for action, subjects in by_action.items()
                if action not in ACTIONS or ACTIONS[action].boundary]  # fmt: skip
    head = f'plan {plan.digest[:DIGEST_SHOWN]}: one code opens {plan.host} and consents to {len(plan.grants)} grant(s):'
    lines = [head, 'boundary: ' + (', '.join(crossing) if crossing else 'none'), f'  {plan.host}']
    for action, subjects in by_action.items():
        lines.append(f'    {action} ({len(subjects)})')
        lines += [f'      {subject}' for subject in subjects]
    return '\n'.join(lines)
