"""PLATFORM PARTS -- one commit's verdict COMPOSED of a part per platform it ran on (user ruling 2026-10-09).

THE SPLIT IS DECLARED ONCE, per marker, in ``[tool.lab_commons.platforms]`` (:mod:`lab_commons.hpc.platforms`).
A part is named for the platform it RAN ON -- ``linux``, ``windows``, ``macos`` -- never for where it
was launched from. Each part runs the tests its platform can run AND no earlier part ran, and records
what it ``left``: every node id still unrun, mapped to the platforms that can run it.

* The ``linux`` part comes from the cluster: ``python -m lab_commons.hpc verdict`` writes a record,
  :func:`linux_part` turns it into ledger entries STRICTLY -- PASS only when every covered outcome is
  passed / skipped / xfailed; any failed, error, lost or missing id is FAIL; nothing covered is refused.
* A later part (a consumer's gate runner with ``--platform <name>``) asks :func:`to_run` what it
  should run and records ``left`` = :func:`left_after`.

COMPOSITION (:func:`compose`). The newest part per platform for HEAD. A test is covered when some
part ran it, i.e. when it is absent from at least one part's ``left``; the REMAINDER is the
intersection of every part's ``left``. An empty remainder composes; any FAIL part makes it FAIL. A
remainder id that no declared platform can run is refused by name; one that a platform with no
recorded part can run names that part and the command producing it.

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
from lab_commons.hpc.platforms import PLATFORMS, host_platform
from lab_commons.log import emit

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

__all__ = [
    'LINUX',
    'PASSING',
    'Composition',
    'PartRefusal',
    'compose',
    'left_after',
    'linux_part',
    'main',
    'parts_for',
    'remainder',
    'this_platform',
    'to_run',
]

LINUX: Final = 'linux'

#: Covered outcomes that do not fail a part: ran and passed, or declined by the test's own design.
PASSING: Final = frozenset({'passed', 'skipped', 'xfailed'})

#: How many ids a missing-part refusal names before eliding; the count is always given.
_NAMED: Final = 5

#: The cluster record's word for an id it left to another platform.
_NOT_COVERED: Final = 'not-covered'

_LINUX_COMMAND: Final = (
    'python -m lab_commons.hpc verdict --sha {head} --repo-url <https> --install "<cmd>" -o <record.json>, then '
    'python -m lab_commons.dev.platformparts record-linux <record.json> --tier <tier>'
)
_PART_COMMAND: Final = "the repo's gate runner on a {platform} box with `--platform {platform}`"


class PartRefusal(ValueError):
    """A part that cannot be recorded or selected -- recording it would claim a run nobody made."""


def _command(platform: str, head: str) -> str:
    return _LINUX_COMMAND.format(head=head) if platform == LINUX else _PART_COMMAND.format(platform=platform)


def linux_part(record_: Mapping[str, Any], *, tier: str, log: str) -> list[Entry]:
    """The cluster record as ledger rows: the part's run entry first, then one row per covered id."""
    outcomes: dict[str, str] = dict(record_['outcomes'])
    covered = {node: outcome for node, outcome in outcomes.items() if outcome != _NOT_COVERED}
    if not covered:
        msg = f'the linux record for {record_["sha"]} covers no test -- an empty part is not a pass'
        raise PartRefusal(msg)
    left = {node: list(record_['left'].get(node, [])) for node, outcome in outcomes.items() if outcome == _NOT_COVERED}
    failing = sorted(node for node, outcome in covered.items() if outcome not in PASSING)
    sha = str(record_['sha'])
    tree = f'commit:{sha}'
    env = f'hpc:{record_["cluster"]}:{record_["platform"]}:python-{record_["python"]}'

    def row(test: str, result: str, left: dict[str, list[str]] | None = None) -> Entry:
        return Entry(tree, env, test, result, tier=tier, commit=sha, log=log, part=LINUX, left=left or {})

    run = row(run_test_id(f'{tier} linux-part'), 'FAIL' if failing else 'PASS', left=left)
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


def remainder(parts: Mapping[str, Entry]) -> dict[str, list[str]]:
    """Every id NO part ran -- in every part's ``left`` -- with the platforms that can run it."""
    if not parts:
        return {}
    keys = set.intersection(*(set(part.left) for part in parts.values()))
    first = next(iter(parts.values()))
    return {node: list(first.left[node]) for node in sorted(keys)}


def to_run(
    rows: Sequence[Entry], *, head: str, platform: str, env: str, host: str
) -> tuple[list[str], dict[str, list[str]]]:
    """``(ids this platform's part runs, the remainder it starts from)``; refused when no part exists yet."""
    parts = {name: part for name, part in parts_for(rows, head=head, env=env, host=host).items() if name != platform}
    if not parts:
        msg = (
            f'no platform part is recorded for {head}, so there is nothing to select from; '
            f'record the linux part first: {_command(LINUX, head)}'
        )
        raise PartRefusal(msg)
    remaining = remainder(parts)
    return [node for node, can in remaining.items() if platform in can], remaining


def left_after(remaining: Mapping[str, list[str]], ran: Sequence[str]) -> dict[str, list[str]]:
    """What a part leaves: the remainder it started from, minus what it ran."""
    done = set(ran)
    return {node: list(can) for node, can in remaining.items() if node not in done}


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
    remaining = remainder(parts)
    nowhere = sorted(node for node, can in remaining.items() if not can)
    if nowhere:
        problems.append(f'no declared platform can run {len(nowhere)} test(s): {", ".join(nowhere)}')
    missing: dict[str, list[str]] = {}
    for node, can in remaining.items():
        for platform in can:
            if platform not in parts:
                missing.setdefault(platform, []).append(node)
    for platform in PLATFORMS:
        if platform in missing:
            ids = missing[platform]
            problems.append(
                f'missing the {platform} part for {len(ids)} test(s) no part ran ({", ".join(ids[:_NAMED])}'
                f'{", ..." if len(ids) > _NAMED else ""}); produce it with {_command(platform, head)}'
            )
    unrun = sorted(node for node, can in remaining.items() if can and all(platform in parts for platform in can))
    if unrun:
        problems.append(
            f'{len(unrun)} test(s) no part ran though a part exists for each platform that can: {", ".join(unrun)}'
        )
    return Composition(parts=ordered, result=result, problems=tuple(problems))


def _evidence(path: Path) -> str:
    return f'{path}@sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}'


def main(argv: Sequence[str] | None = None) -> int:
    """``record-linux <record.json> --tier <tier>``: append the cluster record to the verdict ledger."""
    parser = argparse.ArgumentParser(
        prog='python -m lab_commons.dev.platformparts', description=__doc__.splitlines()[0]
    )
    parser.add_argument('verb', choices=['record-linux'])
    parser.add_argument('record', type=Path, help='the record `python -m lab_commons.hpc verdict -o` wrote')
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
    emit(f'[platformparts] linux part {run.result} for {run.commit} env={run.env}; left {len(run.left)} -> {target}')
    return 0


def this_platform() -> str:
    """The platform THIS box runs a part on."""
    return host_platform(sys.platform)


if __name__ == '__main__':
    raise SystemExit(main())
