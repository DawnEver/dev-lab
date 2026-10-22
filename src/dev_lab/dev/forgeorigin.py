"""A commit's ORIGIN HOST: stamped at commit-msg as ``Forge-Host: <host card>``, read back, and vouched.

A host's ``[priority] hosts`` orders the jobs host H created first. Git records no host and the forge records only
the pusher's LOGIN -- every session on a workstation may push as one login -- so the host travels in the
commit, as a trailer this hook writes. It is CLAIMED, never trusted: a reader keeps it only where the
forge-recorded author of the PR vouches for it, as the login that publishes that host card
(:func:`vouched`). The host is the card name a tick on this machine
publishes (:func:`dev_lab.dev.forgehosts.this_host`: ``<cluster>/<account>`` on a cluster login node).
The one family hook that rewrites its input: it
appends the trailer (replacing an earlier one) and never refuses a commit.
"""

from __future__ import annotations

import dataclasses
import subprocess
import sys
from collections.abc import Collection, Mapping, Sequence
from pathlib import Path
from typing import Final

import lab_commons.launch as _door
from lab_commons.compute.model import REQUEST, Candidate
from lab_commons.log import emit

from dev_lab.dev.forge import _GIT, _GIT_TIMEOUT_S
from dev_lab.dev.forgehosts import host_id, this_host
from dev_lab.dev.forgework import GITHUB, Client, ForgeCallFailed

__all__ = ['ORIGIN_HOST', 'head_login', 'main', 'origin_host_of', 'stamp', 'vouched']

#: The commit trailer naming the host card a commit was made on (written by the ``forge-host`` commit-msg hook).
ORIGIN_HOST: Final = 'Forge-Host'


def origin_host_of(root: Path, sha: str) -> str:
    """The CLAIMED origin host of commit *sha* (its last :data:`ORIGIN_HOST` trailer); ``''`` when it has none."""
    done = _door.run(
        [_GIT, '-C', str(root), 'show', '-s', f'--format=%(trailers:key={ORIGIN_HOST},valueonly)', sha],
        capture_output=True, text=True, encoding='utf-8', timeout=_GIT_TIMEOUT_S, check=False,
    )  # fmt: skip
    values = done.stdout.split() if done.returncode == 0 else []
    return values[-1] if values else ''


def head_login(client: Client, sha: str) -> str:
    """The forge login commit *sha* resolves to (author, else committer); ``''`` when the forge resolves none.

    The forge maps the commit's email to an account; git's own author text is never read as a login, so an
    unresolved head carries no origin -- and no login priority -- rather than a guess. A credential refusal raises.
    """
    path = f'{client.repo}/commits/{sha}' if client.backend is GITHUB else f'{client.repo}/git/commits/{sha}'
    try:
        raw = client.call('GET', path)
    except ForgeCallFailed as failed:
        if failed.credential_refused:
            raise
        return ''
    if not isinstance(raw, Mapping):
        return ''
    for role in ('author', 'committer'):
        who = raw.get(role)
        if isinstance(who, Mapping) and who.get('login'):
            return str(who['login'])
    return ''


def vouched(found: Sequence[Candidate], owners: Mapping[str, Collection[str]]) -> tuple[Candidate, ...]:
    """*found* with each ``origin_host`` kept only where its FORGE-RECORDED login publishes that host card.

    A trailer or a request body is text anyone can write; the forge records who authored the PR or the
    issue, and the hosts issue who authored each card
    (*owners*: host -> its login, :func:`~dev_lab.dev.forgehosts.card_owners`). A part's unvouched trailer
    is dropped; a public repo's card is keyed by the opaque :func:`~dev_lab.dev.forgehosts.host_id`
    of the raw name the trailer carries, and vouches it the same.
    A REQUEST's unvouched ``host`` pin is REFUSED by name (``refused``), never silently run unpinned.
    """
    return tuple(_vouched(one, owners) for one in found)


def _vouched(one: Candidate, owners: Mapping[str, Collection[str]]) -> Candidate:
    publishers = (*owners.get(one.origin_host, ()), *owners.get(host_id(one.origin_host), ()))
    if not one.origin_host or one.origin in publishers:
        return one
    if one.kind != REQUEST:
        return dataclasses.replace(one, origin_host='')
    publisher = ', '.join(sorted(publishers)) or 'nobody'
    why = (
        f'host = "{one.origin_host}" pins a host card {one.origin or "its author"} does not publish '
        f'(published by {publisher}): drop the pin, or ask its publisher'
    )
    return dataclasses.replace(one, origin_host='', refused=why)


def stamp(message_file: str, host: str) -> None:
    """Append ``Forge-Host: <host>`` to *message_file*, replacing a trailer already there."""
    _door.run(
        [_GIT, 'interpret-trailers', '--in-place', '--if-exists', 'replace', '--trailer', f'{ORIGIN_HOST}: {host}',
         message_file],
        check=True, timeout=_GIT_TIMEOUT_S,
    )  # fmt: skip


def main(argv: Sequence[str] | None = None) -> int:
    """The hook: stamp the message file git hands it; 0 on every path, and a failure is SAID."""
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        stamp(args[-1], this_host())
    except (IndexError, OSError, subprocess.SubprocessError) as failed:
        emit(f'[forge-host] no origin host stamped: {failed}', err=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
