"""Request issues as :class:`~lab_commons.compute.model.Candidate` jobs, for :mod:`dev_lab.dev.forgeschedule`.

Every request's producer and sha come from its body, its need-set from what that sha declares; the declarations
of every listed request are prefetched in ONE git child. Carved out of ``forgeschedule`` to keep it inside the
module-size band.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final

from lab_commons.compute.model import REQUEST, Candidate
from lab_commons.hpc.shell import FULL

from dev_lab.dev.forgerequest import (
    UndeclaredRequest,
    declared_request,
    parse_body,
    parse_deadline,
    parse_paths,
    prefetch_requests,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from pathlib import Path

    from dev_lab.dev.forgerequest import Declared

__all__ = ['issue_labels', 'request_candidates']

_REQUEST_SHA: Final = re.compile(r'^\s*sha\s*=\s*["\'](?P<sha>[^"\'\n]*)["\']', re.MULTILINE)
_REQUEST_HOST: Final = re.compile(r'^\s*host\s*=\s*["\'](?P<host>[\w./-]+)["\']', re.MULTILINE)


def issue_labels(raw: Mapping[str, Any]) -> tuple[str, ...]:
    """The label names a raw forge issue carries."""
    return tuple(str(label['name']) for label in raw.get('labels') or ())


def request_candidates(
    root: Path,
    issues: Sequence[Mapping[str, Any]],
    repo: str,
    now: datetime,
    *,
    late: str,
    say: Callable[[str], None],
    declare: Callable[..., Declared] = declared_request,
) -> list[Candidate]:
    """Every request issue in *issues* as a job; one past its deadline is refused with the *late* reason.

    A request whose producer is undeclared is still listed (part ``''``): the claim pass refuses it by name.
    One naming no full sha is work at no commit: it is SKIPPED and said, one line naming the issue.
    """
    found = []
    asks = [(parse_body(body), parse_paths(body)) for body in (raw.get('body') or '' for raw in issues)]
    prefetch_requests(root, [(sha, producer, paths) for (producer, sha), paths in asks if sha])  # ONE git child
    for raw in issues:
        body = raw.get('body') or ''
        producer, sha = parse_body(body)
        if not sha:
            named = _REQUEST_SHA.search(body)
            got = f' (got "{named["sha"]}")' if named else ''
            say(f'[serve] skipped request issue #{raw["number"]}: its body names no 40-hex `sha`{got}')
            continue
        paths = parse_paths(body)
        created = raw.get('created_at') or ''
        since = datetime.fromisoformat(created).astimezone(UTC) if created else now
        try:
            platform = declare(root, sha, producer, paths).part
        except UndeclaredRequest:
            platform = ''
        number = int(raw['number'])
        host = _REQUEST_HOST.search(body)
        deadline = parse_deadline(body)
        refused = f'{late}: unclaimed at its deadline {deadline.isoformat()}' if deadline and now > deadline else ''
        found.append(
            Candidate(
                repo,
                f'issue/{number}',
                sha,
                platform,
                REQUEST,
                since,
                FULL,
                labels=issue_labels(raw),
                number=number,
                origin=str((raw.get('user') or {}).get('login', '')),
                origin_host=host['host'] if host else '',
                producer=producer,
                paths=paths,
                refused=refused,
            )
        )
    return found
