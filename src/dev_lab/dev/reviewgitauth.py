"""THE REVIEW DOOR OWNS ITS GIT AUTH: a forge token reaches the door's own git calls, never the reviewer's env.

The review job's checkout is blobless (``--filter=blob:none``), so the door's ``git diff a..b`` fetches blobs from
origin on demand and needs the forge's auth header on a private forge (F-ca1dda52c2ef). The reviewer it launches
(ai-lab, an LLM reading the PR's content) needs no forge credential, and anything in the door's environment is
inherited by it (F-5a82981c5f22). So :func:`take` reads the token ONCE at start, removes every named token variable
and any ``GIT_CONFIG_*`` from the process environment before any subprocess starts, and holds the header for
:func:`git_env` -- the env of the door's git calls alone. The header is derived here, never in a workflow's shell.
"""

from __future__ import annotations

import base64
import os
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import MutableMapping, Sequence

__all__ = ['SERVER_ENVS', 'git_env', 'take']

SERVER_ENVS = ('FORGE_URL', 'GITHUB_SERVER_URL')  # the forge the checkout's origin is on; the first set one
_GIT_CONFIG = re.compile(r'GIT_CONFIG_(COUNT|KEY_\d+|VALUE_\d+)')
_held: dict[str, str] = {}  # the process-scoped header env of the door's git calls; empty: none


def take(names: Sequence[str], environ: MutableMapping[str, str] | None = None) -> bool:
    """Hold the git header for the first non-empty token of *names*; remove them all and any ``GIT_CONFIG_*``.

    Returns whether a header is held (a token and a server were both set).
    """
    env = os.environ if environ is None else environ
    token = next((value for name in names if (value := env.get(name, ''))), '')
    for name in [*names, *(key for key in env if _GIT_CONFIG.fullmatch(key))]:
        env.pop(name, None)
    server = next((value for name in SERVER_ENVS if (value := env.get(name, ''))), '')
    _held.clear()
    if token and server:
        basic = base64.b64encode(f'x-access-token:{token}'.encode()).decode()
        _held.update({
            'GIT_CONFIG_COUNT': '1',
            'GIT_CONFIG_KEY_0': f'http.{server.rstrip("/")}/.extraHeader',
            'GIT_CONFIG_VALUE_0': f'Authorization: basic {basic}',
        })  # fmt: skip
    return bool(_held)


def git_env() -> dict[str, str] | None:
    """The env of one door git call: this process's env plus the held header; ``None`` (inherit) when none is held."""
    return {**os.environ, **_held} if _held else None
