"""PLATFORM PARTS -- one commit's result COMPOSED of a part per platform it ran on, held on the FORGE.

THE SPLIT IS DECLARED ONCE, per marker, in ``[tool.lab_commons.platforms]`` (:mod:`lab_commons.hpc.platforms`).
A part is named for the platform it RAN ON -- ``linux``, ``windows``, ``macos`` -- never for where it
was launched from. EVERY COLLECTED ID IS ASSIGNED TO EXACTLY ONE PART by one rule,
:func:`lab_commons.hpc.platforms.assign`: the first platform in ``PLATFORMS`` order that can run it
(linux, else windows, else macos). A part's selection is therefore a pure function of the commit's
table and its collected ids; no part reads another part, so every part can start at any time and in
parallel. Each part says what it HANDS to other parts.

A PART IS A COMMIT STATUS (forge plan, user ruling 2026-10-09): context :func:`part_context`
(``tests/<platform>``), state ``success`` (PASS) or ``failure`` (FAIL), and a description every
workstation can read without the record -- :meth:`Part.description`::

    scope=full ran=1234 hands=windows:12,macos:3 nowhere=0

``hands`` is, per OTHER platform, how many collected ids this part assigned to it; ``nowhere`` how
many ids no declared platform can run. The full per-id outcome stays in the run record, attached on
the forge and linked as the status's ``target_url`` (:mod:`lab_commons.dev.forgerecords`). A ``pending``
status in the same context is a CLAIM on the part (:mod:`lab_commons.dev.forgetick`), not a part.

* A part comes from a RUN record (``run-<sha>-<platform>-<req>.json.gz``): ``python -m lab_commons.hpc
  run gather`` writes it, and ``python -m lab_commons.dev.platformparts post <record>`` queues its
  status and the record (:mod:`lab_commons.dev.forgeoutbox`) -- posted once the commit is on origin.
  :func:`part_of` derives the part STRICTLY: PASS only when every covered outcome is passed / skipped
  / xfailed; a failed or error id is FAIL. A record with ANY lost or missing id is INCONCLUSIVE and is
  REFUSED, never posted: measured 2026-10-09 a record of 50349 lost ids (a build that never produced a
  venv) was written as a linux FAIL. Nothing covered is refused, and so is a record handing off an id
  that is assigned to its own platform.
* Any other producer (a consumer's runner with ``--platform <name>``) calls :func:`select` with a
  collector over its own checkout, runs the ids assigned to it and writes a record of the same shape.

COMPOSITION (:func:`compose`). The latest part per platform for the commit. Every platform some part
hands ids to must have a part; any FAIL part makes it FAIL; a part naming ``nowhere`` ids is refused
by name, as is a missing part.

HOW A PART IS PRODUCED IS DECLARED ONCE, in the consuming repo's pyproject, and :func:`part_argv`
turns it into ONE fully filled argv run with the checkout's own venv python, cwd = the checkout::

    [tool.lab_commons.hpc]                 # the cluster (linux) part
    install = "uv sync --extra dev"          # must install the project: its venv reports the env key
    needs = ["cargo", "cc"]                # optional: login-node commands beyond git and uv
    collect = "tests"                      # optional: pytest arguments selecting the tests

    [tool.lab_commons.parts]
    output = "output/logs"                 # base of the dated run-record directory (datedlog)

    [tool.lab_commons.parts.produce.windows]   # a local part: argv after the venv python, per scope
    full = ["-m", "lab_commons.dev.verify"]

The repo url is origin's, spelled https. A missing declaration is refused naming the key to add --
never a command with a hole in it. The linux argv is ``platformparts cluster``: submit, gather
``--wait``, post, in one process.
"""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from lab_commons.dev.datedlog import dated_log
from lab_commons.dev.forge import forge_from_remote
from lab_commons.dev.forgeoutbox import Post, PostFailed, enqueue, flush
from lab_commons.dev.producer import ProducerExit
from lab_commons.dev.venvpath import checkout_interpreter
from lab_commons.hpc.__main__ import main as hpc_main
from lab_commons.hpc.cluster import Unreachable
from lab_commons.hpc.platforms import LINUX, PLATFORMS, assign, cannot_run, host_platform, runnable, table_at
from lab_commons.hpc.records import read_record
from lab_commons.hpc.retired import refusal
from lab_commons.hpc.shell import FULL, INCREMENTAL
from lab_commons.log import emit

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from lab_commons.dev.forgestatus import Status

__all__ = [
    'CONTEXT_PREFIX',
    'LINUX',
    'PASSING',
    'Composition',
    'Part',
    'PartRefusal',
    'Standing',
    'UndeclaredPart',
    'cluster',
    'compose',
    'main',
    'part_argv',
    'part_context',
    'part_of',
    'parts_of',
    'select',
    'split',
    'standing',
    'this_platform',
]

#: Every part's status context starts with this; the rest is the platform.
CONTEXT_PREFIX: Final = 'tests/'

#: Covered outcomes that do not fail a part: ran and passed, or declined by the test's own design.
PASSING: Final = frozenset({'passed', 'skipped', 'xfailed'})

#: How many ids a refusal names before eliding; the count is always given.
_NAMED: Final = 5

#: Outcomes of ids that never reported: they make a part INCONCLUSIVE, never FAIL.
_UNRUN: Final = frozenset({'lost', 'missing'})

#: The record's word for an id it handed to another part.
_NOT_COVERED: Final = 'not-covered'

_STATE: Final = {'PASS': 'success', 'FAIL': 'failure'}
_RESULT: Final = {state: result for result, state in _STATE.items()}

_DESCRIPTION: Final = re.compile(
    r'^scope=(?P<scope>\w+) ran=(?P<ran>\d+) hands=(?P<hands>-|[a-z]+:\d+(?:,[a-z]+:\d+)*) nowhere=(?P<nowhere>\d+)$'
)

#: The remedy a missing part names: the tick that claims it runs :func:`part_argv`.
_PRODUCE: Final = 'a `lab_commons.dev.forge tick` serving {platform} claims and produces it'

#: Where the run records a cluster part gathers land, under the declared dated base.
_RECORD_KIND: Final = 'parts'


class PartRefusal(ValueError):
    """A part that cannot be posted -- posting it would claim a run nobody made."""


class UndeclaredPart(ValueError):
    """The repo does not declare how to produce a part; the message names the pyproject key to add."""


def part_context(platform: str) -> str:
    """``tests/<platform>`` -- the one status context a platform's part (and a claim on it) uses."""
    return f'{CONTEXT_PREFIX}{platform}'


def _text(table: Mapping[str, Any], name: str, key: str, example: str, *, required: bool) -> str:
    value = table.get(key, None if required else '')
    if not isinstance(value, str) or (required and not value):
        msg = f'pyproject.toml must declare [{name}] {key} as a non-empty string, e.g. {key} = {example}'
        raise UndeclaredPart(msg)
    return value


def _strings(value: object, name: str, key: str, example: str, *, required: bool) -> list[str]:
    if value is None and not required:
        return []
    if not isinstance(value, list) or not value or not all(isinstance(item, str) and item for item in value):
        msg = f'pyproject.toml must declare [{name}] {key} as a non-empty array of strings, e.g. {key} = {example}'
        raise UndeclaredPart(msg)
    return list(value)


def record_directory(root: Path, head: str) -> Path:
    """The dated directory *head*'s run records go to, under ``[tool.lab_commons.parts] output``.

    Raises:
        UndeclaredPart: the output is not declared; the message names the key.

    """
    declared = tomllib.loads((root / 'pyproject.toml').read_text(encoding='utf-8')).get('tool', {})
    parts = declared.get('lab_commons', {}).get('parts', {})
    output = _text(parts, 'tool.lab_commons.parts', 'output', '"output/logs"', required=True)
    return dated_log(root, head, base=output, kind=_RECORD_KIND)


def part_argv(root: Path, platform: str, head: str, *, scope: str, os_name: str) -> list[str]:
    """The ONE fully filled argv producing *platform*'s part of commit *head* at *scope* (module docstring).

    Raises:
        UndeclaredPart: a declaration it needs is absent or malformed; the message names the key.
        FileNotFoundError: the checkout has no own venv.

    """
    if platform not in PLATFORMS or scope not in {FULL, INCREMENTAL}:
        msg = f'a part is one of {PLATFORMS} at scope {FULL} or {INCREMENTAL}, not {platform!r} at {scope!r}'
        raise ValueError(msg)
    declared = tomllib.loads((root / 'pyproject.toml').read_text(encoding='utf-8')).get('tool', {})
    declared = declared.get('lab_commons', {})
    if platform != LINUX:
        table = f'tool.lab_commons.parts.produce.{platform}'
        produce = declared.get('parts', {}).get('produce', {}).get(platform, {}).get(scope)
        argv = _strings(produce, table, scope, '["-m", "lab_commons.dev.verify"]', required=True)
        return [str(checkout_interpreter(root, os_name=os_name)), *argv]
    if scope != FULL:
        msg = f'a cluster part is produced at scope {FULL}; {INCREMENTAL} needs the re-run ids (run submit --only)'
        raise ValueError(msg)
    hpc, name = declared.get('hpc', {}), 'tool.lab_commons.hpc'
    _text(hpc, name, 'install', '"uv sync --extra dev"', required=True)  # read at --sha by hpc run submit
    collect = _text(hpc, name, 'collect', '"tests"', required=False)
    directory = record_directory(root, head)
    forge = forge_from_remote(root)
    python = str(checkout_interpreter(root, os_name=os_name))
    return [
        python, '-m', 'lab_commons.dev.platformparts', 'cluster', '--sha', head,
        '--repo-url', f'https://{forge.host}/{forge.owner}/{forge.repo}.git',
        '--collect', collect, '-o', str(directory),
    ]  # fmt: skip


def _elided(ids: Sequence[str]) -> str:
    return ', '.join(ids[:_NAMED]) + (', ...' if len(ids) > _NAMED else '')


@dataclass(frozen=True)
class Part:
    """One platform's result for a commit, as the forge holds it."""

    platform: str
    scope: str
    result: str
    ran: int
    hands: dict[str, int] = field(default_factory=dict)
    nowhere: int = 0

    @property
    def state(self) -> str:
        """``success`` for PASS, ``failure`` for FAIL."""
        return _STATE[self.result]

    def description(self) -> str:
        """The status description: ``scope= ran= hands= nowhere=`` (module docstring)."""
        hands = ','.join(f'{name}:{count}' for name, count in sorted(self.hands.items())) or '-'
        return f'scope={self.scope} ran={self.ran} hands={hands} nowhere={self.nowhere}'


def part_of(record: Mapping[str, Any]) -> Part:
    """The part a run record proves, by the strict rule in the module docstring.

    The platform and scope are the record's own -- read, never re-declared.
    """
    platform, scope, sha = str(record['platform']), str(record['scope']), str(record['sha'])
    outcomes: dict[str, str] = dict(record['outcomes'])
    covered = {node: outcome for node, outcome in outcomes.items() if outcome != _NOT_COVERED}
    if not covered:
        msg = f'the {platform} record for {sha} covers no test -- an empty part is not a pass'
        raise PartRefusal(msg)
    unrun = sorted(node for node, outcome in covered.items() if outcome in _UNRUN)
    if unrun:
        msg = (
            f'the {platform} record for {sha} is INCONCLUSIVE: {len(unrun)} of {len(covered)} covered test(s) '
            f'never reported ({_elided(unrun)}) -- gather again or re-submit; it is not posted, so no admission '
            'can cite it'
        )
        raise PartRefusal(msg)
    handed = {node: list(record['handed'].get(node, [])) for node, out in outcomes.items() if out == _NOT_COVERED}
    disowned = sorted(node for node, can in handed.items() if assign(can) == platform)
    if disowned:
        msg = f'the {platform} record for {sha} hands off {len(disowned)} test(s) it is assigned: {_elided(disowned)}'
        raise PartRefusal(msg)
    hands: dict[str, int] = {}
    for can in handed.values():
        owner = assign(can)
        if owner is not None:
            hands[owner] = hands.get(owner, 0) + 1
    failing = any(outcome not in PASSING for outcome in covered.values())
    return Part(
        platform=platform,
        scope=scope,
        result='FAIL' if failing else 'PASS',
        ran=len(covered),
        hands=hands,
        nowhere=sum(1 for can in handed.values() if assign(can) is None),
    )


def parts_of(statuses: Sequence[Status]) -> tuple[dict[str, Part], tuple[str, ...]]:
    """``(parts by platform, problems)`` from a commit's LATEST status per context.

    A ``tests/<platform>`` status that is not a settled part -- a claim still ``pending``, an
    ``error``, or a description this module did not write -- is a problem naming itself, never a part.
    """
    parts: dict[str, Part] = {}
    problems: list[str] = []
    for status in statuses:
        if not status.context.startswith(CONTEXT_PREFIX):
            continue
        platform = status.context.removeprefix(CONTEXT_PREFIX)
        found = _DESCRIPTION.match(status.description)
        if status.state not in _RESULT or found is None or platform not in PLATFORMS:
            problems.append(f'{status.context} is {status.state} ({status.description!r}) -- not a settled part')
            continue
        hands = {} if found['hands'] == '-' else dict(item.split(':') for item in found['hands'].split(','))
        parts[platform] = Part(
            platform=platform,
            scope=found['scope'],
            result=_RESULT[status.state],
            ran=int(found['ran']),
            hands={name: int(count) for name, count in hands.items()},
            nowhere=int(found['nowhere']),
        )
    return parts, tuple(problems)


def split(can: Mapping[str, Sequence[str]], platform: str) -> tuple[list[str], dict[str, list[str]]]:
    """``(ids assigned to *platform*'s part, every other id with the platforms that can run it)``."""
    mine = [node for node, platforms in can.items() if assign(platforms) == platform]
    handed = {node: list(platforms) for node, platforms in can.items() if assign(platforms) != platform}
    return mine, handed


def select(
    root: Path, sha: str, platform: str, *, collect: Callable[[str], Sequence[str]]
) -> tuple[list[str], dict[str, list[str]]]:
    """:func:`split` of what *collect* yields, by the table commit *sha* of *root* declares.

    *collect* takes a pytest marker expression (``''`` for none) and returns the node ids it collects
    in the consumer's checkout: once for everything, once per platform that cannot run some marker.
    """
    if platform not in PLATFORMS:
        msg = f'unknown platform {platform!r}; a part is named for the platform it runs on, one of {PLATFORMS}'
        raise ValueError(msg)
    table = table_at(root, sha)
    ids = list(collect(''))
    cannot = {name: set(collect(expr)) for name in PLATFORMS if (expr := cannot_run(table, name))}
    return split(runnable(ids, cannot), platform)


@dataclass(frozen=True)
class Composition:
    """The composed answer: the parts it rests on, PASS/FAIL, and why it cannot be cited (empty when it can)."""

    parts: tuple[Part, ...]
    result: str
    problems: tuple[str, ...]


def compose(parts: Mapping[str, Part], *, head: str) -> Composition:
    """Compose *parts* by the rule in the module docstring."""
    ordered = tuple(parts[name] for name in sorted(parts))
    result = 'FAIL' if any(part.result != 'PASS' for part in ordered) else 'PASS'
    problems: list[str] = []
    if not ordered:
        problems.append(f'no part is posted for {head}; {_PRODUCE.format(platform=LINUX)}')
    nowhere = sum(part.nowhere for part in ordered)
    if nowhere:
        named = ', '.join(f'{part.platform}={part.nowhere}' for part in ordered if part.nowhere)
        problems.append(f'no declared platform can run some collected test(s) ({named})')
    for platform in PLATFORMS:
        handing = {part.platform: part.hands[platform] for part in ordered if part.hands.get(platform)}
        if handing and platform not in parts:
            by = ', '.join(f'{name} hands {count}' for name, count in sorted(handing.items()))
            problems.append(f'missing the {platform} part ({by}); {_PRODUCE.format(platform=platform)}')
    return Composition(parts=ordered, result=result, problems=tuple(problems))


@dataclass(frozen=True)
class Standing:
    """A commit's result as its parts on the forge say it: ``PASS``, ``FAIL``, or ``''`` while unsettled.

    THE ONE READING of a platform result, shared by push admission and the integrator's queue: a FAIL
    part is ``FAIL`` whatever else is missing; otherwise any problem (a part missing, unsettled, of the
    wrong scope, or ids runnable nowhere) leaves it ``''``; else ``PASS``.
    """

    result: str
    parts: tuple[Part, ...]
    problems: tuple[str, ...]

    def cited(self) -> str:
        """The parts it rests on, one ``platform=RESULT/scope ran=N`` each."""
        return ', '.join(f'{part.platform}={part.result}/{part.scope} ran={part.ran}' for part in self.parts)


def standing(statuses: Sequence[Status], *, head: str, scope: str | None = None) -> Standing:
    """The :class:`Standing` of commit *head* from its latest statuses; *scope* requires every part at it."""
    parts, unsettled = parts_of(statuses)
    composed = compose(parts, head=head)
    problems = [*unsettled, *composed.problems]
    if scope is not None:
        problems += [
            f'{part.platform} is {part.result} of scope {part.scope}; only a PASS of scope {scope} counts here'
            for part in composed.parts
            if part.result != 'PASS' or part.scope != scope
        ]
    failed = any(part.result == 'FAIL' for part in composed.parts)
    return Standing(result=_settled(failed=failed, problems=problems), parts=composed.parts, problems=tuple(problems))


def _settled(*, failed: bool, problems: Sequence[str]) -> str:
    if failed:
        return 'FAIL'
    return '' if problems else 'PASS'


def post(root: Path, path: Path) -> str:
    """Queue the part *path*'s record proves, with the record attached, and flush; returns the lines."""
    record = read_record(path)
    part = part_of(record)
    enqueue(root, Post(str(record['sha']), part_context(part.platform), part.state, part.description()), record=path)
    lines = flush(root)
    return '\n'.join([f'[platformparts] {part.platform} part {part.result}: {part.description()}', *lines])


def cluster(
    root: Path,
    *,
    sha: str,
    hpc_args: Sequence[str],
    output: Path,
    hpc: Callable[[list[str]], int] = hpc_main,
) -> tuple[ProducerExit, str]:
    """Produce the linux part of *sha*: ``hpc run submit`` (full), ``run gather --wait``, then :func:`post`.

    *hpc_args* are the submit flags :func:`part_argv` filled. The newest record gathered into *output*
    is posted -- a red run is a FAIL part and still posted; no record at all is refused. Returns the
    posted part's exit (PASS or FAIL) and the lines; an outage raises :class:`Unreachable`.
    """
    submitted = hpc(['run', 'submit', '--sha', sha, '--scope', FULL, '--repo', str(root), *hpc_args])
    if submitted != 0:
        msg = f'run submit for {sha} exited {submitted}; nothing was submitted, so there is nothing to post'
        raise PartRefusal(msg)
    hpc(['run', 'gather', '--sha', sha, '-o', str(output), '--wait'])
    records = sorted(output.glob(f'run-{sha}-{LINUX}-*.json.gz'), key=lambda path: path.stat().st_mtime)
    if not records:
        msg = f'run gather wrote no linux record for {sha} into {output}; its output above says why'
        raise PartRefusal(msg)
    result = part_of(read_record(records[-1])).result
    return (ProducerExit.PASS if result == 'PASS' else ProducerExit.FAIL), post(root, records[-1])


def main(argv: Sequence[str] | None = None) -> int:
    """``post <run-record>`` | ``cluster --sha ...``: post a record's part, or produce the linux part."""
    parser = argparse.ArgumentParser(
        prog='python -m lab_commons.dev.platformparts', description=__doc__.splitlines()[0]
    )
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv and (refused := refusal('platformparts', argv[0])):
        parser.error(refused)
    verbs = parser.add_subparsers(dest='verb', required=True)
    posting = verbs.add_parser('post', help='post a run record as its part')
    posting.add_argument('record', type=Path, help='the run record `python -m lab_commons.hpc run gather -o` wrote')
    producing = verbs.add_parser('cluster', help='submit, gather and post the linux part (argv from forge tick)')
    producing.add_argument('--sha', required=True)
    producing.add_argument('-o', '--output', type=Path, required=True, help='the dated run-record directory')
    for flag in ('--repo-url', '--collect'):
        producing.add_argument(flag, required=True, help=f'passed to hpc run submit {flag}')
    for each in (posting, producing):
        each.add_argument('--root', type=Path, default=Path.cwd(), help='the checkout whose origin receives the part')
    args = parser.parse_args(argv)
    try:
        if args.verb == 'post':
            emit(post(args.root, args.record))
            return 0
        flags = ['--repo-url', args.repo_url, '--collect', args.collect]
        code, lines = cluster(args.root, sha=args.sha, hpc_args=flags, output=args.output)
    except (Unreachable, PostFailed) as why:  # infrastructure, not code: the claim is released retryable
        emit(f'[platformparts] unreachable: {why}', err=True)
        return ProducerExit.UNREACHABLE
    except PartRefusal as why:
        emit(f'[platformparts] refused: {why}', err=True)
        return ProducerExit.INCONCLUSIVE if args.verb == 'cluster' else 1
    emit(lines)
    return code


def this_platform() -> str:
    """The platform THIS box runs a part on."""
    return host_platform(sys.platform)


if __name__ == '__main__':
    raise SystemExit(main())
