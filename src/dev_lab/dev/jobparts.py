"""PARTS PRODUCED BY WORKFLOW JOBS -- GitHub's producer of the same ``tests/<part>`` parts (:mod:`platformparts`).

ONE LIFECYCLE ON BOTH FORGES (user ruling 2026-10-29); only who PRODUCES and who TRIGGERS differ. On Gitea a
``forge serve`` host claims a part and runs the declared producer; on GitHub a workflow fans out one job per part:

* ``python -m dev_lab.dev.jobparts matrix [--runners hosted]`` prints the checkout's parts, each with the runner
  its need-set needs (:func:`runner_for`), as the JSON a workflow's ``fromJSON`` fans out over -- the matrix is
  this COMMAND's output, never a list typed into a workflow;
* each job runs ``produce <part>``: the ONE declared producer (:func:`dev_lab.dev.platformparts.producer_argv`),
  which posts its part as any local verify does, the job token being the credential there
  (:func:`dev_lab.dev.forgework.actions_token`);
* an ``if: always()`` job runs ``absent <sha>``: ``failure`` on every part the checkout derives that no job
  settled, so a job that died before posting -- or a part no hosted runner can produce -- reads red, never as
  nothing. :data:`ABSENT` is never a part's own description, so it is never read as a part.
"""

from __future__ import annotations

import argparse
import json
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
from dev_lab.dev.platformparts import part_context, producer_argv

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from dev_lab.dev.forgework import Client

__all__ = ['ABSENT', 'HOSTED_RUNNERS', 'absent', 'main', 'matrix', 'produce', 'pytest_collector', 'runner_for']

#: The GitHub-hosted runner of each OS resource (the values of :data:`lab_commons.compute.probe.OS_NAMES`).
HOSTED_RUNNERS: Final = {'linux': 'ubuntu-latest', 'macos': 'macos-latest', 'windows': 'windows-latest'}

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


def matrix(
    root: Path, *, collect: Callable[[str], Sequence[str]], hosted: bool = False
) -> dict[str, list[dict[str, Any]]]:
    """The parts *root*'s checkout derives (:data:`BASE` always), each with :func:`runner_for`: a fromJSON matrix.

    *hosted* keeps only the parts a GitHub-hosted runner produces; :func:`absent` then names the rest.
    """
    pyproject = root / 'pyproject.toml'
    vocabulary = read_vocabulary(pyproject.read_text(encoding='utf-8') if pyproject.is_file() else '')
    ids = list(collect(''))
    carrying = {name: set(collect(name)) for name in vocabulary.resources}
    names = sorted({BASE, *need_sets(ids, carrying).values()})
    rows = [{'part': name, 'runs-on': runner_for(name)} for name in names]
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
    """Run the one declared producer of *part* at *root*'s HEAD with this interpreter, cwd *root*; its exit code."""
    head = _door.run(['git', 'rev-parse', 'HEAD'], cwd=root, capture_output=True, text=True, check=True)
    argv = producer_argv(root, part, sha=head.stdout.strip())
    return _door.run([sys.executable, *argv], cwd=root, check=False).returncode


def main(argv: Sequence[str] | None = None) -> int:
    """``matrix [--runners hosted]``, ``produce <part>``, ``absent <sha>`` (module docstring)."""
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.jobparts', description=__doc__.splitlines()[0])
    verbs = parser.add_subparsers(dest='verb', required=True)
    listing = verbs.add_parser('matrix', help="print the checkout's parts and their runners as a fromJSON matrix")
    listing.add_argument(
        '--runners', choices=('all', 'hosted'), default='all',
        help='hosted: only the parts a GitHub-hosted runner produces (absent names the rest)',
    )  # fmt: skip
    verbs.add_parser('produce', help='run the declared producer of one part at HEAD').add_argument('part')
    verbs.add_parser('absent', help='post failure on every derived part no job settled').add_argument('sha')
    for sub in verbs.choices.values():
        sub.add_argument('--root', type=Path, default=Path.cwd(), help='the checkout the parts are derived from')
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    collect = pytest_collector(args.root)
    if args.verb == 'matrix':
        emit(json.dumps(matrix(args.root, collect=collect, hosted=args.runners == 'hosted')))
        return 0
    if args.verb == 'produce':
        return produce(args.root, args.part)
    for line in absent(client_for(args.root), args.sha, matrix(args.root, collect=collect)):
        emit(f'[jobparts] {line}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
