"""THE OUTBOX -- every outward forge write is journaled before it is attempted and replayed until acknowledged.

TWO HALVES, ONE DIRECTORY. The WRITE JOURNAL (:mod:`lab_commons.dev._forge_journal`, ``writes/``) holds every
write the forge door attempted and the forge has not acknowledged -- a status, a comment, an attachment, a
label, an issue -- fsynced before the attempt; :func:`replay` sends each again (after its probe found it not
landed) until the forge answers, so a crash or a forge outage loses nothing and never double-posts. The HELD
STATUSES (below) are the posts whose commit the forge does not hold yet: they wait here, then go through the
same door, and so through the same journal.

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
per entry, so two runs never race on one document.

A RESULT IS CONTENT-ADDRESSED HERE BEFORE IT IS UPLOADED (design D19). :func:`enqueue` writes the record
beside its entry under :func:`content_name` -- its name with the sha-256 of its bytes -- through a durable
write (temp, fsync, rename), so a crash leaves the whole record or none; the upload then names it by that
hash and :func:`~lab_commons.dev.forgerecords.attach` sends nothing the forge already holds under it. The same
bytes are one asset however often they are queued; different bytes are a different asset, never a rewrite.
A record leaves the outbox once no queued entry still names it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final

from lab_commons.dev._forge_journal import OUTBOX_REL, Journal, durable_write, journal_for, outbox_dir
from lab_commons.dev.forge import (
    NoCredential,
    Transport,
    UnreadableRemote,
    https_transport,
    on_origin,
)
from lab_commons.dev.forgealarm import NONDETERMINISM, Alarm, sound
from lab_commons.dev.forgerecords import attach
from lab_commons.dev.forgestatus import STATES, Status, status_history, status_post
from lab_commons.dev.forgework import Client, ForgeCallFailed, client_for
from lab_commons.log import emit

__all__ = [
    'OUTBOX_REL',
    'RESULTS',
    'Post',
    'PostFailed',
    'content_name',
    'enqueue',
    'flush',
    'main',
    'outbox_dir',
    'queued',
    'replay',
    'unprompted_client',
]

#: The states that are a RESULT -- a verdict; ``error`` releases a claim and ``pending`` is one.
RESULTS: Final = frozenset({'success', 'failure'})

#: The length of a full sha-1 commit id, the only commit name the forge's status endpoint takes.
SHA_LENGTH: Final = 40

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


def content_name(name: str, data: bytes) -> str:
    """*name* with 16 hex of the sha-256 of *data* before its suffixes (``run-<sha>-linux-r1-<hash>.json.gz``)."""
    stem, dot, suffixes = name.partition('.')
    return f'{stem}-{hashlib.sha256(data).hexdigest()[:16]}{dot}{suffixes}'


def enqueue(root: Path, post: Post, *, record: Path | None = None) -> Path:
    """Queue *post*, its *record* stored beside it under its content name; returns the entry's path.

    A queued entry for the same commit and context is REPLACED -- the newer run speaks for the commit.
    """
    directory = outbox_dir(root)
    directory.mkdir(parents=True, exist_ok=True)
    if record is not None:
        data = record.read_bytes()
        kept = durable_write(directory / content_name(record.name, data), data)
        post = Post(post.sha, post.context, post.state, post.description, record=kept.name)
    return durable_write(
        directory / f'{post.key}.json', json.dumps({**asdict(post), 'queued_at': time.time()}).encode()
    )


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


def replay(journal: Journal, client: Client, *, now: float | None = None) -> list[str]:
    """Send every journaled write again until the forge acknowledges it; one line per write.

    A write past its ``until`` is dropped by name (a lease is worth only its first answer); a write whose
    probe finds it already landed is acknowledged without sending; one the forge still refuses or cannot
    take stays journaled for the next tick.
    """
    lines: list[str] = []
    moment = time.time() if now is None else now
    for write in journal.pending():
        what = f'{write.method} {write.path.split("?")[0]}'
        if write.until <= moment:
            journal.ack(write.key)
            lines.append(f'outbox: dropped {what} -- past its until, never replayed')
            continue
        try:
            if client.landed(write) is not None:
                journal.ack(write.key)
                lines.append(f'outbox: {what} had landed -- acknowledged, not sent again')
                continue
            client.resend(write)
        except ForgeCallFailed as exc:
            lines.append(f'outbox: kept {what} -- {exc.report.diagnosis.value}')
            continue
        journal.ack(write.key)
        lines.append(f'outbox: replayed {what}')
    return lines


def _replayed(root: Path, client: Callable[[Path], Client]) -> list[str]:
    """Replay *root*'s write journal; a box with no credential keeps it and says so."""
    journal = journal_for(root)
    if not journal.pending():
        return []
    try:
        built = client(root)
    except (NoCredential, UnreadableRemote) as exc:
        return [f'outbox: kept {len(journal.pending())} journaled write(s) -- no forge credential or remote ({exc})']
    return replay(journal, built)


def _deliver(root: Path, built: Client, post: Post, alarm: Callable[[Alarm], object]) -> str:
    """Post *post* with its record -- unless a RESULT for its commit and context is already on the forge.

    THE FIRST RESULT WINS (design D18). A run is deterministic, so a second result for the same unit is a
    duplicate run (a lost lease, a partition): an identical one is dropped; a DIFFERING one is never posted
    and sounds :data:`~lab_commons.dev.forgealarm.NONDETERMINISM` -- the unit is not deterministic.
    """
    directory = outbox_dir(root)
    first = _decided(built, post)
    if first is None:
        url = attach(built, directory / post.record).url if post.record else ''
        status_post(
            built, post.sha, context=post.context, state=post.state, description=post.description, target_url=url
        )
        line = f'status: {post.context}={post.state} on {post.sha[:12]}' + (f' -> {url}' if url else '')
    elif first.state == post.state:
        line = f'status: {post.context} on {post.sha[:12]} already holds {first.state} -- the identical result dropped'
    else:
        forge = built.forge
        alarm(
            Alarm(
                NONDETERMINISM, f'https://{forge.host}/{forge.owner}/{forge.repo}.git',
                f'{post.context} on {post.sha[:12]} gave {first.state} and then {post.state}',
                f'the first result ({first.description}) stands; the later one ({post.description}) was not posted. '
                'The same unit gave two results: find what made it non-deterministic.',
            )
        )  # fmt: skip
        line = f'status: {post.context} on {post.sha[:12]} held {first.state}; a later {post.state} ALARMED, not posted'
    (directory / f'{post.key}.json').unlink(missing_ok=True)
    if post.record and all(other.record != post.record for other in queued(root)):
        (directory / post.record).unlink(missing_ok=True)
    return line


def _decided(built: Client, post: Post) -> Status | None:
    """The first RESULT (:data:`RESULTS`) already posted in *post*'s context on its commit, when *post* is one."""
    if post.state not in RESULTS:
        return None
    history = status_history(built, post.sha)
    return next((one for one in history if one.context == post.context and one.state in RESULTS), None)


def flush(
    root: Path, *, client: Callable[[Path], Client] = unprompted_client, alarm: Callable[[Alarm], object] = sound
) -> list[str]:
    """Replay the write journal, then post every held entry whose commit is on ``origin``; one line per entry.

    Raises:
        PostFailed: at least one attempted post failed; every other entry was still tried, and the
            failed ones stay queued.

    """
    lines: list[str] = _replayed(root, client)
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
            lines.append(_deliver(root, built, post, alarm))
        except ForgeCallFailed as exc:
            failures.append(f'{post.context} on {post.sha[:12]} ({exc.report.diagnosis.value}): {exc}')
            continue
        except (OSError, ValueError, KeyError) as exc:
            failures.append(f'{post.context} on {post.sha[:12]}: {exc!r}')
            continue
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
