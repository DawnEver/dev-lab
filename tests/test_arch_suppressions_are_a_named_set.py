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
#: RE-MEASURED 2026-09-17, when this repo adopted the family's 58-selector `select`: 62 sites, of
#: which 10 are the ``tests/**`` per-file ignores in ``pyproject.toml``. It was 14 the day before,
#: and the jump is the cost of the adoption rather than a loosening: 50 selector groups that had
#: never been asked anything here started asking, and every site below names which rule it silences,
#: on what source line, and why that one is allowed.
#:
#: THE PREVIOUS MEASUREMENT, KEPT: 2026-09-16 read 8 sites across 5 modules under ``src/``, 6 across
#: 4 modules under ``tests/`` (three source lines, two of which silence two rules each), and 0
#: per-file ignores in ``pyproject.toml``.
#:
#: THE ``src/`` COUNT ALREADY SAID 5 MODULES WHILE THE TABLE HELD 4, and that is worth a line here.
#: ``3cce383`` added a marker in ``docsite.py`` and one in ``test_dev_githooks.py`` and declared
#: neither, so this guard had been red since -- found on 2026-09-16 by a verify for an unrelated fix.
#: The COUNT was right and the TABLE was wrong, the direction this file's own docstring warns about,
#: so both rows are declared below rather than any number being edited down to meet the tree.
ALLOWED: Final[dict[Site, str]] = {
    (
        'src/lab_commons/dev/docsite.py',
        'arg-type',
        'run(pdoc_argv(modules, out_dir, **options), cwd=root)',
    ): 'pdoc_argv takes `**options: object` so any caller option reaches it; run() is typed on str',
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
        'src/lab_commons/structured.py',
        'ARG001',
        'def redact_secrets_processor(logger: object, method_name: str, event_dict: dict) -> dict:',
    ): 'structlog fixes the processor signature; the unused parameters are the protocol, not dead code',
    (
        'src/lab_commons/structured.py',
        'PLW0603',
        'global _structlog_configured',
    ): 'one-shot process-wide structured-logging configuration, the same idempotence flag as log.py',
    (
        'src/lab_commons/dev/durations.py',
        'PLC0415',
        'from xdist import dsession',
    ): 'an OPTIONAL scheduler: a top-level import would make the whole module unimportable without it',
    (
        'tests/test_dev_githooks.py',
        'PLC0415',
        'import os',
    ): 'one helper needs the AMBIENT environment; a module-level import reads a monkeypatched one',
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
        'tests/test_dev_doorcensus.py',
        'arg-type',
        'return DoorRow(why=_WHY, **kwargs)',
    ): 'one local builder supplies the shared reason and forwards its dict[str, object] fields verbatim',
    (
        'tests/test_famtests_injectedwidth.py',
        'arg-type',
        'assert_widths_are_the_named_set(scan, **(kwargs | over))',
    ): 'one local helper builds the keyword set as dict[str, object] so a case can override any one',
    (
        'tests/test_famtests_injectedwidth.py',
        'arg-type',
        'scan = real(paths, **kwargs)',
    ): 'a monkeypatch stand-in takes the shipped call untyped and forwards it verbatim to the real one',
    (
        'tests/test_famtests_trackedcjk.py',
        'ANN003',
        'def _forgetful(paths, **kwargs):',
    ): 'the same stand-in shape: annotating it would assert a signature the patch is not claiming',
    (
        'tests/test_famtests_trackedcjk.py',
        'ANN202',
        'def _forgetful(paths, **kwargs):',
    ): 'its return is whatever the shipped scanner returns, so a written return type would be a second claim',
    (
        'tests/test_famtests_upperbounds.py',
        'ARG005',
        "lambda spec, *, ecosystem: 'everything is a bound' if spec.strip() else None,",
    ): 'the planted control is CONVICT-EVERYTHING, so ignoring `ecosystem` is the doctoring under test',
    (
        'tests/test_famtests_upperbounds.py',
        'arg-type',
        'assert_no_undeclared_upper_bound(scan, **(kwargs | over))',
    ): 'the same overridable dict[str, object] keyword set as injectedwidth, for the same reason',
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
    (
        'pyproject.toml',
        'ANN001',
        'tests/**',
    ): "a test's parameters are fixtures; the type is declared once ON the fixture, and ANN2xx is not waived",
    (
        'pyproject.toml',
        'ARG002',
        'tests/**',
    ): 'a fixture requested for its SIDE EFFECT is used by being requested; dropping the parameter drops the setup',
    (
        'pyproject.toml',
        'D101',
        'tests/**',
    ): 'a test class is a named grouping; the name and the methods below it are the prose',
    (
        'pyproject.toml',
        'D102',
        'tests/**',
    ): 'a test method name in this suite is already a sentence, and a docstring would restate it',
    (
        'pyproject.toml',
        'D103',
        'tests/**',
    ): 'the same for a module-level test function',
    (
        'pyproject.toml',
        'INP001',
        'tests/**',
    ): 'tests/ is rootdir-relative by design; an __init__.py here would shadow the package under test',
    (
        'pyproject.toml',
        'N802',
        'tests/**',
    ): 'this suite SHOUTS the load-bearing word in 64 test names, and lower-casing them deletes the emphasis',
    (
        'pyproject.toml',
        'PLR2004',
        'tests/**',
    ): 'the literal in an assertion IS the expected value; hoisting it to a constant hides what is asserted',
    (
        'pyproject.toml',
        'S101',
        'tests/**',
    ): 'assert is the test vocabulary; src/ carries S101 unwaived',
    (
        'pyproject.toml',
        'SLF001',
        'tests/**',
    ): 'a test that cannot read a private member cannot pin a private invariant',
    (
        'src/lab_commons/dev/dep.py',
        'PLW0108',
        'key: Callable[[], str] = field(default=lambda: current_env_key())',
    ): 'the lambda is a FORWARD reference: current_env_key is defined below this dataclass',
    (
        'src/lab_commons/dev/quantity_values.py',
        'BLE001',
        'except Exception:',
    ): 'folding every pint failure into one answer IS the contract; one typo must not crash the scan',
    (
        'src/lab_commons/dev/units.py',
        'C901',
        'def _python_signatures(text: str) -> Iterator[_Signature]:',
    ): 'one branch per AST node kind read; splitting it hides that the set is exhaustive',
    (
        'src/lab_commons/dev/verdict.py',
        'S105',
        "PASS = 'pass'",
    ): 'a verdict name, not a credential: S105 matches the word PASS in an enum member',
    (
        'src/lab_commons/dev/verify.py',
        'S607',
        "['git', 'rev-parse', '--show-toplevel'],",
    ): 'git is resolved through PATH on purpose; an absolute path is wrong on every other box',
    (
        'src/lab_commons/em.py',
        'N802',
        'def Q_list2array(',
    ): "pint's own Q_ spelling, and wdg-lab imports this name; a rename is a cross-repo move",
    (
        'src/lab_commons/em.py',
        'N802',
        'def array2list_2Dpoint(',
    ): 'the same: 2D is the domain spelling and wdg-lab imports this name',
    (
        'src/lab_commons/em.py',
        'N802',
        'def is_equal_2DPoint(',
    ): 'the same: 2DPoint is the domain spelling and wdg-lab imports this name',
    (
        'src/lab_commons/em.py',
        'N803',
        'Q_list: list[PintQuantityType],',
    ): "pint's Q_ prefix on a parameter that carries a quantity rather than a number",
    (
        'src/lab_commons/em.py',
        'N803',
        'Q_unit: str | Unit,',
    ): 'the same prefix on the unit that goes with it',
    (
        'src/lab_commons/multiprocess.py',
        'BLE001',
        'except Exception as e:',
    ): 'a worker may raise anything; tagging it ERROR is the report this path exists to produce',
    (
        'src/lab_commons/multiprocess.py',
        'C901',
        'def __init__(',
    ): 'a flat chain of "if this knob is None take the declared default", one branch per knob',
    (
        'src/lab_commons/multiprocess.py',
        'PLR0912',
        'def __init__(',
    ): 'the same chain counted as branches; merging them would hide which knob defaulted',
    (
        'src/lab_commons/multiprocess.py',
        'C901',
        'def run(self) -> list[dict]:',
    ): 'one branch per pool-task outcome (ok / timeout / error / retry), each naming its own report',
    (
        'src/lab_commons/multiprocess.py',
        'PLR0912',
        'def run(self) -> list[dict]:',
    ): 'the same outcomes counted as branches',
    (
        'src/lab_commons/paths.py',
        'DTZ005',
        "return datetime.datetime.now().strftime(r'%H-%M-%S')",
    ): 'a run folder is read by a human on the box that wrote it, so LOCAL wall clock is the right reading',
    (
        'src/lab_commons/paths.py',
        'DTZ005',
        'now = datetime.datetime.now()',
    ): 'the date half of the same stamp, for the same reason',
    (
        'src/lab_commons/proc.py',
        'FBT003',
        'handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)',
    ): 'bInheritHandle is positional in the Win32 signature; ctypes cannot take it by keyword',
    (
        'src/lab_commons/proc.py',
        'FBT003',
        'handle = kernel32.OpenProcess(_PROCESS_TERMINATE, False, pid)',
    ): 'the same Win32 signature, called with the terminate right',
    (
        'src/lab_commons/proc.py',
        'N801',
        'class _PROCESS_MEMORY_COUNTERS(ctypes.Structure):',
    ): 'the name MIRRORS the psapi struct, so a reader can find it in the Win32 documentation',
    (
        'src/lab_commons/proc.py',
        'PLR0911',
        'def pid_alive(pid: int) -> bool:',
    ): 'one return per platform branch, each naming its own answer rather than falling through',
    (
        'src/lab_commons/resources.py',
        'SLF001',
        'clock=self._broker._creation_clock,',
    ): 'one module, one owner: the grant and its broker are written and changed together',
    (
        'src/lab_commons/resources.py',
        'SLF001',
        'grant._release()',
    ): 'the same pair: release is private BECAUSE only this context manager may call it',
    (
        'src/lab_commons/units.py',
        'N801',
        'class BaseModel_with_q(BaseModel):',
    ): 'imported BY NAME in wdg-lab; a rename is a cross-repo move, not a lint fix',
    (
        'tests/test_dev_shadow_build.py',
        'ARG001',
        'def _fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess:',
    ): 'a stand-in for maturin: it must ACCEPT the real call and ignore it',
    (
        'tests/test_dev_shadow_build.py',
        'ARG001',
        'def _fake_run(argv, *args: object, **kwargs: object) -> subprocess.CompletedProcess:',
    ): 'the same stand-in, in the arm that reads argv and ignores the rest',
    (
        'tests/test_dev_shadow_build.py',
        'ARG001',
        'def _fake_time_once(probe, shadow, **kwargs: object) -> float:',
    ): 'the ORDER of the arms is the whole subject; the timing arguments are deliberately ignored',
    (
        'tests/test_em.py',
        'N806',
        "Q_0m = Q_(0, 'm')",
    ): "pint's Q_<magnitude><unit> spelling for a quantity literal, which wdg-lab also imports by name",
    (
        'tests/test_em.py',
        'N806',
        "Q_1m = Q_(1, 'm')",
    ): 'the same spelling, one metre',
    (
        'tests/test_em.py',
        'N806',
        "Q_1000mm = Q_(1000, 'mm')",
    ): 'the same spelling, the millimetre twin it is compared against',
    (
        'tests/test_em.py',
        'N806',
        "Q_180deg = Q_(180, 'deg')",
    ): 'the same spelling, in degrees',
    (
        'tests/test_em.py',
        'N806',
        "Q_pi_rad = Q_(np.pi, 'rad')",
    ): 'the same spelling, in radians',
    (
        'tests/test_the_config_census_is_measured.py',
        'S608',
        "assert ruff_select(root) == set(CONSUMER_SELECT), f'{repo}: select diverged from the family 58'",
    ): "the word 'select' here names a ruff selector list; there is no database in this repo",
    (
        'tests/test_two_repos_cannot_both_hold_the_box.py',
        'S607',
        "subprocess.run(['git', 'init', '-q'], cwd=root, check=True, capture_output=True)",
    ): 'git through PATH, the same deliberate resolution as verify.project_root',
    (
        'tests/test_dev_rules.py',
        'S607',
        "['git', '-C', str(tmp_path), 'init'],",
    ): 'git through PATH in a scratch checkout the test builds; an absolute path is wrong on every box',
    (
        'tests/test_dev_rules.py',
        'S607',
        "['git', '-C', str(tmp_path), 'add', '-A'],",
    ): 'the same scratch checkout, staging the files the guard is then asked to read',
    (
        'src/lab_commons/dev/collectscope.py',
        'S607',
        "['git', '-C', str(root), 'cat-file', '--batch'],",
    ): 'git through PATH, reading 2632 blobs in ONE process where a per-file show is 2632',
    (
        'src/lab_commons/dev/collectscope.py',
        'S607',
        "['git', '-C', str(root), *args],",
    ): 'the same resolution for the ls-tree that lists the blobs that batch then reads',
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
    live = pyproject_sites(ROOT / 'pyproject.toml')
    assert {glob for _, _, glob in live} == {'tests/**'}, f'a second per-file glob appeared: {live}'
    assert len(live) == 10, f'measured 2026-09-17, when the 58-selector set was adopted: {live}'

    bare = tmp_path / 'bare.py'
    bare.write_text(
        'x: int = "s"  # ' + 'type: ignore\ndef f():  # ' + 'pragma: no cover\n    ...\n',
        encoding='utf-8',
    )
    codes = {code for _, code, _ in python_sites((bare,))}
    assert codes == {'type-ignore:ALL', 'no-cover'}, codes
