"""THE ACTION REGISTRY: every action a consent credential may name, its params schema, scope and lifetimes.

The one source of truth (user ruling 2026-11-07): the issuer refuses a request this table does not admit, and every
verifier reads the same row. A row's ``default_ttl`` is what a request naming no ``ttl`` gets; ``max_ttl`` the
longest one may ask -- above it the issuer REFUSES, never clamps. ``params`` maps each parameter to its type; a
request carries exactly those keys. A ``campaign`` credential carries a ``cap`` the issuer debits; a ``single`` one
is spent by its one use.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

__all__ = ['ACTIONS', 'CAMPAIGN', 'SCOPES', 'SINGLE', 'Action']

SINGLE: Final = 'single'
CAMPAIGN: Final = 'campaign'
#: Every scope a credential may carry.
SCOPES: Final = (SINGLE, CAMPAIGN)
_MINUTE: Final = 60.0
_HOUR: Final = 3600.0


@dataclass(frozen=True)
class Action:
    """One registry row (see the module docstring); TTLs are in seconds."""

    name: str
    params: Mapping[str, type]
    scope: str
    default_ttl: float
    max_ttl: float

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
        Action('budget.approve', {}, CAMPAIGN, 15 * _MINUTE, 24 * _HOUR),
        # One raise of a review cap to ``cap``.
        Action('review.raise-cap', {'cap': int}, SINGLE, 15 * _MINUTE, 15 * _MINUTE),
        # One break-glass wave: its merge cap (0 = none) and window (user ruling 2026-11-07: up to 24 h).
        Action('breakglass.wave', {'max_merges': int, 'hours': float}, SINGLE, 15 * _MINUTE, 24 * _HOUR),
        # One change of a host's security boundary through `ops config apply`; subject = the candidate's SHA-256.
        Action('ops.config', {}, SINGLE, 15 * _MINUTE, 1 * _HOUR),
        # One `ops forge account ensure` (a machine account and its Read grants); subject = the request's digest.
        Action('ops.forge.account', {}, SINGLE, 15 * _MINUTE, 1 * _HOUR),
        # One `ops forge token mint` (one named token of one login); subject = the request's digest.
        Action('ops.forge.token', {}, SINGLE, 15 * _MINUTE, 1 * _HOUR),
        # One `ops forge token mint-batch` (one login's closed, ordered batch); subject = the whole batch's digest.
        Action('ops.forge.tokens', {}, SINGLE, 15 * _MINUTE, 1 * _HOUR),
        # One `ops forge token revoke` (one named token of one login, deleted); subject = the request's digest.
        Action('ops.forge.revoke', {}, SINGLE, 15 * _MINUTE, 1 * _HOUR),
    )
})  # fmt: skip
