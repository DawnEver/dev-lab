"""``forge request <producer> --sha <sha>`` -- PUBLISH a request only when a serve host could reproduce it.

A request was a hand-written issue body plus a label; a producer the sha does not declare, a sha origin
cannot serve, a sha without a lock, or a label the repository lacks (Gitea drops an unknown label name
and answers 201) all published "successfully" and never ran. This verb refuses each by name BEFORE the
issue exists: it fetches origin, reads the producer at the sha (:func:`~dev_lab.dev.forgerequest.
declared_request`, its size included), checks origin serves the sha and the sha commits its lock, creates
the request labels when missing, and only then opens the issue and labels it.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from pathlib import Path

from lab_commons.log import emit

from dev_lab.dev.forge import NoCredential, Transport, UnreadableRemote, fetch_origin, https_transport
from dev_lab.dev.forgelabels import add_label, ensure_labels
from dev_lab.dev.forgerequest import (
    DONE_LABEL,
    UndeclaredRequest,
    declared_request,
    request_body,
    unreproducible,
    unserved,
)
from dev_lab.dev.forgeschedule import load_schedule
from dev_lab.dev.forgework import Client, ForgeCallFailed, Issue, client_for

__all__ = ['RequestRefused', 'main', 'publish']


class RequestRefused(ValueError):
    """A request no serve host could reproduce; the message names why. Nothing was published."""


def publish(
    root: Path,
    client: Client,
    producer: str,
    sha: str,
    *,
    label: str,
    paths: Sequence[str] = (),
    deadline: datetime | None = None,
) -> Issue:
    """Open the request issue for *producer* at *sha*, labelled *label*, once every check passes, until *deadline*.

    Raises:
        RequestRefused: the producer is undeclared or unsized at the sha, origin serves no ref containing it,
            or it commits no lock.

    """
    try:
        declared_request(root, sha, producer, paths)
    except UndeclaredRequest as why:
        raise RequestRefused(str(why)) from None
    if why := unserved(root, sha) or unreproducible(root, sha):
        raise RequestRefused(why)
    ensure_labels(client, [label, DONE_LABEL])
    issue = client.issue_create(
        f'request {producer} at {sha[:12]}', request_body(producer, sha, paths, deadline=deadline)
    )
    add_label(client, issue.number, label)
    return issue


def main(
    argv: Sequence[str] | None = None,
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    transport: Transport = https_transport,
    fetch: Callable[[Path], None] = fetch_origin,
) -> int:
    """``request <producer> --sha <sha>``; exit 2 refused (nothing published), 1 the forge failed."""
    parser = argparse.ArgumentParser(prog='dev_lab.dev.forge request', description=__doc__.splitlines()[0])
    parser.add_argument('producer', help='a name the sha declares under [tool.lab_commons.requests]')
    parser.add_argument('--sha', required=True, help='the 40-hex commit to run it at')
    parser.add_argument('--paths', nargs='+', default=(), help='producer `tests` only: the test files to run')
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    root = Path.cwd() if cwd is None else cwd
    try:
        fetch(root)
        built = client_for(root, env=dict(os.environ) if env is None else env, transport=transport)
        issue = publish(
            root,
            built,
            args.producer,
            args.sha.lower(),
            label=load_schedule(root).request_label,
            paths=tuple(args.paths),
        )
    except RequestRefused as refused:
        emit(f'[request] refused, nothing published: {refused}', err=True)
        return 2
    except (ForgeCallFailed, NoCredential, UnreadableRemote, OSError) as failed:
        emit(f'[request] {failed}', err=True)
        return 1
    emit(f'#{issue.number} {issue.url}')
    return 0
