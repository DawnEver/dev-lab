"""What differs between the two forges :mod:`dev_lab.dev.forgework` speaks: one table row each.

Split out of ``forgework`` (MODULE-SIZE-ALARM) as data; ``forgework`` re-exports every name, so the
public import path is unchanged.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from dev_lab.dev.forge import Forge

__all__ = ['ACTIONS_BOT', 'GITEA', 'GITHUB', 'GITHUB_HOST', 'Backend', 'actions_token', 'backend_for']

#: The one host that is GitHub. Every other host is treated as the Gitea-shaped forge.
GITHUB_HOST: Final = 'github.com'

#: The login GitHub records for every write a workflow's job token makes: the author a GitHub ledger is trusted by.
ACTIONS_BOT: Final = 'github-actions[bot]'


@dataclass(frozen=True)
class Backend:
    """What differs between forges: where the API lives, how it authenticates, how it lists issues."""

    name: str
    api_root: str
    auth_scheme: str
    list_query: str
    fixed_host: str | None = None
    headers: tuple[tuple[str, str], ...] = ()
    page_param: str = 'limit'
    #: Where a branch is DELETED, relative to the repository collection; ``{name}`` is the branch.
    branch_delete: str = 'branches/{name}'

    def host(self, forge: Forge) -> str:
        """The API host: GitHub's is fixed, a Gitea forge serves its API on its own host."""
        return self.fixed_host or forge.host

    def repo_path(self, forge: Forge) -> str:
        """The repository's API collection."""
        return f'{self.api_root}/repos/{forge.owner}/{forge.repo}'


GITEA: Final = Backend(
    name='gitea',
    api_root='/api/v1',
    auth_scheme='token',
    list_query='state={state}&type=issues&limit={limit}',
)

GITHUB: Final = Backend(
    name='github',
    api_root='',
    auth_scheme='Bearer',
    list_query='state={state}&per_page={limit}',
    fixed_host='api.github.com',
    page_param='per_page',
    branch_delete='git/refs/heads/{name}',
    headers=(
        ('Accept', 'application/vnd.github+json'),
        ('X-GitHub-Api-Version', '2022-11-28'),
    ),
)


def backend_for(forge: Forge) -> Backend:
    """GitHub for ``github.com``, the Gitea-shaped forge for every other host."""
    return GITHUB if forge.host.lower() == GITHUB_HOST else GITEA


def actions_token(forge: Forge, env: Mapping[str, str]) -> str:
    """The job's ``GITHUB_TOKEN`` when this process runs inside GitHub Actions against GitHub, else ``''``.

    WHO PRODUCES differs between the forges, never what is produced: on GitHub the parts, the review and the merge
    decision run as workflow jobs, where no git credential store exists and the job token is the credential. Read
    ONLY there (``GITHUB_ACTIONS=true`` and a ``github.com`` remote): anywhere else the store is the one source.
    """
    if backend_for(forge) is not GITHUB or env.get('GITHUB_ACTIONS') != 'true':
        return ''
    return env.get('GITHUB_TOKEN', '')
