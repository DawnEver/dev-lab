"""PROJECT-FILES-HAVE-ONE-SOURCE, as the bodies every consumer runs.

Two questions, and a repo answers both with one test file:

* :func:`assert_every_project_file_is_accounted_for` -- every tracked project-level file is in the
  family list (:data:`lab_commons.dev.famfiles.PROJECT_FILES`) or in the repo's own *owned_here* with
  a reason. A file in neither is drifting with nobody saying so.
* :func:`assert_every_managed_file_is_rendered` -- every famconfig base is declared, no delta restates
  a base line, and every artefact on disk is what base plus delta render. It COMPOSES the
  :mod:`lab_commons.dev.famtests.configrender` bodies rather than re-implementing them.

Every repo-shaped fact -- the root, the repo name, the deltas, the remedy, the owned files -- arrives
as a keyword argument with no default, as everywhere in this package.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from lab_commons.dev.famconfig import BASES
from lab_commons.dev.famfiles import PROJECT_FILES, project_files_on_disk, unaccounted
from lab_commons.dev.famtests.configrender import (
    assert_artefact_is_rendered,
    assert_delta_is_not_a_fork,
    assert_every_base_is_accounted_for,
)

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from lab_commons.dev.famconfig import Delta

__all__ = ['assert_every_managed_file_is_rendered', 'assert_every_project_file_is_accounted_for']

#: A repo with fewer tracked project-level files than this was not read: every repo has at least a
#: pyproject, a .gitignore and a Makefile.
_FILE_FLOOR = 3


def assert_every_project_file_is_accounted_for(*, root: Path, owned_here: Mapping[str, str]) -> None:
    """Every project-level file of *root* is family-managed or repo-owned WITH a reason -- nothing else.

    *owned_here* is the repo's own list, for files whose noun is the repo's (a lockfile of its own, a
    toolchain the family does not share). It may not restate a family row, may not carry an empty
    reason, and may not name a file the repo does not have: each of those is a declaration that lies.
    """
    on_disk = project_files_on_disk(root)
    problems: list[str] = []
    if len(on_disk) < _FILE_FLOOR:
        problems.append(f'only {len(on_disk)} project-level file(s) read in {root}; the scan read nothing')
    problems += [
        f'{path}: owned here AND a family row -- delete the local entry' for path in owned_here if path in PROJECT_FILES
    ]
    problems += [f'{path}: owned here with no reason' for path, why in owned_here.items() if not why.strip()]
    problems += [f'{path}: owned here but not tracked in this repo' for path in owned_here if path not in on_disk]
    problems += [
        f'{path}: tracked, and neither in lab_commons.dev.famfiles.PROJECT_FILES nor owned here -- add it to '
        f'one of them (the family row if its content is the family`s toolchain, owned_here with the reason if not)'
        for path in unaccounted(root, owned_here)
    ]
    if problems:
        raise AssertionError('PROJECT-FILES-HAVE-ONE-SOURCE:\n  ' + '\n  '.join(problems))


def assert_every_managed_file_is_rendered(
    *, root: Path, deltas: Mapping[str, Delta], repo: str, rerender_hint: str
) -> None:
    """Every famconfig base is declared, no delta forks its base, and every file is base plus delta.

    *rerender_hint* is the repo's own command; ``python -m lab_commons.dev.famfiles --deltas <its
    module>`` is the family one and renders every artefact at once.
    """
    assert_every_base_is_accounted_for(deltas=deltas, repo=repo)
    for artefact in sorted(BASES):
        assert_delta_is_not_a_fork(artefact=artefact, deltas=deltas, repo=repo)
        assert_artefact_is_rendered(root=root, artefact=artefact, deltas=deltas, repo=repo, rerender_hint=rerender_hint)
