"""A coverage tool's JSON report read into per-file COUNTS -- coverage.py's and ``cargo llvm-cov``'s. Knows no owner.

The counts are what a report STATES, never a percentage it printed: a percentage cannot be summed, so every reader
above this one would average them, and an average of file percentages weighs a three-line file like a thousand-line
one. Which files belong to whom is :mod:`dev_lab.dev.ownercov`'s.

* coverage.py: ``coverage json -o <report>`` (pytest-cov: ``--cov-report=json:<report>``). ``files.<path>.summary``
  gives ``num_statements``/``covered_lines`` and, under ``[tool.coverage.run] branch = true``,
  ``num_branches``/``covered_branches``; ``meta.branch_coverage`` says whether branches were measured.
* ``cargo llvm-cov --branch --json --summary-only --output-path <report>``: the ``llvm.coverage.json.export``
  document, ``data[].files[].summary.lines`` and ``.branches`` (``count``/``covered``). It does not say whether
  branches were measured; a report counting NO branch anywhere was run without ``--branch`` (stable Rust measures
  none), and :attr:`Measurement.branch` says so rather than reading that as "nothing to miss".

A path is read relative to the repo root (an absolute one outside it stays absolute, for the caller to refuse), with
``/`` separators. A file stated twice is refused: two counts for one file are two facts, and summing or keeping
either would be a guess.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import TYPE_CHECKING, Any, Final, NoReturn

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

__all__ = [
    'PYTHON_TOOL',
    'PYTHON_WRITES',
    'RUST_TOOL',
    'RUST_WRITES',
    'Counts',
    'Measurement',
    'ReportRefused',
    'python_report',
    'rust_report',
]

PYTHON_TOOL: Final = 'coverage.py'
RUST_TOOL: Final = 'cargo llvm-cov'
#: The command that writes each report, which every refusal of that report names.
PYTHON_WRITES: Final = (
    'coverage json -o <report> (pytest-cov: --cov-report=json:<report>), with [tool.coverage.run] branch = true'
)
RUST_WRITES: Final = 'cargo llvm-cov --branch --json --summary-only --output-path <report>'
_LLVM_TYPE: Final = 'llvm.coverage.json.export'


class ReportRefused(ValueError):
    """A report that is missing or not its tool's shape; the message names the report and the command that writes it."""


@dataclass(frozen=True, slots=True)
class Counts:
    """What one file (or a sum of files) states: lines and lines hit, branches and branches hit."""

    lines: int = 0
    lines_hit: int = 0
    branches: int = 0
    branches_hit: int = 0

    def __add__(self, other: Counts) -> Counts:
        """The two summed, field by field."""
        return Counts(
            self.lines + other.lines,
            self.lines_hit + other.lines_hit,
            self.branches + other.branches,
            self.branches_hit + other.branches_hit,
        )


@dataclass(frozen=True, slots=True)
class Measurement:
    """One report: the tool, the report read, whether it measured branches, and each file's counts."""

    tool: str
    report: str
    branch: bool
    files: Mapping[str, Counts]


def _refuse(tool: str, report: Path, why: str) -> NoReturn:
    writes = PYTHON_WRITES if tool == PYTHON_TOOL else RUST_WRITES
    msg = f'{tool} report {report}: {why} -- write it with: {writes}'
    raise ReportRefused(msg)


def _load(tool: str, report: Path) -> Any:  # noqa: ANN401 -- JSON is untyped
    if not report.is_file():
        _refuse(tool, report, 'no report there')
    try:
        return json.loads(report.read_text(encoding='utf-8'))
    except (ValueError, UnicodeDecodeError) as exc:
        _refuse(tool, report, f'is not JSON ({exc})')


def _relative(root: Path, name: str) -> str:
    """*name* relative to *root* with ``/`` separators; an absolute name outside *root* stays absolute."""
    if PureWindowsPath(name).is_absolute() or PurePosixPath(name).is_absolute():
        try:
            return Path(name).resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            return name.replace('\\', '/')
    return PurePosixPath(name.replace('\\', '/')).as_posix()


def _int(tool: str, report: Path, where: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        _refuse(tool, report, f'{where} is {value!r}, not a count')
    return value


def _collect(tool: str, report: Path, rows: Iterable[tuple[str, Counts]]) -> dict[str, Counts]:
    out: dict[str, Counts] = {}
    for name, counts in rows:
        if name in out:
            _refuse(tool, report, f'{name} is stated twice; one file has one count')
        out[name] = counts
    return out


def python_report(root: Path, report: Path) -> Measurement:
    """coverage.py's JSON *report* under *root*, per file.

    Raises:
        ReportRefused: no report, not JSON, or not coverage.py's shape; names *report* and the command.

    """
    data = _load(PYTHON_TOOL, report)
    meta = data.get('meta') if isinstance(data, dict) else None
    files = data.get('files') if isinstance(data, dict) else None
    if not isinstance(meta, dict) or not isinstance(meta.get('branch_coverage'), bool) or not isinstance(files, dict):
        _refuse(PYTHON_TOOL, report, 'no meta.branch_coverage and files table: not a coverage.py JSON report')

    def row(name: str, entry: object) -> tuple[str, Counts]:
        summary = entry.get('summary') if isinstance(entry, dict) else None
        if not isinstance(summary, dict):
            _refuse(PYTHON_TOOL, report, f'files.{name} has no summary')
        get = summary.get
        counts = [
            _int(PYTHON_TOOL, report, f'files.{name}.summary.{key}', get(key, 0 if 'branch' in key else None))
            for key in ('num_statements', 'covered_lines', 'num_branches', 'covered_branches')
        ]
        return _relative(root, name), Counts(*counts)

    found = _collect(PYTHON_TOOL, report, (row(name, entry) for name, entry in files.items()))
    return Measurement(PYTHON_TOOL, str(report), meta['branch_coverage'], found)


def rust_report(root: Path, report: Path) -> Measurement:
    """``cargo llvm-cov``'s JSON summary *report* under *root*, per file.

    Raises:
        ReportRefused: no report, not JSON, or not the ``llvm.coverage.json.export`` shape; names *report*.

    """
    data = _load(RUST_TOOL, report)
    if not isinstance(data, dict) or data.get('type') != _LLVM_TYPE or not isinstance(data.get('data'), list):
        _refuse(RUST_TOOL, report, f'not an {_LLVM_TYPE} document (its "type" and "data")')

    def row(entry: object) -> tuple[str, Counts]:
        name = entry.get('filename') if isinstance(entry, dict) else None
        summary = entry.get('summary') if isinstance(entry, dict) else None
        if not isinstance(name, str) or not isinstance(summary, dict):
            _refuse(RUST_TOOL, report, f'a file entry has no filename and summary: {entry!r}')
        lines, branches = summary.get('lines') or {}, summary.get('branches') or {}
        counts = [
            _int(RUST_TOOL, report, f'{name} {key}.{field}', table.get(field))
            for key, table in (('lines', lines), ('branches', branches))
            for field in ('count', 'covered')
        ]
        return _relative(root, name), Counts(*counts)

    entries = [entry for export in data['data'] if isinstance(export, dict) for entry in export.get('files', [])]
    found = _collect(RUST_TOOL, report, (row(entry) for entry in entries))
    return Measurement(RUST_TOOL, str(report), any(c.branches for c in found.values()), found)
