"""A PUSH BUILDS ON THE NEWEST MILESTONE, and an agent mints no version tag unasked.

User ruling 2026-11-13: a milestone is a version tag. The integration branch carries dev versions
(``v0.2.13.dev1``), a trunk promotion ``vX.Y.Z``; every agent iterates on a base holding the newest one, and a
version tag is added only on promotion to the trunk or at the user's request. Two pre-push rules, LOCAL reads only
(no network call beyond the push itself):

* ``BASE-HOLDS-THE-MILESTONE`` -- a branch the push creates or updates must contain (``merge-base
  --is-ancestor``) the newest milestone: the highest ``v*`` tag in the family grammar
  ``v<major>.<minor>.<patch>[.dev<N>][-unverified]`` (stdlib regex: the dev layer imports no :mod:`packaging`),
  a release outranking its dev tags, the legacy suffix read as its base, any other tag ignored -- and only a tag
  ON THE LINE: contained in ``origin/<integration>`` or ``origin/<trunk>`` (the pushed tip's
  ``[tool.dev_lab.integrator]``, else ``integrate/main`` and ``main``). A local-only tag reachable from neither
  is a stray no ``forge sync`` can bring in, so it is ignored, never a wall without an exit. The hook reads the
  local tracking refs and fetches nothing: ``forge sync`` fetches them, so a stale local view judges against an
  older milestone, never a wrong one. No milestone -> nothing to hold. Remedy: ``python -m dev_lab.dev.forge sync``.
* ``VERSION-TAG-NEEDS-APPROVAL`` -- in an agent session (:data:`dev_lab.dev.sessionprs.SESSION_ENV` set), a push
  CREATING a ``v*`` tag on origin is refused unless :data:`APPROVED_ENV` holds the user's own words -- the
  ``--approved "<words>"`` pattern of ``branchset --discard``, through the environment because git passes a hook
  no flags. A dev tag not ending in ``.dev0`` is refused even approved: hatch-vcs chooses the ``.devN`` distance
  itself and refuses a custom one, so a milestone is ``vX.Y.Z.dev0`` and the next bumps the patch or minor. A human
  push and an existing remote tag are not judged.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final

import lab_commons.launch as _door
from lab_commons.log import emit

from dev_lab.dev.lanepolicy import Policy, policy_at
from dev_lab.dev.refspec import pushed_refs
from dev_lab.dev.sessionprs import SESSION_ENV

__all__ = [
    'APPROVED_ENV',
    'BASE_RULE',
    'HOOK_ID',
    'TAG_RULE',
    'main',
    'milestone_version',
    'newest_milestone',
    'refusals',
]

BASE_RULE: Final = 'BASE-HOLDS-THE-MILESTONE'
TAG_RULE: Final = 'VERSION-TAG-NEEDS-APPROVAL'
#: The id this guard runs under in ``githooks/base.toml``.
HOOK_ID: Final = 'milestone-base'
#: The user's own approval words for a version tag pushed from an agent session.
APPROVED_ENV: Final = 'DEV_LAB_TAG_APPROVED'
_VERSIONS: Final = 'refs/tags/v'
_INTEGRATION: Final = 'integrate/main'
_GRAMMAR: Final = re.compile(r'v(\d+)\.(\d+)\.(\d+)(?:\.dev(\d+))?(?:-unverified)?')
_GIT: Final = shutil.which('git') or 'git'


def _git(root: Path, *args: str) -> tuple[int, str]:
    done = _door.run(
        [_GIT, '-C', str(root), *args], capture_output=True, text=True, encoding='utf-8', check=False, timeout=60
    )
    return done.returncode, done.stdout.strip()


def milestone_version(tag: str) -> tuple[int, int, int, tuple[int, int]] | None:
    """The sort key of a family version tag, or ``None``: ``.devN`` ranks ``(0, N)``, a release ``(1, 0)``."""
    if (match := _GRAMMAR.fullmatch(tag)) is None:
        return None
    major, minor, patch, dev = match.groups()
    return int(major), int(minor), int(patch), (1, 0) if dev is None else (0, int(dev))


def _line(root: Path, sha: str) -> tuple[str, ...]:
    """The origin tracking refs of the integration line and trunk *sha* declares, the family defaults otherwise."""
    try:
        policy = policy_at(root, sha)
    except (ValueError, OSError):
        policy = Policy(integration=_INTEGRATION)
    return tuple(f'refs/remotes/origin/{branch}' for branch in dict.fromkeys((policy.integration, policy.trunk)))


def newest_milestone(root: Path, line: Sequence[str]) -> str | None:
    """The ``v*`` tag naming the highest family version contained in a ref of *line*, or ``None``.

    A tag reachable from no ref of *line* -- a local-only stray -- is not a milestone.
    """
    tags: set[str] = set()
    for ref in line:
        code, out = _git(root, 'for-each-ref', '--format=%(refname:strip=2)', f'--merged={ref}', 'refs/tags/')
        tags.update(out.splitlines() if code == 0 else [])
    parsed = [(version, tag) for tag in tags if (version := milestone_version(tag))]
    return max(parsed)[1] if parsed else None


def _behind(tag: str, branch: str, sha: str) -> str:
    return (
        f'{BASE_RULE}: {branch} at {sha[:12]} does not contain the newest milestone {tag}; every push builds on it. '
        f'Merge the integration branch in: `python -m dev_lab.dev.forge sync`, then push again'
    )


def _unapproved(tag: str) -> str:
    return (
        f'{TAG_RULE}: an agent session creates {tag} on origin only at the user`s request (a version tag marks a '
        f'milestone or a promotion); rerun the push with {APPROVED_ENV}="<the user`s words>"'
    )


def _not_dev0(tag: str) -> str:
    return (
        f'{TAG_RULE}: {tag} is refused even approved: hatch-vcs builds a dev tag only as .dev0 (it picks the .devN '
        f'distance itself); a milestone is vX.Y.Z.dev0, the next one bumps the patch or minor'
    )


def refusals(root: Path, lines: str, *, env: Mapping[str, str] | None = None) -> list[str]:
    """Every refusal for the push *lines* describe; *env* defaults to the process environment."""
    env = os.environ if env is None else env
    found: list[str] = []
    for ref in pushed_refs(lines.splitlines()):
        if ref.deleted:
            continue
        if ref.branch is not None:
            milestone = newest_milestone(root, _line(root, ref.local_sha))
            if milestone is None:
                continue
            code, _ = _git(root, 'merge-base', '--is-ancestor', f'{milestone}^{{commit}}', ref.local_sha)
            if code != 0:
                found.append(_behind(milestone, ref.branch, ref.local_sha))
        elif ref.created and ref.remote_ref.startswith(_VERSIONS) and env.get(SESSION_ENV):
            tag = ref.remote_ref.removeprefix('refs/tags/')
            if (match := _GRAMMAR.fullmatch(tag)) is not None and match.group(4) not in {None, '0'}:
                found.append(_not_dev0(tag))
            elif not env.get(APPROVED_ENV, '').strip():
                found.append(_unapproved(tag))
    return found


def main(argv: Sequence[str] | None = None) -> int:
    """The pre-push hook: git's ref lines on stdin; exit 1 refuses, 0 publishes."""
    del argv  # git passes the remote name and url; nothing here reads the remote
    _, top = _git(Path.cwd(), 'rev-parse', '--show-toplevel')
    stdin = '' if sys.stdin is None or sys.stdin.isatty() else sys.stdin.read()
    found = refusals(Path(top or Path.cwd()), stdin)
    if found:
        emit('\n'.join(['', *(f'  REFUSED: {line}' for line in found), '']), err=True)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
