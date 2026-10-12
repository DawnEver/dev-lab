"""A LOCAL RUN AS A PART -- what a workstation's verify posts, in the cluster record's shape.

The cluster's linux part comes from ``hpc run gather``; a local run's part comes from here, so both are
one kind of run record and post as one kind of ``tests/<platform>`` part
(:mod:`lab_commons.dev.platformparts`). A local verify runs EVERY collected id, so its record COVERS
every id it judged that the commit's platform table lets this platform run, and hands off ``not-covered``
only the ids this platform cannot run -- measured 2026-10-11: assigning by the cluster's rule left a
windows full verify of lab-commons (no platform markers, so every id is linux's) covering nothing, and
neither a fresh nor a cited PASS ever posted a part.

The record is written where ``[tool.lab_commons.parts] output`` declares
(:func:`lab_commons.dev.platformparts.record_directory`). A CITED verdict posts from the cited run's own
outcomes, kept beside its log: the cache already holds the evidence, so nothing re-runs.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from lab_commons.dev.forgeoutbox import PostFailed
from lab_commons.dev.forgestatus import verdict_commit
from lab_commons.dev.outcomes import outcomes_dir, read_outcomes, read_reasons
from lab_commons.dev.platformparts import PartRefusal, UndeclaredPart, post, record_directory, this_platform
from lab_commons.hpc.platforms import cannot_run, runnable, table_at
from lab_commons.hpc.records import write_record
from lab_commons.hpc.shell import FULL, INCREMENTAL, parse_ids

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

__all__ = ['local_record', 'post_cited', 'post_local', 'post_part']

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

    The ids are the ones the run reported (*collect* is asked only for the marker expressions the table
    declares). An id *platform* can run carries its outcome; an id it cannot run is handed off,
    ``not-covered``, with the platforms that can.
    """
    table = table_at(root, sha)
    cannot = {name: set(collect(expr)) for name in table.parts if (expr := cannot_run(table, name))}
    can = runnable(list(outcomes), cannot)
    mine = [node for node, platforms in can.items() if platform in platforms]
    handed = {node: platforms for node, platforms in can.items() if platform not in platforms}
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


def post_cited(
    root: Path, cited_log: str, arguments: tuple[str, ...], *, head: str | None, dirt: tuple[str, ...]
) -> str:
    """Post a CITED run's part; its outcomes beside its log (``<path>@<digest>`` in the cache) are the evidence.

    It is about *head* only when the tree is clean (*dirt* empty); nothing re-runs.
    """
    log = root / cited_log.split('@', 1)[0]
    return post_part(root, log, verdict_commit(head, head, dirt, dirt), arguments, settled=True)


def post_part(root: Path, log: Path, commit: str | None, arguments: tuple[str, ...], *, settled: bool) -> str:
    """Post the run judged in *log* as this platform's ``tests/<platform>`` part of *commit*; one line says what.

    *log* is a fresh verdict's log or a CITED run's evidence; its outcomes sit beside it.
    """
    if commit is None:
        return 'part: not posted -- the tree was dirty or moved, so this run is about no commit'
    if not settled:
        return 'part: not posted -- an INCONCLUSIVE run is no part'
    try:
        directory = record_directory(root, commit)
    except UndeclaredPart as why:
        return f'part: not posted -- {why}'

    def collect(expression: str) -> list[str]:
        argv = [sys.executable, '-m', 'pytest', '--collect-only', '-q', '-p', 'no:cacheprovider', '--color=no']
        command = [*argv, '-m', expression, *arguments]
        done = subprocess.run(command, cwd=root, capture_output=True, text=True, encoding='utf-8', check=False)
        return parse_ids(done.stdout)

    judged = outcomes_dir(log)
    record = local_record(
        root,
        sha=commit,
        platform=this_platform(),
        scope=INCREMENTAL if arguments else FULL,
        req=log.stem,
        outcomes=read_outcomes(judged),
        reasons=read_reasons(judged),
        collect=collect,
    )
    return post_local(root, record, directory)
