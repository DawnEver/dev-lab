"""A LOCAL RUN AS PARTS -- what a workstation's verify posts, in the cluster record's shape.

The cluster's parts come from ``hpc run gather``; a local run's come from here, so both are one kind of
run record and post as one kind of ``tests/<part>`` part (:mod:`dev_lab.dev.platformparts`). Each
reported id belongs to ONE part, its need-set (:mod:`lab_commons.hpc.needsets`); a record holds the test
cells of its own part's ids and names, in ``handed``, the part every other collected id belongs to.

WHICH PARTS A RUN POSTS. A producer told its part (``verify --part <part>``, the declared ``produce``)
posts exactly that part. A run nobody named a part for posts EVERY part it judged whose needs THIS host
has (:func:`present_here`: its OS and the tools its machine file declares and the probes find) -- a FEMM
test that ran on a host without FEMM proved nothing about FEMM, so its part is not posted from here.
Measured 2026-10-11: a windows full verify of lab-commons covered nothing under the old per-OS
assignment; under need-sets every unmarked test is ``base`` and a bare verify posts it.

The record is written where ``[tool.dev_lab.parts] output`` declares
(:func:`dev_lab.dev.platformparts.record_directory`). A CITED verdict posts from the cited run's own
outcomes, kept beside its log: the cache already holds the evidence, so nothing re-runs.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from lab_commons.box.machine import provided
from lab_commons.box.providers import inventory
from lab_commons.compute.presence import cached, declared_versions, measured, refresh
from lab_commons.compute.probe import os_name
from lab_commons.config import section
from lab_commons.envkey import env_record
from lab_commons.hpc.needsets import BASE, need_sets, needs_of, read_vocabulary, selecting, vocabulary_at
from lab_commons.hpc.records import write_record
from lab_commons.hpc.shell import FULL, INCREMENTAL
from lab_commons.hpc.testcells import TestCell

from dev_lab.dev.forgeoutbox import PostFailed
from dev_lab.dev.forgestatus import verdict_commit
from dev_lab.dev.jobparts import pytest_collector
from dev_lab.dev.partrows import row_part, row_system, this_platform
from dev_lab.dev.platformparts import PartRefusal, UndeclaredPart, post, record_directory
from dev_lab.dev.test_outcomes import outcomes_dir, read_cells

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Mapping, Sequence

__all__ = ['local_record', 'owners', 'part_selection', 'post_cited', 'post_local', 'post_part', 'present_here']


def present_here(root: Path) -> frozenset[str]:
    """The resources THIS host has: its OS, and every tool present or declared without a check.

    Presence is re-probed where due against *root*'s declared versions (:func:`lab_commons.compute.presence.refresh`).
    """
    found = inventory(provided(section('capabilities')), refresh(declared_versions(root)))
    return frozenset({this_platform(), *(name for name, one in found.items() if one.present)})


def owners(root: Path, sha: str, reported: Collection[str], collect: Callable[[str], Sequence[str]]) -> dict[str, str]:
    """``{id: its part}`` over the *reported* ids and everything collected; no resources declared: all base.

    *collect* is asked once for everything (``''``) and once per declared resource marker.
    """
    vocabulary = vocabulary_at(root, sha)
    if not vocabulary.resources:
        return dict.fromkeys(reported, BASE)
    ids = list(dict.fromkeys([*reported, *collect('')]))
    return need_sets(ids, {name: set(collect(name)) for name in vocabulary.resources})


def local_record(
    *,
    sha: str,
    part: str,
    scope: str,
    req: str,
    cells: Mapping[str, TestCell],
    owned: Mapping[str, str],
    flaky: Collection[str] = (),
    tools: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """The run record of *part* from a LOCAL run, in the cluster record's shape.

    An id of *part* the run reported carries its test cell (and is ``flaky`` when the run decided it both
    ways); every other id of *owned* (id -> part) is handed off to the part it belongs to.
    It states the environment it ran against
    (:func:`lab_commons.envkey.env_record`) and the vendor tool versions this host's presence probe READ
    (*tools*, default :func:`lab_commons.compute.presence.measured` over the cached reading): nothing is
    pinned, so the record is the reproducibility.
    """
    need = row_part(part)
    mine = [node for node, owner in owned.items() if owner == need and node in cells]
    handed = {node: owner for node, owner in owned.items() if owner != need}
    return {
        'sha': sha,
        'platform': part,
        'scope': scope,
        'req': req,
        'cells': {node: cells[node].to_plain() for node in mine},
        'flaky': sorted(node for node in flaky if node in mine),
        'handed': handed,
        **env_record(),
        'tools': dict(measured(cached()) if tools is None else tools),
    }


def post_local(root: Path, record: Mapping[str, Any], directory: Path) -> str:
    """Write *record* under *directory* and post its part; a refused part is one line, never a raise."""
    path = write_record(dict(record), directory)
    try:
        return post(root, path)
    except (PartRefusal, PostFailed) as why:
        return f'[platformparts] not posted: {why}'


def post_cited(
    root: Path,
    cited_log: str,
    arguments: tuple[str, ...],
    *,
    head: str | None,
    dirt: tuple[str, ...],
    part: str = '',
) -> str:
    """Post a CITED run's part(s); its outcomes beside its log (``<path>@<digest>`` in the cache) are the evidence.

    It is about *head* only when the tree is clean (*dirt* empty); nothing re-runs.
    """
    log = root / cited_log.split('@', 1)[0]
    return post_part(root, log, verdict_commit(head, head, dirt, dirt), arguments, settled=True, part=part)


def post_part(
    root: Path,
    log: Path,
    commit: str | None,
    arguments: tuple[str, ...],
    *,
    settled: bool,
    part: str = '',
    present: Callable[[], frozenset[str]] | None = None,
) -> str:
    """Post the run judged in *log* as *part* of *commit*, or every part this host has the needs of; one line each.

    With no *part*: every part it judged whose needs this host has (module docstring).

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

    collect = pytest_collector(root, arguments)
    judged = outcomes_dir(log)
    cells, flaky = read_cells(judged)
    owned = owners(root, commit, list(cells), collect)
    if part:
        chosen = [part]
    else:
        here = present() if present else present_here(root)
        chosen = sorted({owned[node] for node in cells if needs_of(owned[node]) <= here}) or [BASE]
    scope = INCREMENTAL if arguments else FULL
    return '\n'.join(
        post_local(
            root,
            local_record(sha=commit, part=name, scope=scope, req=log.stem, cells=cells, owned=owned, flaky=flaky),
            directory,
        )
        for name in chosen
    )


def part_selection(root: Path, part: str) -> tuple[str, ...]:
    """The pytest arguments selecting exactly *part*'s tests in *root*'s checkout; ``()`` for no part.

    Raises:
        ValueError: *part* is no need-set over the checkout's declared resources, or a row of another OS.

    """
    if (system := row_system(part)) and system != os_name():
        msg = f'{part} is the {system} row of {row_part(part)}; this host runs {os_name()}'
        raise ValueError(msg)
    manifest = root / 'pyproject.toml'
    declared = manifest.read_text(encoding='utf-8') if manifest.is_file() else ''
    expression = selecting(read_vocabulary(declared), row_part(part)) if part else ''
    return ('-m', expression) if expression else ()
