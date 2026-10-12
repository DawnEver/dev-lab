"""The forge credential: how a secret from the git credential store is presented to a forge.

Split out of :mod:`lab_commons.dev.forge` (2026-10-12) when naming WHY a credential is absent pushed
that module past the size band; the store itself -- reading, storing and that diagnosis -- moved on to
the runtime :mod:`lab_commons.credentials` (2026-10-13), which model API keys read too. What stays here
is forge-specific: the header, the refusal statuses and their remedy.
"""

from __future__ import annotations

import base64
from typing import TYPE_CHECKING, Final

from lab_commons.credentials import credential_for

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

__all__ = ['AUTH_REFUSED', 'AUTH_REMEDY', 'authorization', 'token_for']

#: HTTP statuses that refuse the presented credential: permanent, the remedy is a re-stored credential.
AUTH_REFUSED: Final = frozenset({401, 403})

#: The remedy an auth refusal names.
AUTH_REMEDY: Final = 'the forge refused the stored credential; re-store it: python -m lab_commons.dev.forge auth login'


def authorization(username: str, secret: str, scheme: str) -> str:
    """HTTP Basic with the credential's username, exactly as git presents it; ``<scheme> <secret>`` only without one.

    A secret with no username is a bare token handed to ``auth login`` -- the one case Basic cannot carry.
    """
    if username:
        return 'Basic ' + base64.b64encode(f'{username}:{secret}'.encode()).decode()
    return f'{scheme} {secret}'


def token_for(host: str, *, cwd: Path | None = None, env: Mapping[str, str] | None = None) -> str:
    """The secret half of :func:`lab_commons.credentials.credential_for`."""
    return credential_for(host, cwd=cwd, env=env)[1]
