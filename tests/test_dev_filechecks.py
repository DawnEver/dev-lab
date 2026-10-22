"""The base's per-file checks: each convicts its planted defect, passes a clean file, and rewrites nothing."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from dev_lab.dev.filechecks import CHECKS, main
from dev_lab.dev.githooks.table import base_rows

_DEFECTS: dict[str, tuple[str, bytes, bytes]] = {
    'ast': ('m.py', b'def f(:\n', b'def f():\n    pass\n'),
    'json': ('d.json', b'{"a": }\n', b'{"a": 1}\n'),
    'toml': ('c.toml', b'a = \n', b'a = 1\n'),
    'merge-conflict': ('t.txt', b'<<<<<<< HEAD\na\n=======\nb\n>>>>>>> x\n', b'a\n=======\n'),
    'debug-statements': ('m.py', b'import pdb\nbreakpoint()\n', b'import os\n'),
    'end-of-file': ('t.txt', b'a', b'a\n'),
    'mixed-line-ending': ('t.txt', b'a\r\nb\n', b'a\r\nb\r\n'),
    'trailing-whitespace': ('t.txt', b'a \nb\n', b'a\nb\n'),
}


@pytest.mark.parametrize('check', sorted(_DEFECTS))
def test_each_check_convicts_its_defect_and_rewrites_nothing(check: str, tmp_path: Path) -> None:
    name, bad, good = _DEFECTS[check]
    path = tmp_path / name
    path.write_bytes(bad)
    assert main([check, str(path)]) == 1
    assert path.read_bytes() == bad, 'a check reports; it never rewrites'
    path.write_bytes(good)
    assert main([check, str(path)]) == 0


def test_blank_lines_at_the_end_are_a_finding(tmp_path: Path) -> None:
    path = tmp_path / 't.txt'
    path.write_bytes(b'a\n\n')
    assert main(['end-of-file', str(path)]) == 1


def test_a_binary_file_is_skipped_by_the_text_checks(tmp_path: Path) -> None:
    path = tmp_path / 'b.bin'
    path.write_bytes(b'\0 \r\nx \n')
    for check in ('trailing-whitespace', 'mixed-line-ending', 'end-of-file', 'merge-conflict'):
        assert main([check, str(path)]) == 0


def test_a_large_file_is_measured_against_the_declared_threshold(tmp_path: Path) -> None:
    path = tmp_path / 'big.bin'
    path.write_bytes(b'x' * 3 * 1024)
    assert main(['large-files', '--max-kb', '2', str(path)]) == 1
    assert main(['large-files', '--max-kb', '4', str(path)]) == 0


def test_a_case_conflict_with_a_tracked_path_is_a_finding(tmp_path: Path, monkeypatch) -> None:
    git = shutil.which('git') or 'git'
    subprocess.run([git, 'init', '-q', str(tmp_path)], check=True, capture_output=True)
    (tmp_path / 'Readme.md').write_text('a\n', encoding='utf-8')
    subprocess.run([git, '-C', str(tmp_path), 'add', 'Readme.md'], check=True, capture_output=True)
    monkeypatch.chdir(tmp_path)
    other = tmp_path / 'sub'
    other.mkdir()
    (other / 'x.md').write_text('a\n', encoding='utf-8')
    assert main(['case-conflict', 'sub/x.md']) == 0
    # On a case-insensitive filesystem this writes Readme.md again; the PATH SET still holds both names.
    (tmp_path / 'README.md').write_text('a\n', encoding='utf-8')
    assert main(['case-conflict', 'README.md']) == 1


def test_every_check_the_base_names_exists() -> None:
    named = {row['run'][3] for row in base_rows()['pre-commit'] if row['run'][1:3] == ['-m', 'dev_lab.dev.filechecks']}
    assert named == set(CHECKS)
