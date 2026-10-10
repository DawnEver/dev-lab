"""A LOCAL RUN AS A PART -- what a workstation's verify posts, in the cluster record's shape.

The cluster's linux part comes from ``hpc run gather``; a local run's part comes from here, so both are
one kind of run record and post as one kind of ``tests/<platform>`` part
(:mod:`lab_commons.dev.platformparts`). The ids are assigned by the commit's platform table exactly as
:func:`lab_commons.dev.platformparts.select` assigns them: an id assigned to this platform carries its
outcome, every other id is handed off ``not-covered``.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from lab_commons.dev.forgeoutbox import PostFailed
from lab_commons.dev.outcomes import outcomes_dir, read_outcomes, read_reasons
from lab_commons.dev.platformparts import PartRefusal, post, split, this_platform
from lab_commons.hpc.platforms import PLATFORMS, cannot_run, runnable, table_at
from lab_commons.hpc.records import write_record
from lab_commons.hpc.shell import FULL, INCREMENTAL, parse_ids

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from lab_commons.dev.verdict import Verdict

__all__ = ['local_record', 'post_local', 'post_part']

#: The record's word for an id handed to another part (the cluster record's own).
_NOT_COVERED = 'not-covered'


def local_record(
    root: Path,
    *,
    sha: str,
    platform: str,
    scope: str,
    req: str,
    outcomes: Mapping[str, str],
    reasons: Mapping[str, str],
    collect: Callable[[str], Sequence[str]],
) -> dict[str, Any]:
    """The run record of a LOCAL run, in the cluster record's shape, so it posts as the same kind of part.

    The ids are the ones the run reported; each is assigned by the commit's table exactly as
    :func:`select` assigns them (*collect* is asked only for the marker expressions the table declares).
    An id assigned to *platform* carries its outcome; every other id is handed off, ``not-covered``.
    """
    table = table_at(root, sha)
    cannot = {name: set(collect(expr)) for name in PLATFORMS if (expr := cannot_run(table, name))}
    mine, handed = split(runnable(list(outcomes), cannot), platform)
    return {
        'sha': sha,
        'platform': platform,
        'scope': scope,
        'req': req,
        'outcomes': {**{node: outcomes[node] for node in mine}, **dict.fromkeys(handed, _NOT_COVERED)},
        'handed': handed,
        'reasons': {node: why for node, why in reasons.items() if node in mine},
    }


def post_local(root: Path, record: Mapping[str, Any], directory: Path) -> str:
    """Write *record* under *directory* and post its part; a refused part is one line, never a raise."""
    path = write_record(dict(record), directory)
    try:
        return post(root, path)
    except (PartRefusal, PostFailed) as why:
        return f'[platformparts] not posted: {why}'


def post_part(root: Path, verdict: Verdict, commit: str | None, arguments: tuple[str, ...]) -> str:
    """Post a settled run as this platform's ``tests/<platform>`` part of *commit*; one line says what happened."""
    if commit is None:
        return 'part: not posted -- the tree was dirty or moved, so this run is about no commit'
    if not verdict.result.outcome.settled:
        return 'part: not posted -- an INCONCLUSIVE run is no part'
    directory = outcomes_dir(verdict.log.path)

    def collect(expression: str) -> list[str]:
        argv = [sys.executable, '-m', 'pytest', '--collect-only', '-q', '-p', 'no:cacheprovider', '--color=no']
        command = [*argv, '-m', expression, *arguments]
        done = subprocess.run(command, cwd=root, capture_output=True, text=True, encoding='utf-8', check=False)
        return parse_ids(done.stdout)

    record = local_record(
        root,
        sha=commit,
        platform=this_platform(),
        scope=INCREMENTAL if arguments else FULL,
        req=verdict.log.path.stem,
        outcomes=read_outcomes(directory),
        reasons=read_reasons(directory),
        collect=collect,
    )
    return post_local(root, record, directory)
