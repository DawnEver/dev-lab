"""The family rows NO repo can drop: a pytest plugin that installing dev-lab switches on.

THE ONE EXCEPTION TO THIS PACKAGE'S SHAPE, and it is a user ruling (2026-11-07), not a convenience:
NO-CJK-IN-TRACKED-SOURCE is enforced in every family repo from ONE place, with no per-repo copy and
no opt-out. Every other body in :mod:`dev_lab.dev.famtests` is parametrized by a consumer file that
names its repo's facts; this rule has none left to name -- the corpus is the repo's tracked files,
the exemptions are :data:`dev_lab.dev.cjk.EXEMPT_PREFIXES`, and the declared set is empty in every
repo -- so a consumer file could only be a copy, or a place to forget it.

HOW IT REACHES A REPO. dev-lab registers this module under pytest's ``pytest11`` entry point, so
any pytest session in an environment where dev-lab is installed loads it. When the session's rootdir
is a git toplevel it appends one item per row in :data:`ROWS`; a session rooted anywhere else (a
pytester tree, an unpacked sdist) has no tracked corpus and gets none. :data:`dev_lab.dev.rules.ALWAYS_ON`
is the registry's half: an adoption may neither list these rules nor declare them absent.

THE FLOOR IS ONE FILE, and that is the vacuity guard and nothing more: :func:`dev_lab.dev.rules.tracked_files`
raises rather than answering empty, so the remaining failure is a corpus with nothing decodable in it.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Final

import pytest

from dev_lab.dev import cjk
from dev_lab.dev.rules import tracked_files

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = ['ROWS', 'check_no_cjk']

_GIT_TIMEOUT_S: Final = 60
_GIT: Final = shutil.which('git') or 'git'


def check_no_cjk(root: Path) -> None:
    """Raise unless no tracked, non-exempt file under *root* carries CJK and no translation is orphaned."""
    tracked = sorted(tracked_files(root))
    problems = list(cjk.orphaned_translations(tracked))
    scan = cjk.scan_files([root / name for name in tracked], exempt_prefixes=cjk.EXEMPT_PREFIXES, root=root)
    if scan.files_read < 1:
        problems.append(f'the scan read no file out of {len(tracked)} tracked, so a clean result would mean nothing')
    problems.extend(cjk.ratchet(scan.occurrences, ()))
    if problems:
        raise AssertionError('\n  '.join(('NO-CJK-IN-TRACKED-SOURCE:', *problems)))


#: Rule ID -> the check run over the repo root. The IDs are :data:`dev_lab.dev.rules.ALWAYS_ON`.
ROWS: Final[dict[str, Callable[[Path], None]]] = {'NO-CJK-IN-TRACKED-SOURCE': check_no_cjk}


class FamilyItem(pytest.Item):
    """One always-on row, run against the session's repo root."""

    def __init__(self, *, check: Callable[[Path], None], root: Path, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._check = check
        self._root = root

    def runtest(self) -> None:
        self._check(self._root)

    def repr_failure(self, excinfo: pytest.ExceptionInfo[BaseException], style: object = None) -> str:  # noqa: ARG002
        return str(excinfo.value)

    def reportinfo(self) -> tuple[Path, None, str]:
        return self._root, None, f'family row {self.name}'


def _toplevel(root: Path) -> Path | None:
    try:
        out = subprocess.run(
            [_GIT, 'rev-parse', '--show-toplevel'],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
            timeout=_GIT_TIMEOUT_S,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return Path(out.stdout.strip()).resolve() if out.returncode == 0 else None


def pytest_collection_modifyitems(session: pytest.Session, config: pytest.Config, items: list[pytest.Item]) -> None:
    """Append one item per row when the session is rooted at a git toplevel."""
    root = Path(config.rootpath).resolve()
    if _toplevel(root) != root:
        return
    items.extend(
        FamilyItem.from_parent(session, name=f'family::{rule}', check=check, root=root) for rule, check in ROWS.items()
    )
