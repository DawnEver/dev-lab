"""The coverage REPORT and the tool-cache environment every verify pytest step runs with.

Split out of :mod:`dev_lab.dev.verifysteps` (2026-11-25, MODULE-SIZE-ALARM) along its own seam: that module runs
the steps and reads their verdict; this one only names where a step's coverage and caches go, and reads the total.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from dev_lab.dev.datedlog import output_dir

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    'CACHE_VARS',
    'COVERAGE_KIND',
    'cache_env',
    'coverage_args',
    'coverage_env',
    'coverage_report',
    'coverage_total',
]

#: THE COVERAGE REPORT (user ruling 2026-11-05): every pytest step measures coverage with pytest-cov and writes it
#: as Markdown to ``<output>/<yy>/<mm>/<dd>/coverage/`` (:func:`dev_lab.dev.datedlog.output_dir`), named by its
#: log. A REPORT, NEVER A GATE -- no ``--cov-fail-under``, so a coverage number cannot move a verdict.
#: ``--cov`` names no source, so a repo's own ``[tool.coverage.run]`` decides what is measured.
_COVERAGE_TOTAL: Final = '| **TOTAL**'


#: The output-tree kind the coverage report and its data file go to (user ruling 2026-11-05).
COVERAGE_KIND: Final = 'coverage'


def coverage_report(root: Path, log: Path) -> Path:
    """The Markdown coverage report of the run logged at *log*: ``<log stem>.coverage.md`` in today's coverage dir."""
    return output_dir(root, COVERAGE_KIND) / f'{log.stem}.coverage.md'


def coverage_env(root: Path, log: Path) -> dict[str, str]:
    """The coverage DATA file of the run logged at *log*, beside its report, so no run writes ``.coverage`` here."""
    return {'COVERAGE_FILE': str(output_dir(root, COVERAGE_KIND) / f'{log.stem}.coverage')}


#: THE TOOL CACHES (user ruling 2026-11-24): every cache lives under ``output/cache/<tool>/``, never at the root,
#: so the family `.gitignore` need not name one. pytest's and ruff's go there through the family pyproject rows;
#: these two have no pyproject key every repo shares (hypothesis has none at all), so the door that runs them sets
#: the variable each tool reads.
CACHE_VARS: Final[dict[str, str]] = {'HYPOTHESIS_STORAGE_DIRECTORY': 'hypothesis', 'MYPY_CACHE_DIR': 'mypy'}


def cache_env(root: Path) -> dict[str, str]:
    """Each :data:`CACHE_VARS` variable pointed at ``<root>/output/cache/<tool>``."""
    return {var: str(root / 'output' / 'cache' / tool) for var, tool in CACHE_VARS.items()}


def coverage_args(root: Path, log: Path, *, append: bool = False) -> tuple[str, ...]:
    """pytest-cov's arguments for the run logged at *log* under *root*; *append* adds to the stage before it."""
    report = coverage_report(root, log).relative_to(root).as_posix()  # relative: a drive colon would split the option
    return ('--cov', f'--cov-report=markdown:{report}', *(('--cov-append',) if append else ()))


def coverage_total(report: Path) -> str | None:
    """The TOTAL percentage *report* states, or ``None`` when there is no report to read."""
    if not report.is_file():
        return None
    for line in report.read_text(encoding='utf-8').splitlines():
        if line.startswith(_COVERAGE_TOTAL):
            return line.rstrip(' |').rsplit('|', 1)[-1].strip(' *')
    return None
