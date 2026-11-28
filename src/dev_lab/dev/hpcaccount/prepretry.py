"""THE DOOR TO A FAILED PREP JOB: ``hpcaccount prep-retry --account <user> <repo>``.

Measured 2026-11-28 (Ada, ezxmw9/ezztz): a served repo's environment prep jobs failed ``Failed to build a native library
through cargo`` before the kit installed cargo; the cause was fixed, yet every tick reported ``job <id> failed`` and
nothing could retry -- the failure is never retried blind (:func:`lab_commons.hpc.prep.submit_env_prep`). A failure
under an OLDER kit is resubmitted by the tick itself (:func:`~dev_lab.dev.hpcaccount.prep.kit_of`); this is the door
for one under the current kit, once its cause is fixed elsewhere (a module, a quota, a flaky node).

``prep-retry`` runs, through the account's own transport pinned to its declared login host (no raw ssh), the
ACCOUNT'S OWN kit: ``python -m dev_lab.dev.hpcaccount prep-retry-here <repo>``
(:func:`~dev_lab.dev.hpcaccount.tick.prep_retry`), which reads the
repo's current environment key and asks the prep job with ``retry`` -- one job submitted over the failure, never a
build on the login node (ONE-LOGIN-POLLER). An environment already current is said and nothing submitted.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence

from dev_lab.dev.hpcaccount import look, tick
from dev_lab.dev.hpcaccount.fleet import declared_target, in_checkout
from dev_lab.dev.hpcaccount.storage import Pin, on_host
from dev_lab.dev.hpcaccount.transport import grant_runner

__all__ = ['main', 'main_here', 'retry', 'retry_command']


def retry_command(repo: str) -> list[str]:
    """The on-account argv of ``prep-retry-here``."""
    return ['-m', 'dev_lab.dev.hpcaccount', 'prep-retry-here', repo]


def retry(
    user: str,
    repo: str,
    *,
    connect: Callable[..., look.Runner] = grant_runner,
    pin: Pin = on_host,
    say: Callable[[str], None] = tick.emit,
) -> int:
    """Run ``prep-retry-here <repo>`` on *user*'s declared login host; 2 refused or unreachable."""
    if not look.REPO_NAME.fullmatch(repo):
        say(f'prep-retry: {repo!r} is not a repo name')
        return 2
    try:
        grant = next(g for g in look.reached_machine([user]).grants if g.user == user)
        target = declared_target(grant, connect(grant))
        if isinstance(target, str):
            say(target)
            return 2
        out = pin(grant, target.host)(in_checkout(target, retry_command(repo)) + '; echo "rc=$?"', None)
    except (PermissionError, LookupError, RuntimeError, OSError, ValueError) as refused:
        say(f'prep-retry: {user}: refused -- {refused}')
        return 2
    lines = out.rstrip().splitlines()
    for line in lines[:-1] if lines and lines[-1].startswith('rc=') else lines:
        say(line)
    return 0 if lines and lines[-1] == 'rc=0' else 2


def main_here(argv: Sequence[str]) -> int:
    """``prep-retry-here <repo>``: run ON the account by ``prep-retry``."""
    parser = argparse.ArgumentParser(prog='dev_lab.dev.hpcaccount prep-retry-here')
    parser.add_argument('repo')
    return tick.prep_retry(parser.parse_args(list(argv)).repo)


def main(argv: Sequence[str]) -> int:
    """``prep-retry --account <user> <repo>``."""
    parser = argparse.ArgumentParser(prog='dev_lab.dev.hpcaccount prep-retry')
    parser.add_argument('--account', required=True)
    parser.add_argument('repo')
    args = parser.parse_args(list(argv))
    return retry(args.account, args.repo)
