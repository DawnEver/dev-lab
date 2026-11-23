"""A FORGE TOKEN'S DECLARED SHAPE, per forge kind: every intake checks it before anything is stored or sent.

Measured 2026-11-23: ``forge auth login`` with no ``--host`` asked for the checkout's forge (github.com), showed the
Gitea hint, took a pasted Gitea token ("40 characters, hex" -- no GitHub token is that) and sent it to GitHub, which
answered 401. And four other intakes -- ``forge auth login --token-stdin``, ``devcredential``, ``hpcaccount
credential`` (both through :func:`dev_lab.dev.credstore.place_verified`) and ``sshhold credential`` -- took a token
with no check at all. So each forge KIND declares its hint and its shape here, once (:data:`KINDS`), and every intake
judges a token through :func:`checked` -- the same :func:`dev_lab.dev.ask.judged` the typed prompt uses. A token
of ANOTHER kind's shape is refused naming the likely mix-up and the ``--host`` that kind lives on.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from dev_lab.dev._forgebackends import GITHUB_HOST
from dev_lab.dev.ask import AskRefused, judged

__all__ = ['GITEA', 'GITHUB', 'KINDS', 'TICK_SCOPES', 'TokenKind', 'checked', 'kind_of']

#: The token scopes a serve tick needs, as a Gitea token page names them.
TICK_SCOPES: Final = 'repository (read and write), issue (read and write), user (read)'


@dataclass(frozen=True)
class TokenKind:
    """One forge kind's token: its *name*, where a person finds one (*hint*), and its declared *shape* (a regex)."""

    name: str
    hint: str
    shape: str


GITEA: Final = TokenKind(
    'Gitea', f'the forge user settings -> Applications -> Generate token, scopes {TICK_SCOPES}', r'[0-9a-f]{40}'
)
GITHUB: Final = TokenKind(
    'GitHub',
    'github.com -> Settings -> Developer settings -> Personal access tokens (ghp_... or github_pat_...)',
    r'gh[pousr]_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{22,255}',
)
#: Every kind, by the name a refusal says.
KINDS: Final = (GITEA, GITHUB)


def kind_of(host: str) -> TokenKind:
    """The token kind *host* takes: GitHub's own host, else a Gitea forge."""
    return GITHUB if host == GITHUB_HOST else GITEA


def checked(host: str, token: str, *, name: str = 'token') -> tuple[str, str]:
    """``(token, check line)`` of a token for *host*, judged against its kind's shape; never the value.

    Raises:
        AskRefused: empty, control characters, or not the shape -- naming a mix-up when another kind's shape fits.

    """
    kind = kind_of(host)
    line, why = judged(name, token.strip('\r\n'), kind.shape)
    if why:
        fits = [one.name for one in KINDS if one != kind and re.fullmatch(one.shape, token.strip()) is not None]
        mixed = ''.join(f'; it has the shape of a {fit} token -- is it for another forge (`--host <that forge>`)?'
                        for fit in fits[:1])  # fmt: skip
        msg = f'{why} of a {kind.name} token for {host}{mixed}; nothing was stored or sent'
        raise AskRefused(msg)
    return token.strip('\r\n'), line
