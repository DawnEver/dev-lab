r"""THE PUBLISHER RENDERS ITS OWN `.gitignore` FROM THE FAMILY BASE, as every consumer does.

UNTIL 2026-10-03 THIS MODULE PINNED THE OPPOSITE: that the kit's ten-pattern file was a subset of no
consumer and the base was not adoptable here. The user ruled that day that every project-level file
has ONE source in this package, and what closed the gap was the BASE growing the family-mandated lines
(`_famconfig_rows.GITIGNORE_FAMILY_LINES`) -- after which this tree's file is the base plus one line.
The module's old re-opening trigger ("when the unadopted set empties, adopt rather than deleting this
arm") is exactly what happened; the arms below are the adoption's.

NOTHING HERE RE-IMPLEMENTS THE KIT: every arm is a body from :mod:`lab_commons.dev.famtests.configrender`,
the same ones the consumers parametrize, plus the one fact the old module was right to keep -- the
hatch-vcs version file must stay ignored, because a committed one makes a build irreproducible from tags.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Final

from _famconfig_delta import DELTAS, GITIGNORE, REPO

from lab_commons.dev.famconfig import RENDERED
from lab_commons.dev.famtests.configrender import (
    assert_artefact_is_rendered,
    assert_delta_is_not_a_fork,
    assert_every_base_is_accounted_for,
    assert_modes_are_as_agreed,
    assert_no_base_line_left_undeclared,
    assert_render_round_trips,
)

ROOT: Final = Path(__file__).resolve().parents[1]

#: The repo's own re-render line -- the remedy a red names. No Makefile target exists for it here.
RERENDER: Final = (
    "python -c \"import sys, pathlib; sys.path.insert(0, 'tests'); "
    'from _famconfig_delta import DELTAS, GITIGNORE; '
    'from lab_commons.dev.famconfig import artefact_base, render; '
    "pathlib.Path(GITIGNORE).write_text(render(artefact_base(GITIGNORE), DELTAS[GITIGNORE]), encoding='utf-8')\""
)

#: The file hatch-vcs writes at build time. It must be ignored here, through whichever base line reaches it.
VERSION_FILE: Final = 'src/lab_commons/__version__.py'


def test_the_declaration_is_a_delta_of_the_base_and_not_a_fork() -> None:
    """A delta restating a base line is refused here, before the bytes are compared."""
    assert_delta_is_not_a_fork(artefact=GITIGNORE, deltas=DELTAS, repo=REPO)


def test_the_file_on_disk_is_what_the_live_base_and_this_delta_render() -> None:
    """THE PROPERTY. Re-rendered from the LIVE base, so an upstream base edit moves this verdict."""
    assert_artefact_is_rendered(root=ROOT, artefact=GITIGNORE, deltas=DELTAS, repo=REPO, rerender_hint=RERENDER)


def test_no_base_line_left_the_file_without_a_declared_drop() -> None:
    """The survey's route in, which does not go through the bytes."""
    assert_no_base_line_left_undeclared(root=ROOT, artefact=GITIGNORE, repo=REPO)


def test_the_gitignore_is_judged_rendered_and_every_base_is_accounted_for() -> None:
    """RENDERED is byte equality; and with all three bases adopted, the completeness arm runs here too."""
    assert_modes_are_as_agreed(modes={GITIGNORE: RENDERED})
    assert_every_base_is_accounted_for(deltas=DELTAS, repo=REPO)


def test_a_planted_hand_edit_is_refused(tmp_path: Path) -> None:
    """PLANTED CONTROL: un-floating the cache rule -- the spelling this file carried before adoption."""
    assert_render_round_trips(
        artefact=GITIGNORE,
        deltas=DELTAS,
        repo=REPO,
        scratch=tmp_path,
        edit=('**/__pycache__/', '__pycache__/'),
    )


def test_the_hatch_vcs_version_file_stays_ignored() -> None:
    """Read through git itself, so the answer is the rendered file's, not this module's opinion of it."""
    done = subprocess.run(
        [shutil.which('git') or 'git', '-C', str(ROOT), 'check-ignore', '-q', '--no-index', VERSION_FILE],
        check=False,
        timeout=60,
    )
    assert done.returncode == 0, f'{VERSION_FILE} is not ignored; a build would commit it'
