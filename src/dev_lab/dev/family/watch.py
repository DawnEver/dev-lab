"""THE FAMILY WATCH: a half-joined member is NOTICED, not found weeks later by failing at something else.

The serve tick runs :func:`step` in its repo-wide pass (:func:`dev_lab.dev.forgeservesteps.repo_wide`), on the
dev-lab checkout's tick only (:data:`~dev_lab.dev.hpcaccount.spec.KIT`), so ONE pass per serving machine covers its
whole family. Each finding is one :data:`~dev_lab.dev.forgealarm.FAMILY` alarm ``about`` the member, so it repeats
on its own and no oftener than the alarm path's repeat window. ``python -m dev_lab.dev.family check`` is the same
reading by hand (:func:`findings`).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path

from lab_commons.config import section
from lab_commons.home import repos

from dev_lab.dev.family.forgefacts import ClientFacts
from dev_lab.dev.family.horizontal import compare, features
from dev_lab.dev.family.members import Facts, Finding, check
from dev_lab.dev.forgealarm import FAMILY, Alarm
from dev_lab.dev.forgework import client_for
from dev_lab.dev.hpcaccount.spec import KIT
from dev_lab.dev.taskkeys import REVIEW_TASK, secret_name

__all__ = ['findings', 'step']


def findings() -> list[Finding]:
    """Every finding of this machine's family, read from its forges, and the horizontal comparison of its members."""
    serve = section('serve')
    exceptions = section('family').get('exceptions', {})

    def horizontally(read: Mapping[str, tuple[Path, Facts]]) -> list[Finding]:
        return compare(
            {name: (facts.host, features(root, facts)) for name, (root, facts) in read.items()},
            exceptions,
            {secret_name(REVIEW_TASK)},
        )

    return check(repos(), forge=lambda _name, root: ClientFacts(client_for(root)),
                 served=serve.get('repos') if serve else None, now=datetime.now(UTC),
                 bundle_name=secret_name(REVIEW_TASK), compare=horizontally)  # fmt: skip


def step(
    root: Path, repo: str, *, say: Callable[[str], None], alarm: Callable[[Alarm], object],
    read: Callable[[], list[Finding]] = findings,
) -> None:  # fmt: skip
    """On the kit's tick, one alarm per finding; any other repo's tick does nothing."""
    if root.name != KIT:
        return
    found = read()
    for finding in found:
        alarm(Alarm(FAMILY, repo, f'Family member {finding.member} is not fully joined', finding.what,
                    about=f'{finding.member}:{finding.what.split(":", 1)[0]}'))  # fmt: skip
    say(f'[serve] family: {len(found)} finding(s)' if found else '[serve] family: every fact holds')
