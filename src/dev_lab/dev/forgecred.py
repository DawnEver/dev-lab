"""The forge credential: how a secret from the git credential store is presented to a forge.

Split out of :mod:`dev_lab.dev.forge` (2026-10-12) when naming WHY a credential is absent pushed
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

__all__ = ['AUTH_REFUSED', 'AUTH_REMEDY', 'AUTH_TRANSIENT', 'authorization', 'token_for']

#: HTTP statuses that MAY refuse the presented credential -- a SUSPICION, never a verdict. One 401 is not
#: evidence the credential is bad: 2026-10-18 a gitea answered 401 "invalid username, password or token" and
#: minutes later the same stored credential authenticated. The verdict is MEASURED by asking the forge who the
#: credential is (``GET /user``, what ``auth status`` asks); only a refusal THERE names the credential.
AUTH_REFUSED: Final = frozenset({401, 403})

#: The remedy a MEASURED credential refusal names (the request AND ``GET /user`` refused it).
AUTH_REMEDY: Final = 'the forge refused the stored credential; re-store it: python -m dev_lab.dev.forge auth login'

#: What a 401/403 says when ``GET /user`` still authenticated the same credential: re-storing cannot help.
AUTH_TRANSIENT: Final = (
    'the forge refused this request, yet the stored credential authenticates (GET /user answered) -- '
    'do not re-store it; report this output if it persists'
)


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
