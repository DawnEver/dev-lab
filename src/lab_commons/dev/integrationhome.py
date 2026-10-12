"""INTEGRATION-LIVES-IN-THE-MAIN-CHECKOUT: the integration branch and the trunk have ONE home.

User ruling 2026-10-12. THE INCIDENT: a consumer's integrator merged and committed ``integrate/main``
from a LINKED worktree while the MAIN checkout -- on that same branch -- sat 52 commits behind it. The
worktree's reason (a local heavy run importing the main tree) had gone with local heavy runs; the
habit stayed, and two checkouts of the long-lived branches drifted apart on one box.

So the declared integration branch and trunk (``[tool.lab_commons.integrator]``, read through
:func:`lab_commons.dev.lanepolicy.load_policy`, never spelled here) live in the main checkout, whose
single editor is the integrator; lanes live in linked worktrees on lane branches. Two halves:

* :func:`refusal` -- the commit-time refusal. Installed at ``commit-msg`` because that stage runs for
  a merge commit too (``pre-commit`` does not), and the incident WAS a merge commit. It is the
  counterpart of a consumer's "development belongs in a worktree, not on the checkout's own main":
  that one keeps lanes out of the main checkout, this one keeps the integration line out of lanes.
* :func:`staleness` -- the session-start note: the main checkout's integration branch or trunk is
  behind its origin by N commits, and the fast-forward that clears it.

Which checkout this is comes from git (``--git-dir`` against ``--git-common-dir``), never a path
convention. No escape hatch: the way past is the workflow the refusal names.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

from lab_commons.dev.lanepolicy import load_policy
from lab_commons.dev.worktreeplace import main_checkout
from lab_commons.log import emit

__all__ = ['RULE', 'main', 'refusal', 'staleness']

RULE = 'INTEGRATION-LIVES-IN-THE-MAIN-CHECKOUT'
_GIT = shutil.which('git') or 'git'
_PULL = 'sh scripts/hooks/with-retry.sh pull --ff-only'


def _git(root: Path, *args: str) -> str | None:
    done = subprocess.run(
        [_GIT, '-C', str(root), *args], capture_output=True, text=True, encoding='utf-8', check=False, timeout=30
    )
    return done.stdout.strip() if done.returncode == 0 else None


def _is_linked(root: Path) -> bool:
    paths = _git(root, 'rev-parse', '--path-format=absolute', '--git-dir', '--git-common-dir')
    if paths is None:
        return False
    git_dir, common = (Path(line).resolve() for line in paths.splitlines())
    return git_dir != common


def _long_lived(root: Path) -> frozenset[str]:
    policy = load_policy(root)
    return frozenset({policy.integration, policy.trunk})


def refusal(root: Path) -> str | None:
    """Why a commit at *root* is refused: a LINKED worktree whose HEAD is the integration branch or trunk."""
    top = _git(root, 'rev-parse', '--show-toplevel')
    branch = _git(root, 'symbolic-ref', '--short', '-q', 'HEAD')
    if top is None or not branch or not _is_linked(root) or branch not in _long_lived(Path(top)):
        return None
    home = main_checkout(root)
    return (
        f'{RULE}: this linked worktree ({top}) is on `{branch}`, a declared long-lived branch; it has ONE home, '
        f'the main checkout ({home}), whose single editor is the integrator.\n'
        f'  Remedy: commit or merge it in the main checkout ({home}), or put this work on a lane branch in '
        f'this worktree (git switch -c lane/<name>) and merge that lane from the main checkout.'
    )


def staleness(root: Path) -> str | None:
    """The main checkout's integration branch or trunk is behind its origin: by how much, and the remedy."""
    home = main_checkout(root)
    branch = _git(home, 'symbolic-ref', '--short', '-q', 'HEAD')
    if not branch or branch not in _long_lived(home):
        return None
    count = _git(home, 'rev-list', '--count', f'HEAD..origin/{branch}')
    if not count or count == '0':
        return None
    return (
        f'integration-home: the main checkout ({home}) is on `{branch}`, behind origin/{branch} by {count} '
        f'commit(s). Fast-forward it there: {_PULL}'
    )


def main(argv: list[str] | None = None) -> int:
    """``commit-msg [msgfile]`` refuses (exit 1); ``report`` prints the staleness note and always exits 0."""
    parser = argparse.ArgumentParser(prog='lab_commons.dev.integrationhome', description=__doc__.splitlines()[0])
    parser.add_argument('mode', choices=('commit-msg', 'report'))
    parser.add_argument('rest', nargs='*', help='git hook arguments (ignored)')
    parser.add_argument('--root', type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    if args.mode == 'report':
        emit(staleness(args.root) or 'integration-home: the main checkout is current.')
        return 0
    reason = refusal(args.root)
    if reason is None:
        return 0
    emit(f'\n  REFUSED: {reason}\n', err=True)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
