"""``python -m dev_lab.dev.hpcaccount salvage-fetch <salvaged checkout> --into <repo> [--apply]`` -- a bundle, landed.

User ruling 2026-11-25 (an account is cleaned completely): ``hpcaccount salvage`` brings an account checkout's own
commits home as ``commits.bundle`` (:mod:`~dev_lab.dev.hpcaccount.salvage`). This is the local half: it fetches
that bundle into a NAMED local repo as branches and touches no working tree, no index and no other ref.

* THE MATCH RULE: the checkout belongs in *repo* when the REPOSITORY NAME of its ``origin`` -- the url's last path
  segment, ``.git`` stripped, case folded -- is the name of one of *repo*'s fetch remotes. The name, not the url:
  one repository is served by several forges under different owners (measured 2026-11-25: an account's
  ``numerics-lab`` cloned from one forge, the workstation's from another). A checkout whose origin names no remote
  of *repo*, or that has no origin, is refused by name; nothing is fetched.
* EVERY REF OF THE BUNDLE becomes ``refs/heads/salvage/<account>/<checkout>/<name>``: ``<checkout>`` its
  home-relative path (a ref component cannot begin with ``.``, so a leading dot is dropped: ``.claude`` ->
  ``claude``), ``<name>`` the bundle's ref without ``refs/heads/`` (else without ``refs/``): a branch keeps its name,
  ``tags/<t>``, ``stash``, ``r2/solid``, a detached ``HEAD``, another worktree's ``worktrees/<id>/HEAD``.
* The refspecs are never forced: a salvage branch already there at another commit is refused by git, named.

Without ``--apply`` the bundle is verified against *repo* (``git bundle verify``: its prerequisite commits must be
there -- else fetch the repo's origin first) and each ref is printed with the branch it would become.
"""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Callable, Sequence
from pathlib import Path, PurePosixPath
from typing import Any, Final

import lab_commons.launch as _door
from lab_commons.log import emit

from dev_lab.dev.hpcaccount.salvage import FILES, MANIFEST

__all__ = ['BRANCH', 'branch_of', 'fetch', 'main', 'repository_name']

#: The branch one bundle ref lands on.
BRANCH: Final = 'salvage/{account}/{checkout}/{name}'
_TIMEOUT_S: Final = 600


class _Refused(Exception):
    """Nothing was fetched; the message names why and the door."""


def repository_name(url: str) -> str:
    """The repository NAME of *url* (https, ``host:path`` or a path): its last segment, ``.git`` stripped, folded."""
    tail = re.split(r'[/:\\]', url.rstrip('/\\'))[-1]
    return tail.removesuffix('.git').casefold()


def branch_of(account: str, checkout: str, ref: str) -> str:
    """The local branch bundle ref *ref* of *account*'s *checkout* (home-relative) lands on."""
    name = ref.removeprefix('refs/heads/') if ref.startswith('refs/heads/') else ref.removeprefix('refs/')
    where = 'home' if checkout == '.' else '/'.join(part.lstrip('.') for part in PurePosixPath(checkout).parts)
    return BRANCH.format(account=account, checkout=where, name=name)


def _git(repo: Path, *args: str) -> tuple[int, str]:
    done = _door.run(
        ['git', '-C', str(repo), *args], capture_output=True, text=True, encoding='utf-8', errors='replace',
        check=False, timeout=_TIMEOUT_S,
    )  # fmt: skip
    return done.returncode, (done.stdout + done.stderr).strip()


def _entry(checkout: Path) -> tuple[str, dict[str, Any]]:
    """The account and the manifest entry of salvaged *checkout*: the nearest manifest above it that lists it."""
    for folder in (checkout, *checkout.parents):
        manifest = folder / MANIFEST
        if not manifest.is_file():
            continue
        record = json.loads(manifest.read_text(encoding='utf-8'))
        parts = PurePosixPath(record.get('path', '.')).parts if record.get('path') != '.' else ()
        home = folder.parents[len(parts) - 1] if parts else folder
        for entry in record.get('checkouts', []):
            if (home if entry['path'] == '.' else home.joinpath(*PurePosixPath(entry['path']).parts)) == checkout:
                return record['account'], entry
    msg = f'{checkout} is not a salvaged checkout: no {MANIFEST} above it lists it (hpcaccount salvage ... --apply)'
    raise _Refused(msg)


def _matched(repo: Path, checkout: str, origin: str) -> None:
    """Refuse unless *origin*'s repository name is one of *repo*'s fetch remotes' (the match rule)."""
    code, said = _git(repo, 'remote', '-v')
    if code:
        msg = f'{repo} is not a git repository git can read: {said}'
        raise _Refused(msg)
    remotes = sorted({line.split()[1] for line in said.splitlines() if line.endswith('(fetch)')})
    if not origin:
        msg = f'{checkout} had no remote on the account: no rule names its repo; nothing fetched'
        raise _Refused(msg)
    if repository_name(origin) not in {repository_name(url) for url in remotes}:
        msg = (
            f'{checkout} (origin {origin}, repository {repository_name(origin)!r}) is not a checkout of {repo} '
            f'(remotes: {", ".join(remotes) or "none"}): the rule is the repository NAME of the origin; fetch it into '
            f'the repo with a remote named {repository_name(origin)!r}; nothing fetched'
        )
        raise _Refused(msg)


def _refspecs(repo: Path, account: str, checkout: str, bundle: Path) -> list[tuple[str, str, str]]:
    """``(sha, bundle ref, local branch)`` for every ref of *bundle*; a branch git refuses is refused by name."""
    code, said = _git(repo, 'bundle', 'list-heads', str(bundle))
    if code:
        msg = f'{bundle} does not read as a bundle: {said}'
        raise _Refused(msg)
    specs = []
    for line in said.splitlines():
        sha, _, ref = line.partition(' ')
        branch = branch_of(account, checkout, ref)
        if _git(repo, 'check-ref-format', '--branch', branch)[0]:
            msg = f'bundle ref {ref} of {checkout} would land on {branch}, which git refuses as a branch name'
            raise _Refused(msg)
        specs.append((sha, ref, branch))
    return specs


def _verified(repo: Path, checkout: str, bundle: Path) -> None:
    """Refuse unless *repo* holds every commit *bundle* builds on (``git bundle verify``, read-only)."""
    code, said = _git(repo, 'bundle', 'verify', str(bundle))
    if code:
        msg = (
            f'{repo} lacks commits the bundle of {checkout} builds on ({said.splitlines()[-1] if said else code}): '
            f'fetch its origin first: python -m dev_lab.dev.netverb -- git -C {repo} fetch origin'
        )
        raise _Refused(msg)


def fetch(checkout: Path, repo: Path, *, apply: bool, say: Callable[[str], None] = emit) -> int:
    """Fetch salvaged *checkout*'s bundle into *repo* as salvage branches (*apply*), else verify and print; 0 or 2."""
    try:
        account, entry = _entry(checkout.resolve())
        name = entry['path']
        bundle = checkout / FILES['bundle']
        if not bundle.is_file():
            say(f'salvage-fetch: {name}: nothing to fetch -- every commit of it was on a remote (no bundle)')
            return 0
        _matched(repo, name, entry.get('origin', ''))
        specs = _refspecs(repo, account, name, bundle)
        _verified(repo, name, bundle)
    except (_Refused, OSError, ValueError, KeyError) as refused:
        say(f'salvage-fetch: refused -- {refused}')
        return 2
    for sha, ref, branch in specs:
        say(f'salvage-fetch: {name}: {ref} {sha[:10]} -> {branch}')
    if not apply:
        say(f'salvage-fetch: dry run -- the bundle verifies against {repo}; --apply fetches {len(specs)} branch(es)')
        return 0
    refspecs = [f'{ref}:refs/heads/{branch}' for _sha, ref, branch in specs]
    code, said = _git(repo, 'fetch', '--no-tags', '--no-write-fetch-head', str(bundle), *refspecs)
    if code:
        say(f'salvage-fetch: refused -- git fetch of {name} into {repo} failed: {said}')
        return 2
    say(f'salvage-fetch: {name}: {len(specs)} branch(es) under salvage/{account}/ in {repo}; no working tree touched')
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Parse ``salvage-fetch`` and run it."""
    parser = argparse.ArgumentParser(prog='dev_lab.dev.hpcaccount salvage-fetch', description=__doc__.splitlines()[0])
    parser.add_argument('checkout', type=Path, help='a salvaged checkout directory (it holds commits.bundle)')
    parser.add_argument('--into', type=Path, required=True, help='the local repo whose remote names its repository')
    parser.add_argument('--apply', action='store_true', help='fetch; default: verify and print what would land')
    args = parser.parse_args(list(argv or ()))
    return fetch(args.checkout, args.into, apply=args.apply)
