"""THE REVIEW DOOR OWNS ITS FORGE TOKENS: they reach the door from files, never through any process environment.

The review job's checkout is blobless (``--filter=blob:none``), so the door's ``git diff a..b`` fetches blobs from
origin on demand and needs the forge's auth header on a private forge (F-ca1dda52c2ef); the door's forge client
needs the job's API token. The reviewer it launches (ai-lab, an LLM reading the PR's content) needs neither, and
anything in an environment is readable: ``os.environ.pop`` unsets only the in-process copy, the original strings
stay in ``/proc/<pid>/environ`` of the door and of the step's shell (F-5a82981c5f22, F-d61706393b50). So the
workflow writes each token to a private file in a step of its own, and :func:`take` reads each ONCE, unlinks it,
holds the git header for :func:`git_env` (the env of the door's git calls alone) and returns the API token for the
client the door builds. A forge token or an ``http.*.extraHeader`` slot still in the environment is a template
defect and is refused; every other ``GIT_CONFIG_*`` slot (safe.directory, a proxy, sslCAInfo) is the job's and
survives -- the held header is appended as the next free slot.
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
_EXTRA_HEADER = re.compile(r'http\..*\.extraheader', re.IGNORECASE)  # git config keys are case-insensitive
_held: dict[str, str] = {}  # the header slot of the door's git calls: {'key': ..., 'value': ...}; empty: none


class TokenInEnvironment(ValueError):
    """A forge token or an auth header reached the review door's environment: ``/proc/<pid>/environ`` holds it."""


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
        TokenInEnvironment: a forge token or an ``http.*.extraHeader`` ``GIT_CONFIG_*`` slot is in the
            environment (both files are removed first, so a refusal leaves no token on disk).

    """
    env = os.environ if environ is None else environ
    git_token, api_token = _read_once(git_file), _read_once(api_file)
    headers = [
        f'GIT_CONFIG_KEY_{n}' for n in range(_slots(env)) if _EXTRA_HEADER.fullmatch(env.get(f'GIT_CONFIG_KEY_{n}', ''))
    ]
    if leaked := sorted([*(key for key in env if key in FORGE_TOKEN_ENVS), *headers]):
        msg = f'{", ".join(leaked)} in the review door environment: hand the token over by file instead'
        raise TokenInEnvironment(msg)
    server = next((value for name in SERVER_ENVS if (value := env.get(name, ''))), '')
    _held.clear()
    if git_token and server:
        basic = base64.b64encode(f'x-access-token:{git_token}'.encode()).decode()
        _held.update({'key': f'http.{server.rstrip("/")}/.extraHeader', 'value': f'Authorization: basic {basic}'})
    return api_token


def _slots(env: Mapping[str, str]) -> int:
    count = env.get('GIT_CONFIG_COUNT', '0')
    return int(count) if count.isdigit() else 0


def git_env() -> dict[str, str] | None:
    """The env of one door git call: this process's env plus the held header; ``None`` (inherit) when none is held."""
    if not _held:
        return None
    n = _slots(os.environ)
    return {
        **os.environ,
        'GIT_CONFIG_COUNT': str(n + 1),
        f'GIT_CONFIG_KEY_{n}': _held['key'],
        f'GIT_CONFIG_VALUE_{n}': _held['value'],
    }
