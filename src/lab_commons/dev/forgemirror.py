"""GITHUB-PRS-ARRIVE-ON-THE-FORGE: each open PR on the GitHub mirror is carried to gitea as ``pr/gh-<N>``.

User ruling 2026-10-19: gitea is the single source of truth; GitHub (``DawnEver/*``) is a read-only public
mirror, and cloud sessions -- which reach only GitHub -- open their pull requests there. So the forge tick
(:func:`lab_commons.dev.forgeintegration.main`, and every ``forge serve`` tick) carries each one across:

1. fetches the GitHub PR's head (``refs/pull/<N>/head``, a fork's included) from the mirror declared ONCE
   as ``[tool.lab_commons.integrator] mirror``;
2. DROPS each commit that only registers the PR's own branch in ``[tool.lab_commons.branchset] sessions``
   (:func:`drop_registrations`) -- the hack the ephemeral namespace made unnecessary. The commits after it are
   replayed in the object store with their authors, committers, dates and messages kept, so the same GitHub
   head gives the same sha on every tick and every host;
3. pushes that commit to gitea's ``pr/gh-<N>`` (a declared ephemeral namespace) when it differs;
4. opens -- or brings up to date -- one gitea PR from ``pr/gh-<N>`` into integration, its title and body
   carried with a link back;
5. keeps ONE comment on the GitHub PR linking the gitea one (:func:`lab_commons.dev.forgepulls.comment_upsert`);
6. once that gitea PR has merged or closed, says so in the same comment and CLOSES the GitHub PR.

Idempotent: a second tick pushes nothing, opens nothing and writes no comment. The GitHub credential is read
like the forge's (``git credential fill`` for ``github.com``, :func:`lab_commons.dev.forgework.client_for`) and
never printed.

THE PUSH SKIPS THE PUSHING CHECKOUT'S HOOKS (``--no-verify``), and only this one: it is a machine copy into
a declared ephemeral namespace, judged by the forge's parts like any PR head. The client hooks judge a ref by
the declaration its pushed commit carries, which a GitHub head cut before the namespace existed does not.
"""

from __future__ import annotations

import os
import re
import subprocess
import tomllib
from collections.abc import Callable, Mapping
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import lab_commons.launch as _door
from lab_commons.dev.forge import _GIT, _GIT_TIMEOUT_S
from lab_commons.dev.forgepulls import Marker, comment_list, comment_upsert, marker, pr_list
from lab_commons.dev.forgework import PullRequest, client_for, pull_of
from lab_commons.dev.netverb import run_network_verb
from lab_commons.dev.trialmerge import rev
from lab_commons.hpc.declared import pyproject_at

if TYPE_CHECKING:
    from collections.abc import Sequence

    from lab_commons.dev.forgework import Client
    from lab_commons.dev.lanepolicy import Policy

__all__ = ['PREFIX', 'drop_registrations', 'mirror', 'mirror_client', 'registers_only', 'step']

#: The gitea branch namespace a GitHub PR's head is carried to: ``pr/gh-<N>``.
PREFIX: Final = 'pr/gh-'

_PULLS: Final = 'refs/lab-commons/pulls/mirror/'
_GITEA_PULL: Final = re.compile(r'/pulls/(\d+)\b')
_MANIFEST: Final = 'pyproject.toml'

#: ``(root, number) -> sha``: fetch GitHub PR *number*'s head into the object store.
FetchPull = Callable[[Path, int], str]


def _git(root: Path, *args: str, env: Mapping[str, str] | None = None) -> tuple[int, str]:
    done = _door.run(
        [_GIT, *args],
        cwd=root,
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        timeout=_GIT_TIMEOUT_S,
        check=False,
        env=None if env is None else {**os.environ, **env},
    )
    return done.returncode, done.stdout


def _fetch_pull(root: Path, number: int, *, url: str) -> str:
    """Fetch PR *number*'s head from the repository at *url* through the retry wrapper; its sha."""
    ref = f'{_PULLS}{number}'
    report = run_network_verb([_GIT, 'fetch', '--quiet', url, f'+refs/pull/{number}/head:{ref}'], cwd=root, timeout=300)
    if not report.ok:
        raise OSError(report.remedy)
    found = rev(root, ref)
    if found is None:
        msg = f'pull {number} on {url} fetched no commit'
        raise OSError(msg)
    return found


def _push(root: Path, sha: str, branch: str) -> None:
    report = run_network_verb(
        [_GIT, 'push', '--quiet', '--no-verify', 'origin', f'+{sha}:refs/heads/{branch}'], cwd=root, timeout=300
    )
    if not report.ok:
        raise OSError(report.remedy)


def _sessions_apart(text: str) -> tuple[dict[str, Any], frozenset[str]]:
    """The manifest without its branch-set sessions, and those sessions."""
    data = tomllib.loads(text)
    table = data.get('tool', {}).get('lab_commons', {}).get('branchset', {})
    sessions = table.pop('sessions', []) if isinstance(table, dict) else []
    return data, frozenset(sessions if isinstance(sessions, list) else ())


def registers_only(root: Path, commit: str, branch: str) -> bool:
    """Whether *commit* does nothing but add *branch* to ``[tool.lab_commons.branchset] sessions``."""
    code, parents = _git(root, 'rev-list', '--parents', '-n', '1', commit)
    if code != 0 or len(parents.split()) != 2:  # noqa: PLR2004 -- the commit and its one parent
        return False
    _, changed = _git(root, 'diff-tree', '--no-commit-id', '--name-only', '-r', f'{commit}^', commit)
    if changed.split() != [_MANIFEST]:
        return False
    try:
        before, old = _sessions_apart(pyproject_at(root, f'{commit}^'))
        after, new = _sessions_apart(pyproject_at(root, commit))
    except (OSError, ValueError, subprocess.CalledProcessError):  # a TOMLDecodeError is a ValueError
        return False
    return before == after and old < new and new - old == {branch}


def _replay(root: Path, commit: str, onto: str, parent: str) -> str | None:
    """*commit* re-made on *onto* instead of its first parent *parent*, everything else kept; ``None``: conflicts."""
    code, out = _git(root, 'merge-tree', '--write-tree', f'--merge-base={parent}', onto, commit)
    if code != 0:
        return None
    _, raw = _git(root, 'log', '-1', '--format=%an%x00%ae%x00%aI%x00%cn%x00%ce%x00%cI%x00%P%x00%B', commit)
    an, ae, ad, cn, ce, cd, parents, message = raw.split('\x00', 7)
    env = {
        'GIT_AUTHOR_NAME': an, 'GIT_AUTHOR_EMAIL': ae, 'GIT_AUTHOR_DATE': ad,
        'GIT_COMMITTER_NAME': cn, 'GIT_COMMITTER_EMAIL': ce, 'GIT_COMMITTER_DATE': cd,
    }  # fmt: skip
    others = [arg for sha in parents.split()[1:] for arg in ('-p', sha)]
    # Unsigned on purpose: the replay must give the same sha on every host, and no host holds the author's key.
    code, made = _git(
        root, 'commit-tree', '--no-gpg-sign', out.split()[0], '-p', onto, *others, '-m', message.rstrip('\n'), env=env
    )
    return made.strip() if code == 0 else None


def drop_registrations(root: Path, base: str, head: str, branch: str) -> str:
    """*head* without the commits (first-parent, past *base*) that only register *branch* as a session.

    The commits after a dropped one are replayed onto its parent (:func:`_replay`); *head* itself when there is
    nothing to drop, or when a replay conflicts (the hack then stays, and its PR shows it).
    """
    _, listed = _git(root, 'rev-list', '--first-parent', '--reverse', head, f'^{base}')
    line = listed.split()
    if not any(registers_only(root, sha, branch) for sha in line):
        return head
    moved: dict[str, str] = {}
    for sha in line:
        _, parents = _git(root, 'rev-list', '--parents', '-n', '1', sha)
        parent = parents.split()[1]
        onto = moved.get(parent, parent)
        if registers_only(root, sha, branch):
            moved[sha] = onto
        elif onto == parent:
            moved[sha] = sha
        elif (made := _replay(root, sha, onto, parent)) is not None:
            moved[sha] = made
        else:
            return head
    return moved[head]


def mirror_client(root: Path, policy: Policy) -> Client | None:
    """The GitHub mirror's client, or ``None`` when the repo declares no mirror."""
    return client_for(root, url=policy.mirror) if policy.mirror else None


def _body(pr: PullRequest) -> str:
    return f'{pr.body}\n\n---\nMirrored from {pr.url} (GitHub PR #{pr.number}, by {pr.author}).'


def _linked(github: Client, number: int) -> int | None:
    """The gitea PR this GitHub PR's mirror comment links, or ``None`` when it was never mirrored."""
    line = marker(Marker.MIRROR)
    for comment in comment_list(github, number):
        if line in comment.body and (found := _GITEA_PULL.search(comment.body)):
            return int(found.group(1))
    return None


def _finish(origin: Client, github: Client, pr: PullRequest, number: int) -> str | None:
    """Close GitHub *pr* once its gitea PR *number* is no longer open; the line said, or ``None`` while open."""
    raw = origin.call('GET', f'{origin.repo}/pulls/{number}')
    done = pull_of(raw)
    if done.state == 'open':
        return None
    how = 'merged' if raw.get('merged') else 'closed without merging'
    comment_upsert(
        github, pr.number, kind=Marker.MIRROR,
        text=f'Its forge pull request {done.url} was {how}; this mirror PR is closed. '
        'The forge is the source of truth.',
    )  # fmt: skip
    github.call('PATCH', f'{github.repo}/pulls/{pr.number}', {'state': 'closed'})
    return f'github #{pr.number}: forge #{number} {how}; closed'


def _carry(
    root: Path, origin: Client, policy: Policy, pr: PullRequest, sha: str, *, found: PullRequest | None
) -> tuple[str, PullRequest]:
    """Push *sha* to ``pr/gh-<N>`` when it differs, and open or update its gitea PR; the line said, and that PR."""
    branch = f'{PREFIX}{pr.number}'
    said = []
    if rev(root, f'refs/remotes/origin/{branch}') != sha:
        _push(root, sha, branch)
        said.append(f'pushed {sha[:12]}')
    body = _body(pr)
    if found is None:
        found = origin.pr_create(pr.title, body, head=branch, base=policy.integration)
        said.append(f'opened forge #{found.number}')
    elif found.title != pr.title or not found.body.endswith(body):
        origin.call('PATCH', f'{origin.repo}/pulls/{found.number}', {'title': pr.title, 'body': body})
        said.append(f'updated forge #{found.number}')
    return f'github #{pr.number} -> {branch} forge #{found.number}: {", ".join(said) or "unchanged"}', found


def mirror(
    root: Path, origin: Client, github: Client, policy: Policy, *, fetch_pull: FetchPull | None = None
) -> tuple[str, ...]:
    """One pass over the mirror's open PRs (see the module docstring); a line per PR."""
    fetch = fetch_pull or partial(_fetch_pull, url=policy.mirror)
    base = f'refs/remotes/origin/{policy.integration}'
    open_here = {pr.head: pr for pr in pr_list(origin) if pr.head.startswith(PREFIX)}
    lines: list[str] = []
    for pr in pr_list(github):
        found = open_here.get(f'{PREFIX}{pr.number}')
        linked = _linked(github, pr.number) if found is None else None
        if linked is not None and (closed := _finish(origin, github, pr, linked)) is not None:
            lines.append(closed)
            continue
        sha = drop_registrations(root, base, fetch(root, pr.number), pr.head)
        line, target = _carry(root, origin, policy, pr, sha, found=found)
        comment_upsert(
            github, pr.number, kind=Marker.MIRROR,
            text=f'Mirrored to the forge as {target.url}: it is tested and merged into `{policy.integration}` '
            'there, and this PR closes when that one merges or closes.',
        )  # fmt: skip
        lines.append(line)
    return tuple(lines)


def step(root: Path, origin: Client, policy: Policy, *, say: Callable[[str], None]) -> Sequence[str]:
    """The tick's mirror step: :func:`mirror` when a mirror is declared; nothing otherwise."""
    github = mirror_client(root, policy)
    if github is None:
        return ()
    lines = mirror(root, origin, github, policy)
    for line in lines:
        say(f'[mirror] {line}')
    return lines
