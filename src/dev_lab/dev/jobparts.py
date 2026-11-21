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
* an ``if: always()`` job runs ``absent <sha>`` over the SAME event's matrix: ABSENT IS A STATE, NOT A FAILURE
  (ruling D50-1, consumer #124: a full Windows run read red only because no job took the row). Every row the
  checkout derives that no job settled is posted ``pending`` saying :data:`ABSENT` and since when, so every reader
  sees its age; a row already absent keeps its first time.
  A FAILED JOB IS NOT ABSENT (2026-11-13, claude-code-config #6: a ``tests/base@windows`` job exited
  unreachable and the row read pending for hours). A producer that exits without a part has its job post the
  row ``error`` naming why (:func:`produce`); a row whose job CONCLUDED failed or cancelled with no record is
  ``error`` naming that job (:func:`run_jobs`), so a watch reads it red and a merge reads it failed, never waiting.
  It is never a settled part (:func:`dev_lab.dev.platformparts.parts_of`), so merge-ready and promote still
  refuse until every row stands PASS; a re-run job settles it.
* NO MATRIX IS A NAMED RED, NEVER A SILENT SKIP (2026-11-17, cc-market #29: collection failed, the matrix came out
  empty, every part job skipped and merge-ready waited on ``tests/base`` forever). A ``matrix`` that cannot be
  derived posts ``tests/base`` ``error`` saying :data:`NO_MATRIX` and why, and exits non-zero.

A COMMAND-PART REPO (:mod:`dev_lab.dev.commandpart`, a JS suite) has ONE part, ``base``: there is no pytest
collection to cut into need-sets, so its matrix never collects (:func:`command_part`).

ACTIONS ALONE (user ruling 2026-11-11): a GitHub repo's parts are produced by these jobs on GitHub-hosted runners and
nothing else -- no self-hosted runner, workstation or cluster. A part no hosted runner produces (a heavy test) is
KEPT, for a consumer's unified run to select, and is OFF THE GATE (:func:`off_gate`): it has no row, so nothing posts
it absent, and ``integrate promote`` on GitHub waives it.

A PART WITH ITS OWN SETUP (user decision 2026-10-30; a secretless setup 2026-11-15). A part whose resource no
hosted runner has can still run hosted when a SETUP command installs it, or repository secrets supply it: the ai-lab
TASKS whose key bundles it needs (:mod:`dev_lab.dev.taskkeys`, 2026-11-05). The repo declares that ONCE, in its
pyproject -- each entry ``setup``, ``tasks`` or both::

    [tool.dev_lab.parts]
    hosted = { live = { tasks = ["live"] }, linux = { setup = "sudo apt-get install -y xvfb" } }

Its job runs on the part's own hosted runner (:func:`hosted_runner`), the setup step before the produce step. A
part naming no task names no secret and runs on EVERY event, a pull request included: secrets are the only reason a
part's row is withheld from one.

A part naming tasks gets ONE row, on a full run only (as macos, D84), carrying its bundles' secret NAMES
(:func:`~dev_lab.dev.hostedparts.hosted_parts`, each :func:`~dev_lab.dev.taskkeys.secret_name`). The generic
matrix job never runs it: :func:`dev_lab.dev.hostedjobs.hosted_jobs` renders it its own job, in which ONE
setup step alone has the bundles in its environment and pipes each
to ai-lab's loader on stdin -- never argv, never echoed -- before the part is produced. The render names
a secret; it never holds a value, and it names no provider (ai-lab's routes say which a task uses).
No pull request has its row, and a PR's merge gate waits on no part but base's rows
(:func:`dev_lab.dev.forgemergewaits.hand_parts`); the full
run produces it, and ``integrate promote`` reads it there.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import lab_commons.launch as _door
from lab_commons.compute.probe import OS_NAMES
from lab_commons.hpc.needsets import BASE, need_sets, read_vocabulary
from lab_commons.hpc.shell import parse_collection_errors, parse_ids
from lab_commons.log import emit
from lab_commons.temp import TEMP_PREFIX

from dev_lab.dev.commandtests import declared_command
from dev_lab.dev.famtests.alwayson import assert_required_collected, resource_nodes
from dev_lab.dev.forgeclient import client_for
from dev_lab.dev.forgefailure import ForgeCallFailed
from dev_lab.dev.forgeoutbox import deliver_unit
from dev_lab.dev.forgestatus import status_list, status_post
from dev_lab.dev.hostedparts import Hosted, hosted_parts
from dev_lab.dev.partrows import ROW_SEPARATOR, needs_of_row, row_part
from dev_lab.dev.platformparts import part_context, producer_argv
from dev_lab.dev.producer import OUTCOME_VAR, Owner, outage_said, owned, producing, release_reason
from dev_lab.dev.unproduced import unproduced, unproduced_parts

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping, Sequence

    from dev_lab.dev.forgework import Client

__all__ = [
    'ABSENT',
    'FAILED_JOB',
    'HOSTED_RUNNERS',
    'NO_MATRIX',
    'Job',
    'absent',
    'command_part',
    'main',
    'matrix',
    'off_gate',
    'produce',
    'pytest_collector',
    'rows',
    'run_jobs',
    'runner_for',
    'systems_for',
]

#: The GitHub-hosted runner of each OS resource (the values of :data:`lab_commons.compute.probe.OS_NAMES`).
HOSTED_RUNNERS: Final = {'linux': 'ubuntu-latest', 'macos': 'macos-latest', 'windows': 'windows-latest'}

#: The OSes a pull request's OS-free parts run on (ruling D84); every other event runs them on every hosted OS.
PULL_REQUEST_SYSTEMS: Final = ('linux', 'windows')

#: What an expected part no job settled says (``pending``): never a part's own description, so never a part.
ABSENT: Final = 'absent: no job settled this part'

#: How often, and how many seconds apart, :func:`produce` re-reads the forge for the part its producer posted.
#: GitHub's status LIST lags its POST (dev-lab run 44917070995: a success posted at 15:12:15 read absent a second
#: later, and the job posted ``error`` over it); the bound keeps a producer that truly posted nothing a named red.
SETTLE_READS: Final = 6
SETTLE_WAIT_S: Final = 2.0

#: What ``tests/base`` says when the parts matrix could not be derived: no part job can run, so none will post.
NO_MATRIX: Final = 'no parts matrix (jobparts matrix failed; its job log says why)'


_STAMP: Final = '%Y-%m-%dT%H:%M:%SZ'

#: Pytest's documented exit status for a completed collection selecting no tests.
_NO_TESTS_COLLECTED: Final = 5

#: The states a part a job settled reads back as: a verdict, or the job's own ``error`` (:func:`produce`).
_SETTLED: Final = frozenset({'success', 'failure', 'error'})

#: The conclusions of a job that ended without producing (:func:`absent`): it failed, it is not absent.
FAILED_JOB: Final = frozenset({'failure', 'cancelled', 'timed_out', 'startup_failure'})


@dataclass(frozen=True)
class Job:
    """An Actions job that concluded: how, and its web page."""

    conclusion: str
    url: str


#: How many of pytest's own lines a collection refusal quotes: enough for every distinct cause, bounded for a log.
_CAUSE_LINES: Final = 20


def collection_cause(stdout: str, stderr: str) -> list[str]:
    """Pytest's own reason a collection failed: its ``E`` exception and ``ERROR`` summary lines, else stderr's tail."""
    lines = [line.rstrip() for line in (*stdout.splitlines(), *stderr.splitlines())]
    cause = list(dict.fromkeys(line for line in lines if line.startswith(('E   ', 'ERROR '))))
    return (cause or [line for line in stderr.splitlines() if line.strip()])[-_CAUSE_LINES:]


def pytest_collector(root: Path, arguments: Sequence[str] = ()) -> Callable[[str], list[str]]:
    """A collector over *root*'s checkout: given a marker expression (``''`` for none), the ids pytest collects."""

    def collect(expression: str) -> list[str]:
        argv = [sys.executable, '-m', 'pytest', '--collect-only', '-q', '-p', 'no:cacheprovider', '--color=no']
        command = [*argv, *(['-m', expression] if expression else []), *arguments]
        done = _door.run(command, cwd=root, capture_output=True, text=True, encoding='utf-8', check=False)
        ids = parse_ids(done.stdout)
        errors = parse_collection_errors(done.stdout + '\n' + done.stderr)
        empty = done.returncode == _NO_TESTS_COLLECTED and not ids and not errors
        if errors or (done.returncode != 0 and not empty):
            cause = ''.join(f'\n  {line}' for line in collection_cause(done.stdout, done.stderr))
            msg = (
                f'pytest collection failed with exit {done.returncode} for marker {expression!r}; '
                f'{len(ids)} partial node(s) cannot define a complete part manifest. '
                f'Rerun {shlex.join(command)} in the checkout and repair collection before producing parts. '
                f'pytest said:{cause}'
            )
            raise ValueError(msg)
        assert_required_collected(root, ids)
        return ids

    return collect


def runner_for(part: str) -> str | None:
    """*part*'s GitHub-hosted ``runs-on`` when it needs at most one OS; ``None``: no Actions job produces it.

    A need-set naming a resource no hosted runner has (``femm``, a heavy part) is OFF THE GITHUB GATE (user ruling
    2026-11-11): GitHub wires no self-hosted runner, workstation or cluster, so it has no row and nothing waits on
    it -- the test stays, for a consumer's unified run to select (:func:`off_gate`).
    """
    needs = needs_of_row(part)
    systems = needs & set(OS_NAMES.values())
    if needs == systems and len(systems) <= 1:
        return HOSTED_RUNNERS[next(iter(systems), 'linux')]
    return None


def hosted_runner(part: str) -> str:
    """The ``runs-on`` of a declared hosted *part*'s own job: its :func:`runner_for`, else linux's."""
    return runner_for(part) or HOSTED_RUNNERS['linux']


def off_gate(parts: Iterable[str], declared: Mapping[str, Hosted]) -> frozenset[str]:
    """The *parts* no gating Actions job produces: a ``manual`` hosted one, or neither hosted nor hosted-runnable."""
    return frozenset(
        part for part in parts if (declared[part].manual if part in declared else runner_for(row_part(part)) is None)
    )


def systems_for(event: str) -> tuple[str, ...]:
    """The OSes a part naming none runs on for GitHub *event*: :data:`PULL_REQUEST_SYSTEMS`, else every one."""
    return PULL_REQUEST_SYSTEMS if event == 'pull_request' else tuple(sorted(HOSTED_RUNNERS))


def rows(part: str, event: str, declared: Mapping[str, Hosted]) -> list[dict[str, Any]]:
    """*part*'s matrix rows: one per OS of *event* when it runs hosted and names no OS, else its one runner.

    A *declared* hosted part has one :func:`hosted_runner` row carrying its secrets' names (its own job's mark),
    and none on a pull request when it names any; a ``manual`` one has a row on a manual dispatch alone.
    """
    if part in declared and declared[part].manual and event != 'workflow_dispatch':
        return []
    if part in declared:
        row = {'part': part, 'runs-on': hosted_runner(part), 'secrets': list(declared[part].secrets)}
        return [] if event == 'pull_request' and row['secrets'] else [row]
    home = runner_for(part)
    if home is None:
        return []
    if needs_of_row(part) & set(OS_NAMES.values()):
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
    Each part has its :func:`runner_for` row, plus one per further OS of *event* when it names none (:func:`rows`).
    *hosted* keeps only the rows the generic job produces on a GitHub-hosted runner -- a declared hosted row
    (it carries ``secrets``, maybe none) has its own job (:func:`dev_lab.dev.hostedjobs.hosted_jobs`) -- and
    :func:`absent` then names the rest.
    """
    pyproject = root / 'pyproject.toml'
    text = pyproject.read_text(encoding='utf-8') if pyproject.is_file() else ''
    if command_part(text):
        derived = {BASE}
    else:
        vocabulary = read_vocabulary(text)
        ids = list(collect(''))
        carrying = {name: set(resource_nodes(root, collect(name))) for name in vocabulary.resources}
        derived = {BASE, *need_sets(ids, carrying).values()}
    names = sorted(derived - unproduced_parts(derived, unproduced(text)))
    declared = hosted_parts(text)
    every = [row for name in names for row in rows(name, event, declared)]
    generic = [row for row in every if 'secrets' not in row]
    return {'include': generic if hosted else every}


def command_part(text: str) -> bool:
    """Whether pyproject *text* declares :mod:`dev_lab.dev.commandpart` its producer: one part, never collected."""
    return declared_command(text) is not None


def no_matrix(client: Client, sha: str, cause: Exception, env: Mapping[str, str]) -> str:
    """Post ``tests/base`` ``error`` at *sha* saying :data:`NO_MATRIX` and *cause*; the line said.

    The commit's own declaration or collection failed (:attr:`Owner.CODE`), so merge-ready reads a named red.
    """
    description = owned(Owner.CODE, f'{NO_MATRIX}: {cause}')
    status_post(
        client, sha, context=part_context(BASE), state='error', description=description, target_url=_run_url(env)
    )
    return f'{part_context(BASE)}: error {NO_MATRIX}: {cause}'


def run_jobs(client: Client, run: str) -> dict[str, Job]:
    """The CONCLUDED jobs of Actions *run*, by name (a part job's is its context); ``{}`` when none can be read.

    Unreadable (no run, a forge without the endpoint, no ``actions: read``) is no job concluded: rows read absent.
    """
    if not run:
        return {}
    try:
        listed: Any = client.call('GET', f'{client.repo}/actions/runs/{run}/jobs?per_page=100')
    except ForgeCallFailed:
        return {}
    jobs = listed.get('jobs', []) if isinstance(listed, dict) else []
    return {
        str(job['name']): Job(str(job['conclusion']), str(job.get('html_url') or ''))
        for job in jobs
        if isinstance(job, dict) and job.get('name') and job.get('conclusion')
    }


def absent(
    client: Client,
    sha: str,
    expected: Mapping[str, Any],
    *,
    jobs: Mapping[str, Job] | None = None,
    now: datetime | None = None,
) -> list[str]:
    """Post each part of *expected* (a :func:`matrix`) no job settled ``pending`` saying :data:`ABSENT`; the lines.

    Settled is a latest ``success``, ``failure`` or ``error``: a ``pending`` claim left behind is a job that died.
    A row whose job in *jobs* (:func:`run_jobs`) concluded :data:`FAILED_JOB` is posted ``error`` naming the job:
    it FAILED, it is not absent. Any other row already absent is left as it is, keeping when it went absent.
    """
    stamp = (now or datetime.now(UTC)).strftime(_STAMP)
    latest = {status.context: status for status in status_list(client, sha)}
    lines = []
    for context in sorted(part_context(one['part']) for one in expected['include']):
        status = latest.get(context)
        if status is not None and status.state in _SETTLED:
            continue
        job = (jobs or {}).get(context)
        if job is not None and job.conclusion in FAILED_JOB:
            description = owned(Owner.ENVIRONMENT, f'failed: its job concluded {job.conclusion} with no record')
            status_post(client, sha, context=context, state='error', description=description, target_url=job.url)
            lines.append(f'{context}: {description} {job.url}'.rstrip())
            continue
        if status is not None and status.description.startswith(ABSENT):
            lines.append(f'{context}: {status.description}')
            continue
        description = f'{ABSENT} since {stamp}'
        status_post(client, sha, context=context, state='pending', description=description)
        lines.append(f'{context}: {description}')
    return lines


def produce(root: Path, part: str, client: Client, *, env: Mapping[str, str] | None = None) -> int:
    """Run the one declared producer of *part* at *root*'s HEAD with this interpreter, cwd *root*; its exit code.

    The job IS the producer of ``tests/<part>`` at that sha, so the child carries :func:`producing` -- the same
    marker ``forge serve`` hands its producer -- and the full suite it runs is admitted for that part only.
    The part is read back with a bound (:func:`_settled`): the forge's list lags its post.
    A producer that ends with no settled part (unreachable, inconclusive, refused, crashed) leaves no row
    pending: the job posts it ``error`` on *client* -- the reason the producer declared (:func:`outage_said`),
    else its exit code's (:func:`release_reason`) -- naming this run, and exits non-zero.
    """
    given = os.environ if env is None else env
    sha = _head(root)
    argv = producer_argv(root, part, sha=sha)
    context = part_context(part)
    with tempfile.TemporaryDirectory(prefix=TEMP_PREFIX) as scratch:
        outcome = Path(scratch) / 'outcome'
        child = {**given, **producing(context, sha), OUTCOME_VAR: str(outcome)}
        code = _door.run([sys.executable, *argv], cwd=root, env=child, check=False).returncode
        said = outcome.read_text(encoding='utf-8') if outcome.is_file() else ''
    for line in deliver_unit(root, client, sha, context):  # its own held result first (forgeoutbox.deliver_unit)
        emit(f'[jobparts] {line}', err=True)
    if _settled(client, sha, context):
        return code
    description = outage_said(said) or release_reason(code, outage=None)
    status_post(client, sha, context=context, state='error', description=description, target_url=_run_url(given))
    emit(f'[jobparts] {context}: error {description}', err=True)
    return code or 1


def _settled(client: Client, sha: str, context: str) -> bool:
    """Whether *context* reads settled at *sha*, re-read :data:`SETTLE_READS` times :data:`SETTLE_WAIT_S` apart.

    The list endpoint lags the post: one read right after the producer exits can miss the part it just posted.
    """
    for attempt in range(SETTLE_READS):
        if attempt:
            time.sleep(SETTLE_WAIT_S)
        latest = {status.context: status for status in status_list(client, sha)}
        if context in latest and latest[context].state in _SETTLED:
            return True
    return False


def _head(root: Path) -> str:
    """*root*'s HEAD sha."""
    head = _door.run(
        ['git', 'rev-parse', 'HEAD'], cwd=root, capture_output=True, text=True, encoding='utf-8', check=True
    )
    return head.stdout.strip()


def _run_url(env: Mapping[str, str]) -> str:
    """The web URL of the Actions run *env* names, ``''`` outside one."""
    parts = (env.get('GITHUB_SERVER_URL', ''), env.get('GITHUB_REPOSITORY', ''), env.get('GITHUB_RUN_ID', ''))
    return '{}/{}/actions/runs/{}'.format(*parts) if all(parts) else ''


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
    verbs.add_parser('absent', help='post pending (absent) on every derived part no job settled').add_argument('sha')
    for sub in (listing, verbs.choices['absent']):
        sub.add_argument(
            '--event', default='push', help='the GitHub event whose OSes the rows span (default push: every OS)'
        )
    for sub in verbs.choices.values():
        sub.add_argument('--root', type=Path, default=Path.cwd(), help='the checkout the parts are derived from')
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    collect = pytest_collector(args.root)
    if args.verb == 'matrix':
        try:
            found = matrix(args.root, collect=collect, event=args.event, hosted=args.runners == 'hosted')
        except ValueError as cause:  # UndeclaredPart among them
            emit(f'[jobparts] {no_matrix(client_for(args.root), _head(args.root), cause, os.environ)}', err=True)
            return 1
        emit(json.dumps(found))
        return 0
    client = client_for(args.root)
    if args.verb == 'produce':
        return produce(args.root, args.part, client)
    jobs = run_jobs(client, os.environ.get('GITHUB_RUN_ID', ''))
    for line in absent(client, args.sha, matrix(args.root, collect=collect, event=args.event), jobs=jobs):
        emit(f'[jobparts] {line}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
