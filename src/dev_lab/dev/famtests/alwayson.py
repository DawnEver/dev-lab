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
331 s over motronics' 22k files. The PCRE class is built from :data:`dev_lab.dev.cjk.CJK_RANGES` and
the exclusions from :data:`dev_lab.dev.cjk.EXEMPT_PREFIXES`; ``-I`` skips binaries. The translation
exemption and orphan check run in Python on the short list, and only hit files are re-read to name
line and column. The floor: ``git ls-files`` lists at least one file.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Final

import pytest
from lab_commons.launch import run

from dev_lab.dev import cjk
from dev_lab.dev.rules import ALWAYS_ON, tracked_files

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = ['append_rows', 'candidates', 'check_no_cjk', 'cjk_pattern', 'exclude_pathspecs', 'rows']

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
_CHECKS: Final[dict[str, Callable[[Path], None]]] = {'NO-CJK-IN-TRACKED-SOURCE': check_no_cjk}


def rows() -> dict[str, Callable[[Path], None]]:
    """Rule ID -> check, for every ``always_on`` registry row (:data:`dev_lab.dev.rules.ALWAYS_ON`).

    Which rules are always on is the registry's data; this module owns only the checks. A row with no
    check here raises KeyError rather than being skipped.
    """
    return {rule: _CHECKS[rule] for rule in sorted(ALWAYS_ON)}


class FamilyItem(pytest.Item):
    """One always-on row, run against the session's repo root."""

    def __init__(self, *, name: str, parent: pytest.Session, check: Callable[[Path], None], root: Path) -> None:
        super().__init__(name=name, parent=parent)
        self._check = check
        self._root = root

    def runtest(self) -> None:
        self._check(self._root)

    def reportinfo(self) -> tuple[Path, None, str]:
        return self._root, None, f'family row {self.name}'


def _toplevel(root: Path) -> Path | None:
    try:
        out = _git(root, 'rev-parse', '--show-toplevel')
    except (OSError, subprocess.TimeoutExpired):
        return None
    return Path(out.stdout.decode('utf-8').strip()).resolve() if out.returncode == 0 else None


def append_rows(session: pytest.Session, config: pytest.Config, items: list[pytest.Item]) -> None:
    """Append one item per row when the session is rooted at a git toplevel.

    Called at collection by :mod:`dev_lab.pytest_family`, the ``pytest11`` entry point.
    """
    root = Path(config.rootpath).resolve()
    if _toplevel(root) != root:
        return
    items.extend(
        FamilyItem.from_parent(session, name=f'family::{rule}', check=check, root=root)
        for rule, check in rows().items()
    )
