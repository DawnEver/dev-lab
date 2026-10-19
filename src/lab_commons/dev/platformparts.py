"""PARTS -- one commit's result COMPOSED of a part per NEED-SET, held on the FORGE.

A part is named for the resources its tests need (:mod:`lab_commons.hpc.needsets`): ``tests/base`` for the
tests needing no declared resource, ``tests/jmag``, ``tests/femm+windows``... PARTS ARE DERIVED, never
declared: every collected id belongs to exactly ONE part, its need-set, read off the markers it carries
against the commit's ``[tool.lab_commons.tests] resources``. A part's selection is therefore a pure
function of the commit's declaration and its collected ids; no part reads another part, so every part can
start at any time and in parallel. Each part says what it HANDS to other parts.

A PART IS A COMMIT STATUS (forge plan, user ruling 2026-10-09): context :func:`part_context`
(``tests/<part>``), state ``success`` (PASS) or ``failure`` (FAIL), and a description every
workstation can read without the record -- :meth:`Part.description`::

    scope=full ran=1234 hands=femm+windows:12,jmag:3 kept=0123456789ab:900

``kept`` (absent when none) counts, per sha12 they RAN at, the outcomes this part CARRIED from an earlier
run of the same part because no changed path reaches them (:mod:`lab_commons.dev.forgecarry`); they are
judged like any outcome and never counted in ``ran``.

``hands`` is, per OTHER part, how many collected ids belong to it. That is how a commit's parts are
DISCOVERED (:func:`derived`): ``base`` is always wanted, and so is every part a posted part hands to. A
part CARRIED to a reach-equivalent descendant (:mod:`lab_commons.dev.forgecarry`) ends ``carried from
<sha12>: every outcome carried by footprint`` and is a part like any other: the sha it was judged at is named,
never hidden. The full per-id outcome stays in the run record, attached on the forge and linked as the
status's ``target_url`` (:mod:`lab_commons.dev.forgerecords`). A ``pending`` status in the same context
is a CLAIM on the part (:mod:`lab_commons.dev.forgetick`), not a part.

* A part comes from a RUN record (``run-<sha>-<part>-<req>.json.gz``; its ``platform`` key holds the
  part's name): ``python -m lab_commons.hpc run gather`` writes it, and ``python -m
  lab_commons.dev.platformparts post <record>`` queues its status and the record
  (:mod:`lab_commons.dev.forgeoutbox`) -- posted once the commit is on origin. :func:`part_of` derives
  the part STRICTLY, as :func:`lab_commons.hpc.testcells.conclude` over the record's test cells: PASS only
  when every covered cell is DECIDED and meets its expectation, FAIL on any decided miss. An INCONCLUSIVE
  record -- a RETRYABLE cell (never reported, lost, killed) and no miss, or a flaky id -- is REFUSED, never
  posted: measured 2026-10-09 a record of 50349 ids lost to a build that never produced a venv was written
  as a FAIL. Nothing covered is refused, and so is a record handing off an id of its own part.
* Any other producer (a consumer's door, run as the declared ``produce``) calls :func:`select` with a
  collector over its own checkout, runs the ids of its part and writes a record of the same shape.

COMPOSITION (:func:`compose`). The latest part per need-set for the commit. ``base`` must have a part,
and so must every part some part hands ids to; any FAIL part makes it FAIL. "Every derived part green"
is therefore what a PASS means, and what ``integrate promote`` requires.

HOW A PART IS PRODUCED IS DECLARED ONCE, in the consuming repo's pyproject. A LOCAL part is the ONE
declared argv (:func:`producer_argv`, read at the claimed commit, ``{part}`` filled) run by the own venv
interpreter of a tree the producer builds at that commit, cwd = that tree (:mod:`lab_commons.dev.shatree`);
a CLUSTER part is a run advanced one step per ``forge serve`` tick on the cluster's login node
(:mod:`lab_commons.dev.forgerun`), from :func:`cluster_part`::

    [tool.lab_commons.hpc]                 # a part produced on the cluster
    install = "uv sync --extra dev"          # must install the project: its venv reports the env key
    needs = ["cargo", "cc"]                # optional: login-node commands beyond git and uv
    collect = "tests"                      # optional: pytest arguments selecting the tests

    [tool.lab_commons.parts]
    output = "output/logs"                 # base of the dated run-record directory (datedlog)

    [tool.lab_commons.tests]
    resources = ["femm", "jmag"]           # the markers naming a resource (lab_commons.hpc.needsets)
    produce = ["-m", "lab_commons.dev.verify", "--part", "{part}"]   # a local part: argv after the interpreter

    [tool.lab_commons.parts.refs.windows]      # optional: the refs (fnmatch) this part is produced for
    full = ["integrate/main", "main"]          # absent = every ref the serving mode serves

A ref filter is what keeps HEAVY work off development branches (user ruling 2026-10-13): the scheduler
(:func:`lab_commons.dev.forgeschedule.candidates`) never offers a ref the part's filter excludes, and
says so. It is read from the SERVING checkout, so a branch cannot widen the filter that judges it.

The repo url is origin's, spelled https. A missing declaration is refused naming the key to add --
never a command with a hole in it.
"""

from __future__ import annotations

import argparse
import dataclasses
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from lab_commons.compute.probe import os_name
from lab_commons.dev.datedlog import dated_log
from lab_commons.dev.forge import forge_from_remote
from lab_commons.dev.forgeoutbox import Post, PostFailed, enqueue, flush
from lab_commons.dev.forgestatus import state_for
from lab_commons.dev.producer import ProducerExit
from lab_commons.hpc.declared import kit_tables, pyproject_at
from lab_commons.hpc.needsets import BASE, PART_NAME, need_sets, needs_of, selecting, vocabulary_at
from lab_commons.hpc.records import cells_of, read_record
from lab_commons.hpc.retired import refusal
from lab_commons.hpc.testcells import conclude
from lab_commons.log import emit
from lab_commons.outcomes import Conclusion

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from lab_commons.dev.forgestatus import CommitStatus

__all__ = [
    'BASE',
    'CONTEXT_PREFIX',
    'PART_FIELD',
    'ClusterPart',
    'Composition',
    'Part',
    'PartRefusal',
    'Standing',
    'UndeclaredPart',
    'cluster_part',
    'compose',
    'derived',
    'main',
    'origin_url',
    'part_context',
    'part_of',
    'parts_of',
    'producer_argv',
    'select',
    'split',
    'standing',
    'this_platform',
]

#: Every part's status context starts with this; the rest is the part's name (its need-set).
CONTEXT_PREFIX: Final = 'tests/'

#: The placeholder the declared producer carries; the claimed part's name replaces it.
PART_FIELD: Final = '{part}'

#: How many ids a refusal names before eliding; the count is always given.
_NAMED: Final = 5

#: The forge state a settled part reads back as; ``error`` (INCONCLUSIVE) is never a settled part.
_RESULT: Final = {state_for(result): result for result in (Conclusion.PASS, Conclusion.FAIL)}

_DESCRIPTION: Final = re.compile(
    r'^scope=(?P<scope>\w+) ran=(?P<ran>\d+) '
    r'hands=(?P<hands>-|[a-z0-9_+]+:\d+(?:,[a-z0-9_+]+:\d+)*)'
    r'(?: kept=(?P<kept>[0-9a-f]{12}:\d+(?:,[0-9a-f]{12}:\d+)*))?'
    r'(?: carried from (?P<carried>[0-9a-f]{12}): every outcome carried by footprint)?$'
)

#: The remedy a missing part names: a host whose resources admit it claims it and runs :func:`producer_argv`.
_PRODUCE: Final = 'a `lab_commons.dev.forge serve` host having every resource it needs claims and produces it'

#: An example of the one declared producer.
_PRODUCE_EXAMPLE: Final = '["-m", "lab_commons.dev.verify", "--part", "{part}"]'

#: Where the run records a cluster part gathers land, under the declared dated base.
_RECORD_KIND: Final = 'parts'


class PartRefusal(ValueError):
    """A part that cannot be posted -- posting it would claim a run nobody made."""


class UndeclaredPart(ValueError):
    """The repo does not declare how to produce a part; the message names the pyproject key to add."""


def part_context(part: str) -> str:
    """``tests/<part>`` -- the one status context a part (and a claim on it) uses."""
    return f'{CONTEXT_PREFIX}{part}'


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

    Every part writes there: the cluster's (:func:`cluster_part`) and a local verify's
    (:func:`lab_commons.dev.localpart.post_part`, a fresh or a cited run alike). *root* is the tree that was
    judged, clean at *head*, so its working tree IS the commit's declaration.

    Raises:
        UndeclaredPart: the output is not declared; the message names the key.

    """
    return _records(root, head, _declared(root))


def _records(root: Path, head: str, declared: Mapping[str, Any]) -> Path:
    output = _text(declared.get('parts', {}), 'tool.lab_commons.parts', 'output', '"output/logs"', required=True)
    return dated_log(root, head, base=output, kind=_RECORD_KIND)


def producer_argv(root: Path, part: str, *, sha: str) -> list[str]:
    """The ONE declared producer's argv for *part*, as commit *sha* declares it, ``{part}`` filled.

    It is what follows the interpreter: the producer runs it with the own venv interpreter of the tree it
    built at *sha* (:mod:`lab_commons.dev.shatree`), so neither half depends on where the serving checkout is.

    Raises:
        UndeclaredPart: the producer is absent, malformed or never told its part; the message names the key.

    """
    needs_of(part)  # a name that is no need-set is refused by name
    declared = _declared(root, sha).get('tests', {}).get('produce')
    produce = _strings(declared, 'tool.lab_commons.tests', 'produce', _PRODUCE_EXAMPLE, required=True)
    if not any(PART_FIELD in item for item in produce):
        msg = f'[tool.lab_commons.tests] produce must carry {PART_FIELD} so the producer is told its part: '
        raise UndeclaredPart(msg + _PRODUCE_EXAMPLE)
    return [item.replace(PART_FIELD, part) for item in produce]


def part_refs(root: Path, platform: str, scope: str) -> tuple[str, ...] | None:
    """The refs (fnmatch patterns) *platform*'s part at *scope* is produced for; ``None`` when undeclared.

    Raises:
        UndeclaredPart: the declaration is present and not a list of strings.

    """
    declared = _declared(root).get('parts', {}).get('refs', {}).get(platform, {}).get(scope)
    if declared is None:
        return None
    table = f'tool.lab_commons.parts.refs.{platform}'
    return tuple(_strings(declared, table, scope, '["integrate/main", "main"]', required=True))


def _declared(root: Path, sha: str | None = None) -> dict[str, Any]:
    """The kit's tables as commit *sha* declares them, or *root*'s working tree when no sha is named."""
    return kit_tables(pyproject_at(root, sha) if sha else (root / 'pyproject.toml').read_text(encoding='utf-8'))


def origin_url(root: Path) -> str:
    """*root*'s ``origin``, spelled https -- the read-only remote a cluster fetches a commit from."""
    forge = forge_from_remote(root)
    return f'https://{forge.host}/{forge.owner}/{forge.repo}.git'


@dataclass(frozen=True)
class ClusterPart:
    """What a cluster run of one commit needs from the checkout: where to fetch, what to collect, where records go."""

    repo_url: str
    collect: str
    output: Path
    outputs: tuple[str, ...] = ()  # declared outputs to pack and store (lab_commons.dev.artefacts); none by default


def cluster_part(root: Path, head: str) -> ClusterPart:
    """A cluster (scope full) part of commit *head*, filled from the declarations alone.

    The build (install, needs) is NOT here: ``hpc`` reads it from the commit itself at *head*.

    Raises:
        UndeclaredPart: a declaration it needs is absent or malformed; the message names the key.

    """
    declared = _declared(root, head)
    hpc, name = declared.get('hpc', {}), 'tool.lab_commons.hpc'
    _text(hpc, name, 'install', '"uv sync --extra dev"', required=True)
    collect = _text(hpc, name, 'collect', '"tests"', required=False)
    outputs = _strings(hpc.get('outputs'), name, 'outputs', '["output/fields/*.h5"]', required=False)
    return ClusterPart(
        repo_url=origin_url(root),
        collect=collect,
        output=_records(root, head, declared),
        outputs=tuple(outputs),
    )


def _elided(ids: Sequence[str]) -> str:
    return ', '.join(ids[:_NAMED]) + (', ...' if len(ids) > _NAMED else '')


@dataclass(frozen=True)
class Part:
    """One part's result for a commit, as the forge holds it; *platform* is the part's name (its need-set)."""

    platform: str
    scope: str
    result: Conclusion
    ran: int
    hands: dict[str, int] = field(default_factory=dict)
    carried: str = ''  # the sha12 this verdict was judged at, when it is carried (lab_commons.dev.forgecarry)
    kept: dict[str, int] = field(default_factory=dict)  # outcomes carried in, per sha12 they ran at; never in ran

    @property
    def state(self) -> str:
        """The forge state its conclusion posts as (:func:`lab_commons.dev.forgestatus.state_for`)."""
        return state_for(self.result)

    def description(self) -> str:
        """The status description: ``scope= ran= hands=`` (module docstring)."""
        hands = ','.join(f'{name}:{count}' for name, count in sorted(self.hands.items())) or '-'
        kept = ' kept=' + ','.join(f'{sha}:{count}' for sha, count in sorted(self.kept.items())) if self.kept else ''
        carried = f' carried from {self.carried}: every outcome carried by footprint' if self.carried else ''
        return f'scope={self.scope} ran={self.ran} hands={hands}{kept}{carried}'


def part_of(record: Mapping[str, Any]) -> Part:
    """The part a run record proves, by the strict rule in the module docstring.

    The part and scope are the record's own -- read, never re-declared. Its ``handed`` maps every id it
    did not cover to the part that id belongs to.
    """
    platform, scope, sha = str(record['platform']), str(record['scope']), str(record['sha'])
    covered = cells_of(dict(record))
    if not covered:
        msg = f'the {platform} record for {sha} covers no test -- an empty part is not a pass'
        raise PartRefusal(msg)
    flaky = sorted(record.get('flaky', ()))
    result = conclude(covered.values(), flaky)
    if result is Conclusion.INCONCLUSIVE:
        unanswered = sorted(node for node, one in covered.items() if one.met is None)
        msg = (
            f'the {platform} record for {sha} is INCONCLUSIVE: {len(unanswered)} of {len(covered)} covered test(s) '
            f'gave no answer ({_elided(unanswered)})'
            + (f' and {len(flaky)} were decided both ways ({_elided(flaky)})' if flaky else '')
            + ' -- gather again or re-submit; it is not posted, so no admission can cite it'
        )
        raise PartRefusal(msg)
    handed = {node: str(owner) for node, owner in record['handed'].items()}
    disowned = sorted(node for node, owner in handed.items() if owner == platform)
    if disowned:
        msg = f'the {platform} record for {sha} hands off {len(disowned)} test(s) of its own part: {_elided(disowned)}'
        raise PartRefusal(msg)
    unowned = sorted(node for node, owner in handed.items() if not PART_NAME.match(owner))
    if unowned:
        msg = f'the {platform} record for {sha} hands {len(unowned)} test(s) to no part: {_elided(unowned)}'
        raise PartRefusal(msg)
    hands: dict[str, int] = {}
    for owner in handed.values():
        hands[owner] = hands.get(owner, 0) + 1
    kept: dict[str, int] = {}
    for node, origin in record.get('carried', {}).items():
        if node in covered:
            kept[origin[:12]] = kept.get(origin[:12], 0) + 1
    return Part(
        platform=platform,
        scope=scope,
        result=result,
        ran=len(covered) - sum(kept.values()),
        hands=hands,
        kept=kept,
    )


def parts_of(statuses: Sequence[CommitStatus]) -> tuple[dict[str, Part], tuple[str, ...]]:
    """``(parts by name, problems)`` from a commit's LATEST status per context.

    A ``tests/<part>`` status that is not a settled part -- a claim still ``pending``, an
    ``error``, or a description this module did not write -- is a problem naming itself, never a part.
    """
    parts: dict[str, Part] = {}
    problems: list[str] = []
    for status in statuses:
        if not status.context.startswith(CONTEXT_PREFIX):
            continue
        name = status.context.removeprefix(CONTEXT_PREFIX)
        found = _DESCRIPTION.match(status.description)
        if status.state not in _RESULT or found is None or not PART_NAME.match(name):
            problems.append(f'{status.context} is {status.state} ({status.description!r}) -- not a settled part')
            continue
        hands = {} if found['hands'] == '-' else dict(item.split(':') for item in found['hands'].split(','))
        parts[name] = Part(
            platform=name,
            scope=found['scope'],
            result=_RESULT[status.state],
            ran=int(found['ran']),
            hands={owner: int(count) for owner, count in hands.items()},
            carried=found['carried'] or '',
            kept={sha: int(n) for sha, n in (one.split(':') for one in found['kept'].split(','))}
            if found['kept']
            else {},
        )
    return parts, tuple(problems)


def derived(statuses: Sequence[CommitStatus]) -> tuple[str, ...]:
    """The parts a commit is known to need, sorted: :data:`BASE`, every posted part, and every part one hands to."""
    parts, _ = parts_of(statuses)
    return tuple(sorted({BASE, *parts, *(name for part in parts.values() for name in part.hands)}))


def split(owners: Mapping[str, str], part: str) -> tuple[list[str], dict[str, str]]:
    """``(the ids of *part*, every other id with the part it belongs to)`` from *owners* (id -> part)."""
    mine = [node for node, owner in owners.items() if owner == part]
    handed = {node: owner for node, owner in owners.items() if owner != part}
    return mine, handed


def select(
    root: Path, sha: str, part: str, *, collect: Callable[[str], Sequence[str]]
) -> tuple[list[str], dict[str, str]]:
    """:func:`split` of what *collect* yields, by the vocabulary commit *sha* of *root* declares.

    *collect* takes a pytest marker expression (``''`` for none) and returns the node ids it collects
    in the consumer's checkout: once for everything, once per declared resource.
    """
    vocabulary = vocabulary_at(root, sha)
    selecting(vocabulary, part)  # a part that is no need-set over the vocabulary is refused by name
    ids = list(collect(''))
    carrying = {name: set(collect(name)) for name in vocabulary.resources}
    return split(need_sets(ids, carrying), part)


@dataclass(frozen=True)
class Composition:
    """The composed answer: the parts it rests on, PASS/FAIL, and why it cannot be cited (empty when it can)."""

    parts: tuple[Part, ...]
    result: Conclusion
    problems: tuple[str, ...]


def compose(parts: Mapping[str, Part], *, head: str) -> Composition:
    """Compose *parts* by the rule in the module docstring."""
    ordered = tuple(parts[name] for name in sorted(parts))
    result = Conclusion.FAIL if any(part.result is not Conclusion.PASS for part in ordered) else Conclusion.PASS
    problems: list[str] = []
    if BASE not in parts:
        problems.append(f'no {part_context(BASE)} part is posted for {head}; {_PRODUCE}')
    for name in sorted({name for part in ordered for name in part.hands}):
        handing = {part.platform: part.hands[name] for part in ordered if part.hands.get(name)}
        if handing and name not in parts:
            by = ', '.join(f'{owner} hands {count}' for owner, count in sorted(handing.items()))
            problems.append(f'missing the {name} part ({by}); {_PRODUCE}')
    return Composition(parts=ordered, result=result, problems=tuple(problems))


@dataclass(frozen=True)
class Standing:
    """A commit's result as its parts on the forge say it: PASS, FAIL, or INCONCLUSIVE while unsettled.

    THE ONE READING of a commit's parts, shared by push admission and the integrator's queue: a FAIL
    part is ``FAIL`` whatever else is missing; otherwise any problem (a part missing, unsettled, or of
    the wrong scope) leaves it INCONCLUSIVE; else PASS.
    """

    result: Conclusion
    parts: tuple[Part, ...]
    problems: tuple[str, ...]

    def cited(self) -> str:
        """The parts it rests on, one ``part=RESULT/scope ran=N`` each."""
        return ', '.join(f'{part.platform}={part.result.name}/{part.scope} ran={part.ran}' for part in self.parts)


def standing(statuses: Sequence[CommitStatus], *, head: str, scope: str | None = None) -> Standing:
    """The :class:`Standing` of commit *head* from its latest statuses; *scope* requires every part at it."""
    parts, unsettled = parts_of(statuses)
    composed = compose(parts, head=head)
    problems = [*unsettled, *composed.problems]
    if scope is not None:
        problems += [
            f'{part.platform} is {part.result.name} of scope {part.scope}; only a PASS of scope {scope} counts here'
            for part in composed.parts
            if part.result is not Conclusion.PASS or part.scope != scope
        ]
    failed = any(part.result is Conclusion.FAIL for part in composed.parts)
    return Standing(result=_settled(failed=failed, problems=problems), parts=composed.parts, problems=tuple(problems))


def _settled(*, failed: bool, problems: Sequence[str]) -> Conclusion:
    if failed:
        return Conclusion.FAIL
    return Conclusion.INCONCLUSIVE if problems else Conclusion.PASS


def post(root: Path, path: Path, onto: str = '') -> str:
    """Queue the part *path*'s record proves, with the record attached, and flush; returns the lines.

    *onto* names a reach-equivalent descendant (:mod:`lab_commons.dev.forgecarry`): the same part is
    posted THERE instead, naming the record's sha it was judged at.
    """
    record = read_record(path)
    part = part_of(record)
    if onto:
        part = dataclasses.replace(part, carried=str(record['sha'])[:12])
    sha = onto or str(record['sha'])
    enqueue(root, Post(sha, part_context(part.platform), part.state, part.description()), record=path)
    lines = flush(root)
    return '\n'.join([f'[platformparts] {part.platform} part {part.result.name}: {part.description()}', *lines])


def main(argv: Sequence[str] | None = None) -> int:
    """``post <run-record>``: queue and post the part a run record proves."""
    parser = argparse.ArgumentParser(
        prog='python -m lab_commons.dev.platformparts', description=__doc__.splitlines()[0]
    )
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv and (refused := refusal('platformparts', argv[0])):
        parser.error(refused)
    verbs = parser.add_subparsers(dest='verb', required=True)
    posting = verbs.add_parser('post', help='post a run record as its part')
    posting.add_argument('record', type=Path, help='the run record `python -m lab_commons.hpc run gather -o` wrote')
    posting.add_argument('--root', type=Path, default=Path.cwd(), help='the checkout whose origin receives the part')
    args = parser.parse_args(argv)
    try:
        emit(post(args.root, args.record))
    except PostFailed as why:
        emit(f'[platformparts] unreachable: {why}', err=True)
        return ProducerExit.UNREACHABLE
    except PartRefusal as why:
        emit(f'[platformparts] refused: {why}', err=True)
        return 1
    return 0


def this_platform() -> str:
    """The OS resource THIS box is (:func:`lab_commons.compute.probe.os_name`)."""
    return os_name(sys.platform)


if __name__ == '__main__':
    raise SystemExit(main())
