"""NO-REFLECTION, adopted over this repo's tracked Python by the family body.

The scan, the banned names, the attic/archived exclusion and the two-sided allow-set are
`lab_commons.dev.famtests.noreflection`'s. This module supplies this tree's allow-set (empty) and its
floor, and plants the controls the body must convict.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from lab_commons.dev.famtests.noreflection import assert_no_reflection, reflection_sites

_ROOT = Path(__file__).resolve().parents[1]

#: Measured 2026-10-04: 331 tracked *.py outside attic/archived. Below it for ordinary deletion.
_FLOOR = 300

_GIT = shutil.which('git') or 'git'


#: Path -> why reflection IS the operation there.
_ALLOWED = {
    'src/lab_commons/dev/seams.py': (
        'rebind/restore_all rebind a name handed in as DATA (a Seam path) on an arbitrary owner and put '
        'the original back; the attribute name is not known to any type, so setattr is the operation'
    ),
}


def test_this_tree_carries_no_reflection() -> None:
    assert_no_reflection(root=_ROOT, allowed=_ALLOWED, floor=_FLOOR)


def test_every_banned_form_is_found() -> None:
    planted = (
        'def __getattr__(name):\n'
        '    return getattr(object(), name)\n'
        'hasattr(o, "a")\nsetattr(o, "a", 1)\ndelattr(o, "a")\n'
    )
    assert reflection_sites(planted, '<planted>') == [1, 2, 3, 4, 5]


def _repo(tmp_path: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text, encoding='utf-8')
    subprocess.run([_GIT, 'init', '-q'], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run([_GIT, 'add', '.'], cwd=tmp_path, check=True, capture_output=True)
    return tmp_path


def test_a_planted_site_reds_and_history_is_excluded(tmp_path: Path) -> None:
    root = _repo(
        tmp_path,
        {'a.py': 'setattr(o, "x", 1)\n', 'attic/b.py': 'getattr(o, "x")\n', 'archived/c.py': 'hasattr(o, "x")\n'},
    )
    with pytest.raises(AssertionError, match=r'a\.py:1'):
        assert_no_reflection(root=root, allowed={}, floor=1)
    assert_no_reflection(root=root, allowed={'a.py': 'planted boundary'}, floor=1)


def test_a_stale_or_unreasoned_allow_entry_reds(tmp_path: Path) -> None:
    root = _repo(tmp_path, {'a.py': 'x = 1\n', 'b.py': 'getattr(o, "x")\n'})
    with pytest.raises(AssertionError, match='stale allow entries'):
        assert_no_reflection(root=root, allowed={'a.py': 'gone', 'b.py': 'kept'}, floor=1)
    with pytest.raises(AssertionError, match=r"without a reason=\['b.py'\]"):
        assert_no_reflection(root=root, allowed={'b.py': ' '}, floor=1)


def test_an_unread_tree_reds(tmp_path: Path) -> None:
    root = _repo(tmp_path, {'a.py': 'x = 1\n'})
    with pytest.raises(AssertionError):
        assert_no_reflection(root=root, allowed={}, floor=2)
