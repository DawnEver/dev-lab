"""TRACKED-CITES-NO-EPHEMERAL, as the full-tree assertion every consumer runs in its base part.

The scanner, the tiers, the escape set and the pre-commit entry are :mod:`lab_commons.dev.ephemeralrefs`;
this is the full-tree half (the pre-commit sees only staged files and cannot judge an orphaned escape).
The one repo-shaped fact besides the root is the FLOOR: the measured number of tracked text files the
scan reads, bound on both sides.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from lab_commons.dev import ephemeralrefs, floors, venvpath
from lab_commons.launch import run

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ['assert_no_tracked_file_cites_ephemeral', 'assert_the_scanner_still_convicts']


def assert_no_tracked_file_cites_ephemeral(*, root: Path, floor: int, headroom: int) -> None:
    """Every tracked file of *root*, escapes from its ``pyproject.toml`` applied: no refusal.

    Raises:
        lab_commons.dev.floors.FloorUnmet: fewer files were read than *floor*.
        lab_commons.dev.floors.SlackFloor: the floor has stopped binding and must be re-measured.
        AssertionError: a citation, a forced-in ignored file, or a misdeclared escape set.

    """
    problems, read = ephemeralrefs.scan(root)
    floors.assert_floor(read, floor=floor, what=ephemeralrefs.RULE)
    floors.assert_floor_still_binds(read, floor=floor, headroom=headroom, what=ephemeralrefs.RULE)
    if problems:
        head = f'{ephemeralrefs.RULE}: {len(problems)} refusal(s); {ephemeralrefs.REMEDY}:'
        msg = '\n  '.join((head, *problems))
        raise AssertionError(msg)


#: Assembled from pieces so neither the private-marker scan nor the foreign-path scan reads a path here.
_WINDOWS_HOME = 'C:/' + 'Users/someone/' + 'x.txt'
_POSIX_HOME = '/' + 'home/someone/x'
_INTERPRETER = venvpath.venv_interpreter(os_name='nt')

#: The five planted text files the scan must read (the force-added one among them).
_PLANTED_FILES = 5

#: What the planted tree must yield, exactly -- each convicted for the reason named.
_CONVICT = (
    "code.py:1: cites ignored path 'scratch/probe.py'",
    "code.py:2: reads ignored path 'output/reference/a.jproj'",
    "doc.md:1: cites ignored path 'output/logs/26/10/19/run.json'",
    "doc.md:2: cites ignored path 'output/forge/outbox/'",
    f"doc.md:3: cites machine-local path '{_WINDOWS_HOME}'",
    f"doc.md:4: cites machine-local path '{_POSIX_HOME}'",
    'output/forced.md: tracked under an ignored root (git add -f)',
)
_DOC = (
    'see `output/logs/26/10/19/run.json` here\n'
    'and `output/forge/outbox/` too\n'
    f'{_WINDOWS_HOME}\n'
    f'{_POSIX_HOME}\n'
    'shape `output/logs/<yy>/<mm>/<dd>/<kind>/`, root `output/`, `C:/Users/<you>/src`, '
    f'https://example.org/output/x, `{_INTERPRETER}`, `$TMPDIR`, `src/pkg/a.py`\n'
)
_CODE = (
    '# scratch/probe.py\n'
    "TEXT = open('output/reference/a.jproj').read()\n"
    "open('output/logs/run.json', 'w').write(TEXT)  # write target: `output/` is for that\n"
    "BASED = (BASE / 'scratch/x.py').read_text()\n"
)


def assert_the_scanner_still_convicts(plant_root: Path) -> None:
    """THE PLANTED CONTROL, both directions, through the shipped scanner over a real git repo.

    Convicts a concrete output file, a nested ignored dir, two machine-local paths, a code comment, a
    code READ of an ignored input and a force-added file; clears a placeholder shape, the bare
    ignored root, a URL, the interpreter door, a bare temp root, a tracked path, a WRITE to output and
    a literal joined onto a base.

    Raises:
        AssertionError: the scan named anything other than exactly the planted offenders.

    """

    def git(*args: str) -> None:
        run(['git', *args], cwd=plant_root, check=True, capture_output=True, timeout=60)

    git('init', '-q')
    (plant_root / '.gitignore').write_text('/output/\nscratch/\n', encoding='utf-8')
    (plant_root / 'doc.md').write_text(_DOC, encoding='utf-8')
    (plant_root / 'code.py').write_text(_CODE, encoding='utf-8')
    (plant_root / 'src/pkg').mkdir(parents=True)
    (plant_root / 'src/pkg/a.py').write_text('', encoding='utf-8')
    (plant_root / 'output').mkdir()
    (plant_root / 'output/forced.md').write_text('', encoding='utf-8')
    git('add', '.gitignore', 'doc.md', 'code.py', 'src/pkg/a.py')
    git('add', '-f', 'output/forced.md')
    problems, read = ephemeralrefs.scan(plant_root)
    if tuple(problems) != _CONVICT or read != _PLANTED_FILES:
        msg = (
            f'the scanner read {read} file(s) and named {problems}; '
            f'it must read {_PLANTED_FILES} and name exactly {list(_CONVICT)}'
        )
        raise AssertionError(msg)
