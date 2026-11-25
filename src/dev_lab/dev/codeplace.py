"""Where source code may live, and where nothing unclaimed may sit -- one scan, every repo.

Migrated 2026-09-25 from consumer-a, where a probe, a patch script and 132 one-off drivers had
accumulated under ``output/logs/...``: untracked, untested, and never reaching the entry point the
repo ships. One of them patched ``src/`` instead of the function it was changing being edited.

THREE RULES OVER ONE MAP; this module holds the map and the first, the other two are their own modules:

* ``CODE-IN-CODE-ROOTS`` -- a source file (:data:`CODE_SUFFIXES`) lives only under a root the repo
  DECLARES for code. An ALLOW-list, not a deny-list: a new directory is refused until it is added
  on purpose, so the next ``output/`` cannot happen silently. The walk is of the FILESYSTEM, never
  ``git ls-files``, because the defect is precisely an untracked file.
* ``SCRATCH-IS-NEVER-COMMITTED`` -- the one-off sink this map declares: visible to git, never
  committed beyond its README (nothing at all under ``scratch_anchor = false``), left by promotion
  into ``src/`` with tests or by deletion: :mod:`dev_lab.dev.scratch`.
* ``STRAY-FILE-REFUSED`` -- an untracked, non-ignored file outside the declared stray roots is a defect the
  moment it appears: :mod:`dev_lab.dev.strays`, which reads ``stray_roots`` and ``retired`` off this map.

THE PLACEMENT MAP IS THE FAMILY'S, THE EXTRA ROOTS ARE THE REPO'S (user ruling 2026-10-02). Every
file kind has ONE home, :data:`FAMILY_HOMES`; the homes that hold code are :data:`FAMILY_CODE_ROOTS`.
A repo declares ONLY what it adds, in ONE place -- the top level of its root :data:`LAYOUT_FILE`
(``layout.toml``; user ruling 2026-11-24), read by :func:`placement_table` and :func:`declared_placement`. Its
``[layout]`` table is :mod:`dev_lab.dev.layout`'s. The retired ``[tool.dev_lab.placement]`` of ``pyproject.toml``
is refused by name with its migration (FORMATS-MIGRATE-ONCE)::

    # layout.toml
    code_roots = ['rust/', 'attic/']        # the repo's own roots, beyond the family's
    pruned_paths = ['.claude/worktrees']    # other checkouts inside this one, judged by their own run
    stray_roots = []                        # where an untracked file may sit, beyond scratch
    scratch = 'scratch/'                    # the one-off sink; the family's home when omitted
    max_age = "3 d"                         # when the SessionStart notice starts naming a one-off
    scratch_anchor = true                   # false: no tracked README, nothing under scratch is tracked
    retired = []                            # files a tool this repo uses retired (dev_lab.dev.retiredfiles)

ONE TABLE, ONE PREDICATE, TWO CALLERS. The architecture test calls :func:`declared_misplaced` over
the tree; the ``PreToolUse`` hook (``python -m dev_lab.dev.codeplace``, wired on
``Write|Edit|MultiEdit``) calls :func:`refuse_write` on the one path about to be written. Both
decide through :func:`admits` over the same declaration, so the hook cannot refuse what the test
admits or the reverse -- the second copy of the rule a hand-written hook would be.

THE CLI: ``python -m dev_lab.dev.codeplace`` is the write hook, its only mode.
"""

from __future__ import annotations

import dataclasses
import importlib
import json
import os
import sys
import tomllib
from collections.abc import Iterable
from pathlib import Path, PurePosixPath
from types import ModuleType
from typing import Final, TextIO

from lab_commons.log import emit
from lab_commons.quantity import QuantityRefused, Renamed, parse, refuse_renamed

from dev_lab.dev import gitdirs
from dev_lab.dev.consentguard import refuse_write as refuse_consent_write
from dev_lab.dev.family import declared_table
from dev_lab.dev.frozen import refuse_write as refuse_frozen_write
from dev_lab.dev.ledgerguard import refuse_write as refuse_ledger_write
from dev_lab.dev.machineguard import refuse_write as refuse_machine_file_write
from dev_lab.dev.outputcode import refuse_code_in_output
from dev_lab.dev.priorart import refuse_new_module
from dev_lab.dev.reportplace import refuse_report
from dev_lab.dev.retiredfiles import RetiredFile, declared_retired
from dev_lab.dev.writeroots import refuse_outside_tree

__all__ = [
    'ARCHIVED_SEGMENTS',
    'ARCHIVE_DIRECTORY',
    'CODE_SUFFIXES',
    'FAMILY_CODE_ROOTS',
    'FAMILY_HOMES',
    'FAMILY_STRAY_ROOTS',
    'PRUNED_NAMES',
    'SCRATCH_MAX_AGE',
    'Placement',
    'PlacementNotDeclared',
    'admits',
    'checkout_root',
    'declared_misplaced',
    'declared_placement',
    'is_archived',
    'main',
    'misplaced_code',
    'placement_table',
    'refuse_write',
]

#: The file suffixes that are SOURCE CODE -- a language a machine executes or compiles.
CODE_SUFFIXES = frozenset({
    '.py', '.pyx', '.pyi', '.rs', '.sh', '.bash', '.ps1', '.psm1', '.bat', '.cmd', '.vbs',
    '.js', '.mjs', '.cjs', '.ts', '.m', '.lua', '.jl', '.c', '.cc', '.cpp', '.h', '.hpp',
})  # fmt: skip

#: Directories never walked, matched by NAME at any depth: tool state, environments and build
#: output, none of it written by a person.
PRUNED_NAMES = frozenset({
    '.git', '.venv', '.venvs', 'venv', 'node_modules', 'target', '__pycache__', '.pytest_cache', '.ruff_cache',
    '.mypy_cache',
    # the cluster run's record, written INTO the tree it judges (lab_commons.hpc: streams, env.sh, job.sh)
    '.lab-ci', '.lab-hpc',
})  # fmt: skip

#: THE FAMILY PLACEMENT MAP: every file kind and its ONE home, repo-relative POSIX.
FAMILY_HOMES: dict[str, str] = {
    'product source': 'src/',
    'tests': 'tests/',
    'one-off experiment, probe or verification': 'scratch/',
    'memory, and one-offs archived before 2026-10-22': '.claude/memory/',
    'docs': 'docs-src/',
    'artifacts': 'output/logs/',
}

#: The family homes that hold CODE; docs and artifacts are homes, but never for a source file.
FAMILY_CODE_ROOTS: tuple[str, ...] = tuple(
    FAMILY_HOMES[kind]
    for kind in (
        'product source',
        'tests',
        'one-off experiment, probe or verification',
        'memory, and one-offs archived before 2026-10-22',
    )
)

#: Where an untracked file may sit in every repo: the family's scratch home, nothing else.
FAMILY_STRAY_ROOTS: tuple[str, ...] = (FAMILY_HOMES['one-off experiment, probe or verification'],)

#: The family default for ``max_age``, in seconds (:mod:`dev_lab.dev.scratch` reads it off the placement): 3 days.
SCRATCH_MAX_AGE = 3 * 86400.0
#: Unit-suffixed keys retired by the 2026-11-25 ruling (a value carries its unit), refused with their new line.
_UNIT_RENAMED: Final = {'max_age_days': Renamed('max_age', 'd')}

#: The directory under a day's memory that held archived one-offs until that exit was retired
#: (2026-10-22); what is already there stays archived history.
ARCHIVE_DIRECTORY = 'attachments'
#: Segments whose tree is read-only archived code at ANY depth: a migrated repo's ``attic/`` and an
#: ``archived/`` tree. With a memory day's :data:`ARCHIVE_DIRECTORY` these are every archive a scan
#: skips; :func:`is_archived` is the one reading, so no scan keeps its own copy of the set.
ARCHIVED_SEGMENTS = frozenset({'attic', 'archived'})
#: Where a repo declares its placement and its layout: this ONE root file (user ruling 2026-11-24).
LAYOUT_FILE = 'layout.toml'
#: The retired home of the placement, refused by name (FORMATS-MIGRATE-ONCE).
_RETIRED = '[tool.dev_lab.placement] of pyproject.toml'


def admits(rel: str, code_roots: tuple[str, ...]) -> bool:
    """THE ONE PREDICATE: may repo-relative POSIX *rel* live where it is? A non-code file always may."""
    return Path(rel).suffix.lower() not in CODE_SUFFIXES or rel.startswith(code_roots)


def misplaced_code(root: Path, *, code_roots: Iterable[str], pruned_paths: Iterable[str] = ()) -> list[str]:
    """Every source file under *root* that no *code_roots* prefix admits, repo-relative POSIX, sorted.

    Args:
        root: the tree to walk.
        code_roots: repo-relative POSIX prefixes where code may live, e.g. ``'src/'``.
        pruned_paths: repo-relative directories not walked at all -- another checkout's worktrees,
            which are judged by their own run.

    Raises:
        ValueError: no code roots -- a scan that admits nothing refuses every repo, and one that is
            handed an empty list by mistake must not read as a verdict.

    """
    roots = tuple(code_roots)
    if not roots:
        msg = 'misplaced_code needs the code roots this repo declares; an empty allow-list refuses everything'
        raise ValueError(msg)
    skip = {p.strip('/') for p in pruned_paths}
    found: list[str] = []
    for current, dirs, files in os.walk(root):
        rel_dir = Path(current).relative_to(root).as_posix()
        dirs[:] = [d for d in dirs if d not in PRUNED_NAMES and (d if rel_dir == '.' else f'{rel_dir}/{d}') not in skip]
        for name in files:
            rel = name if rel_dir == '.' else f'{rel_dir}/{name}'
            if not admits(rel, roots):
                found.append(rel)
    return sorted(found)


class PlacementNotDeclared(LookupError):
    """A repo's ``layout.toml`` is absent, unreadable or not the declared shape, or the retired table remains."""


def placement_table(root: Path) -> dict | None:
    """*root*'s :data:`LAYOUT_FILE` as a table; ``None`` when the checkout has none.

    Raises:
        PlacementNotDeclared: the file is unreadable or not TOML, or ``pyproject.toml`` still holds the retired
            ``[tool.dev_lab.placement]`` -- refused by name with its migration, never read as a second path.

    """
    try:
        manifest = tomllib.loads((root / 'pyproject.toml').read_text(encoding='utf-8'))
    except (OSError, tomllib.TOMLDecodeError):
        manifest = {}
    if declared_table(manifest, 'placement') is not None:
        msg = (
            f'{root / "pyproject.toml"} still holds {_RETIRED}: the placement and the layout live in {root.name}/'
            f'{LAYOUT_FILE} (user ruling 2026-11-24). Migrate ONCE (FORMATS-MIGRATE-ONCE): move each key of '
            f'[tool.dev_lab.placement] to the top level of {LAYOUT_FILE}, its [tool.dev_lab.placement.layout] rows '
            f'under [layout], and delete the table from pyproject.toml'
        )
        raise PlacementNotDeclared(msg)
    path = root / LAYOUT_FILE
    try:
        text = path.read_text(encoding='utf-8')
    except FileNotFoundError:
        return None
    except OSError as exc:
        msg = f'{path} is not readable: {exc}'
        raise PlacementNotDeclared(msg) from exc
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        msg = f'{path} is not TOML: {exc}'
        raise PlacementNotDeclared(msg) from exc


@dataclasses.dataclass(frozen=True)
class Placement:
    """A repo's placement: code roots, paths not walked, stray roots, scratch lifecycle, and its retired files."""

    code_roots: tuple[str, ...]
    pruned_paths: tuple[str, ...] = ()
    stray_roots: tuple[str, ...] = FAMILY_STRAY_ROOTS
    scratch: str = FAMILY_STRAY_ROOTS[0]
    max_age: float = SCRATCH_MAX_AGE  # seconds
    retired: tuple[RetiredFile, ...] = ()
    scratch_anchor: bool = True


def _strings(table: dict, key: str, manifest: Path) -> tuple[str, ...]:
    value = table.get(key, [])
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        msg = f'{key} in {manifest} is {value!r}; it must be a list of repo-relative POSIX paths'
        raise PlacementNotDeclared(msg)
    return tuple(value)


def declared_placement(root: Path) -> Placement:
    """The placement *root* declares: :data:`FAMILY_CODE_ROOTS` plus its own ``code_roots``.

    Raises:
        PlacementNotDeclared: no manifest, no table, or a key that is not a list of strings. An
            adopter's test calls this, so an undeclared repo is a red rather than a vacuous green.

    """
    manifest = root / LAYOUT_FILE
    table = placement_table(root)
    if table is None:
        msg = f'{root} has no {LAYOUT_FILE}; add it, even empty, to adopt the family placement map'
        raise PlacementNotDeclared(msg)
    extra = _strings(table, 'code_roots', manifest)
    scratch = table.get('scratch', FAMILY_STRAY_ROOTS[0])
    if not isinstance(scratch, str) or not scratch.strip('/'):
        msg = f'scratch in {manifest} is {scratch!r}; it must be one repo-relative POSIX directory'
        raise PlacementNotDeclared(msg)
    try:
        refuse_renamed(f'{manifest}:', table, _UNIT_RENAMED)
        age = parse(f'{manifest}: max_age', table['max_age'], 'duration', positive=True) if 'max_age' in table else None
    except QuantityRefused as bad:
        raise PlacementNotDeclared(str(bad)) from bad
    age = SCRATCH_MAX_AGE if age is None else age
    anchor = table.get('scratch_anchor', True)
    if not isinstance(anchor, bool):
        msg = f'scratch_anchor in {manifest} is {anchor!r}; it must be true (a tracked README) or false'
        raise PlacementNotDeclared(msg)
    try:
        retired = declared_retired(table.get('retired', []))
    except ValueError as exc:
        msg = f'{manifest}: {exc}'
        raise PlacementNotDeclared(msg) from exc
    scratch = f'{scratch.strip("/")}/'
    return Placement(
        tuple(dict.fromkeys((*FAMILY_CODE_ROOTS, scratch, *extra))),
        _strings(table, 'pruned_paths', manifest),
        (scratch, *_strings(table, 'stray_roots', manifest)),
        scratch,
        float(age),
        retired,
        anchor,
    )


def declared_misplaced(root: Path) -> list[str]:
    """:func:`misplaced_code` over *root* with the placement *root* declares -- the adopter's scan."""
    placement = declared_placement(root)
    return misplaced_code(root, code_roots=placement.code_roots, pruned_paths=placement.pruned_paths)


def _home_for(rel: str) -> str:
    path = Path(rel)
    if path.name.startswith('test_') or path.stem.endswith('_test') or path.name == 'conftest.py':
        return FAMILY_HOMES['tests']
    return (
        f'{FAMILY_HOMES["product source"]} if it is product code, '
        f'{FAMILY_HOMES["one-off experiment, probe or verification"]} if it is a one-off experiment, '
        f'probe or verification (promoted or deleted, never committed); repo-development mechanism lives in dev-lab'
    )


def checkout_root(path: Path) -> Path | None:
    """The nearest ancestor of *path* holding ``.git`` -- a linked worktree's own; ``None`` outside any checkout."""
    return gitdirs.checkout_of(path.parent)


def refuse_write(path: Path) -> str | None:
    """The refusal for writing code at *path*, naming its home; ``None`` when the write is admitted.

    The checkout is the nearest ancestor holding ``.git`` -- a linked worktree's own, so a lane inside
    the checkout is judged by its own declaration. A path in no checkout, or in one that declares no
    placement, is not this hook's to judge: the adopter's own test reds on a missing declaration.
    """
    target = Path(path).resolve()
    root = checkout_root(target)
    if root is None:
        return None
    try:
        placement = declared_placement(root)
    except PlacementNotDeclared:
        return None
    rel = target.relative_to(root).as_posix()
    pruned = tuple(f'{p.strip("/")}/' for p in placement.pruned_paths)
    if PRUNED_NAMES.intersection(rel.split('/')[:-1]) or rel.startswith(pruned) or admits(rel, placement.code_roots):
        return None
    homes = ', '.join(f'{kind} -> {home}' for kind, home in FAMILY_HOMES.items())
    return (
        f'CODE-IN-CODE-ROOTS: {rel} is a code file outside every declared code root '
        f'{list(placement.code_roots)}. Its home: {_home_for(rel)}. The family map: {homes}. A repo '
        f'adds a root only in code_roots of its {LAYOUT_FILE}, never by writing the file first.'
    )


def _layout() -> ModuleType:
    """:mod:`dev_lab.dev.layout` (DECLARED-LAYOUT) reads this module`s family map, so it loads when the hook runs."""
    return importlib.import_module('dev_lab.dev.layout')


def main(argv: list[str] | None = None, *, stdin: TextIO | None = None) -> int:
    """The ``PreToolUse`` agent hook on Write/Edit/MultiEdit/NotebookEdit; the payload is *stdin*.

    It refuses a report under ``output/``, a write into a write-prone root, a direct write onto a task ledger
    file (:mod:`dev_lab.dev.ledgerguard`) and a new module that cites none of its prior art
    (:mod:`dev_lab.dev.priorart`), and hints a misplaced code file.
    A payload naming no path is allowed: the hook judges a PATH, and such a payload names none. The stray
    census is :mod:`dev_lab.dev.strays`.
    """
    del argv  # the dispatcher passes the row's argv; this hook has one mode
    try:
        payload = json.load(stdin or sys.stdin)
    except ValueError:
        return 0
    tool_input = payload.get('tool_input') if isinstance(payload, dict) else None
    target = (tool_input.get('file_path') or tool_input.get('notebook_path')) if isinstance(tool_input, dict) else None
    if not isinstance(target, str) or not target:
        return 0
    path = Path(target)
    if not path.is_absolute():
        path = Path(payload.get('cwd') or Path.cwd()) / path
    # A report under output/ is lost to the next cleanup, and a write outside every checkout outlives the session
    # (WRITES-STAY-IN-THE-TREE), so both are refused; a misplaced code file is a style
    # finding the forge's placement test reds on anyway, so it is a HINT (toolchain plan P3).
    refused = refuse_report(path) or refuse_machine_file_write(path) or refuse_code_in_output(path)
    refused = refused or refuse_ledger_write(path) or refuse_outside_tree(path) or refuse_consent_write(path)
    refused = refused or _layout().refuse_layout(path)
    refused = refused or refuse_frozen_write(path)
    content = tool_input.get('content') if isinstance(tool_input.get('content'), str) else ''
    refused = refused or refuse_new_module(path, content, FAMILY_HOMES['product source'])
    hint = refuse_write(path)
    if refused is not None:
        decision = {'hookEventName': 'PreToolUse', 'permissionDecision': 'deny', 'permissionDecisionReason': refused}
        emit(json.dumps({'hookSpecificOutput': decision}))
    elif hint is not None:
        emit(json.dumps({'hookSpecificOutput': {'hookEventName': 'PreToolUse', 'additionalContext': hint}}))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))


def is_archived(rel: str) -> bool:
    """Whether repo-relative POSIX *rel* is archived code, which every code scan skips.

    Archived means under an :data:`ARCHIVED_SEGMENTS` segment, or under the :data:`ARCHIVE_DIRECTORY`
    of a ``.claude/memory/`` tree at any depth (memory is scoped per module in some consumers), which
    which held archived one-offs until that exit was retired on 2026-10-22.
    """
    parts = PurePosixPath(rel).parts
    if ARCHIVED_SEGMENTS.intersection(parts):
        return True
    return any(
        parts[i : i + 2] == ('.claude', 'memory') and ARCHIVE_DIRECTORY in parts[i + 2 : -1] for i in range(len(parts))
    )
