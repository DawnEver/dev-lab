"""THE ACTION REGISTRY: every action a consent credential may name, its params schema, scope and lifetimes.

The one source of truth (user ruling 2026-11-07): the issuer refuses a request this table does not admit, and every
verifier reads the same row. A row's ``default_ttl`` is what a request naming no ``ttl`` gets; ``max_ttl`` the
longest one may ask -- above it the issuer REFUSES, never clamps. ``params`` maps each parameter to its type; a
request carries exactly those keys. ``boundary`` says the action changes a SECURITY BOUNDARY -- who or what may
act on a host or forge (a config, an account, a token, a protection, a secret, an installed revision, a role) -- so
a shown plan names it in its summary (:func:`dev_lab.ops.consent.plan.show`). A ``campaign`` credential carries
a ``cap`` the issuer debits; a ``single`` one is spent by its one use. ``reads`` are the ops verb words whose
``--subject`` derives the action's subject on its host, read-only: what the issuer's ``subject`` verb may run
(:func:`dev_lab.ops.consent.door.read_argv`); empty when no host-side read is admitted. A read form whose host
would REFUSE the request as it stands (a token name already held, a login absent) prints that on the line before
the subject (:data:`STANDING`, :func:`read_answer`), so a preflight shows the refusal before a code is spent on it.
``rederives`` says the action changes WHAT ITS HOST DERIVES OR ADMITS afterwards -- its live config (sudo doors, the
placed family file), its installed revision (the verbs and subjects that revision knows) -- so a later step of a
plan on that host can only be checked once this one ran (:mod:`dev_lab.dev.planrunpreflight`: ``after step N``).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

__all__ = ['ACTIONS', 'CAMPAIGN', 'SCOPES', 'SINGLE', 'STANDING', 'Action', 'read_answer']

SINGLE: Final = 'single'
CAMPAIGN: Final = 'campaign'
#: Every scope a credential may carry.
SCOPES: Final = (SINGLE, CAMPAIGN)
_MINUTE: Final = 60.0
_HOUR: Final = 3600.0
_DAY: Final = 24 * _HOUR
#: What a read form prints on the line BEFORE its subject when its host would refuse the request as it stands.
STANDING: Final = 'refused as it stands: '


def read_answer(said: str) -> tuple[str, str | None]:
    """``(subject, standing refusal)`` of a read form's output: its last line, and a :data:`STANDING` line before it.

    The subject is ``''`` when *said* has no line; the refusal ``None`` when the host named none.
    """
    lines = [line.strip() for line in said.splitlines() if line.strip()]
    before = lines[-2] if len(lines) > 1 else ''
    return (lines[-1] if lines else ''), (before[len(STANDING) :] if before.startswith(STANDING) else None)


@dataclass(frozen=True)
class Action:
    """One registry row (see the module docstring); TTLs are in seconds."""

    name: str
    params: Mapping[str, type]
    scope: str
    default_ttl: float
    max_ttl: float
    boundary: bool
    reads: tuple[str, ...] = ()
    rederives: bool = False

    def __post_init__(self) -> None:
        """Refuse a row that lies: an unknown scope, or a default above its ceiling."""
        if self.scope not in SCOPES:
            msg = f'{self.name}: scope {self.scope!r} is not one of {SCOPES}'
            raise ValueError(msg)
        if not 0 < self.default_ttl <= self.max_ttl:
            msg = f'{self.name}: default_ttl {self.default_ttl:g} s must be in (0, max_ttl {self.max_ttl:g} s]'
            raise ValueError(msg)


ACTIONS: Final[Mapping[str, Action]] = MappingProxyType({
    row.name: row
    for row in (
        # A budget a campaign spends against; the cap is the budget, debited per use at the issuer.
        Action('budget.approve', {}, CAMPAIGN, 15 * _MINUTE, 24 * _HOUR, boundary=False),
        # One raise of a review cap to ``cap``.
        Action('review.raise-cap', {'cap': int}, SINGLE, 15 * _MINUTE, 15 * _MINUTE, boundary=False),
        # One break-glass wave: its merge cap (0 = none) and window (user ruling 2026-11-07: up to 24 h).
        Action('breakglass.wave', {'max_merges': int, 'hours': float}, SINGLE, 15 * _MINUTE, 24 * _HOUR, boundary=True),
        # One change of a host's security boundary through `ops config apply`; subject = the candidate's SHA-256.
        Action('ops.config', {}, SINGLE, 15 * _MINUTE, 1 * _HOUR, boundary=True,
               reads=('config', 'apply'), rederives=True),
        # One `ops forge account ensure` (a machine account and its Read grants); subject = the request's digest.
        Action('ops.forge.account', {}, SINGLE, 15 * _MINUTE, 1 * _HOUR, boundary=True,
               reads=('forge', 'account', 'ensure')),
        # One `ops forge token mint` (one named token of one login); subject = the request's digest.
        Action('ops.forge.token', {}, SINGLE, 15 * _MINUTE, 1 * _HOUR, boundary=True,
               reads=('forge', 'token', 'mint')),
        # One `ops forge token mint-batch` (one login's closed, ordered batch); subject = the whole batch's digest.
        Action('ops.forge.tokens', {}, SINGLE, 15 * _MINUTE, 1 * _HOUR, boundary=True,
               reads=('forge', 'token', 'mint-batch')),
        # One `ops forge token revoke` (one named token of one login, deleted); subject = the request's digest.
        Action('ops.forge.revoke', {}, SINGLE, 15 * _MINUTE, 1 * _HOUR, boundary=True,
               reads=('forge', 'token', 'revoke')),
        # One `ops upgrade --sha S` (dev-lab installed at S, the declared upgrade ref's tip); subject = S.
        Action('ops.upgrade', {}, SINGLE, 15 * _MINUTE, 1 * _HOUR, boundary=True,
               reads=('upgrade',), rederives=True),
        # One `ops forge protect apply` (one repo's declared branch protection at a ref); subject = the repo, the ref
        # and the rendered protection's digest.
        Action('ops.forge.protect', {}, SINGLE, 15 * _MINUTE, 1 * _HOUR, boundary=True,
               reads=('forge', 'protect', 'apply')),
        # One `ops secret place` (one declared secret file written); subject = path + the content's SHA-256.
        Action('ops.secret.place', {}, SINGLE, 15 * _MINUTE, 1 * _HOUR, boundary=True),
        # One session holds the integrator role (verification HPC accounts) until expiry; subject = the session id,
        # verified offline on every load (dev_lab.dev.hpcaccount.session); a day at most, never a standing grant.
        Action('session.integrator', {}, SINGLE, 12 * _HOUR, 24 * _HOUR, boundary=True),
        # One TASK holds the integrator role until expiry; subject = the task id `<slug>@<authority>` (the authority the
        # user's own task-open minted). A session inherits it only while the USER's prompt bound it to that task
        # (dev_lab.dev.hpcaccount.session). A week at most: a task outlives its sessions, never its re-consent.
        Action('task.integrator', {}, SINGLE, 3 * _DAY, 7 * _DAY, boundary=True),
        # One CI cron change on one cluster's accounts (`hpcaccount ci-pause[-fleet]` / `ci-resume[-fleet]
        # --credential`); subject = `<pause|resume> <cluster> <sorted accounts>` (dev_lab.dev.hpcaccount.cicron).
        Action('hpcaccount.ci-cron', {}, SINGLE, 15 * _MINUTE, 1 * _HOUR, boundary=False),
        # One agent background shell may live ``minutes`` past the 50-minute default (user ruling 2026-11-15); subject =
        # the SHA-256 of the command after its ``timeout`` prefix. The ttl is the window to LAUNCH it, not its life.
        Action('shell.lifetime', {'minutes': int}, SINGLE, 1 * _HOUR, 1 * _DAY, boundary=False),
        # One vendor-GUI open, and one focus take (user ruling 2026-11-17: no agent opens a vendor GUI or takes the
        # user's focus without the user's authorization); subject = the SHA-256 of the consumer's canonical plan JSON
        # (a focus act's plan is ``{'act', 'plan'}``). Spent through :func:`dev_lab.ops.consent.client.verify_held`.
        Action('desktop.open', {}, SINGLE, 15 * _MINUTE, 1 * _HOUR, boundary=False),
        Action('desktop.focus', {}, SINGLE, 15 * _MINUTE, 15 * _MINUTE, boundary=False),
    )
})  # fmt: skip
