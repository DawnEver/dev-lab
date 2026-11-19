"""The FORGE a break-glass server reaches (:mod:`dev_lab.ops.breakglass`): its calls, their client, and the token.

:class:`Forge` is the narrow surface the server makes on one repository as the break-glass identity;
:class:`ClientForge` serves it over the family's forge client of the repo URL's backend (Gitea or GitHub), and
:func:`credential` is the token that client presents.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from functools import partial
from pathlib import Path
from typing import Protocol

from dev_lab.dev.branchset import branchset_from
from dev_lab.dev.failprint import Fingerprints
from dev_lab.dev.forge import forge_of_url
from dev_lab.dev.forgeapp import installation
from dev_lab.dev.forgemergecall import merge
from dev_lab.dev.forgepulls import pr_list
from dev_lab.dev.forgestatus import CommitStatus, fingerprints_at, status_list
from dev_lab.dev.forgework import Client, Transport, forge_transport
from dev_lab.dev.reviewgate import manifest_at
from dev_lab.ops.config import Breakglass
from dev_lab.ops.served import app_of_forge
from dev_lab.ops.wavesweep import Pull

__all__ = ['ClientForge', 'Forge', 'credential']


class Forge(Protocol):
    """The forge calls the role makes, on one repository, as the break-glass identity."""

    def declaration(self, ref: str) -> str:
        """The repository's ``pyproject.toml`` at *ref*; raises ``ValueError`` when it cannot be read."""
        ...

    def pull(self, number: int) -> tuple[str, str, str]:
        """``(state, base, head_sha)`` of PR *number*."""
        ...

    def statuses(self, head: str) -> Sequence[CommitStatus]:
        """The commit statuses *head* carries, newest first."""
        ...

    def open_pulls(self) -> Sequence[Pull]:
        """Every open PR (:mod:`dev_lab.ops.wavesweep` lands the green ones of an open wave)."""
        ...

    #: The failure fingerprints of a ref (a sha, or a branch's tip), read from its run records.
    fingerprints: Callable[[str], Fingerprints]

    def labels(self, number: int) -> tuple[str, ...]:
        """The labels PR *number* carries now."""
        ...

    def comment(self, number: int, body: str) -> None:
        """Comment on PR *number*."""
        ...

    def merge(self, number: int, *, head: str, message: str) -> None:
        """Merge PR *number* at *head* with a merge commit saying *message*."""
        ...


class ClientForge:
    """:class:`Forge` over the family's forge client of *url*'s backend, presenting *token*."""

    def __init__(self, url: str, token: str, *, transport: Transport = forge_transport) -> None:
        """Reach *url*'s repository through *transport* (the network by default)."""
        self._client = Client(forge_of_url(url), token, transport=transport)
        self.fingerprints = partial(fingerprints_at, self._client)  # :func:`~dev_lab.dev.forgestatus.fingerprints_at`

    def declaration(self, ref: str) -> str:
        """The ``pyproject.toml`` at *ref*, as the forge holds it (:func:`dev_lab.dev.reviewgate.manifest_at`)."""
        return manifest_at(self._client, ref)

    def pull(self, number: int) -> tuple[str, str, str]:
        """``(state, base, head_sha)`` of PR *number*."""
        found = self._client.pr_view(number)
        return found.state, found.base, found.head_sha

    def statuses(self, head: str) -> Sequence[CommitStatus]:
        """The commit statuses *head* carries (:func:`dev_lab.dev.forgestatus.status_list`)."""
        return status_list(self._client, head)

    def open_pulls(self) -> Sequence[Pull]:
        """Every open PR (:func:`dev_lab.dev.forgepulls.pr_list`)."""
        return [Pull(one.number, one.base, one.head_sha, one.draft) for one in pr_list(self._client)]

    def labels(self, number: int) -> tuple[str, ...]:
        """The labels PR *number* carries, read fresh (both backends' pull JSON lists them by name)."""
        return self._client.pr_view(number).labels

    def comment(self, number: int, body: str) -> None:
        """Comment on PR *number*."""
        self._client.issue_comment(number, body)

    def merge(self, number: int, *, head: str, message: str) -> None:
        """Merge PR *number* at *head* (:func:`dev_lab.dev.forgemergecall.merge`, either backend).

        Its head branch is deleted exactly when the integration path would delete it (D18): when the branch set
        the repo declares AT THE PR'S BASE (:func:`dev_lab.dev.branchset.branchset_from`, the one parser) puts the
        head name in an ephemeral namespace. A long-lived branch (the trunk, a declared session) is never deleted.
        The forge refuses a *head* that moved, so a moved head is neither merged nor deleted.
        """
        found = self._client.pr_view(number)
        declared = branchset_from(manifest_at(self._client, found.base), f'pyproject.toml at {found.base}')
        merge(self._client, number, head=head, message=message, delete_branch=declared.is_ephemeral(found.head))


def _installation_token(url: str, app_id: int, key_file: Path) -> str:
    return installation(forge_of_url(url), app_id, key_file)[1]


def credential(
    role: Breakglass, url: str, *, secret: Callable[[str], str],
    mint: Callable[[str, int, Path], str] = _installation_token,
) -> str:  # fmt: skip
    """The token break-glass presents on *url*'s forge: *mint* its App's installation token, else *secret* its file.

    On a forge with an App (GitHub) the token is minted per wave by :func:`dev_lab.dev.forgeapp.installation`, the
    ONE minting code; a token forge (Gitea) reads its declared file.
    """
    if (app := app_of_forge(role.apps, url)) is not None:
        return mint(url, *app)
    return secret(role.token_file(url))
