"""THE SUPPRESSION RATCHET: every silenced check is a NAMED waiver carrying its reason.

A suppression is a check that was asked a question and told not to answer. That is sometimes right --
three of the entries below are unavoidable -- but it is never free, and the failure mode is that the
list only ever grows: each new one looks like the last one, nobody can tell which, and the checks
this repo advertises quietly stop covering the code it ships to four other repos.

THE PIN IS A NAMED SET, NOT A COUNT, and that is the point of the whole module. An integer pin cannot
say WHICH row moved -- a suppression removed and a suppression added net to the same digit -- so the
honest-looking repair when it disagrees is to edit the number, which is how a pin ends up documenting
whatever the tree happens to contain. A named set forces the edit to say what changed.

THE RATCHET HAS TWO SIDES. An undeclared suppression reds, and a declared suppression that has
DISAPPEARED reds too. Without the second half nothing ever comes off the list, and a waiver nothing
uses is exactly as wrong as an undeclared one: it asserts a constraint on code that no longer exists.

THE ANCHOR IS THE SUPPRESSED SOURCE TEXT, NOT A LINE NUMBER. A line number churns on every unrelated
edit above it, and a pin that reds for an unrelated reason is a pin that gets deleted. The code on
the line -- comment stripped -- does not move when something above it does, it distinguishes two
suppressions of the SAME rule inside one function (``multiprocess.py`` has exactly that pair), and it
lets a reader of the pin see what is being waived without opening the file.

THE REASON LIVES IN THE DECLARATION, not on the source line. Two reasons for that call: a per-file
``ruff`` ignore in ``pyproject.toml`` has no source line to carry a comment, so only the declaration
can hold every waiver's reason in one shape; and a trailing comment is prose no tool consults, while
the dict value below is refused when it is empty. A source-line comment stays welcome -- it is just
not the thing under guard.

SCOPE is ``src/`` and ``tests/`` -- the two corpora every sibling guard uses, and this repo has no
``scripts/`` tree -- plus ``pyproject.toml``, where a suppression can hide without appearing in any
Python file at all.
"""

from __future__ import annotations

import io
import re
import tokenize
from pathlib import Path
from typing import Final

import rtoml
from _arch_corpus import ROOT, SOURCE_FLOOR, TEST_FLOOR, assert_floor, rel, source_modules, suite_modules

#: A suppression site: ``(repo-relative path, rule code, anchor)``. The anchor is the suppressed
#: source text with the comment stripped, or -- for a whole-line comment and for a ``pyproject.toml``
#: per-file ignore -- the comment text and the file glob respectively.
Site = tuple[str, str, str]

#: EVERY suppression this repo allows, each with the reason it is allowed to exist.
#: MEASURED 2026-09-16: 8 sites across 5 modules under ``src/``, 5 across 3 modules under ``tests/``
#: (three source lines, two of which silence two rules each), and 0 per-file ignores in
#: ``pyproject.toml``.
ALLOWED: Final[dict[Site, str]] = {
    (
        'src/lab_commons/log.py',
        'PLW0603',
        'global _active_logger',
    ): 'one-shot process-wide logging configuration: the module-level flag IS the idempotence',
    (
        'src/lab_commons/multiprocess.py',
        'PLC0415',
        'from pint import set_application_registry',
    ): 'runs in a freshly spawned worker; the registry installed must be the one THAT process imports',
    (
        'src/lab_commons/multiprocess.py',
        'PLC0415',
        'from lab_commons.units import ureg',
    ): 'same process boundary: a top-level import would bind the parent module objects at spawn time',
    (
        'src/lab_commons/paths.py',
        'PLW0603',
        'global _run_stamp',
    ): 'the per-run timestamp is memoized once per process so every artifact shares one run folder',
    (
        'src/lab_commons/paths.py',
        'PLW0603',
        'global _run_date',
    ): 'the per-run date is memoized the same way, so a run straddling midnight keeps one folder',
    (
        'src/lab_commons/resources.py',
        'PLC0415',
        'from lab_commons.proc import pid_alive',
    ): 'the liveness probe is pulled in only when a stale lock is examined, not on every resources import',
    (
        'src/lab_commons/structured.py',
        'ARG001',
        'def redact_secrets_processor(logger, method_name, event_dict):',
    ): 'structlog fixes the processor signature; the unused parameters are the protocol, not dead code',
    (
        'src/lab_commons/structured.py',
        'PLW0603',
        'global _structlog_configured',
    ): 'one-shot process-wide structured-logging configuration, the same idempotence flag as log.py',
    (
        'tests/test_em.py',
        'F401',
        'import lab_commons.units',
    ): 'the import IS the measurement -- it runs after a sys.modules pop, and binds a name nothing uses',
    (
        'tests/test_em.py',
        'PLC0415',
        'import lab_commons.units',
    ): 'the same line: the measurement only means anything if the import happens inside the test body',
    (
        'tests/test_structured.py',
        'TRY301',
        'raise ValueError(boom)',
    ): 'an intentional raise inside try, to populate the exc_info the test then reads off the record',
    (
        'tests/test_units.py',
        'F401',
        'import lab_commons.units',
    ): 'the import IS the measurement, run after a sys.modules pop; the name is deliberately unused',
    (
        'tests/test_units.py',
        'PLC0415',
        'import lab_commons.units',
    ): 'the same line: a module-level import would measure collection time instead of the call',
}

_NOQA = re.compile(r'\bnoqa\b\s*:?\s*([^#]*)')
_TYPE_IGNORE = re.compile(r'\btype\s*:\s*ignore\s*(?:\[([^\]]*)\])?')
_PRAGMA = re.compile(r'\bpragma\s*:\s*no\s+cover\b')
_RULE_CODE = re.compile(r'\b[A-Z]{1,6}[0-9]{3,4}\b')


def _codes(comment: str) -> tuple[str, ...]:
    """Every rule code a comment silences. A marker naming none silences EVERYTHING: ``...:ALL``."""
    out: list[str] = []
    noqa = _NOQA.search(comment)
    if noqa is not None:
        out.extend(_RULE_CODE.findall((noqa.group(1) or '').split('--')[0]) or ['noqa:ALL'])
    ignore = _TYPE_IGNORE.search(comment)
    if ignore is not None:
        out.extend(re.findall(r'[\w-]+', ignore.group(1) or '') or ['type-ignore:ALL'])
    if _PRAGMA.search(comment) is not None:
        out.append('no-cover')
    return tuple(out)


def python_sites(paths: tuple[Path, ...]) -> tuple[Site, ...]:
    """Every suppression in *paths*, read from real COMMENT tokens -- pure over its argument.

    Tokenized rather than grepped on purpose: a marker inside a string literal is data, not a
    suppression, and this module is itself inside the corpus it scans.
    """
    out: list[Site] = []
    for path in paths:
        text = path.read_text(encoding='utf-8')
        lines = text.splitlines()
        for token in tokenize.generate_tokens(io.StringIO(text).readline):
            if token.type != tokenize.COMMENT:
                continue
            codes = _codes(token.string)
            if not codes:
                continue
            anchor = lines[token.start[0] - 1][: token.start[1]].strip() or token.string.strip()
            out.extend((_name(path), code, anchor) for code in codes)
    return tuple(out)


def pyproject_sites(pyproject: Path) -> tuple[Site, ...]:
    """Every per-file ``ruff`` ignore -- a suppression that appears in no Python file at all."""
    lint = rtoml.load(pyproject).get('tool', {}).get('ruff', {}).get('lint', {})
    tables = (lint.get('per-file-ignores') or {}, lint.get('extend-per-file-ignores') or {})
    return tuple((_name(pyproject), code, glob) for t in tables for glob, codes in t.items() for code in codes)


def undeclared_and_orphaned(sites: tuple[Site, ...], declared: dict[Site, str]) -> tuple[str, ...]:
    """BOTH SIDES OF THE RATCHET, plus the empty-reason refusal -- pure over its arguments."""
    live, pinned = set(sites), set(declared)
    problems = [
        f'UNDECLARED suppression {s} -- add it with the reason it is allowed to exist' for s in sorted(live - pinned)
    ]
    problems += [
        f'ORPHANED waiver {s} -- the suppression is gone; delete the entry in the same edit'
        for s in sorted(pinned - live)
    ]
    problems += [
        f'REASONLESS waiver {s} -- a bare entry says a suppression exists, not why it may'
        for s, why in sorted(declared.items())
        if not why.strip()
    ]
    return tuple(problems)


def _name(path: Path) -> str:
    try:
        return rel(path)
    except ValueError:
        return path.name


def test_every_suppression_is_declared_and_every_declaration_is_used() -> None:
    """THE CHECK, over this repo's source, its suite and its ``pyproject.toml``."""
    source, suite = source_modules(), suite_modules()
    assert_floor(len(source), SOURCE_FLOOR, 'suppression (src)')
    assert_floor(len(suite), TEST_FLOOR, 'suppression (tests)')
    sites = python_sites(source + suite) + pyproject_sites(ROOT / 'pyproject.toml')
    problems = undeclared_and_orphaned(sites, ALLOWED)
    assert problems == (), 'the suppression ratchet moved:\n  ' + '\n  '.join(problems)


def test_a_planted_suppression_and_a_planted_orphan_are_refused(tmp_path: Path) -> None:
    """THE PLANTED CONTROL, BOTH DIRECTIONS, through the REAL scanner, past a clean file."""
    marker = '# ' + 'noqa: F401'
    dirty = tmp_path / 'dirty.py'
    dirty.write_text(f'import os  {marker}\n', encoding='utf-8')
    quoted = tmp_path / 'quoted.py'
    quoted.write_text(f'MARKER = "{marker}"\n', encoding='utf-8')
    found = python_sites((dirty, quoted))
    assert found == (('dirty.py', 'F401', 'import os'),), f'the comment counts and the string literal does not: {found}'

    undeclared = undeclared_and_orphaned(found, {})
    assert any('UNDECLARED' in p for p in undeclared), undeclared

    orphaned = undeclared_and_orphaned((), {('gone.py', 'F401', 'import os'): 'stale'})
    assert any('ORPHANED' in p for p in orphaned), orphaned

    reasonless = undeclared_and_orphaned(found, {found[0]: '   '})
    assert any('REASONLESS' in p for p in reasonless), reasonless
    assert undeclared_and_orphaned(found, {found[0]: 'a real reason'}) == ()


def test_a_planted_per_file_ignore_and_a_planted_bare_marker_are_seen(tmp_path: Path) -> None:
    """The two hiding places a comment scan of ``src/`` alone would miss."""
    cfg = tmp_path / 'pyproject.toml'
    cfg.write_text('[tool.ruff.lint.per-file-ignores]\n"tests/*" = ["F401", "E501"]\n', encoding='utf-8')
    assert pyproject_sites(cfg) == (('pyproject.toml', 'F401', 'tests/*'), ('pyproject.toml', 'E501', 'tests/*'))
    assert pyproject_sites(ROOT / 'pyproject.toml') == (), 'measured 2026-09-16: this repo declares none'

    bare = tmp_path / 'bare.py'
    bare.write_text(
        'x: int = "s"  # ' + 'type: ignore\ndef f():  # ' + 'pragma: no cover\n    ...\n',
        encoding='utf-8',
    )
    codes = {code for _, code, _ in python_sites((bare,))}
    assert codes == {'type-ignore:ALL', 'no-cover'}, codes
