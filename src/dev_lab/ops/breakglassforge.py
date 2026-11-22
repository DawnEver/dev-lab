"""The FORGE a break-glass server reaches (:mod:`dev_lab.ops.breakglass`): its calls, their client, and the token.

:class:`Forge` is the narrow surface the server makes on one repository as the break-glass identity;
:class:`ClientForge` serves it over the family's forge client of the repo URL's backend (Gitea or GitHub), and
:func:`credential` is the token that client presents.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Mapping, Sequence
from functools import partial
from pathlib import Path
from typing import Final, Protocol

import lab_commons.launch as _door
from lab_commons.temp import TEMP_PREFIX

from dev_lab.dev.branchset import branchset_from
from dev_lab.dev.failprint import Fingerprints
from dev_lab.dev.forge import forge_of_url
from dev_lab.dev.forgeapp import installation
from dev_lab.dev.forgecred import authorization
from dev_lab.dev.forgemergecall import merge
from dev_lab.dev.forgepulls import pr_list
from dev_lab.dev.forgestatus import CommitStatus, fingerprints_at, status_list
from dev_lab.dev.forgework import Client, Transport, forge_transport
from dev_lab.dev.reviewgate import manifest_at
from dev_lab.ops.config import Breakglass
from dev_lab.ops.served import app_of_forge
from dev_lab.ops.wavesweep import Pull

__all__ = ['ClientForge', 'Forge', 'NotFastForward', 'credential', 'fast_forward']

_GIT: Final = shutil.which('git') or 'git'


class NotFastForward(ValueError):
    """The trunk may not move to the sha: it is off the integration branch, or the move is not a fast-forward."""


def _git(cwd: Path, env: Mapping[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return _door.run([_GIT, '-C', str(cwd), *args], capture_output=True, text=True, encoding='utf-8', check=False,
                     timeout=600, env=dict(env))  # fmt: skip


def fast_forward(url: str, header: str, trunk: str, integration: str, sha: str) -> str:
    """Move *url*'s *trunk* to *sha* by a NON-FORCED push; returns the trunk's sha before the move.

    *sha* must be on *integration* and contain the trunk (TRUNK-MOVES-BY-FAST-FORWARD), else :class:`NotFastForward`
    and nothing is pushed. *header* (``Authorization: ...``, may be ``''``) reaches git through the environment,
    never argv, so no process listing shows the token. A blobless fetch into a throwaway directory: nothing is kept.
    """
    env = {**os.environ, 'GIT_TERMINAL_PROMPT': '0'}
    if header:
        env |= {'GIT_CONFIG_COUNT': '1', 'GIT_CONFIG_KEY_0': 'http.extraHeader', 'GIT_CONFIG_VALUE_0': header}
    with tempfile.TemporaryDirectory(prefix=f'{TEMP_PREFIX}breakglass-promote-') as held:
        where = Path(held)
        _git(where, env, 'init', '-q', '--bare')
        wanted = (f'+refs/heads/{integration}:refs/i', f'+refs/heads/{trunk}:refs/t')
        if (got := _git(where, env, 'fetch', '-q', '--filter=blob:none', url, *wanted)).returncode != 0:
            msg = f'fetching {integration} and {trunk} failed: {got.stderr.strip()[-300:]}'
            raise OSError(msg)
        old = _git(where, env, 'rev-parse', 'refs/t').stdout.strip()
        if _git(where, env, 'merge-base', '--is-ancestor', sha, 'refs/i').returncode != 0:
            msg = f'{sha[:12]} is not a commit of {integration}'
            raise NotFastForward(msg)
        if _git(where, env, 'merge-base', '--is-ancestor', old, sha).returncode != 0:
            msg = f'{trunk} ({old[:12]}) is not an ancestor of {sha[:12]}: it cannot fast-forward'
            raise NotFastForward(msg)
        if (pushed := _git(where, env, 'push', '-q', url, f'{sha}:refs/heads/{trunk}')).returncode != 0:
            msg = f'{trunk} did not take {sha[:12]}: {pushed.stderr.strip()[-300:]}'
            raise OSError(msg)
        return old


class Forge(Protocol):
    """The forge calls the role makes, on one repository, as the break-glass identity."""

    def declaration(self, ref: str) -> str:
        """The repository's ``pyproject.toml`` at *ref*; raises ``ValueError`` when it cannot be read."""
        ...

    def pull(self, number: int) -> tuple[str, str, str]:
        """``(state, base, head_sha)`` of PR *number*."""
        ...

    def statuses(self, head: str) -> Sequence[CommitStatus]:
        """The commit statuses *head* carries, newest first."""
        ...

    def open_pulls(self) -> Sequence[Pull]:
        """Every open PR (:mod:`dev_lab.ops.wavesweep` lands the green ones of an open wave)."""
        ...

    #: The failure fingerprints of a ref (a sha, or a branch's tip), read from its run records.
    fingerprints: Callable[[str], Fingerprints]

    def labels(self, number: int) -> tuple[str, ...]:
        """The labels PR *number* carries now."""
        ...

    def comment(self, number: int, body: str) -> None:
        """Comment on PR *number*."""
        ...

    def merge(self, number: int, *, head: str, message: str) -> None:
        """Merge PR *number* at *head* with a merge commit saying *message*."""
        ...

    def fast_forward(self, trunk: str, integration: str, sha: str) -> str:
        """Push *trunk* to *sha*, non-forced; raises :class:`NotFastForward`; returns the trunk before."""
        ...


class ClientForge:
    """:class:`Forge` over the family's forge client of *url*'s backend, presenting *token*."""

    def __init__(self, url: str, token: str, *, transport: Transport = forge_transport) -> None:
        """Reach *url*'s repository through *transport* (the network by default)."""
        self._client = Client(forge_of_url(url), token, transport=transport)
        self._url, self._token = url, token
        self.fingerprints = partial(fingerprints_at, self._client)  # :func:`~dev_lab.dev.forgestatus.fingerprints_at`

    def declaration(self, ref: str) -> str:
        """The ``pyproject.toml`` at *ref*, as the forge holds it (:func:`dev_lab.dev.reviewgate.manifest_at`)."""
        return manifest_at(self._client, ref)

    def pull(self, number: int) -> tuple[str, str, str]:
        """``(state, base, head_sha)`` of PR *number*."""
        found = self._client.pr_view(number)
        return found.state, found.base, found.head_sha

    def statuses(self, head: str) -> Sequence[CommitStatus]:
        """The commit statuses *head* carries (:func:`dev_lab.dev.forgestatus.status_list`)."""
        return status_list(self._client, head)

    def open_pulls(self) -> Sequence[Pull]:
        """Every open PR (:func:`dev_lab.dev.forgepulls.pr_list`)."""
        return [Pull(one.number, one.base, one.head_sha, one.draft) for one in pr_list(self._client)]

    def labels(self, number: int) -> tuple[str, ...]:
        """The labels PR *number* carries, read fresh (both backends' pull JSON lists them by name)."""
        return self._client.pr_view(number).labels

    def comment(self, number: int, body: str) -> None:
        """Comment on PR *number*."""
        self._client.issue_comment(number, body)

    def fast_forward(self, trunk: str, integration: str, sha: str) -> str:
        """Push *trunk* to *sha* as the break-glass identity (:func:`fast_forward`); returns the trunk before."""
        header = f'Authorization: {authorization("x-access-token", self._token, "")}'
        return fast_forward(self._url, header, trunk, integration, sha)

    def merge(self, number: int, *, head: str, message: str) -> None:
        """Merge PR *number* at *head* (:func:`dev_lab.dev.forgemergecall.merge`, either backend).

        Its head branch is deleted exactly when the integration path would delete it (D18): when the branch set
        the repo declares AT THE PR'S BASE (:func:`dev_lab.dev.branchset.branchset_from`, the one parser) puts the
        head name in an ephemeral namespace. A long-lived branch (the trunk, a declared session) is never deleted.
        The forge refuses a *head* that moved, so a moved head is neither merged nor deleted. The merge is FORCED:
        a wave waives the tests, so the branch's unmet required checks are overridden, which Gitea does only when
        asked (:func:`~dev_lab.dev.forgemergecall.merge`).
        """
        found = self._client.pr_view(number)
        declared = branchset_from(manifest_at(self._client, found.base), f'pyproject.toml at {found.base}')
        ephemeral = declared.is_ephemeral(found.head)
        merge(self._client, number, head=head, message=message, delete_branch=ephemeral, force=True)


def _installation_token(url: str, app_id: int, key_file: Path) -> str:
    return installation(forge_of_url(url), app_id, key_file)[1]


def credential(
    role: Breakglass, url: str, *, secret: Callable[[str], str],
    mint: Callable[[str, int, Path], str] = _installation_token,
) -> str:  # fmt: skip
    """The token break-glass presents on *url*'s forge: *mint* its App's installation token, else *secret* its file.

    On a forge with an App (GitHub) the token is minted per wave by :func:`dev_lab.dev.forgeapp.installation`, the
    ONE minting code; a token forge (Gitea) reads its declared file.
    """
    if (app := app_of_forge(role.apps, url)) is not None:
        return mint(url, *app)
    return secret(role.token_file(url))
