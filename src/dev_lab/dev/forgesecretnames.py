"""``forge secrets list [--org]``: the Actions secret NAMES a repository, or its owner org, holds.

Read only, through the family door (:func:`dev_lab.dev.forgework.client_for`: the credential git's store holds for
the checkout's ``origin``, never one read by hand). ``GET <repo>/actions/secrets`` or ``GET /orgs/<owner>/actions/
secrets``: Gitea answers a list, GitHub ``{"secrets": [...]}``, and neither returns a value. Only each row's ``name``
is ever printed, one per line, sorted -- any other field an answer carries is dropped unread. A read the forge
refuses is refused here (exit 2), never read as "holds none": a list that was not read says nothing.

The question it answers: does a member hold a secret it must not (the review bundle is withheld from every
non-GitHub forge, :func:`dev_lab.dev.forgesecrets.withheld`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from lab_commons.log import emit

from dev_lab.dev.forgefailure import ForgeCallFailed

if TYPE_CHECKING:
    from dev_lab.dev.forge import Forge

__all__ = ['Reader', 'listed', 'names']


class Reader(Protocol):
    """The family client's read surface this verb uses."""

    forge: Forge

    @property
    def repo(self) -> str:
        """The repository's API collection path."""
        ...

    def call(self, method: str, path: str) -> object:
        """One REST call through the door."""
        ...


def names(answer: object) -> tuple[str, ...]:
    """The sorted secret names of either forge's answer; every other field is dropped unread."""
    rows = answer.get('secrets', []) if isinstance(answer, dict) else answer if isinstance(answer, list) else []
    return tuple(sorted({str(row['name']) for row in rows if isinstance(row, dict) and row.get('name')}))


def _collection(client: Reader, *, org: bool) -> str:
    if not org:
        return f'{client.repo}/actions/secrets'
    root = client.repo.removesuffix(f'/repos/{client.forge.owner}/{client.forge.repo}')
    return f'{root}/orgs/{client.forge.owner}/actions/secrets'


def listed(client: Reader, *, org: bool) -> int:
    """Print the names, one per line: exit 0, or 2 when the forge refused the read."""
    path = _collection(client, org=org)
    try:
        answer = client.call('GET', path)
    except ForgeCallFailed as refused:
        whose = f'the {client.forge.owner} org' if org else client.forge.identity
        emit(f'[secrets] refused: the secret names of {whose} were not read: {str(refused).splitlines()[0]}',
             err=True)  # fmt: skip
        return 2
    for name in names(answer):
        emit(name)
    return 0
