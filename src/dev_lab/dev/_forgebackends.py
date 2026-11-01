"""What differs between the two forges :mod:`dev_lab.dev.forgework` speaks: one table row each.

Split out of ``forgework`` (MODULE-SIZE-ALARM) as data; ``forgework`` re-exports every name, so the
public import path is unchanged.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from dev_lab.dev.forge import Forge

__all__ = [
    'ACTIONS_BOT',
    'GITEA',
    'GITEA_ACTIONS_LOGIN',
    'GITHUB',
    'GITHUB_HOST',
    'Backend',
    'actions_token',
    'backend_for',
]

#: The one host that is GitHub. Every other host is treated as the Gitea-shaped forge.
GITHUB_HOST: Final = 'github.com'

#: The login GitHub records for every write a workflow's job token makes: the author a GitHub ledger is trusted by.
ACTIONS_BOT: Final = 'github-actions[bot]'

#: The login Gitea records for every comment or issue a workflow job token writes: its Actions system user (id -2),
#: which the API resolves through ``GetPossibleUserByID`` (models/user/user.go). Trusting it by LOGIN is sound only
#: because Gitea RESERVES it: ``reservedUsernames`` holds ``"gitea-actions", // gitea builtin user (id: -2)`` and
#: ``IsUsableUsername`` refuses it, so no account can register it (Gitea main, models/user/user.go).
GITEA_ACTIONS_LOGIN: Final = 'gitea-actions'


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
    #: Where the web UI shows a file at a commit, relative to the repository's web root.
    file_at: str = 'src/commit/{sha}/{path}'
    #: The login a workflow job token writes comments and issues as: the forge's own Actions identity.
    actions_login: str = GITEA_ACTIONS_LOGIN

    def host(self, forge: Forge) -> str:
        """The API host: GitHub's is fixed, a Gitea forge serves its API on its own host."""
        return self.fixed_host or forge.host

    def repo_path(self, forge: Forge) -> str:
        """The repository's API collection."""
        return f'{self.api_root}/repos/{forge.owner}/{forge.repo}'

    def commit_url(self, repo: str, sha: str) -> str:
        """The web page of commit *sha* in the repository whose web root is *repo*."""
        return f'{repo}/commit/{sha}'

    def file_url(self, repo: str, sha: str, path: str) -> str:
        """The web page of *path* as it stands at commit *sha* in the repository whose web root is *repo*."""
        return f'{repo}/' + self.file_at.format(sha=sha, path=path)


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
    file_at='blob/{sha}/{path}',
    actions_login=ACTIONS_BOT,
    headers=(
        ('Accept', 'application/vnd.github+json'),
        ('X-GitHub-Api-Version', '2022-11-28'),
    ),
)


def backend_for(forge: Forge) -> Backend:
    """GitHub for ``github.com``, the Gitea-shaped forge for every other host."""
    return GITHUB if forge.host.lower() == GITHUB_HOST else GITEA


def actions_token(forge: Forge, env: Mapping[str, str]) -> str:
    """The job's ``GITHUB_TOKEN`` when this process runs as a workflow job ON *forge*'s own Actions, else ``''``.

    WHO PRODUCES differs between the forges, never what is produced: the parts, the review and the merge decision
    may run as workflow jobs, where no git credential store exists and the job token is the credential. Read ONLY
    there: GitHub Actions (``GITHUB_ACTIONS=true``) against a ``github.com`` remote, or Gitea Actions (its runner
    sets ``GITEA_ACTIONS=true`` as well) against a Gitea remote. Anywhere else the store is the one source.
    """
    if env.get('GITHUB_ACTIONS') != 'true':
        return ''
    if (env.get('GITEA_ACTIONS') == 'true') != (backend_for(forge) is GITEA):
        return ''
    return env.get('GITHUB_TOKEN', '')
