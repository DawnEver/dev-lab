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
    'ACTIONS',
    'ACTIONS_BOT',
    'ADVISORY',
    'BACKENDS',
    'FORGE_SERVE',
    'GITEA',
    'GITEA_ACTIONS_LOGIN',
    'GITHUB',
    'GITHUB_HOST',
    'JUDGE_HOST',
    'Backend',
    'NotWired',
    'actions_token',
    'backend_for',
    'require_producer',
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


#: THE PRODUCERS a forge may wire -- who posts a check its merge or promotion reads (user ruling 2026-11-11):
#: the forge's own Actions jobs; a ``forge serve`` host (a cluster account, a workstation) claiming parts and
#: reviewing; the isolated judge host (a Gitea login or a GitHub App) posting the review verdict.
ACTIONS: Final = 'actions'
FORGE_SERVE: Final = 'forge-serve'
JUDGE_HOST: Final = 'judge-host'


#: The producers whose verdict is INFORMATION, never a merge condition, on every forge (user ruling 2026-11-11): the
#: judge host's review is posted, and no merge gate, required context or approval count waits on it.
ADVISORY: Final = frozenset({JUDGE_HOST})


class NotWired(ValueError):
    """A declaration asks for a producer its forge does not wire (:attr:`Backend.producers`)."""


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
    #: The repository permissions ``GET .../collaborators/{login}/permission`` answers for a login that may WRITE.
    writer_permissions: frozenset[str] = frozenset({'admin', 'owner', 'write'})
    #: Whether an author must be VETTED before the forge merges their PR or admits their cap raise. Gitea is the
    #: family's private forge: every author is trusted (user ruling 2026-11-06). GitHub is public: a fork's head
    #: or an author without write permission is external (:meth:`~dev_lab.dev.forgework.Client.trusts`).
    vets_authors: bool = False
    #: What the issue listing adds to exclude pulls server-side: Gitea's ``type=issues``. GitHub has no such
    #: parameter (it answers 422), so its listing filters pulls client-side (:func:`dev_lab.dev.forgepulls.is_pull`).
    issues_only: tuple[tuple[str, str], ...] = (('type', 'issues'),)
    #: The ``path`` an Actions run of the base's workflow ``{workflow}`` for pull request ``{pull}`` is listed with:
    #: Gitea's ``<file>@refs/pull/<n>/head`` names the pull request; GitHub's is the workflow file alone.
    run_path: str = '{workflow}@refs/pull/{pull}/head'
    #: Whether a run names its pull request in ``pull_requests`` instead of its ``path`` (GitHub).
    run_pulls_listed: bool = False
    #: A pull request's unified diff: the suffix on ``pulls/{n}`` and the ``Accept`` it is asked with -- Gitea's
    #: ``pulls/{n}.diff``, GitHub's ``pulls/{n}`` as ``application/vnd.github.diff``.
    diff_at: tuple[str, str] = ('.diff', 'text/plain')
    #: Who may produce a check this forge's merge and promotion read. Gitea, the family's private forge, wires
    #: every producer; GitHub, whose repos are the toolchain, wires its Actions alone (user ruling 2026-11-11).
    producers: frozenset[str] = frozenset({ACTIONS, FORGE_SERVE, JUDGE_HOST})

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
    writer_permissions=frozenset({'admin', 'maintain', 'write'}),
    vets_authors=True,
    issues_only=(),
    run_path='.github/workflows/{workflow}',
    run_pulls_listed=True,
    producers=frozenset({ACTIONS}),
    diff_at=('', 'application/vnd.github.diff'),
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


#: Every backend by its name (``github``, ``gitea``): what a rendered workflow's ``forge`` key names.
BACKENDS: Final = {backend.name: backend for backend in (GITEA, GITHUB)}


def require_producer(backend: Backend, producer: str, what: str) -> None:
    """Refuse *what* when *backend* does not wire *producer* (:attr:`Backend.producers`).

    Raises:
        NotWired: naming *what*, the producer and the forge.

    """
    if producer not in backend.producers:
        msg = (
            f'{what} needs the {producer} producer, which {backend.name} does not wire: its repos are tested and gated '
            f'by {", ".join(sorted(backend.producers))} alone (user ruling 2026-11-11)'
        )
        raise NotWired(msg)
