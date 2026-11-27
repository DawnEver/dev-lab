"""The REPO side of ``hpcaccount salvage``: where a checkout's git work lands, and the git writes that land it.

Split out of :mod:`~dev_lab.dev.hpcaccount.salvage` by concept (the door reads the account and writes the record;
this module owns the salvage BRANCH NAMES, the match rule and every write into the local repo). Every write goes
through a private index or a bundle in a family-prefixed temp dir: no working tree, no index and no other ref of
the repo is touched, and an existing branch is never moved.
"""

from __future__ import annotations

import io
import re
import tarfile
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Final

import lab_commons.launch as _door
from lab_commons.temp import TEMP_PREFIX

from dev_lab.dev.harness import child_env
from dev_lab.dev.hpcaccount import salvageread

__all__ = [
    'BRANCH', 'JOIN', 'WORKTREE', 'Refused', 'Where', 'branch_name', 'fetched', 'matched', 'repository_name',
    'tree_entries', 'worktree_commit',
]  # fmt: skip

#: The branch a salvaged ref lands on; ``<name>`` is :func:`branch_name`'s, never free text.
BRANCH: Final = 'salvage/{day}-{name}'
#: The ref name of the commit holding a checkout's uncommitted work (no ref git bundles is named so).
WORKTREE: Final = '@worktree'
_GIT_S: Final = 120

#: What joins a path's names into one (the home's own segment is ``~``): not a ``look.REPO_NAME`` character.
JOIN: Final = '+'
#: Any character a derived branch name never holds (git refuses most of them in a ref).
_UNSAFE: Final = re.compile(r'[^A-Za-z0-9._+@-]')


class Refused(Exception):
    """One checkout (or the whole door) is refused; the message names why and the door."""


@dataclass(frozen=True)
class Where:
    """What every salvage branch and commit of one run is derived from."""

    day: str
    account: str
    host: str
    checkout: str
    reason: str


def repository_name(url: str) -> str:
    """The repository NAME of *url* (https, ``host:path`` or a path): its last segment, ``.git`` stripped, folded."""
    tail = re.split(r'[/:\\]', url.rstrip('/\\'))[-1]
    return tail.removesuffix('.git').casefold()


def branch_name(day: str, account: str, checkout: str, ref: str) -> str:
    """``salvage/<day>-<account>-<checkout>-<ref>``: every part DERIVED, none free text.

    *checkout* is home-relative (``.`` is ``home``), its names joined by ``+`` with a leading dot dropped (a ref
    component cannot begin with one); *ref* loses ``refs/heads/`` (else ``refs/``) and its ``/`` become ``+``. Any
    other character outside ``[A-Za-z0-9._+@-]`` becomes ``-``; git still judges the result (``check-ref-format``).
    """
    if not re.fullmatch(r'[0-9]{8}', day):
        msg = f'salvage: day {day!r} is not yyyymmdd'
        raise ValueError(msg)
    where = 'home' if checkout == '.' else JOIN.join(part.lstrip('.') for part in PurePosixPath(checkout).parts)
    name = ref.removeprefix('refs/heads/') if ref.startswith('refs/heads/') else ref.removeprefix('refs/')
    name = JOIN.join(part.lstrip('.') for part in name.split('/'))
    return BRANCH.format(day=day, name=_UNSAFE.sub('-', f'{account}-{where}-{name}'))


def _git(repo: Path, *args: str, data: bytes | None = None, env: dict[str, str] | None = None) -> tuple[int, str]:
    done = _door.run(
        ['git', '-C', str(repo), *args], input=data, capture_output=True, check=False, timeout=_GIT_S,
        env=None if env is None else child_env(env),
    )  # fmt: skip
    return done.returncode, (done.stdout + done.stderr).decode('utf-8', 'replace').strip()


def matched(repo: Path, checkout: str, origin: str) -> None:
    """Refuse unless *origin*'s repository name is one of *repo*'s fetch remotes' (the match rule)."""
    code, said = _git(repo, 'remote', '-v')
    if code:
        msg = f'{repo} is not a git repository git can read: {said}'
        raise Refused(msg)
    remotes = sorted({line.split()[1] for line in said.splitlines() if line.endswith('(fetch)')})
    if not origin:
        msg = f'{checkout} had no remote on the account: no rule names its repo; nothing landed'
        raise Refused(msg)
    if repository_name(origin) not in {repository_name(url) for url in remotes}:
        msg = (
            f'{checkout} (origin {origin}, repository {repository_name(origin)!r}) is not a checkout of {repo} '
            f'(remotes: {", ".join(remotes) or "none"}): the rule is the repository NAME of the origin; salvage it '
            f'--into the repo with a remote named {repository_name(origin)!r}; nothing landed'
        )
        raise Refused(msg)


def _checked(repo: Path, branch: str) -> str:
    """*branch* when git accepts it as a branch name; else refused by name."""
    if _git(repo, 'check-ref-format', '--branch', branch)[0]:
        msg = f'{branch} is refused by git as a branch name'
        raise Refused(msg)
    return branch


def _reached(repo: Path, sha: str) -> str:
    """The first ref of *repo* that reaches commit *sha*; ``''`` when none does (or *repo* lacks it)."""
    code, said = _git(repo, 'for-each-ref', '--contains', sha, '--count=1', '--format=%(refname)')
    return said.splitlines()[0] if code == 0 and said else ''


def fetched(repo: Path, where: Where, bundle: bytes, say: Callable[[str], None]) -> list[dict[str, str]]:
    """Every ref of *bundle* no ref of *repo* reaches, fetched onto its salvage branch (the file is transient)."""
    with tempfile.TemporaryDirectory(prefix=f'{TEMP_PREFIX}salvage-') as tmp:
        held = Path(tmp) / 'commits.bundle'
        held.write_bytes(bundle)
        code, said = _git(repo, 'bundle', 'verify', str(held))
        if code:
            msg = (
                f'{repo} lacks commits the bundle of {where.checkout} builds on '
                f'({said.splitlines()[-1] if said else code}): fetch its origin first: '
                f'python -m dev_lab.dev.netverb -- git -C {repo} fetch origin'
            )
            raise Refused(msg)
        _, said = _git(repo, 'bundle', 'list-heads', str(held))
        landed: list[dict[str, str]] = []
        specs: list[str] = []
        for line in said.splitlines():
            sha, _, ref = line.partition(' ')
            if reached := _reached(repo, sha):
                say(f'salvage: {where.checkout}: {ref} {sha[:10]} skipped -- {reached} already reaches it')
                continue
            branch = _checked(repo, branch_name(where.day, where.account, where.checkout, ref))
            specs.append(f'{ref}:refs/heads/{branch}')
            landed.append({'branch': branch, 'sha': sha, 'from': ref})
        if specs:
            code, said = _git(repo, 'fetch', '--no-tags', '--no-write-fetch-head', str(held), *specs)
            if code:
                msg = f'git fetch of {where.checkout} into {repo} failed: {said}'
                raise Refused(msg)
    return landed


def tree_entries(tar: bytes) -> list[tuple[str, str, bytes]]:
    """``(mode, path, blob)`` of every regular file and symlink the untracked tar carries."""
    entries: list[tuple[str, str, bytes]] = []
    with tarfile.open(fileobj=io.BytesIO(tar)) as held:
        for member in held.getmembers():
            name = member.name.removeprefix('./')
            if member.issym():
                entries.append(('120000', name, member.linkname.encode('utf-8')))
            elif member.isfile() and (blob := held.extractfile(member)) is not None:
                entries.append(('100755' if member.mode & 0o111 else '100644', name, blob.read()))
    return entries


def worktree_commit(
    repo: Path, where: Where, found: salvageread.Checkout, diff: bytes, untracked: list[tuple[str, str, bytes]]
) -> dict[str, str]:
    """The tracked diff and the untracked files as ONE commit on *found*'s HEAD, on the :data:`WORKTREE` branch."""
    if found.head and _git(repo, 'cat-file', '-e', f'{found.head}^{{commit}}')[0]:
        msg = (
            f'{repo} lacks HEAD {found.head[:10]} of {where.checkout}, which its uncommitted work sits on: fetch its '
            f'origin first: python -m dev_lab.dev.netverb -- git -C {repo} fetch origin'
        )
        raise Refused(msg)
    branch = _checked(repo, branch_name(where.day, where.account, where.checkout, WORKTREE))
    who = f'{where.account}@{where.host}'
    with tempfile.TemporaryDirectory(prefix=f'{TEMP_PREFIX}salvage-') as tmp:
        env = {
            'GIT_INDEX_FILE': str(Path(tmp) / 'index'), 'GIT_AUTHOR_NAME': where.account, 'GIT_AUTHOR_EMAIL': who,
            'GIT_COMMITTER_NAME': where.account, 'GIT_COMMITTER_EMAIL': who,
        }  # fmt: skip
        steps: list[tuple[tuple[str, ...], bytes | None]] = [
            (('read-tree', found.head) if found.head else ('read-tree', '--empty'), None)
        ]
        if diff:
            steps.append((('apply', '--cached', '--binary', '-'), diff))
        for step, data in steps:
            code, said = _git(repo, *step, data=data, env=env)
            if code:
                msg = f'git {step[0]} of {where.checkout} failed in {repo}: {said}'
                raise Refused(msg)
        for mode, path, blob in untracked:
            code, sha = _git(repo, 'hash-object', '-w', '--stdin', data=blob, env=env)
            if code or _git(repo, 'update-index', '--add', '--cacheinfo', f'{mode},{sha},{path}', env=env)[0]:
                msg = f'untracked {path} of {where.checkout} did not land in {repo}: {sha}'
                raise Refused(msg)
        _, tree = _git(repo, 'write-tree', env=env)
        parents = ('-p', found.head) if found.head else ()
        message = f'salvage: {who}:~/{where.checkout} uncommitted work\n\n{where.reason}\n'
        code, sha = _git(repo, 'commit-tree', tree, *parents, data=message.encode('utf-8'), env=env)
    if code:
        msg = f'the worktree commit of {where.checkout} was not written in {repo}: {sha}'
        raise Refused(msg)
    code, said = _git(repo, 'update-ref', f'refs/heads/{branch}', sha, '')
    if code:
        msg = f'{branch} was not created in {repo} (an existing branch is never moved): {said}'
        raise Refused(msg)
    return {'branch': branch, 'sha': sha, 'from': WORKTREE}
