"""WHO REVIEWS: the identity a review is posted as, and the two refusals that keep it independent.

* A REVIEW STATUS comes only from the forge's own identity (:func:`ruling`): the Actions bot a workflow job token
  writes as (:data:`CI_LOGINS`), or the ``forge serve`` process. A developer or agent session never posts one,
  whatever ``LAB_SESSION`` says (#11 round 2, F-e97824b7b801).
* NO SESSION REVIEWS ITS OWN HEAD (:func:`self_review`): the review is an INDEPENDENT acceptance check, so a session
  that authored the head may not review it, and a reviewer naming no session is no identity (fail closed).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from dev_lab.dev._forgebackends import GITEA, GITHUB
from dev_lab.dev.labsession import ENV as SESSION_ENV

if TYPE_CHECKING:
    from dev_lab.dev.forgework import Client

__all__ = ['CI_LOGINS', 'Identity', 'ReviewerRefused', 'identity', 'ruling', 'self_review']

#: The logins a workflow job token writes as -- GitHub's Actions bot, Gitea's Actions user. Only a job holds that
#: token, so the login (read from the forge, never from an env variable) is what binds a review status to CI.
CI_LOGINS: Final = frozenset({GITHUB.actions_login, GITEA.actions_login})


class ReviewerRefused(ValueError):
    """Refused: this identity may not review this head, and why."""


@dataclass(frozen=True)
class Identity:
    """Who acts: the forge login, the host, the agent session, and whether it IS the forge.

    *session* is ``LAB_SESSION`` (``''`` for the forge itself); *ci* is a :data:`CI_LOGINS` login or the serve
    process -- the one identity whose review posts a status.
    """

    login: str
    host: str
    session: str = ''
    ci: bool = False

    def text(self) -> str:
        """``login@host`` and the session when there is one -- as every record names it."""
        return f'{self.login}@{self.host}' + (f' session {self.session}' if self.session else '')


def identity(client: Client, host: str, env: Mapping[str, str] | None = None, *, serving: bool = False) -> Identity:
    """The :class:`Identity` this process acts as on *client*'s forge.

    It is the forge's own (*ci*) when the token's login is a :data:`CI_LOGINS` bot, or when *serving*: the
    ``forge serve`` tick passes it from its own code path, never from a variable a session could set.
    """
    login = client.whoami()
    session = (os.environ if env is None else env).get(SESSION_ENV, '').strip()
    return Identity(login, host, session, ci=serving or login in CI_LOGINS)


def ruling(who: Identity, what: str) -> None:
    """Refuse unless *who* is the forge itself: a review status is never a developer's or an agent's."""
    if not who.ci:
        msg = (
            f"{what}: refused -- the forge's review comes only from the forge (its Actions job or `forge serve`), "
            f'never from {who.text()}; `forge review takeover <sha>` posts a session review as advice'
        )
        raise ReviewerRefused(msg)


def self_review(reviewer: Identity, authors: frozenset[str], what: str) -> None:
    """Refuse when *reviewer*'s session authored the head under review: the review is independent.

    FAIL CLOSED: a reviewer that is not the forge and names no session is refused -- an unset ``LAB_SESSION`` is
    no identity, so it cannot be proved different from the author's.
    """
    if not reviewer.ci and not reviewer.session:
        msg = f'{what}: refused -- {reviewer.text()} names no session (LAB_SESSION unset), so it is no reviewer'
        raise ReviewerRefused(msg)
    if reviewer.session and reviewer.session in authors:
        msg = (
            f'{what}: session {reviewer.session} authored this head, so it may not review it; '
            'the forge, or another session, does'
        )
        raise ReviewerRefused(msg)
