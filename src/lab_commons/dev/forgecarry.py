"""REACH-CARRY -- an outcome judged at A stands at a descendant B when no path changed from A to B can reach it.

THE WASTE THIS CLOSES, measured 2026-10-13 on a consumer: a full linux suite takes hours in 30-69 Slurm
shards, and every new ``integrate/main`` push superseded the run, so no commit got one verdict in a day.
Superseding is right for a test the new tip COULD change, and pure waste for every other one.

THE RULE IS DERIVED PER TEST FILE, not declared per repo. Each test file has a FOOTPRINT
(:mod:`lab_commons.dev.footprint`): its conftest chain, its transitive in-repo imports, the env, declared
reads -- EVERYTHING when it reads the repo by a path it cannot prove. An outcome of test file F at A is
CARRIED to B (:func:`carried`) when B descends from A and no path in ``git diff --no-renames A B`` lies in
F's footprint at A -- a rename counts both its sides. Any doubt (no ancestry, an unreadable declaration)
carries nothing: the carry is an optimisation, refusing it only costs the run it would have saved.

APPLIED AT TWO GRAINS, both from that one rule:

* PER OUTCOME, on a cluster run (:func:`carry_from`): B's run takes every outcome its nearest ancestor runs
  hold -- a finished record, the folded rounds of a superseded one, and the streams its last round left --
  that :func:`carried` keeps, and only runs the rest (:func:`lab_commons.hpc.run.submit_run`). The record
  names each carried outcome's origin sha, and the part counts them apart from ``ran``.
* PER PART (:func:`equivalent`): EVERY test file at A carries and no test file is added -- then a producer
  whose ref moved on is NOT superseded, it finishes (:mod:`lab_commons.dev.forgeproduce`,
  :func:`lab_commons.dev.forgerun.supersede_moved`), and its part is ALSO posted on the tip
  (:func:`carry_target`), naming A (:class:`lab_commons.dev.platformparts.Part`).

A tip whose part is already settled (``success``/``failure``) is never overwritten: a real verdict on B
outranks one carried to it.
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Final

from lab_commons.dev.footprint import Footprints, test_files
from lab_commons.dev.forge import _GIT
from lab_commons.dev.forgeschedule import tip_of
from lab_commons.dev.forgestatus import status_history
from lab_commons.dev.platformparts import part_context, post

if TYPE_CHECKING:
    from lab_commons.dev.forgework import Client

__all__ = [
    'NEAREST',
    'SETTLED',
    'UNCARRIED',
    'carried',
    'carry_from',
    'carry_target',
    'changed_paths',
    'equivalent',
    'nearest',
    'publish',
]

#: The states that are a part's verdict; ``pending`` is a claim and ``error`` a release.
SETTLED: Final = frozenset({'success', 'failure'})

#: The outcomes that are not a run's: an id never reported, or handed to another part.
UNCARRIED: Final = frozenset({'lost', 'missing', 'not-covered'})

#: How many ancestor runs B looks back at, nearest first -- each costs one footprint parse.
NEAREST: Final = 3

_GIT_TIMEOUT_S: Final = 60


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [_GIT, '-C', str(root), *args],
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        timeout=_GIT_TIMEOUT_S,
        check=False,
    )


def changed_paths(root: Path, a: str, b: str) -> tuple[str, ...] | None:
    """Every path ``git diff --no-renames`` names from *a* to *b*, sorted; ``None`` unless *b* descends from *a*."""
    if _git(root, 'merge-base', '--is-ancestor', a, b).returncode != 0:
        return None
    done = _git(root, 'diff', '--no-renames', '--name-only', a, b)
    if done.returncode != 0:
        return None
    return tuple(sorted(line for line in done.stdout.splitlines() if line))


def _judged(root: Path, a: str, b: str) -> tuple[tuple[str, ...], Footprints] | None:
    """The diff from *a* to *b* and *a*'s footprints; ``None`` on any doubt (module docstring)."""
    changed = changed_paths(root, a, b)
    if changed is None:
        return None
    try:
        return changed, Footprints.at(root, a)
    except (ValueError, subprocess.SubprocessError):
        return None


def carried(root: Path, a: str, b: str, nodes: Iterable[str]) -> frozenset[str]:
    """The node ids of *nodes* whose outcome at *a* stands at its descendant *b* (module docstring)."""
    judged = _judged(root, a, b)
    if judged is None:
        return frozenset()
    changed, prints = judged
    nodes = tuple(nodes)
    files: dict[str, bool] = {}
    for node in nodes:
        test = node.split('::', 1)[0]
        if test not in files:
            files[test] = '::' in node and not prints.of(test).reaches_any(changed)
    return frozenset(node for node in nodes if files[node.split('::', 1)[0]])


def equivalent(root: Path, a: str, b: str) -> bool:
    """Whether EVERY test file at *a* carries to its descendant *b* and *b* adds no test file (module docstring)."""
    judged = _judged(root, a, b)
    if judged is None:
        return False
    changed, prints = judged
    tests = prints.tests()
    if not tests or test_files(prints.pyproject, sorted(set(changed) - prints.tracked)):
        return False
    return not any(prints.of(test).reaches_any(changed) for test in tests)


def nearest(root: Path, b: str, shas: Iterable[str]) -> list[str]:
    """The :data:`NEAREST` of *shas* that are proper ancestors of *b*, nearest (fewest commits back) first."""
    distance = {}
    for sha in shas:
        if sha != b and _git(root, 'merge-base', '--is-ancestor', sha, b).returncode == 0:
            count = _git(root, 'rev-list', '--count', f'{sha}..{b}').stdout.strip()
            distance[sha] = int(count) if count.isdigit() else 0
    return sorted(distance, key=distance.__getitem__)[:NEAREST]


def carry_from(
    root: Path, b: str, runs: Mapping[str, Mapping[str, tuple[str, str]]]
) -> dict[str, tuple[str, str, str]]:
    """``{node: (outcome, origin sha, run sha)}`` *b* takes from *runs* -- ``{run sha: {node: (outcome, origin)}}``.

    Only the :func:`nearest` runs are read, and an id takes the nearest run's outcome that :func:`carried`
    keeps. *origin* is the sha the outcome was RUN at (an outcome carried again keeps its first origin);
    *run sha* is the run it was read from.
    """
    taken: dict[str, tuple[str, str, str]] = {}
    for sha in nearest(root, b, runs):
        held = {node: told for node, told in runs[sha].items() if node not in taken and told[0] not in UNCARRIED}
        for node in carried(root, sha, b, held):
            taken[node] = (held[node][0], held[node][1], sha)
    return taken


def carry_target(root: Path, client: Client, *, ref: str, sha: str, platform: str) -> str:
    """*ref*'s origin tip when *sha*'s *platform* part should also be posted there; else ``''``.

    The tip must have moved past *sha*, be :func:`equivalent` to it, and hold no settled part of its own.
    """
    tip = tip_of(root, ref)
    if not tip or tip == sha or not equivalent(root, sha, tip):
        return ''
    context = part_context(platform)
    posts = [status for status in status_history(client, tip) if status.context == context]
    return '' if posts and posts[-1].state in SETTLED else tip


def publish(root: Path, record: Path, *, client: Client, ref: str, sha: str, platform: str) -> str:
    """Post *record* as *sha*'s part (:func:`~lab_commons.dev.platformparts.post`); also onto an equivalent tip."""
    lines = post(root, record)
    if target := carry_target(root, client, ref=ref, sha=sha, platform=platform):
        lines += '\n' + post(root, record, onto=target)
    return lines
