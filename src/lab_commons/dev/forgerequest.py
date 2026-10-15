"""A REQUEST IS A JOB ON THE PART PATH -- compute a person or agent asks for, run by a ``forge serve`` host.

Design: one admission for the distributed compute system, migration step 7 (2026-10-13). A test part and a
request are the SAME noun, a :class:`~lab_commons.compute.model.Job` ``(repo, sha, producer, needs)``: they
differ only in who created it (a push, or a person or agent) and in their status context. A part's is
``tests/<part>``; a request's is ``request/<issue number>`` (:func:`request_context`). Both are ranked,
ADMITTED by the one admission (:func:`lab_commons.compute.admission.admit`: its need-set present, its size
free), claimed, leased, renewed and released by the one path (:mod:`lab_commons.dev.forgetake`,
:mod:`lab_commons.dev.forgeproduce`).

A REQUEST IS AN OPEN ISSUE labelled ``forge:request`` whose body names a producer and a sha::

    producer = "femm_goldens"
    sha = "<40-hex commit>"

The repo is the issue's, the requester its author. The body NEVER carries a command: the producer is a
NAME the repository declares at that sha, ONCE, beside its tests' producer, so a request cannot run
anything its repository did not commit (an undeclared name is refused, never run)::

    [tool.lab_commons.requests.femm_goldens]
    argv = ["-m", "solver", "golden", "regenerate", "--reference", "femm"]   # after the tree's python
    needs = ["femm", "windows"]   # its NEED-SET: resource names, an OS among them, like a part's

A request is pinned to its sha, so nothing supersedes it. Its producer knows nothing of the forge, so
serve SETTLES it from the exit code (:func:`result`, :func:`settle`): 0 posts ``success`` and closes the
issue, 1 posts ``failure`` and leaves it open, every other code is released as a part's would be
(:func:`lab_commons.dev.producer.release_reason`). The issue gets a comment naming the outcome, the host,
and the log's tail -- a failure is on record, never silent.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from lab_commons.box.machine import RESOURCE_NAME
from lab_commons.dev.producer import ProducerExit, release_reason
from lab_commons.hpc.declared import OutdatedKit, kit_tables, pyproject_at
from lab_commons.hpc.needsets import part_name

if TYPE_CHECKING:
    from pathlib import Path

    from lab_commons.dev.forgework import Client

__all__ = [
    'CONTEXT_PREFIX',
    'Declared',
    'UndeclaredRequest',
    'declared_request',
    'parse_body',
    'request_body',
    'request_context',
    'result',
    'settle',
]

#: The status context prefix of a request job; a part's is ``tests/``.
CONTEXT_PREFIX: Final = 'request/'
#: How many log lines the result comment quotes.
TAIL_LINES: Final = 40

_LINE: Final = re.compile(r'^\s*(?P<key>producer|sha)\s*=\s*["\'](?P<value>[^"\']*)["\']\s*$', re.MULTILINE)
_SHA: Final = re.compile(r'^[0-9a-f]{40}$')


class UndeclaredRequest(ValueError):
    """A request names a producer its sha does not declare (or declares malformed); the message names the key."""


@dataclass(frozen=True)
class Declared:
    """One declared request producer, as its sha declares it."""

    name: str
    argv: tuple[str, ...]
    needs: frozenset[str] = frozenset()

    @property
    def part(self) -> str:
        """Its need-set spelled as a part is (``femm+windows``): how the queue names it."""
        return part_name(self.needs)


def request_context(number: int) -> str:
    """``request/<number>`` -- the one status context a request (and a claim on it) uses."""
    return f'{CONTEXT_PREFIX}{number}'


def request_body(producer: str, sha: str) -> str:
    """The issue body that IS a request for *producer* at *sha*."""
    return f'producer = "{producer}"\nsha = "{sha}"\n'


def parse_body(body: str) -> tuple[str, str]:
    """``(producer, sha)`` a request body names; ``''`` for one it does not name well."""
    found = {match['key']: match['value'] for match in _LINE.finditer(body or '')}
    producer, sha = found.get('producer', ''), found.get('sha', '').lower()
    return (producer if RESOURCE_NAME.match(producer) else '', sha if _SHA.match(sha) else '')


def declared_request(root: Path, sha: str, name: str) -> Declared:
    """The producer *name* as commit *sha* declares it under ``[tool.lab_commons.requests.<name>]``.

    Raises:
        UndeclaredRequest: absent, malformed, or the sha unreadable; the message names the key.
        OutdatedKit: the sha declares a table this kit does not know.

    """
    table = f'[tool.lab_commons.requests.{name}]'
    if not name or not sha:
        msg = f'a request body names `producer = "<declared name>"` and `sha = "<40-hex>"`; got {name!r} at {sha!r}'
        raise UndeclaredRequest(msg)
    try:
        row = kit_tables(pyproject_at(root, sha)).get('requests', {}).get(name)
    except OutdatedKit:  # the READER is older than the sha: this host's defect, never the commit's
        raise
    except (ValueError, OSError) as why:  # an unknown sha, an unreadable or retired declaration
        msg = f'{table} unreadable at {sha[:12]}: {why}'
        raise UndeclaredRequest(msg) from why
    if not isinstance(row, dict):
        msg = f'{sha[:12]} declares no {table}: a request runs only a producer its repository commits'
        raise UndeclaredRequest(msg)
    argv, needs = row.get('argv'), row.get('needs', [])
    if not isinstance(argv, list) or not argv or not all(isinstance(one, str) and one for one in argv):
        msg = f'{table} argv must be a non-empty array of strings (what follows the tree python)'
        raise UndeclaredRequest(msg)
    if not isinstance(needs, list) or not all(isinstance(one, str) and RESOURCE_NAME.match(one) for one in needs):
        msg = f'{table} needs must be an array of resource names'
        raise UndeclaredRequest(msg)
    return Declared(name, tuple(argv), frozenset(needs))


def result(code: int, host: str) -> tuple[str, str]:
    """The ``(state, description)`` a request's producer exiting *code* on *host* settles it with."""
    if code == ProducerExit.PASS:
        return 'success', f'request done: exit 0 on {host}'
    if code == ProducerExit.FAIL:
        return 'failure', f'request failed: exit 1 on {host}'
    return 'error', release_reason(code)


def settle(client: Client, number: int, state: str, description: str, *, log: str) -> None:
    """Comment the outcome and the log's tail on issue *number*; close it when the request succeeded."""
    tail = '\n'.join(log.rstrip().splitlines()[-TAIL_LINES:])
    client.issue_comment(number, f'**{state}** -- {description}\n\nlog tail:\n\n```\n{tail}\n```')
    if state == 'success':
        client.issue_close(number)
