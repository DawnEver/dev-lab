"""OWNER-COVERAGE: each owner ``dependencies.toml`` declares meets a line and branch BAR and a FLOOR ratcheting up.

Requested by a consumer's v1 review. The owners are :mod:`dev_lab.dev.deptable`'s rows -- the
child packages ``[python.owners]`` names, the crates ``[rust.crates]`` names -- and the measurement is a coverage
tool's own report, read per file by :mod:`dev_lab.dev.covreports` and SUMMED per owner (never an average of file
percentages). A repo without ``dependencies.toml`` is not judged.

THE BAR is the family's :data:`BARS` -- ``95 %`` of lines and ``90 %`` of branches, for Python and Rust alike -- and
a repo may only RAISE it (``BAR-IS-A-CONSTANT``); restating it is a second copy and is refused too::

    [tool.dev_lab.coverage]          # pyproject.toml; optional
    line = "97 %"                    # a value carries its unit: "97 %", never 97 or "0.97"

THE FLOOR is a measurement above the bar, written ONLY by ``record`` into the same table::

    [tool.dev_lab.coverage.floors.python]       # keyed like dependencies.toml: [python.owners] -> python
    contracts = { line = "98.40 %", branch = "93.12 %" }
    [tool.dev_lab.coverage.floors.rust]         # [rust.crates] -> rust
    assemble = { line = "96.00 %" }

``record`` writes each measured share, truncated to 0.01 %, as the owner's new floor when it is above the bar and
above the old floor; it never lowers one, and it deletes a floor at or below the bar (a second copy of the bar). The
ratchet's other side (``RATCHET-TWO-SIDES``): a floor is only ever a measurement ``record`` wrote, so one edited
past the measurement reds exactly like a regression and ``record`` refuses to accept it.

REFUSED, each naming the owner's row: an owner below its bar or floor (with the measured value and the threshold); a
declared owner nothing measured; a measured file (with a line) in no declared owner; a floor naming no declared
owner; a report that measured no branch; a declared language with no report, or a report with no owner table; and
a malformed ``[tool.dev_lab.coverage]`` -- a bare number, a share outside 0..100 %, an unknown key, a lowered bar.

``python -m dev_lab.dev.ownercov check|record [--python <coverage.py JSON>] [--rust <cargo llvm-cov JSON>]``.
"""

from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import tomlkit
from lab_commons.log import emit

from dev_lab.dev import covreports, deptable, ownerdag, rustdeps
from dev_lab.dev._ownercov_policy import BARS, GRID, ROWS, TABLE, WHERE, Policy, Refused, policy, shown
from dev_lab.dev.covreports import Counts, Measurement, ReportRefused
from dev_lab.dev.deptable import Declared, DependenciesError
from dev_lab.dev.rules import tracked_files

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

__all__ = ['BARS', 'DOOR', 'RULE_ID', 'TABLE', 'Refused', 'main', 'problems', 'record', 'shown']

RULE_ID: Final = 'OWNER-COVERAGE'
DOOR: Final = (
    'cover the owner with tests; a floor moves only through `python -m dev_lab.dev.ownercov record` with the '
    'reports, and only up'
)
_DETAILS: Final = 'details: docs-src/dev/refusals.md#owner-coverage (dev-lab)'
_TOOLS: Final = {'python': covreports.PYTHON_TOOL, 'rust': covreports.RUST_TOOL}


@dataclass
class _Judgment:
    policy: Policy
    found: list[str] = field(default_factory=list)
    #: (language, owner) -> its summed counts, and whether its report measured branches
    measured: dict[tuple[str, str], tuple[Counts, bool]] = field(default_factory=dict)


def _owners(root: Path, decl: Declared, files: Iterable[str], language: str) -> dict[str, str | None] | str:
    """Each declared owner of *language* -> its repo directory (``None``: not in the tree); a str is a refusal."""
    if language == 'rust':
        tree = rustdeps.crates(root, files)
        return {name: tree[name].directory if name in tree else None for name in decl.crates}
    python = ownerdag.python_tree(root)
    if python is None:
        return '[python.owners] is declared, but pyproject.toml [project].name names no package at src/<name>'
    return {owner: f'{python.directory}/{owner}' for owner in decl.owners}


def _owner_of(rel: str, owners: Mapping[str, str | None]) -> str | None:
    """The owner whose directory holds *rel* (the deepest one, for a crate inside another)."""
    held = [(len(d), o) for o, d in owners.items() if d is not None and (d == '' or rel.startswith(d + '/'))]
    return max(held)[1] if held else None


def _owners_measured(
    judged: _Judgment, root: Path, decl: Declared, files: list[str], *, language: str, report: Measurement | None
) -> dict[str, str | None] | None:
    """*language*'s owners -> directories when both a declaration and a report exist; else the refusal, and None."""
    row, tool, found = ROWS[language], _TOOLS[language], judged.found
    if not (decl.crates if language == 'rust' else decl.owners):
        if report is not None:
            found.append(
                f'a {tool} report was given but dependencies.toml declares no {row} row to own what it measured'
            )
        return None
    if report is None:
        found.append(f'{row} is declared but no {tool} report was given -- --{language} <report>')
        return None
    owners = _owners(root, decl, files, language)
    if isinstance(owners, str):
        found.append(owners)
        return None
    if not report.branch:
        how = 'set [tool.coverage.run] branch = true' if language == 'python' else 'run cargo llvm-cov --branch'
        found.append(f'{tool} report {report.report} measured no branch, so the branch bar cannot be judged -- {how}')
    return owners


def _stale_floors(judged: _Judgment, language: str, owners: Mapping[str, object]) -> None:
    """A floor naming no declared owner, and a floor at or below the bar (a second copy of the bar)."""
    rows, bars = judged.policy.floors.get(language, {}), judged.policy.bars
    for owner in sorted(set(rows) - set(owners)):
        judged.found.append(
            f'{WHERE}.floors.{language}] {owner}: a floor for an owner no {ROWS[language]} row of dependencies.toml '
            'declares -- move it with the owner when it was renamed, else delete it'
        )
    judged.found += [
        f'{WHERE}.floors.{language}] {owner} {kind} = "{floor.text}" is not above the bar {shown(bars[kind])}: '
        'a floor exists only above the bar -- `record` deletes it'
        for owner, row in sorted(rows.items())
        for kind, floor in row.items()
        if floor.share <= bars[kind]
    ]


def _language(
    judged: _Judgment, root: Path, decl: Declared, files: list[str], *, language: str, report: Measurement | None
) -> None:
    owners = _owners_measured(judged, root, decl, files, language=language, report=report)
    if owners is None or report is None:
        return
    sums: dict[str, Counts] = {}
    for rel, counts in sorted(report.files.items()):
        if (owner := _owner_of(rel, owners)) is not None:
            sums[owner] = sums.get(owner, Counts()) + counts
        elif counts.lines:
            judged.found.append(f'{report.tool} measured {rel}, which lies in no owner dependencies.toml declares')
    _stale_floors(judged, language, owners)
    for owner in sorted(owners):
        if not (counts := sums.get(owner, Counts())).lines:
            where = owners[owner] or 'its crate (no tracked Cargo.toml names it)'
            hint = (
                'is it under [tool.coverage.run] source, and does a test reach it?'
                if language == 'python'
                else 'does `cargo llvm-cov` build it?'
            )
            judged.found.append(f'{ROWS[language]} {owner}: no line was measured in {where} -- {hint}')
            continue
        judged.measured[language, owner] = (counts, report.branch)
        _thresholds(judged, language, owner, counts, measured_branch=report.branch)


def _ratio(counts: Counts, kind: str) -> Fraction:
    if kind == 'line':
        return Fraction(counts.lines_hit, counts.lines)
    return Fraction(counts.branches_hit, counts.branches) if counts.branches else Fraction(1)  # nothing to miss


def _thresholds(judged: _Judgment, language: str, owner: str, counts: Counts, *, measured_branch: bool) -> None:
    row, policy = ROWS[language], judged.policy
    for kind, bar in policy.bars.items():
        if kind == 'branch' and not measured_branch:
            continue
        floor = policy.floors.get(language, {}).get(owner, {}).get(kind)
        share = _ratio(counts, kind)
        if floor is not None and floor.share > bar and share < floor.share:
            judged.found.append(
                f'{row} {owner}: {kind} coverage {shown(share)} is below its floor {shown(floor.share)} -- restore '
                'the tests that covered it; a floor is only ever a measurement `record` wrote, so a floor edited '
                'past one is restored, not met'
            )
        elif share < bar:
            judged.found.append(
                f'{row} {owner}: {kind} coverage {shown(share)} is below the bar {shown(bar)} -- cover it'
            )


def _judge(
    root: Path, files: Iterable[str], python: Measurement | None, rust: Measurement | None
) -> _Judgment | list[str] | None:
    """The judgment of *root*; ``None`` when undeclared; a list when the declaration itself is refused."""
    try:
        decl = deptable.load(root)
        if decl is None:
            return None
        judged = _Judgment(policy(root))
    except (DependenciesError, Refused) as exc:
        return [str(exc)]
    files = sorted(files)
    _language(judged, root, decl, files, language='python', report=python)
    _language(judged, root, decl, files, language='rust', report=rust)
    return judged


def problems(
    root: Path, files: Iterable[str], *, python: Measurement | None = None, rust: Measurement | None = None
) -> list[str] | None:
    """Every OWNER-COVERAGE refusal of *root* against the reports; ``None`` when *root* declares no owners."""
    judged = _judge(root, files, python, rust)
    return judged.found if isinstance(judged, _Judgment) else judged


def _raised(judged: _Judgment) -> dict[str, dict[str, dict[str, str]]]:
    """The floors after this measurement: each share above the bar and the old floor, truncated; none lowered."""
    policy = judged.policy
    out = {
        lang: {o: {k: f.text for k, f in row.items() if f.share > policy.bars[k]} for o, row in rows.items()}
        for lang, rows in policy.floors.items()
    }
    for (language, owner), (counts, measured_branch) in judged.measured.items():
        row = out.setdefault(language, {}).setdefault(owner, {})
        for kind, bar in policy.bars.items():
            if kind == 'branch' and not measured_branch:
                continue
            share = Fraction(math.floor(_ratio(counts, kind) * GRID), GRID)
            old = policy.floors.get(language, {}).get(owner, {}).get(kind)
            if share > bar and (old is None or share > old.share):
                row[kind] = shown(share)
    return {
        lang: {o: dict(sorted(r.items(), key=lambda kv: list(BARS).index(kv[0]))) for o, r in sorted(rows.items()) if r}
        for lang, rows in out.items()
        if any(rows.values())
    }


def _write(path: Path, floors: Mapping[str, Mapping[str, Mapping[str, str]]]) -> None:
    doc = tomlkit.parse(path.read_text(encoding='utf-8'))
    table: Any = doc
    for key in ('tool', 'dev_lab', TABLE):
        if key not in table:
            table[key] = tomlkit.table(is_super_table=True)
        table = table[key]
    table.pop('floors', None)
    if floors:
        whole = tomlkit.table(is_super_table=True)
        for language, rows in floors.items():
            one = tomlkit.table()
            for owner, row in rows.items():
                cell = tomlkit.inline_table()
                cell.update(row)
                one[owner] = cell
            whole[language] = one
        table['floors'] = whole
    path.write_text(tomlkit.dumps(doc), encoding='utf-8', newline='')


def record(
    root: Path, files: Iterable[str], *, python: Measurement | None = None, rust: Measurement | None = None
) -> list[str]:
    """Raise every floor this measurement passes and drop every copy of the bar; the refusals left after it.

    Nothing is written while the declaration is refused; a floor above its measurement is kept and refused.
    """
    judged = _judge(root, files, python, rust)
    if not isinstance(judged, _Judgment):
        return judged or []
    old = {
        lang: {o: {k: f.text for k, f in row.items()} for o, row in rows.items()}
        for lang, rows in judged.policy.floors.items()
        if rows
    }
    if (new := _raised(judged)) != old:
        _write(root / 'pyproject.toml', new)
    return problems(root, files, python=python, rust=rust) or []


def _report(found: list[str]) -> str:
    return '\n'.join([f'{RULE_ID}: {len(found)} refusal(s)', *found, f'door: {DOOR}', _DETAILS])


def main(argv: list[str] | None = None, *, cwd: Path | None = None) -> int:
    """``check`` or ``record`` the tracked tree against the reports; exit 1 on a refusal, 0 when clean or undeclared."""
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.ownercov', description=__doc__.splitlines()[0])
    parser.add_argument('verb', choices=('check', 'record'))
    parser.add_argument('--python', type=Path, help=f'a {covreports.PYTHON_TOOL} JSON report')
    parser.add_argument('--rust', type=Path, help=f'a {covreports.RUST_TOOL} JSON summary report')
    args = parser.parse_args(argv)
    root = cwd or Path.cwd()
    if not deptable.declared(root):
        emit(f'{RULE_ID}: {root.name} holds no {deptable.FILE}, so this repo is not judged (opt-in)', flush=True)
        return 0
    try:
        python = covreports.python_report(root, args.python) if args.python else None
        rust = covreports.rust_report(root, args.rust) if args.rust else None
    except ReportRefused as exc:
        emit(_report([str(exc)]), flush=True)
        return 1
    files = [f for f in tracked_files(root) if (root / f).is_file()]
    judge = record if args.verb == 'record' else problems
    if not (found := judge(root, files, python=python, rust=rust)):
        return 0
    emit(_report(found), flush=True)
    return 1


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
