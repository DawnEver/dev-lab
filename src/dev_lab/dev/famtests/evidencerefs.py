"""EVIDENCE-OUTLIVES-OUTPUT, as the full-tree assertion a consumer runs, and its planted control.

The tier and its escapes are :mod:`dev_lab.dev.evidencerefs`; the repo-shaped fact besides the root is
the FLOOR, the measured number of tracked code and data files the scan reads, bound on both sides.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from lab_commons.launch import run

from dev_lab.dev import evidencerefs, floors
from dev_lab.dev.failprint import subject_lines

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ['assert_no_tracked_value_cites_output_evidence', 'assert_the_evidence_scan_still_convicts']


def assert_no_tracked_value_cites_output_evidence(*, root: Path, floor: int, headroom: int) -> None:
    """Every tracked code and data file of *root*, escapes applied: no evidence cited under the output tree.

    Raises:
        dev_lab.dev.floors.FloorUnmet: fewer files were read than *floor*.
        dev_lab.dev.floors.SlackFloor: the floor has stopped binding and must be re-measured.
        AssertionError: a citation or a misdeclared escape set.

    """
    problems, read = evidencerefs.scan(root)
    floors.assert_floor(read, floor=floor, what=evidencerefs.RULE)
    floors.assert_floor_still_binds(read, floor=floor, headroom=headroom, what=evidencerefs.RULE)
    if problems:
        head = f'{evidencerefs.RULE}: {len(problems)} refusal(s); {evidencerefs.REMEDY}:'
        raise AssertionError('\n  '.join((head, *problems)) + '\n' + subject_lines(problems))


#: The planted tree: (a) a docstring, (b) a literal joined onto the repo root, (c) a TOML value, (d) a JSON
#: field each cite output evidence; (e) writers, a joined literal on another base, and shapes pass.
_CODE = (
    '"""MEASURED on output/logs/26/01/01/x/run.log."""\n'
    "DATA = (repo_root() / 'output/logs/26/01/01/x.json').read_text()\n"
    "open('output/logs/26/01/01/w.json', 'w').write(DATA)\n"
    "Path('output/logs/26/01/01/y.json').write_text(DATA)\n"
    "LOCAL = tmp_path / 'output/x.json'\n"
    "SHAPE = 'output/logs/<yy>/<mm>/<dd>/<kind>/'\n"
)
_TOML = 'source = "output/logs/26/01/01/x"  # output/y in a comment is the prose tier\n'
_JSON = '{\n  "journal": "output/logs/26/01/01/j.jsonl"\n}\n'
_PLANTED_FILES = 3
_CONVICT = (
    "case.json:2: records evidence at ignored path 'output/logs/26/01/01/j.jsonl'",
    "case.toml:1: records evidence at ignored path 'output/logs/26/01/01/x'",
    "code.py:1: records evidence at ignored path 'output/logs/26/01/01/x/run.log'",
    "code.py:2: records evidence at ignored path 'output/logs/26/01/01/x.json'",
)


def assert_the_evidence_scan_still_convicts(plant_root: Path) -> None:
    """THE PLANTED CONTROL, both directions, through the shipped scan over a real git repo.

    Raises:
        AssertionError: the scan named anything other than exactly (a)-(d), or did not read the three files.

    """
    run(['git', 'init', '-q'], cwd=plant_root, check=True, capture_output=True, timeout=60)
    files = {'.gitignore': '/output/\n', 'code.py': _CODE, 'case.toml': _TOML, 'case.json': _JSON}
    for name, text in files.items():
        (plant_root / name).write_text(text, encoding='utf-8')
    run(['git', 'add', *files], cwd=plant_root, check=True, capture_output=True, timeout=60)
    problems, read = evidencerefs.scan(plant_root)
    if tuple(problems) != _CONVICT or read != _PLANTED_FILES:
        msg = (
            f'the evidence scan read {read} file(s) and named {problems}; '
            f'it must read {_PLANTED_FILES} and name exactly {list(_CONVICT)}'
        )
        raise AssertionError(msg)
