"""THE OUTBOX -- a status (and its record) is KEPT until the commit it is about is on the forge, then posted.

THE DEFECT IT FIXES. A run finishes on a commit that is usually not pushed yet -- a lane verifies
before it pushes, an integration tree is judged before the integration push -- and the forge refuses
a status on a commit it does not hold. Posting at the end of the run therefore FAILED EVERY TIME,
and raising (post-failed-and-continue is retired) lost nothing but also published nothing.

THE RULE. A finished run :func:`enqueue`s its post: commit, context, state, description, and the run
record to attach. :func:`flush` posts every queued entry whose commit is reachable from an ``origin``
remote-tracking ref -- the local, offline reading of "the forge holds it", which a push updates the
moment it lands -- and deletes the entry only once the post landed. An entry whose commit is not on
``origin`` yet is HELD, never dropped. Who flushes: the run itself right after queueing (a commit
already pushed posts at once), ``python -m lab_commons.dev.forge publish`` after a push, and every
``forge tick`` (:mod:`lab_commons.dev.forgetick`).

A POST THAT WAS ATTEMPTED AND FAILED RAISES (:class:`PostFailed`, naming its remedy) after every other
entry was tried; the failed entry stays queued. A post that could not be attempted -- no credential
or no ``origin`` on this box -- is reported and kept, never raised: the box simply does not publish.

WHERE IT LIVES. ``output/forge/outbox/`` in the MAIN checkout (resolved through git's common
directory, as the verdict ledger is), so every lane of one repository shares one queue. One JSON file
per entry, the record copied beside it, so two runs never race on one document.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final

from lab_commons.dev.forge import (
    _GIT,
    _GIT_TIMEOUT_S,
    NoCredential,
    Transport,
    UnreadableRemote,
    https_transport,
    on_origin,
)
from lab_commons.dev.forgerecords import attach
from lab_commons.dev.forgestatus import STATES, status_post
from lab_commons.dev.forgework import Client, ForgeCallFailed, client_for
from lab_commons.log import emit

__all__ = [
    'OUTBOX_REL',
    'Post',
    'PostFailed',
    'enqueue',
    'flush',
    'main',
    'outbox_dir',
    'queued',
    'unprompted_client',
]

#: The outbox, relative to the MAIN checkout's root.
#: The length of a full sha-1 commit id, the only commit name the forge's status endpoint takes.
SHA_LENGTH: Final = 40

OUTBOX_REL: Final = 'output/forge/outbox'

_REMEDY: Final = (
    'it stays queued; re-run `python -m lab_commons.dev.forge publish` once the forge answers '
    '(`python -m lab_commons.dev.forge status list <sha>` shows what it holds)'
)


class PostFailed(RuntimeError):
    """A status post was attempted and did not land; the message names the cause and the remedy."""


@dataclass(frozen=True)
class Post:
    """One queued status: what to post on which commit, and the record (a file name in the outbox) to attach."""

    sha: str
    context: str
    state: str
    description: str
    record: str = ''

    def __post_init__(self) -> None:
        """A state the forge does not take, or a sha that is not a full commit id, is refused at queueing."""
        if self.state not in STATES:
            msg = f'a status state is one of {STATES}, not {self.state!r}'
            raise ValueError(msg)
        if len(self.sha) != SHA_LENGTH:
            msg = f'a status names a full 40-hex commit id, not {self.sha!r}'
            raise ValueError(msg)

    @property
    def key(self) -> str:
        """The entry's file stem: one entry per commit and context, a newer run replacing an older one."""
        return f'{self.sha}-{self.context.replace("/", "_")}'


def _common_root(root: Path) -> Path:
    common = subprocess.run(
        [_GIT, '-C', str(root), 'rev-parse', '--path-format=absolute', '--git-common-dir'],
        capture_output=True,
        text=True,
        encoding='utf-8',
        check=True,
        timeout=_GIT_TIMEOUT_S,
    ).stdout.strip()
    return Path(common).parent


def outbox_dir(root: Path) -> Path:
    """The outbox of the repository *root* belongs to, in its MAIN checkout (shared by every lane)."""
    return _common_root(root) / OUTBOX_REL


def enqueue(root: Path, post: Post, *, record: Path | None = None) -> Path:
    """Queue *post*, copying *record* beside it; returns the entry's path.

    A queued entry for the same commit and context is REPLACED -- the newer run speaks for the commit.
    """
    directory = outbox_dir(root)
    directory.mkdir(parents=True, exist_ok=True)
    if record is not None:
        shutil.copyfile(record, directory / record.name)
        post = Post(post.sha, post.context, post.state, post.description, record=record.name)
    entry = directory / f'{post.key}.json'
    staged = entry.with_suffix('.json.tmp')
    staged.write_text(json.dumps({**asdict(post), 'queued_at': time.time()}, indent=2), encoding='utf-8')
    staged.replace(entry)
    return entry


def queued(root: Path) -> tuple[Post, ...]:
    """Every queued post, in file order; a torn entry is skipped, never served."""
    directory = outbox_dir(root)
    found = []
    for path in sorted(directory.glob('*.json')) if directory.is_dir() else ():
        try:
            raw = json.loads(path.read_text(encoding='utf-8'))
            found.append(Post(raw['sha'], raw['context'], raw['state'], raw['description'], raw.get('record', '')))
        except (ValueError, KeyError, TypeError):
            continue
    return tuple(found)


#: A publish runs unattended (end of a verify, inside a tick), so the credential lookup must never PROMPT.
_NO_PROMPT: Final = {'GIT_TERMINAL_PROMPT': '0', 'GCM_INTERACTIVE': 'never'}


def unprompted_client(root: Path) -> Client:
    """The forge client for *root* whose credential lookup never opens a prompt nobody is watching."""
    # Set in THIS process rather than passed as ``env=``: an explicit env is the test seam, which
    # also blanks PATH for ``git credential`` -- and that hides the real helper from a real run.
    for name, value in _NO_PROMPT.items():
        os.environ.setdefault(name, value)
    return client_for(root)


def flush(root: Path, *, client: Callable[[Path], Client] = unprompted_client) -> list[str]:
    """Post every queued entry whose commit is on ``origin``; return one line per entry.

    Raises:
        PostFailed: at least one attempted post failed; every other entry was still tried, and the
            failed ones stay queued.

    """
    directory = outbox_dir(root)
    lines: list[str] = []
    failures: list[str] = []
    built: Client | None = None
    for post in queued(root):
        if not on_origin(root, post.sha):
            lines.append(f'status: held {post.context} on {post.sha[:12]} -- the commit is not on origin yet')
            continue
        try:
            built = built or client(root)
        except (NoCredential, UnreadableRemote) as exc:
            lines.append(f'status: kept {post.context} on {post.sha[:12]} -- no forge credential or remote ({exc})')
            continue
        try:
            url = attach(built, directory / post.record).url if post.record else ''
            status_post(
                built, post.sha, context=post.context, state=post.state, description=post.description, target_url=url
            )
        except ForgeCallFailed as exc:
            failures.append(f'{post.context} on {post.sha[:12]} ({exc.report.diagnosis.value}): {exc.report.remedy}')
            continue
        except (OSError, ValueError, KeyError) as exc:
            failures.append(f'{post.context} on {post.sha[:12]}: {exc!r}')
            continue
        (directory / f'{post.key}.json').unlink(missing_ok=True)
        if post.record:
            (directory / post.record).unlink(missing_ok=True)
        lines.append(f'status: {post.context}={post.state} on {post.sha[:12]}' + (f' -> {url}' if url else ''))
    if failures:
        msg = '\n'.join([*lines, *(f'status: post FAILED {line}' for line in failures), f'remedy: {_REMEDY}'])
        raise PostFailed(msg)
    return lines


def main(
    argv: Sequence[str] | None = None,
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    transport: Transport = https_transport,
) -> int:
    """``python -m lab_commons.dev.forge publish``: post every queued status whose commit is on origin."""
    argparse.ArgumentParser(prog='lab_commons.dev.forge publish', description=main.__doc__).parse_args(
        list(sys.argv[2:] if argv is None else argv)
    )
    root = Path.cwd() if cwd is None else cwd

    def build(here: Path) -> Client:
        return client_for(here, env=env, transport=transport) if env is not None else unprompted_client(here)

    try:
        lines = flush(root, client=build)
    except PostFailed as failed:
        emit(str(failed), err=True)
        return 1
    for line in lines or ['status: the outbox is empty']:
        emit(line)
    return 0


if __name__ == '__main__':
    sys.exit(main())
