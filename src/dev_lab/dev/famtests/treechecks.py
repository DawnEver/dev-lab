"""The family checks whose every argument the checkout itself answers, run by :mod:`~dev_lab.dev.famtests.alwayson`.

User ruling D42 (2026-11-17): every family check no repo ran is ADOPTED in each repo it applies to, and
wired once rather than copied into ten. A body in :mod:`dev_lab.dev.famtests` takes its repo's facts as
arguments with no default; the rows here have no fact left for a repo to name -- the tests tree is
``tests/``, the rules pages are the tracked ``.claude/rules/**.md``, the remedies are the rendered
:data:`dev_lab.dev.agent_wiring.RULES_REL` -- so a consumer file could only be a copy, or a place to forget
it. Each row reads with its body's own PURE reader (``platform_skips``, ``host_node_uses``, ``restated``,
``relative_interpreters``).

APPLICABILITY IS THE TREE'S OWN SHAPE, never an opt-out: a row runs where its population exists, and a
population that exists but reads EMPTY is refused (the floor is one, as for the CJK row).

THE MIGRATION LEDGER IS DATA, as for the CJK row: ``[tool.dev_lab.<row>] declared`` in the repo's
manifest names the findings adoption found and the repo has not yet fixed, one key each (a test file's
repo path; ``<page>::<RULE-ID>``; a deny row's name). It is TWO-SIDED: a finding not declared reds, and a
declared key with no finding left reds as stale, so the set can only shrink.
"""

from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING, Final

from dev_lab.dev.agent_wiring import RULES_REL
from dev_lab.dev.family import declared_table
from dev_lab.dev.famtests.hostnode import host_node_uses
from dev_lab.dev.famtests.platformskips import platform_skips
from dev_lab.dev.famtests.remedypaths import relative_interpreters
from dev_lab.dev.famtests.restatedrules import restated
from dev_lab.dev.famtests.testleaks import WORDS as LEAK_WORDS
from dev_lab.dev.famtests.testleaks import leaks
from dev_lab.dev.rules import tracked_files

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from pathlib import Path

__all__ = ['RESTATED_MAX_SHARED', 'RESTATED_N', 'TREE_CHECKS', 'TreeCheck', 'applicable', 'declared', 'judge']

#: The restated-rules reading: shared 6-word runs, more than two of them convicts (the body's own controls).
RESTATED_N: Final = 6
RESTATED_MAX_SHARED: Final = 2
_TESTS: Final = 'tests/'
_RULES: Final = '.claude/rules/'


@dataclass(frozen=True)
class TreeCheck:
    """One row: where its population lives, how a finding is read and keyed, and the door a finding names."""

    applies: Callable[[Path], bool]
    population: Callable[[Path], Mapping[str, str]]
    findings: Callable[[str], dict[str, str]]  # text -> {key suffix: detail}
    remedy: str


def _tracked(root: Path, prefix: str, suffix: str) -> dict[str, str]:
    names = sorted(name for name in tracked_files(root) if name.startswith(prefix) and name.endswith(suffix))
    return {name: (root / name).read_text(encoding='utf-8') for name in names if (root / name).is_file()}


def _deny_reasons(root: Path) -> dict[str, str]:
    rows = json.loads((root / RULES_REL).read_text(encoding='utf-8'))
    return {row['name']: row['reason'] for row in rows}


def _parsed(source: str, *, words: tuple[str, ...], reader: Callable[[str], tuple[int, ...]]) -> dict[str, str]:
    """*reader*'s lines, parsing only a source that names one of *words*: every finding's AST reads one."""
    found = reader(source) if any(word in source for word in words) else ()
    return {'': ', '.join(f'line {line}' for line in found)} if found else {}


def _restated(text: str) -> dict[str, str]:
    counts = restated(text, n=RESTATED_N, max_shared=RESTATED_MAX_SHARED)
    return {f'::{rule}': f'restates {rule} ({count} shared {RESTATED_N}-word runs)' for rule, count in counts.items()}


def _relative(text: str) -> dict[str, str]:
    found = relative_interpreters(text)
    return {'': ' | '.join(line.strip() for line in found)} if found else {}


def _has(relative: str) -> Callable[[Path], bool]:
    return lambda root: (root / relative).exists()


def _has_python_tests(root: Path) -> bool:
    """A ``tests/`` tree holding Python: a JS-only ``tests/`` has no population for an AST reader."""
    return next((root / _TESTS).rglob('*.py'), None) is not None if (root / _TESTS).is_dir() else False


TREE_CHECKS: Final[dict[str, TreeCheck]] = {
    'platformskips': TreeCheck(
        _has_python_tests,
        partial(_tracked, prefix=_TESTS, suffix='.py'),
        partial(_parsed, words=('platform', 'os.name'), reader=platform_skips),
        'a platform skip runs on NO host; carry @pytest.mark.<os> instead (dev_lab.dev.famtests.platformskips)',
    ),
    'hostnode': TreeCheck(
        _has_python_tests,
        partial(_tracked, prefix=_TESTS, suffix='.py'),
        partial(_parsed, words=('node',), reader=host_node_uses),
        'run JS with dev_lab.dev.jsrun.run_js, the locked engine, never the host node (dev_lab.dev.famtests.hostnode)',
    ),
    'testleaks': TreeCheck(
        _has_python_tests,
        partial(_tracked, prefix=_TESTS, suffix='.py'),
        partial(_parsed, words=LEAK_WORDS, reader=leaks),
        'write under tmp_path (TemporaryDirectory at most), never mkdtemp/mkstemp/gettempdir, '
        'NamedTemporaryFile(delete=False) or a host root like /tmp, /var/tmp, C:/ (dev_lab.dev.famtests.testleaks)',
    ),
    'restatedrules': TreeCheck(
        _has(_RULES),
        partial(_tracked, prefix=_RULES, suffix='.md'),
        _restated,
        'cite the rule ID and keep only the local incident (dev_lab.dev.famtests.restatedrules)',
    ),
    'remedypaths': TreeCheck(
        _has(RULES_REL),
        _deny_reasons,
        _relative,
        'name the interpreter absolute or carry {python} for the engine to expand (dev_lab.dev.famtests.remedypaths)',
    ),
}


def declared(root: Path, row: str) -> tuple[str, ...]:
    """``[tool.dev_lab.<row>] declared`` in *root*'s manifest; no manifest or table is the empty set."""
    path = root / 'pyproject.toml'
    if not path.is_file():
        return ()
    entries = declared_table(tomllib.loads(path.read_text(encoding='utf-8')), row, {}).get('declared', [])
    if not isinstance(entries, list) or not all(isinstance(entry, str) for entry in entries):
        msg = f'[tool.dev_lab.{row}] declared must be a list of strings, not {entries!r}'
        raise AssertionError(msg)
    return tuple(entries)


def judge(root: Path, row: str) -> None:
    """Refuse an empty population, every undeclared finding, and every declared key with none left."""
    check = TREE_CHECKS[row]
    population = check.population(root)
    if not population:
        msg = f'{row}: the population under {root} read EMPTY, so a clean result would mean nothing'
        raise AssertionError(msg)
    found = {
        f'{where}{suffix}': detail
        for where, text in population.items()
        for suffix, detail in check.findings(text).items()
    }
    ledger = set(declared(root, row))
    problems = [f'{key}: {detail}' for key, detail in sorted(found.items()) if key not in ledger]
    problems += [
        f'{key}: declared in [tool.dev_lab.{row}] and no longer found -- delete it'
        for key in sorted(ledger - set(found))
    ]
    if problems:
        raise AssertionError('\n  '.join((f'{row}: {check.remedy}', *problems)))


def applicable(root: Path) -> dict[str, Callable[[Path], None]]:
    """Row name -> check, for every row whose population *root* holds."""
    return {row: partial(judge, row=row) for row, check in TREE_CHECKS.items() if check.applies(root)}
