"""The family rows NO repo can drop: a pytest plugin that installing dev-lab switches on.

THE ONE EXCEPTION TO THIS PACKAGE'S SHAPE, and it is a user ruling (2026-11-07), not a convenience:
NO-CJK-IN-TRACKED-SOURCE is enforced in every family repo from ONE place, with no per-repo copy and
no opt-out. Every other body in :mod:`dev_lab.dev.famtests` is parametrized by a consumer file that
names its repo's facts; this rule has none left to name -- the corpus is the repo's tracked files,
the exemptions are :data:`dev_lab.dev.cjk.EXEMPT_PREFIXES`, and the declared set is empty in every
repo -- so a consumer file could only be a copy, or a place to forget it.

HOW IT REACHES A REPO. dev-lab registers :mod:`dev_lab.pytest_family` under pytest's ``pytest11``
entry point, so any pytest session in an environment where dev-lab is installed loads it, and that
shim calls :func:`append_rows` at collection. When the session's rootdir
is a git toplevel it appends one item per row in :func:`rows`; a session rooted anywhere else (a
pytester tree, an unpacked sdist) has no tracked corpus and gets none. :data:`dev_lab.dev.rules.ALWAYS_ON`
is the registry's half: an adoption may neither list these rules nor declare them absent.

ONE ``git grep`` FINDS THE CANDIDATES (coordinator ruling 2026-11-07): a per-file Python read took
331 s over acme-consumer's 22k files. The PCRE class is built from :data:`dev_lab.dev.cjk.CJK_RANGES` and
the exclusions from :data:`dev_lab.dev.cjk.EXEMPT_PREFIXES`; ``-I`` skips binaries. The translation
exemption and orphan check run in Python on the short list, and only hit files are re-read to name
line and column. The floor: ``git ls-files`` lists at least one file.
"""

from __future__ import annotations

import shutil
import subprocess
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Final

import pytest
from lab_commons.hpc.testcells import TestCell
from lab_commons.launch import run
from lab_commons.outcomes import Cell, Reason, Status

from dev_lab.dev import cjk
from dev_lab.dev.family import is_member
from dev_lab.dev.famtests import modulealarm
from dev_lab.dev.rules import ALWAYS_ON, tracked_files

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

__all__ = [
    'append_rows',
    'assert_required_collected',
    'candidates',
    'check_no_cjk',
    'cjk_pattern',
    'exclude_pathspecs',
    'required_ids',
    'resource_nodes',
    'rows',
    'run_checks',
]

_GIT_TIMEOUT_S: Final = 60
_GIT: Final = shutil.which('git') or 'git'


def cjk_pattern(ranges: tuple[tuple[int, int], ...] = cjk.CJK_RANGES) -> str:
    """A PCRE character class over *ranges* -- DERIVED from :data:`dev_lab.dev.cjk.CJK_RANGES`, never copied."""
    return '(*UTF)[' + ''.join(f'\\x{{{lo:04x}}}-\\x{{{hi:04x}}}' for lo, hi in ranges) + ']'


def exclude_pathspecs(prefixes: tuple[str, ...] = cjk.EXEMPT_PREFIXES) -> tuple[str, ...]:
    """Git pathspecs excluding *prefixes* with :func:`dev_lab.dev.cjk.exempted`'s semantics.

    A leading ``/`` anchors at the root; any other prefix matches as a segment at any depth.
    """
    specs: list[str] = []
    for prefix in prefixes:
        body = prefix.strip('/')
        specs.append(f':(exclude,glob){body}/**' if prefix.startswith('/') else f':(exclude,glob)**/{body}/**')
    return tuple(specs)


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return run([_GIT, *args], cwd=root, capture_output=True, check=False, timeout=_GIT_TIMEOUT_S)


def candidates(root: Path) -> tuple[str, ...]:
    """Tracked, text, non-exempt files under *root* holding a CJK character: ONE ``git grep``.

    ``-I`` skips binaries, which is the scanner's "undecodable is not read". Raises when git fails.
    """
    out = _git(
        root, '-c', 'core.quotepath=off', 'grep', '-I', '-l', '-z', '-P', cjk_pattern(), '--', '.', *exclude_pathspecs()
    )
    if out.returncode not in (0, 1):  # 1 means no match
        msg = f'git grep failed in {root}: {out.stderr.decode("utf-8", "replace").strip()}'
        raise AssertionError(msg)
    return tuple(sorted(name for name in out.stdout.decode('utf-8').split('\0') if name))


def check_no_cjk(root: Path) -> None:
    """Raise unless no tracked, non-exempt file under *root* carries CJK and no translation is orphaned."""
    tracked = tracked_files(root)  # raises rather than answering empty
    problems = list(cjk.orphaned_translations(tracked))
    if not tracked:
        problems.append('git ls-files listed no file, so a clean result would mean nothing')
    hits = [name for name in candidates(root) if not cjk.translation_exempted(name, tracked)]
    scan = cjk.scan_files([root / name for name in hits], exempt_prefixes=cjk.EXEMPT_PREFIXES, root=root)
    problems.extend(cjk.ratchet(scan.occurrences, ()))
    if problems:
        raise AssertionError('\n  '.join(('NO-CJK-IN-TRACKED-SOURCE:', *problems)))


#: Rule ID -> the check this plugin runs for it over the repo root.
_LAYOUT_RULE: Final = 'MODULE-SIZE-ALARM'
_CHECKS: Final[dict[str, Callable[[Path], None]]] = {
    'NO-CJK-IN-TRACKED-SOURCE': check_no_cjk,
    _LAYOUT_RULE: modulealarm.check,
}


def rows() -> dict[str, Callable[[Path], None]]:
    """Rule ID -> check, for every ``always_on`` registry row (:data:`dev_lab.dev.rules.ALWAYS_ON`).

    Which rules are always on is the registry's data; this module owns only the checks. A row with no
    check here raises KeyError rather than being skipped.
    """
    return {rule: _CHECKS[rule] for rule in sorted(ALWAYS_ON)}


def _applicable(root: Path) -> dict[str, Callable[[Path], None]]:
    checks = rows()
    if not is_member(root):
        checks.pop(_LAYOUT_RULE)
    return checks


def _identity(rule: str) -> str:
    return f'::family::{rule}'


def _catalog_ids(root: Path) -> tuple[str, ...]:
    return tuple(_identity(rule) for rule in _applicable(root)) if is_member(root) else ()


def required_ids(root: Path) -> tuple[str, ...]:
    """Exact required identities after fresh family Git-root proof; no claim for other inputs."""
    if not is_member(root):
        return ()
    if _toplevel(root) != root.resolve():
        refused = _git_refusal('the declared family root is not the readable git toplevel')
        raise refused
    return _catalog_ids(root)


def assert_required_collected(root: Path, ids: Sequence[str]) -> None:
    """Reject a family collection whose plugin did not actually supply every required item."""
    if missing := set(required_ids(root)) - set(ids):
        message = (
            f'required family checks missing from collection: {sorted(missing)}; '
            'enable the installed dev_lab_family pytest plugin (remove plugin-disable flags or '
            'PYTEST_DISABLE_PLUGIN_AUTOLOAD), then recollect before producing a complete part'
        )
        raise ValueError(message)


def resource_nodes(root: Path, ids: Sequence[str]) -> list[str]:
    """Identity projection, not qualification; collectors must separately prove their complete manifest."""
    required = set(_catalog_ids(root))
    return [node for node in ids if node not in required]


def run_checks(root: Path) -> dict[str, TestCell]:
    """Execute the same checks for non-pytest family producers, retaining their individual evidence."""
    if not is_member(root):
        return {}
    cells = {}
    for rule, check in _applicable(root).items():
        try:
            check(root)
        except (AssertionError, OSError, ValueError, RuntimeError) as exc:
            cells[_identity(rule)] = TestCell(Cell(Status.REJECTED, reason=Reason('assertion', str(exc))))
        else:
            cells[_identity(rule)] = TestCell(Cell(Status.OK))
    return cells


class FamilyItem(pytest.Item):
    """One always-on row, run against the session's repo root."""

    def __init__(self, *, name: str, parent: pytest.Session, check: Callable[[Path], None], root: Path) -> None:
        super().__init__(name=name, parent=parent, nodeid='::' + name)
        self._check = check
        self._root = root

    def runtest(self) -> None:
        self._check(self._root)

    def reportinfo(self) -> tuple[Path, None, str]:
        return self._root, None, f'family row {self.name}'


def _git_refusal(reason: str) -> ValueError:
    return ValueError(
        f'git identity of the declared family checkout cannot be established: {reason}; '
        'repair git checkout/access, then recollect before producing complete qualification'
    )


def _toplevel(root: Path) -> Path | None:
    try:
        out = _git(root, 'rev-parse', '--show-toplevel')
    except (OSError, subprocess.TimeoutExpired) as exc:
        if is_member(root):
            refused = _git_refusal(f'{type(exc).__name__}: {exc}')
            raise refused from exc
        return None
    if out.returncode != 0:
        if is_member(root):
            refused = _git_refusal(f'exit {out.returncode}: {out.stderr.decode("utf-8", "replace").strip()}')
            raise refused
        return None
    try:
        text = out.stdout.decode('utf-8').strip()
        top = Path(text).resolve() if text else None
    except (UnicodeError, OSError, ValueError) as exc:
        if is_member(root):
            refused = _git_refusal(str(exc))
            raise refused from exc
        return None
    if top is None and is_member(root):
        refused = _git_refusal('git returned an empty toplevel')
        raise refused
    return top


def _unreadable_root(_root: Path, *, reason: str) -> None:
    raise ValueError(reason)


def append_rows(session: pytest.Session, config: pytest.Config, items: list[pytest.Item]) -> None:
    """Append one item per row when the session is rooted at a git toplevel.

    Called at collection by :mod:`dev_lab.pytest_family`, the ``pytest11`` entry point.
    A declared family with unreadable Git retains failed runtime items, never an empty guard set.
    """
    root = Path(config.rootpath).resolve()
    if is_member(root):
        try:
            required_ids(root)
        except ValueError as exc:
            checks = dict.fromkeys(_applicable(root), partial(_unreadable_root, reason=str(exc)))
        else:
            checks = _applicable(root)
    else:
        if _toplevel(root) != root:
            return
        checks = _applicable(root)
    items.extend(
        FamilyItem.from_parent(session, name=_identity(rule).removeprefix('::'), check=check, root=root)
        for rule, check in checks.items()
    )
