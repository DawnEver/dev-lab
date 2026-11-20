"""The base's per-file checks: each convicts its planted defect, passes a clean file, and rewrites nothing.

ONE invocation runs every check (``all``) over the paths once; each check stays selectable, skippable and
excludable by name, because a repo narrows one check without restating the rest.
"""

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


def test_a_large_file_finding_names_its_doors(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """EVERY-WALL-TEACHES: a numerics-lab fixture (1.4 MB) was refused with a size and no door (2026-11-20)."""
    path = tmp_path / 'fixture.json'
    path.write_bytes(b'x' * 3 * 1024)
    assert main(['large-files', '--max-kb', '2', str(path)]) == 1
    said = capsys.readouterr().out
    assert '--exclude large-files=' in said, said
    assert '--max-kb' in said, said
    assert '[[tool.dev_lab.hooks.pre-commit]]' in said, said


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


def test_the_base_runs_every_check_in_one_row() -> None:
    rows = [row for row in base_rows()['pre-commit'] if row['run'][1:3] == ['-m', 'dev_lab.dev.filechecks']]
    assert [row['run'][3:] for row in rows] == [['all']]


def test_all_reports_every_check_a_file_fails_each_under_its_own_name(tmp_path: Path, capsys) -> None:
    """PLANTED: one file failing several checks reports each by name; a clean sibling reports nothing."""
    bad, good = tmp_path / 'bad.py', tmp_path / 'good.py'
    bad.write_bytes(b'x = 1  \nimport pdb')
    good.write_bytes(b'x = 1\n')
    assert main(['all', str(bad), str(good)]) == 1
    said = capsys.readouterr().out
    assert {line.split(']')[0] + ']' for line in said.splitlines()} == {
        '[trailing-whitespace]',
        '[end-of-file]',
        '[debug-statements]',
    }
    assert 'good.py' not in said


def test_a_check_reads_only_the_paths_its_kind_selects(tmp_path: Path) -> None:
    """``ast`` judges Python only: a .txt that would not parse is no finding; PLANTED the same bytes in .py are."""
    (tmp_path / 'notes.txt').write_bytes(b'def f(:\n')
    (tmp_path / 'm.py').write_bytes(b'def f(:\n')
    assert main(['all', str(tmp_path / 'notes.txt')]) == 0
    assert main(['all', str(tmp_path / 'm.py')]) == 1


def test_a_skipped_check_is_not_run_and_the_rest_still_are(tmp_path: Path, capsys) -> None:
    path = tmp_path / 't.txt'
    path.write_bytes(b'a \nb')
    assert main(['all', '--skip', 'trailing-whitespace', str(path)]) == 1
    said = capsys.readouterr().out
    assert '[trailing-whitespace]' not in said
    assert '[end-of-file]' in said, 'PLANTED CONTROL: the check not skipped still reports'
    assert main(['all', '--skip', 'trailing-whitespace', '--skip', 'end-of-file', str(path)]) == 0


def test_an_exclude_narrows_one_check_and_no_other(tmp_path: Path, capsys) -> None:
    path = tmp_path / 'data.tsv'
    path.write_bytes(b'a\t\nb')
    assert main(['all', '--exclude', r'trailing-whitespace=\.tsv$', str(path)]) == 1
    said = capsys.readouterr().out
    assert '[trailing-whitespace]' not in said
    assert '[end-of-file]' in said, 'PLANTED CONTROL: the exclude is that one check`s'


def test_every_check_stays_selectable_by_name(tmp_path: Path) -> None:
    path = tmp_path / 'clean.txt'
    path.write_bytes(b'a\n')
    assert all(main([check, str(path)]) == 0 for check in CHECKS)


@pytest.mark.parametrize(
    'argv',
    [
        ['nope', 'x'],
        ['all', '--skip', 'nope'],
        ['all', '--exclude', 'nope=x'],
        ['all', '--exclude', 'ast=('],
        ['all', '--exclude', 'ast'],
    ],
)
def test_a_check_name_or_regex_that_does_not_exist_is_refused(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as stop:
        main(argv)
    assert stop.value.code == 2
