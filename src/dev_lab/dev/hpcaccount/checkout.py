"""A DEPLOYED CHECKOUT CONVERGES ON ITS DECLARED REF: the ``checkouts`` step for a repo that already has a ``.git``.

A deployed checkout is the account's RENDERING of the declared ref and holds nothing of its own, so the step makes
it that ref whatever an interrupted deploy left behind. Measured 2026-11-22 on an account at its file quota: the
first deploy's ``git clone`` died mid-checkout ("Clone succeeded, but checkout failed"), leaving a ``.git``, no
index and a partial work tree git saw as UNTRACKED; every later deploy's ``git checkout -B`` then exited 1
("untracked working tree files would be overwritten by checkout") and the repo was "refused, skipped by every later
step" forever.

:func:`converge` fetches the ref and forces it (``checkout -f -B``: an untracked file in the way is the interrupted
clone's, overwritten). A ``.git`` git itself cannot read is removed and cloned again. WHAT IS THE ACCOUNT'S OWN IS
STILL REFUSED BY NAME, never forced away: a commit no ``origin`` branch has, and a modified tracked file of a
checkout that has an index (a half-clone has none, so its missing files are not "deletions").
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from lab_commons.log import emit

from dev_lab.dev.diskusage import remove_tree

if TYPE_CHECKING:
    from dev_lab.dev.hpcaccount.spec import Repo
    from dev_lab.dev.hpcaccount.steps import Step

__all__ = ['clone', 'converge']

#: How many modified files a refusal lists.
_SHOWN = 5


def clone(step: Step, checkout: Path, repo: Repo) -> int:
    """Clone *repo* at its declared ref into *checkout*; a failed clone removes what it wrote (user, 2026-11-22)."""
    argv = [*step.tools.git, 'clone', '-q', '-b', repo.ref, repo.url, str(checkout)]
    if rc := step.change(f'git clone -b {repo.ref} {repo.url} {checkout}', argv):
        remove_tree(checkout)  # nothing half-checked-out is left behind
    return rc


def _own(step: Step, checkout: Path) -> str:
    """What *checkout* holds that is the account's own, as a refusal (``''``: nothing; it is forced to the ref)."""
    git = [*step.tools.git, '-C', str(checkout)]
    ahead = step.read([*git, 'rev-list', '--count', 'HEAD', '--not', '--remotes=origin'])
    if ahead.returncode == 0 and int(ahead.stdout.strip() or 0):
        return (
            f'{ahead.stdout.strip()} commit(s) no origin branch has (git log HEAD --not --remotes=origin): push them '
            'through a pull request, or drop them'
        )
    if ahead.returncode or not step.read([*git, 'ls-files']).stdout.strip():
        return ''  # no commit checked out, or no index: an interrupted clone, which holds nothing of its own
    changed = step.read([*git, 'status', '--porcelain', '--untracked-files=no']).stdout.splitlines()
    if changed:
        shown = ', '.join(line[3:] for line in changed[:_SHOWN]) + (', ...' if len(changed) > _SHOWN else '')
        return f'{len(changed)} modified tracked file(s) ({shown}): commit them through a pull request, or restore them'
    return ''


def converge(step: Step, checkout: Path, repo: Repo) -> int:
    """Make the existing *checkout* its declared ref; 2, named, when it holds something of its own."""
    git = [*step.tools.git, '-C', str(checkout)]
    if step.read([*git, 'rev-parse', '--git-dir']).returncode:
        emit(f'  {repo.name}: git cannot read {checkout}/.git (a clone that died mid-way): removed and cloned again')
        if step.dry:
            return 0
        remove_tree(checkout)
        return clone(step, checkout, repo)
    remote = f'refs/remotes/origin/{repo.ref}'
    if rc := step.change(
        f'{repo.name}: git fetch origin {repo.ref}', [*git, 'fetch', '-q', 'origin', f'+refs/heads/{repo.ref}:{remote}']
    ):
        return rc
    if own := _own(step, checkout):
        emit(
            f'  {repo.name}: refused -- {checkout} holds {own}. A deployed checkout is the rendering of {repo.ref} '
            'and takes nothing of its own; then redeploy',
            err=True,
        )
        return 2
    return step.change(
        f'{repo.name}: git checkout -f -B {repo.ref} origin/{repo.ref}',
        [*git, 'checkout', '-q', '-f', '-B', repo.ref, remote],
    )
