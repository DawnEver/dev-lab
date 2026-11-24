r"""THE PUBLISHER RENDERS ITS OWN `.gitignore` FROM THE FAMILY BASE, as every consumer does.

UNTIL 2026-10-03 THIS MODULE PINNED THE OPPOSITE: that the kit's ten-pattern file was a subset of no
consumer and the base was not adoptable here. The user ruled that day that every project-level file
has ONE source in this package, and what closed the gap was the BASE growing the family-mandated lines
(`_famconfig_rows.GITIGNORE_FAMILY_LINES`) -- after which this tree's file is the base plus one line.
The module's old re-opening trigger ("when the unadopted set empties, adopt rather than deleting this
arm") is exactly what happened; the arms below are the adoption's.

NOTHING HERE RE-IMPLEMENTS THE KIT: every arm is a body from :mod:`dev_lab.dev.famtests.configrender`,
the same ones the consumers parametrize, plus the one fact the old module was right to keep -- the
hatch-vcs version file must stay ignored, because a committed one makes a build irreproducible from tags.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Final

from _famconfig_delta import DELTAS, GITIGNORE, REPO

from dev_lab.dev.famconfig import RENDERED
from dev_lab.dev.famtests.configrender import (
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
    'from dev_lab.dev.famconfig import artefact_base, render; '
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


#: THE PRINCIPLE (user ruling 2026-11-24): the base ignores only what legitimately exists untracked; a
#: misplaced artefact is NOT ignored, so it shows in `git status`. Each list is the others' planted
#: control: one base must say yes to one and no to the other.
_TRACKED: Final = (
    '.claude/settings.json',
    '.claude/hooks/deny-commands.js',
    '.claude/hooks/venv_resolver.js',
    '.claude/hooks/py.js',
    '.claude/hooks/deny-rules.json',
    '.claude/hooks/native_session.json',
    '.claude/memory/2026/06/01/a-finding.md',
    '.codex/rules/family-doors.rules',
    '.codex/rules/family-denies.rules',
    '.vscode/settings.json',
)
_IGNORED: Final = (
    '.venv/Scripts/python.exe',
    '.venvs/abc-20261124T000000Z/pyvenv.cfg',
    'src/pkg/__pycache__/x.cpython-312.pyc',
    'build/lib/x.py',
    'dist/x-1.0-py3-none-any.whl',
    'src/pkg/__version__.py',
    'output/logs/26/11/24/verify/x.log',
    'output/cache/pytest/v/cache/nodeids',
    'config/x.toml',
    'temp/x.txt',
    'docs/.DS_Store',
    '.claude/settings.local.json',
    '.claude/automode.json',
    '.claude/worktrees/lane/README.md',
    '.codex/config.toml',
    '.vscode/launch.json',
    # Undeclared `.claude/` entries are ignored by the closed section -- git cannot track them by accident
    # -- and REFUSED on disk by the closed inventory (dev_lab.dev.claudelayout), not by `git status`.
    'src/pkg/.claude/settings.json',
    '.claude/rem.json',
    '.claude/sharp-review.json',
    '.claude/rules/principles.md',
    '.claude/hooks/stray.js',
    '.claude/memory/_meta.json',
    '.claude/memory/2026/06/01/_meta.json',
    '.claude/memory-index.md',
)
#: MISPLACED ARTEFACTS: each was ignored by an older base and must now SHOW in `git status`.
_VISIBLE: Final = (
    '.pytest_cache/v/cache/nodeids',
    '.ruff_cache/x',
    '.mypy_cache/x',
    '.coverage',
    'htmlcov/index.html',
    '.env',
    'x.egg-info/PKG-INFO',
    'log/x.log',
    'scratch/probe.py',
    'src/pkg/output/x.py',
    'src/pkg/temp/x.py',
    'src/pkg/x.c',
)


def test_the_gitattributes_base_is_the_one_normalisation_line() -> None:
    """User ruling 2026-11-24: the base is `* text=auto eol=lf` alone; per-type lines are a repo's delta."""
    from dev_lab.dev._famconfig_rows import GITATTRIBUTES_BASE  # noqa: PLC0415

    assert GITATTRIBUTES_BASE == ('* text=auto eol=lf',)


def _ignored(repo: Path, path: str) -> bool:
    done = subprocess.run(
        [shutil.which('git') or 'git', '-C', str(repo), 'check-ignore', '-q', '--no-index', path],
        check=False,
        timeout=60,
    )
    return done.returncode == 0


def test_only_legitimate_untracked_paths_are_ignored(tmp_path: Path) -> None:
    """Every declared file is trackable, every legitimate artefact ignored, and every misplaced one VISIBLE.

    Asked of a bare repo holding ONLY this checkout's `.gitignore`: a tool's own nested ignore file (pytest
    and ruff write one into their cache) would otherwise answer for the base.
    """
    git = shutil.which('git') or 'git'
    subprocess.run([git, 'init', '-q', str(tmp_path)], check=True, timeout=60)
    shutil.copyfile(ROOT / GITIGNORE, tmp_path / GITIGNORE)
    assert [path for path in _TRACKED if _ignored(tmp_path, path)] == []
    assert [path for path in _IGNORED if not _ignored(tmp_path, path)] == []
    assert [path for path in _VISIBLE if _ignored(tmp_path, path)] == []
