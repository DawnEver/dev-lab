"""BEHIND-IS-BOUNDED at push time: a branch too far behind ``origin/<integration>`` is refused before git sends it.

A lane that drifts far behind integration is a large, late merge; the cheap moment to take integration in
is before the push. The bound is the lane policy's ``behind_max`` (:mod:`lab_commons.dev.lanepolicy`),
declared once; the remedy the refusal names is ``python -m lab_commons.dev.forge sync``. The integration
and trunk branches are exempt (they ARE what a lane is measured against), and so are deletions and
anything outside ``refs/heads/``. Behind is counted against the LOCAL ``origin/<integration>`` ref -- the
last fetch -- because a pre-push hook makes no network call. A checkout with no such ref has no
integration branch to be behind, and passes; a pushed commit git cannot count is refused as unjudgeable.

THE REFSPEC ARRIVES ON STDIN, git's pre-push protocol, parsed once by
:func:`lab_commons.dev.branchset_push.pushed_refs`.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Final

from lab_commons.dev.branchset_push import pushed_refs
from lab_commons.dev.forge import _GIT, _GIT_TIMEOUT_S
from lab_commons.dev.lanepolicy import Policy, load_policy
from lab_commons.log import emit

__all__ = ['ALLOWED', 'COULD_NOT_JUDGE', 'REFUSED', 'REMEDY', 'behind', 'main', 'refusal']

ALLOWED: Final = 0
REFUSED: Final = 1
COULD_NOT_JUDGE: Final = 2

#: What a refused branch runs to take integration in.
REMEDY: Final = 'python -m lab_commons.dev.forge sync'


def behind(root: Path, sha: str, base: str) -> int | None:
    """How many commits *base* has that *sha* lacks; ``None`` when git cannot say (a ref or object missing)."""
    done = subprocess.run(
        [_GIT, 'rev-list', '--count', f'{sha}..{base}'],
        cwd=root, capture_output=True, text=True, encoding='utf-8', timeout=_GIT_TIMEOUT_S, check=False,
    )  # fmt: skip
    return int(done.stdout.strip()) if done.returncode == 0 else None


def refusal(root: Path, *, lines: Iterable[str] = (), policy: Policy | None = None) -> tuple[int, str]:
    """The verdict for one push: ``(ALLOWED, '')``, ``(REFUSED, why)`` or ``(COULD_NOT_JUDGE, why)``."""
    policy = load_policy(root) if policy is None else policy
    base = f'refs/remotes/origin/{policy.integration}'
    exempt = {policy.integration, policy.trunk}
    if behind(root, base, base) is None:  # no integration branch here: nothing to be behind
        return ALLOWED, ''
    judged = [r for r in pushed_refs(lines) if not r.deleted and r.branch is not None and r.branch not in exempt]
    over: list[str] = []
    for ref in judged:
        count = behind(root, ref.local_sha, base)
        if count is None:
            return COULD_NOT_JUDGE, (
                f'[behind-push] REFUSED -- cannot count {ref.branch} against {base.removeprefix("refs/remotes/")}: '
                f'git cannot read {ref.local_sha} here.\n'
            )
        if count > policy.behind_max:
            over.append(f'{ref.branch} is {count} behind')
    if not over:
        return ALLOWED, ''
    return REFUSED, (
        f'[behind-push] REFUSED -- {"; ".join(over)} origin/{policy.integration} '
        f'(bound: {policy.behind_max}, [tool.lab_commons.integrator] behind_max).\n'
        f'[behind-push]   REMEDY: {REMEDY}, then push again.\n'
    )


def main(argv: Sequence[str] | None = None) -> int:
    """``python -m lab_commons.dev.behindpush [ROOT]`` -- the pre-push entry point, refspec lines on stdin."""
    args = list(sys.argv[1:] if argv is None else argv)
    root = Path(args[0]) if args else Path.cwd()
    lines = () if sys.stdin.isatty() else tuple(sys.stdin.read().splitlines())
    code, text = refusal(root, lines=lines)
    if text:
        emit(text, err=True)
    return code


if __name__ == '__main__':
    raise SystemExit(main())
