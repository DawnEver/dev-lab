"""PARTS PRODUCED BY WORKFLOW JOBS -- GitHub's producer of the same ``tests/<part>`` parts (:mod:`platformparts`).

ONE LIFECYCLE ON BOTH FORGES (user ruling 2026-10-29); only who PRODUCES and who TRIGGERS differ. On Gitea a
``forge serve`` host claims a part and runs the declared producer; on GitHub a workflow fans out one job per part:

* ``python -m dev_lab.dev.jobparts matrix [--runners hosted] [--event <name>]`` prints the checkout's parts, each
  with the runner its need-set needs (:func:`runner_for`), as the JSON a workflow's ``fromJSON`` fans out over --
  the matrix is this COMMAND's output, never a list typed into a workflow. A part that names no OS and runs hosted
  runs on every OS of the EVENT (:func:`systems_for`, ruling D84): a pull request on linux and windows, a push or a
  dispatch on macos too. Its row off its own runner is ``<part>@<os>`` (``tests/base@windows``), its own status, so
  two OSes are two settled results; a part that names an OS keeps exactly that OS;
* each job runs ``produce <part>``: the ONE declared producer (:func:`dev_lab.dev.platformparts.producer_argv`),
  which posts its part as any local verify does, the job token being the credential there
  (:func:`dev_lab.dev.forgework.actions_token`);
* an ``if: always()`` job runs ``absent <sha>`` over the SAME event's matrix: ``failure`` on every row the
  checkout derives that no job settled, so a job that died before posting -- or a part no hosted runner can
  produce -- reads red, never as nothing; merge-ready and promote then read every row (one source).
  :data:`ABSENT` is never a part's own description, so it is never read as a part.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import lab_commons.launch as _door
from lab_commons.compute.probe import OS_NAMES
from lab_commons.hpc.needsets import BASE, need_sets, needs_of, read_vocabulary
from lab_commons.hpc.shell import parse_ids
from lab_commons.log import emit

from dev_lab.dev.forgestatus import status_list, status_post
from dev_lab.dev.forgework import client_for
from dev_lab.dev.partrows import ROW_SEPARATOR
from dev_lab.dev.platformparts import part_context, producer_argv
from dev_lab.dev.producer import producing
from dev_lab.dev.unproduced import unproduced, unproduced_parts

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from dev_lab.dev.forgework import Client

__all__ = [
    'ABSENT',
    'HOSTED_RUNNERS',
    'absent',
    'main',
    'matrix',
    'produce',
    'pytest_collector',
    'runner_for',
    'systems_for',
]

#: The GitHub-hosted runner of each OS resource (the values of :data:`lab_commons.compute.probe.OS_NAMES`).
HOSTED_RUNNERS: Final = {'linux': 'ubuntu-latest', 'macos': 'macos-latest', 'windows': 'windows-latest'}

#: The OSes a pull request's OS-free parts run on (ruling D84); every other event runs them on every hosted OS.
PULL_REQUEST_SYSTEMS: Final = ('linux', 'windows')

#: What an expected part no job settled says (``failure``): never a part's own description, so never a part.
ABSENT: Final = 'absent: no job settled this part'

#: The states a settled part reads back as.
_SETTLED: Final = frozenset({'success', 'failure'})


def pytest_collector(root: Path, arguments: Sequence[str] = ()) -> Callable[[str], list[str]]:
    """A collector over *root*'s checkout: given a marker expression (``''`` for none), the ids pytest collects."""

    def collect(expression: str) -> list[str]:
        argv = [sys.executable, '-m', 'pytest', '--collect-only', '-q', '-p', 'no:cacheprovider', '--color=no']
        command = [*argv, *(['-m', expression] if expression else []), *arguments]
        done = _door.run(command, cwd=root, capture_output=True, text=True, encoding='utf-8', check=False)
        return parse_ids(done.stdout)

    return collect


def runner_for(part: str) -> str | list[str]:
    """*part*'s ``runs-on``: a hosted runner when it needs at most one OS, else a self-hosted runner's labels.

    A need-set naming a resource no hosted runner has (``femm``) runs on a self-hosted runner labelled with every
    resource it needs, so a workstation registered under those labels produces it.
    """
    needs = needs_of(part)
    systems = needs & set(OS_NAMES.values())
    if needs == systems and len(systems) <= 1:
        return HOSTED_RUNNERS[next(iter(systems), 'linux')]
    return ['self-hosted', *sorted(needs)]


def systems_for(event: str) -> tuple[str, ...]:
    """The OSes a part naming none runs on for GitHub *event*: :data:`PULL_REQUEST_SYSTEMS`, else every one."""
    return PULL_REQUEST_SYSTEMS if event == 'pull_request' else tuple(sorted(HOSTED_RUNNERS))


def _rows(part: str, event: str) -> list[dict[str, Any]]:
    """*part*'s matrix rows: one per OS of *event* when it runs hosted and names no OS, else its one runner."""
    home = runner_for(part)
    if not isinstance(home, str) or needs_of(part) & set(OS_NAMES.values()):
        return [{'part': part, 'runs-on': home}]
    runners = {system: HOSTED_RUNNERS[system] for system in systems_for(event)}
    return [
        {'part': part if runner == home else f'{part}{ROW_SEPARATOR}{system}', 'runs-on': runner}
        for system, runner in runners.items()
    ]


def matrix(
    root: Path, *, collect: Callable[[str], Sequence[str]], event: str, hosted: bool = False
) -> dict[str, list[dict[str, Any]]]:
    """The rows of the parts *root*'s checkout derives (:data:`BASE` always) for GitHub *event*: a fromJSON matrix.

    A part needing a resource the checkout declares ``unproduced`` has no row (:mod:`dev_lab.dev.unproduced`).
    Each part has its :func:`runner_for` row, plus one per further OS of *event* when it names none (:func:`_rows`).
    *hosted* keeps only the rows a GitHub-hosted runner produces; :func:`absent` then names the rest.
    """
    pyproject = root / 'pyproject.toml'
    text = pyproject.read_text(encoding='utf-8') if pyproject.is_file() else ''
    vocabulary = read_vocabulary(text)
    ids = list(collect(''))
    carrying = {name: set(collect(name)) for name in vocabulary.resources}
    derived = {BASE, *need_sets(ids, carrying).values()}
    names = sorted(derived - unproduced_parts(derived, unproduced(text)))
    rows = [row for name in names for row in _rows(name, event)]
    return {'include': [row for row in rows if not hosted or isinstance(row['runs-on'], str)]}


def absent(client: Client, sha: str, expected: Mapping[str, Any]) -> list[str]:
    """Post ``failure`` saying :data:`ABSENT` on each part of *expected* (a :func:`matrix`) no job settled; the lines.

    Settled is a latest ``success`` or ``failure``: a ``pending`` claim left behind is a job that died -- absent.
    """
    latest = {status.context: status.state for status in status_list(client, sha)}
    lines = []
    for context in sorted(part_context(one['part']) for one in expected['include']):
        if latest.get(context) not in _SETTLED:
            status_post(client, sha, context=context, state='failure', description=ABSENT)
            lines.append(f'{context}: {ABSENT}')
    return lines


def produce(root: Path, part: str) -> int:
    """Run the one declared producer of *part* at *root*'s HEAD with this interpreter, cwd *root*; its exit code.

    The job IS the producer of ``tests/<part>`` at that sha, so the child carries :func:`producing` -- the same
    marker ``forge serve`` hands its producer -- and the full suite it runs is admitted for that part only.
    """
    head = _door.run(
        ['git', 'rev-parse', 'HEAD'], cwd=root, capture_output=True, text=True, encoding='utf-8', check=True
    )
    sha = head.stdout.strip()
    argv = producer_argv(root, part, sha=sha)
    env = os.environ | producing(part_context(part), sha)
    return _door.run([sys.executable, *argv], cwd=root, env=env, check=False).returncode


def main(argv: Sequence[str] | None = None) -> int:
    """``matrix [--runners hosted]``, ``produce <row>``, ``absent <sha>``; each list per ``--event`` (module docs)."""
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.jobparts', description=__doc__.splitlines()[0])
    verbs = parser.add_subparsers(dest='verb', required=True)
    listing = verbs.add_parser('matrix', help="print the checkout's parts and their runners as a fromJSON matrix")
    listing.add_argument(
        '--runners', choices=('all', 'hosted'), default='all',
        help='hosted: only the parts a GitHub-hosted runner produces (absent names the rest)',
    )  # fmt: skip
    verbs.add_parser('produce', help='run the declared producer of one part at HEAD').add_argument('part')
    verbs.add_parser('absent', help='post failure on every derived part no job settled').add_argument('sha')
    for sub in (listing, verbs.choices['absent']):
        sub.add_argument(
            '--event', default='push', help='the GitHub event whose OSes the rows span (default push: every OS)'
        )
    for sub in verbs.choices.values():
        sub.add_argument('--root', type=Path, default=Path.cwd(), help='the checkout the parts are derived from')
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    collect = pytest_collector(args.root)
    if args.verb == 'matrix':
        emit(json.dumps(matrix(args.root, collect=collect, event=args.event, hosted=args.runners == 'hosted')))
        return 0
    if args.verb == 'produce':
        return produce(args.root, args.part)
    for line in absent(client_for(args.root), args.sha, matrix(args.root, collect=collect, event=args.event)):
        emit(f'[jobparts] {line}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
