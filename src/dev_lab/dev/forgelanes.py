"""PUSHED LANES AND THE PULL REQUEST EACH LANDS BY.

The origin branches this checkout tracks, a PR head fetched, and the one PR the forge opens for a pushed
ephemeral lane no PR carries.

:mod:`dev_lab.dev.forgeintegration`'s tick reads these and reports on every child; :mod:`dev_lab.dev.forgetakeover`
fetches the head it reviews with :func:`fetch_pull`.
"""

from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import TYPE_CHECKING, Final

import lab_commons.launch as _door

from dev_lab.dev.branchdelete import landed
from dev_lab.dev.branchset import BranchSetNotDeclared, declared_branchset
from dev_lab.dev.forge import _GIT, _GIT_TIMEOUT_S
from dev_lab.dev.forgemerge import auto_merge
from dev_lab.dev.forgepulls import pr_list
from dev_lab.dev.netverb import run_network_verb
from dev_lab.dev.relock import PREFIX as RELOCK_PREFIX
from dev_lab.dev.trialmerge import rev

if TYPE_CHECKING:
    from dev_lab.dev.forgework import Client
    from dev_lab.dev.lanepolicy import Policy

__all__ = ['OPENED', 'OWNER_CLOSED', 'TRACKING', 'fetch_pull', 'open_lanes', 'read_git', 'tracked']

#: Where this checkout tracks origin's branches.
TRACKING: Final = 'refs/remotes/origin/'
_PULLS: Final = 'refs/lab-commons/pulls/'


def read_git(root: Path, *args: str) -> str:
    """``git <args>``'s stdout in *root*; ``''`` when it fails."""
    done = _door.run(
        [_GIT, *args],
        cwd=root,
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        timeout=_GIT_TIMEOUT_S,
        check=False,
    )
    return done.stdout if done.returncode == 0 else ''


def tracked(root: Path) -> list[tuple[str, str]]:
    """Every origin branch *root* tracks, as ``(branch, sha)``."""
    found = []
    for line in read_git(root, 'for-each-ref', '--format=%(refname) %(objectname)', TRACKING).splitlines():
        ref, sha = line.split(' ')
        found.append((ref.removeprefix(TRACKING), sha))
    return found


def fetch_pull(root: Path, remote: str, number: int) -> str:
    """Fetch PR *number*'s head from *remote* into a private ref; its commit."""
    ref = f'{_PULLS}{remote}/{number}'
    report = run_network_verb(
        [_GIT, 'fetch', '--quiet', remote, f'+refs/pull/{number}/head:{ref}'], cwd=root, timeout=300
    )
    if not report.ok:
        raise OSError(report.remedy)
    found = rev(root, ref)
    if found is None:
        msg = f'pull {number} on {remote} fetched no commit'
        raise OSError(msg)
    return found


#: The body of a PR the tick opens for a pushed lane.
OPENED: Final = (
    'Opened by the forge (`forge integration`): `{branch}` is a pushed `{glob}` lane holding content '
    '`{integration}` lacks, and no pull request carried it. A lane lands by its PR; close this one unmerged '
    'and the forge never opens another for `{branch}`.'
)
#: What the tick says of a lane whose PR its owner closed unmerged: the owner's "do not land".
OWNER_CLOSED: Final = '{branch}: no PR opened -- #{number} was closed unmerged by its owner: do not land'


def open_lanes(
    root: Path, client: Client, policy: Policy, open_heads: set[str]
) -> tuple[list[str], list[tuple[str, str, int]]]:
    """Open the one PR each pushed ephemeral lane lands by; the lines said and each ``(branch, sha, pr)`` opened.

    A lane is an origin branch in a declared ephemeral namespace (``[tool.dev_lab.branchset] ephemeral``) holding
    content integration lacks (:func:`dev_lab.dev.branchdelete.landed`), with no open PR (*open_heads*). A relock
    branch opens its own (:func:`dev_lab.dev.relock.carry`), and a lane whose PR was closed UNMERGED is its
    owner's "do not land": never reopened, only said. The title is the head's newest subject; on GitHub the PR
    is put on auto-merge (:func:`dev_lab.dev.forgemerge.auto_merge`), as ``forge pr create`` does.
    """
    try:
        declared = declared_branchset(root)
    except BranchSetNotDeclared:
        return [], []
    lanes = []
    for branch, sha in tracked(root):
        if branch in open_heads or branch.startswith(f'{RELOCK_PREFIX}-') or not declared.is_ephemeral(branch):
            continue
        if landed(root, policy, f'{TRACKING}{branch}').lost:
            lanes.append((branch, sha))
    if not lanes:
        return [], []
    refused = {pr.head: pr.number for pr in pr_list(client, state='closed') if not pr.merged}
    lines: list[str] = []
    opened: list[tuple[str, str, int]] = []
    for branch, sha in lanes:
        if branch in refused:
            lines.append(OWNER_CLOSED.format(branch=branch, number=refused[branch]))
            continue
        title = read_git(root, 'log', '-1', '--format=%s', sha).strip() or branch
        glob = next(g for g in declared.ephemeral if fnmatch.fnmatchcase(branch, g))
        body = OPENED.format(branch=branch, glob=glob, integration=policy.integration)
        pr = client.pr_create(title, body, head=branch, base=policy.integration, draft=False)  # a lane is done work
        lines.append(f'{branch}: opened #{pr.number} -- {auto_merge(client, pr.number)}')
        opened.append((branch, sha, pr.number))
    return lines, opened
