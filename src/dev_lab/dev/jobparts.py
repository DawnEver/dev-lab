"""PARTS PRODUCED BY WORKFLOW JOBS -- GitHub's producer of the same ``tests/<part>`` parts (:mod:`platformparts`).

ONE LIFECYCLE ON BOTH FORGES (user ruling 2026-10-29); only who PRODUCES and who TRIGGERS differ. On Gitea a
``forge serve`` host claims a part and runs the declared producer; on GitHub a workflow fans out one job per part:

* ``python -m dev_lab.dev.jobparts matrix [--runners hosted] [--event <name>]`` prints the checkout's parts, each
  with the runner its need-set needs (:func:`runner_for`), as the JSON a workflow's ``fromJSON`` fans out over --
  the matrix is this COMMAND's output, never a list typed into a workflow. A part that names no OS and runs hosted
  runs on every OS of the EVENT (:func:`systems_for`, ruling D84): a pull request on linux and windows, any other
  event on macos too (a merge's smoke run passes ``--event pull_request``, D48-1A). Its row off its own runner is
  ``<part>@<os>`` (``tests/base@windows``), its own status, so two
  OSes are two settled results; a part that names an OS keeps exactly that OS;
* each job runs ``produce <part>``: the ONE declared producer (:func:`dev_lab.dev.platformparts.producer_argv`),
  which posts its part as any local verify does, the job token being the credential there
  (:func:`dev_lab.dev.forgework.actions_token`);
* an ``if: always()`` job runs ``absent <sha>`` over the SAME event's matrix: ``failure`` on every row the
  checkout derives that no job settled, so a job that died before posting -- or a part no hosted runner can
  produce -- reads red, never as nothing; merge-ready and promote then read every row (one source).
  :data:`ABSENT` is never a part's own description, so it is never read as a part.

A PART FED BY A SECRET (user decision 2026-10-30). A part whose resource no hosted runner has can still run
hosted when repository secrets supply it; the repo declares that ONCE, in its pyproject::

    [tool.dev_lab.parts]
    hosted = { live = { secrets = ["ANTHROPIC_API_KEY"], setup = "python -m ai_lab.auth login --from-file -" } }

It gets ONE linux row, on a full run only (as macos, D84), carrying its secrets' NAMES
(:func:`hosted_parts`). The generic matrix job never runs it: :func:`hosted_jobs` renders it its own job, in which
ONE setup step alone has the secrets in its environment and reads them on stdin as ``NAME=value`` lines -- never
argv, never echoed -- before the part is produced. The render names a secret; it never holds a value.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import lab_commons.launch as _door
from lab_commons.compute.probe import OS_NAMES
from lab_commons.hpc.needsets import BASE, need_sets, needs_of, read_vocabulary
from lab_commons.hpc.shell import parse_ids
from lab_commons.log import emit

from dev_lab.dev.family import declared_in
from dev_lab.dev.forgestatus import status_list, status_post
from dev_lab.dev.forgework import client_for
from dev_lab.dev.partrows import ROW_SEPARATOR
from dev_lab.dev.platformparts import UndeclaredPart, part_context, producer_argv
from dev_lab.dev.producer import producing
from dev_lab.dev.unproduced import unproduced, unproduced_parts

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from dev_lab.dev.forgework import Client

__all__ = [
    'ABSENT',
    'HOSTED_RUNNERS',
    'Hosted',
    'absent',
    'hosted_jobs',
    'hosted_parts',
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

#: A secret's name: all that ``${{ secrets.<NAME> }}`` and ``"$<NAME>"`` carry into a rendered workflow.
_SECRET_NAME: Final = re.compile(r'[A-Z][A-Z0-9_]*')

#: The ``if`` of a hosted part's job: a FULL run's (the parts job's event is not the PR's set, as macos, D84;
#: a merge's smoke takes the PR's set, D48-1A), never one main already holds (an empty matrix).
_FULL_ONLY: Final = "${{ needs.parts.outputs.matrix != '' && needs.parts.outputs.event != 'pull_request' }}"


@dataclass(frozen=True)
class Hosted:
    """A part run hosted because secrets supply its resource: their names, and the command taking them on stdin."""

    secrets: tuple[str, ...]
    setup: str


def _malformed(name: str, entry: object, produced: set[str]) -> bool:
    """Whether hosted *entry* of part *name* is not a produced resource with named secrets and a setup command."""
    if name not in produced or not isinstance(entry, dict):
        return True
    secrets, setup = entry.get('secrets'), entry.get('setup')
    named = isinstance(secrets, list) and bool(secrets)
    named = named and all(isinstance(one, str) and _SECRET_NAME.fullmatch(one) for one in secrets)
    return not named or not isinstance(setup, str) or not setup.strip()


def hosted_parts(text: str) -> dict[str, Hosted]:
    """``[tool.dev_lab.parts] hosted`` of pyproject *text*, by part; a malformed or unproduced one is refused."""
    parts = declared_in(text, 'parts')
    value = parts.get('hosted', {})
    resources = set(read_vocabulary(text).resources)
    produced = resources - set(parts.get('unproduced', []))
    if not isinstance(value, dict) or any(_malformed(name, entry, produced) for name, entry in value.items()):
        msg = (
            f'[tool.dev_lab.parts] hosted = {value!r}: each a produced resource of {sorted(resources)} '
            '= { secrets = ["UPPER_NAME", ...], setup = "<command reading NAME=value lines on stdin>" }'
        )
        raise UndeclaredPart(msg)
    return {name: Hosted(tuple(entry['secrets']), entry['setup']) for name, entry in value.items()}


def hosted_jobs(workflow: dict[str, Any], declared: Mapping[str, Hosted]) -> dict[str, Any]:
    """*workflow* with one ``part-<name>`` job per *declared* part, cut from its matrix ``part`` job. PURE.

    The job is the ``part`` job at one part: push-only, on linux, its setup step inserted before the produce step
    with the secrets in THAT step's environment only; ``absent-parts`` waits for it. A workflow without the
    ``part`` job, or nothing declared, is returned as is.
    """
    jobs = workflow.get('jobs', {})
    if not declared or 'part' not in jobs:
        return workflow
    template = json.dumps({key: value for key, value in jobs['part'].items() if key != 'strategy'})
    added = {}
    for name, part in sorted(declared.items()):
        one = json.loads(template.replace('${{ matrix.part }}', name))
        values = ' '.join(f'{secret} "${secret}"' for secret in part.secrets)
        setup = {
            'name': f'Set up tests/{name} from its secrets',
            'run': f"printf '%s=%s\\n' {values} | {{ {part.setup}; }}",
            'env': {secret: f'${{{{ secrets.{secret} }}}}' for secret in part.secrets},
        }
        steps = [*one['steps'][:-1], setup, one['steps'][-1]]
        added[f'part-{name}'] = {**one, 'if': _FULL_ONLY, 'runs-on': HOSTED_RUNNERS['linux'], 'steps': steps}
    out = dict(jobs)
    if 'absent-parts' in out:
        needs = out['absent-parts'].get('needs', [])
        needs = [needs] if isinstance(needs, str) else list(needs)
        out['absent-parts'] = {**out['absent-parts'], 'needs': [*needs, *added]}
    return {**workflow, 'jobs': {**out, **added}}


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


def _rows(part: str, event: str, declared: Mapping[str, Hosted]) -> list[dict[str, Any]]:
    """*part*'s matrix rows: one per OS of *event* when it runs hosted and names no OS, else its one runner.

    A *declared* hosted part has one linux row carrying its secrets' names, and none on a pull request.
    """
    if part in declared:
        row = {'part': part, 'runs-on': HOSTED_RUNNERS['linux'], 'secrets': list(declared[part].secrets)}
        return [] if event == 'pull_request' else [row]
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
    *hosted* keeps only the rows the generic job produces on a GitHub-hosted runner -- a row carrying secrets has
    its own job (:func:`hosted_jobs`) -- and :func:`absent` then names the rest.
    """
    pyproject = root / 'pyproject.toml'
    text = pyproject.read_text(encoding='utf-8') if pyproject.is_file() else ''
    vocabulary = read_vocabulary(text)
    ids = list(collect(''))
    carrying = {name: set(collect(name)) for name in vocabulary.resources}
    derived = {BASE, *need_sets(ids, carrying).values()}
    names = sorted(derived - unproduced_parts(derived, unproduced(text)))
    declared = hosted_parts(text)
    rows = [row for name in names for row in _rows(name, event, declared)]
    generic = [row for row in rows if isinstance(row['runs-on'], str) and 'secrets' not in row]
    return {'include': generic if hosted else rows}


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
