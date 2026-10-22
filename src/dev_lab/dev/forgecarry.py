"""REACH-CARRY -- an outcome judged at A stands at a descendant B when no path changed from A to B can reach it.

THE WASTE THIS CLOSES, measured 2026-10-13 on a consumer: a full linux suite takes hours in 30-69 Slurm
shards, and every new ``integrate/main`` push superseded the run, so no commit got one verdict in a day.
Superseding is right for a test the new tip COULD change, and pure waste for every other one.

THE RULE IS DERIVED PER TEST FILE, not declared per repo. Each test file has a FOOTPRINT
(:mod:`dev_lab.dev.footprint`): its conftest chain, its transitive in-repo imports, the env, declared
reads -- EVERYTHING when it reads the repo by a path it cannot prove. An outcome of test file F at A is
CARRIED to B (:func:`carried`) when B descends from A and no path in ``git diff --no-renames A B`` lies in
F's footprint at A -- a rename counts both its sides. Any doubt (no ancestry, an unreadable declaration)
carries nothing: the carry is an optimisation, refusing it only costs the run it would have saved.

APPLIED AT TWO GRAINS, both from that one rule:

* PER OUTCOME, on a cluster run (:func:`carry_from`): B's run takes every outcome its nearest ancestor runs
  hold -- a finished record, the folded rounds of a superseded one, and the streams its last round left --
  that :func:`carried` keeps, and only runs the rest (:func:`lab_commons.hpc.run.submit_run`). The record
  names each carried outcome's origin sha, and the part counts them apart from ``ran``.
* PER PART (:func:`equivalent`): EVERY test file at A carries and no test file is added -- then the part
  a producer judged at A (a box run always finishes, :mod:`dev_lab.dev.forgeproduce`; a cluster run
  finishes unless its ref is coalesced, :mod:`dev_lab.dev.forgerun`) is ALSO posted on the tip
  (:func:`carry_target`), naming A (:class:`dev_lab.dev.platformparts.Part`).

A tip whose part is already settled (``success``/``failure``) is never overwritten: a real verdict on B
outranks one carried to it.

DOCS-ONLY-CARRIES (user ruling 2026-10-21) is the PER PART grain read from the HEAD's side (:func:`docs_only`):
memory is written after the code commit, so a docs-only head is the ordinary case and costs no run. A head
:func:`equivalent` to the nearest tested or running head of its first-parent history is never claimed -- the
claim pass posts the settled verdict on it (:mod:`dev_lab.dev.forgetake`), or it waits while that run
finishes, which is then never superseded for it (:mod:`dev_lab.dev.forgerun`) and carries on landing
(:func:`publish`). The PR review reads the same rule (:mod:`dev_lab.dev.forgereview`).

A DATA-ONLY head that is NOT equivalent -- its diff holds no Python, no :data:`~dev_lab.dev.footprint.ALWAYS`
path and no ``everywhere`` glob, but a test reads the tree by path (``reads = ["*"]``) -- also WAITS while its
source runs, then runs itself carrying every outcome its diff cannot reach (:func:`carry_from`). Measured
2026-10-22: motronics docs(memory) heads ran their full suite BESIDE their running parent, so nothing could
carry (``carried 0`` of 55k cells); 427 of 5124 test files reach a memory path there by a declared whole-tree read.
"""

from __future__ import annotations

import dataclasses
import subprocess
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from fnmatch import fnmatchcase
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import lab_commons.launch as _door

from dev_lab.dev.footprint import ALWAYS, Footprints, declared, test_files
from dev_lab.dev.forge import _GIT
from dev_lab.dev.forgeclaim import CLAIMED, Claim, assess
from dev_lab.dev.forgecoalesce import WAITING_BEHIND, earlier_tips
from dev_lab.dev.forgeschedule import tip_of
from dev_lab.dev.forgestatus import CARRIED_FROM, DOCS_ONLY, CommitStatus, status_history, status_post
from dev_lab.dev.platformparts import part_context, parts_of, post

if TYPE_CHECKING:
    from dev_lab.dev.forgework import Client

__all__ = [
    'NEAREST',
    'RUNNING',
    'SETTLED',
    'DocsOnly',
    'carried',
    'carry_from',
    'carry_target',
    'changed_paths',
    'data_only',
    'docs_only',
    'equivalent',
    'nearest',
    'part_standing',
    'publish',
    'read_by',
]

#: The states that are a part's verdict; ``pending`` is a claim and ``error`` a release.
SETTLED: Final = frozenset({'success', 'failure'})

#: How many ancestor runs B looks back at, nearest first -- each costs one footprint parse.
NEAREST: Final = 3

_GIT_TIMEOUT_S: Final = 60


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return _door.run(
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
            files[test] = '::' in node and not prints.reaches(test, changed)
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
    return not any(prints.reaches(test, changed) for test in tests)


def nearest(root: Path, b: str, shas: Iterable[str]) -> list[str]:
    """The :data:`NEAREST` of *shas* that are proper ancestors of *b*, nearest (fewest commits back) first."""
    distance = {}
    for sha in shas:
        if sha != b and _git(root, 'merge-base', '--is-ancestor', sha, b).returncode == 0:
            count = _git(root, 'rev-list', '--count', f'{sha}..{b}').stdout.strip()
            distance[sha] = int(count) if count.isdigit() else 0
    return sorted(distance, key=distance.__getitem__)[:NEAREST]


def read_by(root: Path, b: str, shas: Iterable[str]) -> list[str]:
    """The runs among *shas* that *b*'s run reads: its own earlier run first, then its :func:`nearest`.

    THE ONE SELECTION -- the cluster carry reads exactly these (:meth:`dev_lab.dev.forgeslurm.SlurmCluster.carry`)
    and storage retention keeps exactly these (:func:`dev_lab.dev.retention.carry_sources`).
    """
    shas = set(shas)
    return [*([b] if b in shas else []), *nearest(root, b, shas)]


def carry_from(
    root: Path, b: str, runs: Mapping[str, Mapping[str, tuple[dict[str, Any], str]]]
) -> dict[str, tuple[dict[str, Any], str, str]]:
    """``{node: (cell, origin sha, run sha)}`` *b* takes from *runs* -- ``{run sha: {node: (cell, origin)}}``.

    *runs* hold DECIDED plain test cells only (:func:`lab_commons.hpc.records.held_cells`): an id never
    reported or handed to another part is no answer and is never offered.

    An earlier run of *b* ITSELF -- one released retryable (an outage, a box with no room) and claimed again --
    gives every outcome it holds first: nothing changed, so each stands. Then only the :func:`nearest` runs are
    read, and an id takes the nearest run's outcome that :func:`carried` keeps. *origin* is the sha the outcome
    was RUN at (an outcome carried again keeps its first origin);
    *run sha* is the run it was read from.
    """
    taken = {node: (told[0], told[1], b) for node, told in runs.get(b, {}).items()}
    for sha in nearest(root, b, runs):
        held = {node: told for node, told in runs[sha].items() if node not in taken}
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
    """Post *record* as *sha*'s part (:func:`~dev_lab.dev.platformparts.post`); also onto an equivalent tip."""
    lines = post(root, record)
    if target := carry_target(root, client, ref=ref, sha=sha, platform=platform):
        lines += '\n' + post(root, record, onto=target)
    return lines


#: A head's part waits on this standing of its nearest tested ancestor: a run in flight (:func:`docs_only`).
RUNNING: Final = 'running'


@dataclass(frozen=True)
class DocsOnly:
    """DOCS-ONLY-CARRIES: a head that runs nothing -- its part is *source*'s, settled as *verdict* or still running."""

    source: str
    verdict: CommitStatus | None = None
    carries: bool = True  # False: a data-only head waits, then runs carrying what its diff cannot reach

    @property
    def hold(self) -> str:
        """Why the head is never claimed: carried from a settled source, else waiting behind its running one."""
        if self.verdict is not None:
            return f'{CARRIED_FROM} {self.source[:12]}: {DOCS_ONLY}'
        if not self.carries:
            return f'{WAITING_BEHIND} {self.source[:12]} (data-only: its run carries what this diff cannot reach)'
        return f'{WAITING_BEHIND} {self.source[:12]} ({DOCS_ONLY}: its result carries here)'

    def description(self, platform: str) -> str:
        """The verdict's description re-posted on the head, naming the sha it was FIRST judged at."""
        if self.verdict is None:
            msg = f'{self.source[:12]} has no verdict yet'
            raise ValueError(msg)
        part = parts_of([self.verdict])[0].get(platform)
        if part is None:
            return f'{self.verdict.description} {CARRIED_FROM} {self.source[:12]}: {DOCS_ONLY}'
        return dataclasses.replace(part, carried=part.carried or self.source[:12]).description()

    def post(self, client: Client, head: str, platform: str) -> CommitStatus:
        """Post the carried verdict on *head*: the same state and record link, no claim, no run."""
        description = self.description(platform)  # refuses a source with no verdict yet
        verdict = self.verdict or CommitStatus('', '', '', '')
        return status_post(client, head, context=verdict.context, state=verdict.state, description=description,
                           target_url=verdict.url)  # fmt: skip


def docs_only(
    root: Path, b: str, standing: Callable[[str], CommitStatus | str], *, data_waits: bool = True
) -> DocsOnly | None:
    """DOCS-ONLY-CARRIES: what *b* takes instead of a run, ``None`` when *b* runs itself.

    *standing* says where a sha's job stands: its settled verdict, :data:`RUNNING`, or ``''`` (never tested).
    *b*'s first-parent history is read newest first to the nearest sha that is tested or running; *b* takes
    it when :func:`equivalent` -- no collected test's footprint reaches the diff, the same rule every carry
    uses -- else *b* runs, except that a :func:`data_only` diff from a RUNNING source waits for it (module
    docstring) -- a test part's rule only: a review (*data_waits* off) carries nothing per outcome.
    An untested head in between is read through: when it touched code, the diff from the tested
    head holds that code, and *b* runs.
    """
    for sha in earlier_tips(root, b):
        stood = standing(sha)
        if stood:
            if equivalent(root, sha, b):
                return DocsOnly(sha, stood if isinstance(stood, CommitStatus) else None)
            waits = data_waits and stood == RUNNING and data_only(root, sha, b)
            return DocsOnly(sha, None, carries=False) if waits else None
    return None


def data_only(root: Path, a: str, b: str) -> bool:
    """Whether ``a..b`` changes no Python file, no ``ALWAYS`` path and no declared ``everywhere`` glob."""
    changed = changed_paths(root, a, b)
    shown = _git(root, 'show', f'{b}:pyproject.toml')
    try:
        everywhere, _ = declared(shown.stdout if shown.returncode == 0 else '')
    except ValueError:
        return False
    return bool(changed) and not any(
        path.endswith('.py') or path in ALWAYS or any(fnmatchcase(path, glob) for glob in everywhere)
        for path in changed or ()
    )


def part_standing(
    history: Callable[[str], Sequence[CommitStatus]], context: str, now: datetime
) -> Callable[[str], CommitStatus | str]:
    """The :func:`docs_only` *standing* of a part in *context*: its settled post, a live claim, else nothing."""
    nobody = Claim('', '', now)

    def stood(sha: str) -> CommitStatus | str:
        posts = [status for status in history(sha) if status.context == context]
        if posts and posts[-1].state in SETTLED:
            return posts[-1]
        return RUNNING if assess(posts, context, me=nobody, now=now)[0] == CLAIMED else ''

    return stood
