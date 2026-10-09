"""PLATFORM PARTS -- one commit's verdict COMPOSED of a part per platform it ran on (user ruling 2026-10-09).

THE SPLIT IS DECLARED ONCE, per marker, in ``[tool.lab_commons.platforms]`` (:mod:`lab_commons.hpc.platforms`).
A part is named for the platform it RAN ON -- ``linux``, ``windows``, ``macos`` -- never for where it
was launched from. EVERY COLLECTED ID IS ASSIGNED TO EXACTLY ONE PART by one rule,
:func:`lab_commons.hpc.platforms.assign`: the first platform in ``PLATFORMS`` order that can run it
(linux, else windows, else macos). A part's selection is therefore a pure function of the commit's
table and its collected ids; no part reads another part's record, so every part can start at any
time and in parallel. Each part records what it ``handed``: every collected id assigned to ANOTHER
part, mapped to the platforms that can run it.

* The ``linux`` part comes from the cluster: ``python -m lab_commons.hpc verdict submit``, then
  ``verdict gather`` writes a record, and :func:`linux_part` turns it into ledger entries STRICTLY -- PASS
  only when every covered outcome is passed / skipped / xfailed; a failed or error id is FAIL. A part
  with ANY lost or missing id is INCONCLUSIVE and is REFUSED, never recorded: a FAIL claims the code
  failed, and measured 2026-10-09 a record of 50349 lost ids (a build that never produced a venv) was
  written as a linux FAIL. Nothing covered is refused too.
* Any other part (a consumer's gate runner with ``--platform <name>``) calls :func:`select` with a
  collector over its own checkout, runs the ids assigned to it and records what it ``handed``.

COMPOSITION (:func:`compose`). The newest part per platform for HEAD. Every id some part handed must
be assigned to a part that is recorded; any FAIL part makes it FAIL. An id no declared platform can
run is refused by name; one whose assigned part is missing names that part and the command producing it.

THE ENV KEY IS HONEST: a linux part's env names the cluster, its platform and its python
(``hpc:<cluster>:<platform>:python-<x.y.z>``), never this box. A part recorded for THIS box's platform
is cited only in this box's env, as a whole run is.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from lab_commons.dev.verdictledger import Entry, LedgerRefusal, ledger_path, record, run_test_id
from lab_commons.hpc.platforms import LINUX, PLATFORMS, assign, cannot_run, host_platform, runnable, table_at
from lab_commons.log import emit

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

__all__ = [
    'LINUX',
    'PASSING',
    'Composition',
    'PartRefusal',
    'compose',
    'linux_part',
    'main',
    'parts_for',
    'select',
    'split',
    'this_platform',
]

#: Covered outcomes that do not fail a part: ran and passed, or declined by the test's own design.
PASSING: Final = frozenset({'passed', 'skipped', 'xfailed'})

#: How many ids a missing-part refusal names before eliding; the count is always given.
_NAMED: Final = 5

#: Outcomes of ids that never reported: they make a part INCONCLUSIVE, never FAIL.
_UNRUN: Final = frozenset({'lost', 'missing'})

#: The cluster record's word for an id it handed to another part.
_NOT_COVERED: Final = 'not-covered'

_LINUX_COMMAND: Final = (
    'python -m lab_commons.hpc verdict submit --sha {head} --repo-url <https> --install "<cmd>", then '
    'python -m lab_commons.hpc verdict gather --sha {head} -o <record.json> until it writes the record, then '
    'python -m lab_commons.dev.platformparts record-linux <record.json> --tier <tier>'
)
_PART_COMMAND: Final = "the repo's gate runner on a {platform} box with `--platform {platform}`"


class PartRefusal(ValueError):
    """A part that cannot be recorded -- recording it would claim a run nobody made."""


def _command(platform: str, head: str) -> str:
    return _LINUX_COMMAND.format(head=head) if platform == LINUX else _PART_COMMAND.format(platform=platform)


def linux_part(record_: Mapping[str, Any], *, tier: str, log: str) -> list[Entry]:
    """The cluster record as ledger rows: the part's run entry first, then one row per covered id."""
    outcomes: dict[str, str] = dict(record_['outcomes'])
    covered = {node: outcome for node, outcome in outcomes.items() if outcome != _NOT_COVERED}
    if not covered:
        msg = f'the linux record for {record_["sha"]} covers no test -- an empty part is not a pass'
        raise PartRefusal(msg)
    unrun = sorted(node for node, outcome in covered.items() if outcome in _UNRUN)
    if unrun:
        msg = (
            f'the linux record for {record_["sha"]} is INCONCLUSIVE: {len(unrun)} of {len(covered)} covered test(s) '
            f'never reported ({", ".join(unrun[:_NAMED])}{", ..." if len(unrun) > _NAMED else ""}) -- '
            'gather again or re-submit; it is not recorded, so no admission can cite it'
        )
        raise PartRefusal(msg)
    handed = {
        node: list(record_['handed'].get(node, [])) for node, outcome in outcomes.items() if outcome == _NOT_COVERED
    }
    failing = sorted(node for node, outcome in covered.items() if outcome not in PASSING)
    sha = str(record_['sha'])
    tree = f'commit:{sha}'
    env = f'hpc:{record_["cluster"]}:{record_["platform"]}:python-{record_["python"]}'

    def row(test: str, result: str, handed: dict[str, list[str]] | None = None) -> Entry:
        return Entry(tree, env, test, result, tier=tier, commit=sha, log=log, part=LINUX, handed=handed or {})

    run = row(run_test_id(f'{tier} linux-part'), 'FAIL' if failing else 'PASS', handed=handed)
    tests = [
        row(node, 'FAIL' if node in failing else 'PASS') for node, out in sorted(covered.items()) if out != 'skipped'
    ]
    return [run, *tests]


def parts_for(rows: Sequence[Entry], *, head: str, env: str, host: str) -> dict[str, Entry]:
    """The newest part run entry per platform for *head*; this box's platform only in this box's *env*."""
    found: dict[str, Entry] = {}
    for row in rows:
        if row.part and row.commit == head and row.test.startswith('run:') and (row.part != host or row.env == env):
            found[row.part] = row
    return found


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

    parts: tuple[Entry, ...]
    result: str
    problems: tuple[str, ...]


def compose(parts: Mapping[str, Entry], *, head: str) -> Composition:
    """Compose *parts* by the rule in the module docstring."""
    ordered = tuple(parts[name] for name in sorted(parts))
    result = 'FAIL' if any(part.result != 'PASS' for part in ordered) else 'PASS'
    problems: list[str] = []
    handed: dict[str, list[str]] = {}
    for part in ordered:
        handed.update(part.handed)
    nowhere = sorted(node for node, can in handed.items() if assign(can) is None)
    if nowhere:
        problems.append(f'no declared platform can run {len(nowhere)} test(s): {", ".join(nowhere)}')
    missing: dict[str, list[str]] = {}
    for node, can in sorted(handed.items()):
        owner = assign(can)
        if owner is not None and owner not in parts:
            missing.setdefault(owner, []).append(node)
    for platform in PLATFORMS:
        if platform in missing:
            ids = missing[platform]
            problems.append(
                f'missing the {platform} part for {len(ids)} test(s) assigned to it ({", ".join(ids[:_NAMED])}'
                f'{", ..." if len(ids) > _NAMED else ""}); produce it with {_command(platform, head)}'
            )
    disowned = sorted(node for part in ordered for node, can in part.handed.items() if assign(can) == part.part)
    if disowned:
        problems.append(f'{len(disowned)} test(s) handed off by the part they are assigned to: {", ".join(disowned)}')
    return Composition(parts=ordered, result=result, problems=tuple(problems))


def _evidence(path: Path) -> str:
    return f'{path}@sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}'


def main(argv: Sequence[str] | None = None) -> int:
    """``record-linux <record.json> --tier <tier>``: append the cluster record to the verdict ledger."""
    parser = argparse.ArgumentParser(
        prog='python -m lab_commons.dev.platformparts', description=__doc__.splitlines()[0]
    )
    parser.add_argument('verb', choices=['record-linux'])
    parser.add_argument('record', type=Path, help='the record `python -m lab_commons.hpc verdict gather -o` wrote')
    parser.add_argument('--tier', required=True, help='the tier the cluster selection amounts to (gate, heavy)')
    parser.add_argument('--root', type=Path, default=Path.cwd(), help='the checkout whose ledger is written')
    parser.add_argument('--ledger', type=Path, help="the verdict ledger (default: the main checkout's)")
    args = parser.parse_args(argv)
    record_ = json.loads(args.record.read_text(encoding='utf-8'))
    try:
        rows = linux_part(record_, tier=args.tier, log=_evidence(args.record))
        target = args.ledger if args.ledger is not None else ledger_path(args.root)
        record(target, rows)
    except (PartRefusal, LedgerRefusal) as refusal:
        emit(f'[platformparts] refused: {refusal}')
        return 1
    run = rows[0]
    emit(
        f'[platformparts] linux part {run.result} for {run.commit} env={run.env}; handed {len(run.handed)} -> {target}'
    )
    return 0


def this_platform() -> str:
    """The platform THIS box runs a part on."""
    return host_platform(sys.platform)


if __name__ == '__main__':
    raise SystemExit(main())
