"""THE REVIEW DOOR OWNS ITS FORGE TOKENS: they reach the door from files, never through any process environment.

The review job's checkout is blobless (``--filter=blob:none``), so the door's ``git diff a..b`` fetches blobs from
origin on demand and needs the forge's auth header on a private forge (F-ca1dda52c2ef); the door's forge client
needs the job's API token. The reviewer it launches (ai-lab, an LLM reading the PR's content) needs neither, and
anything in an environment is readable: ``os.environ.pop`` unsets only the in-process copy, the original strings
stay in ``/proc/<pid>/environ`` of the door and of the step's shell (F-5a82981c5f22, F-d61706393b50). So the
workflow writes each token to a private file in a step of its own, and :func:`take` reads each ONCE, unlinks it,
holds the git header for :func:`git_env` (the env of the door's git calls alone) and returns the API token for the
client the door builds. A forge token still in the environment is a template defect and is refused.
"""

from __future__ import annotations

import base64
import os
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

__all__ = ['FORGE_TOKEN_ENVS', 'SERVER_ENVS', 'TokenInEnvironment', 'git_env', 'take']

SERVER_ENVS = ('FORGE_URL', 'GITHUB_SERVER_URL')  # the forge the checkout's origin is on; the first set one
FORGE_TOKEN_ENVS = ('FAMILY_READ_TOKEN', 'GITHUB_TOKEN')  # never in the review door's environment
_GIT_CONFIG = re.compile(r'GIT_CONFIG_(COUNT|KEY_\d+|VALUE_\d+)')
_held: dict[str, str] = {}  # the process-scoped header env of the door's git calls; empty: none


class TokenInEnvironment(ValueError):
    """A forge token or a git header reached the review door's environment: its ``/proc/<pid>/environ`` holds it."""


def _read_once(path: Path | None) -> str:
    """The file's content, the file then removed; ``''`` for no path."""
    if path is None:
        return ''
    try:
        return path.read_text(encoding='utf-8').strip()
    finally:
        path.unlink(missing_ok=True)


def take(git_file: Path | None, api_file: Path | None, environ: Mapping[str, str] | None = None) -> str:
    """Read and remove both token files; hold the git header; return the API token (``''``: none given).

    Raises:
        TokenInEnvironment: a forge token or a ``GIT_CONFIG_*`` slot is in the environment (both files are
            removed first, so a refusal leaves no token on disk).

    """
    env = os.environ if environ is None else environ
    git_token, api_token = _read_once(git_file), _read_once(api_file)
    if leaked := sorted(key for key in env if key in FORGE_TOKEN_ENVS or _GIT_CONFIG.fullmatch(key)):
        msg = f'{", ".join(leaked)} in the review door environment: hand the token over by file instead'
        raise TokenInEnvironment(msg)
    server = next((value for name in SERVER_ENVS if (value := env.get(name, ''))), '')
    _held.clear()
    if git_token and server:
        basic = base64.b64encode(f'x-access-token:{git_token}'.encode()).decode()
        _held.update({
            'GIT_CONFIG_COUNT': '1',
            'GIT_CONFIG_KEY_0': f'http.{server.rstrip("/")}/.extraHeader',
            'GIT_CONFIG_VALUE_0': f'Authorization: basic {basic}',
        })  # fmt: skip
    return api_token


def git_env() -> dict[str, str] | None:
    """The env of one door git call: this process's env plus the held header; ``None`` (inherit) when none is held."""
    return {**os.environ, **_held} if _held else None
