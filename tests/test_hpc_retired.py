"""Retired spellings of the test-run surface: refused by name, and found nowhere else in the tree."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from lab_commons.dev import admission, platformparts
from lab_commons.hpc import __main__ as hpc_main
from lab_commons.hpc.retired import RETIRED, refusal

ROOT = Path(__file__).resolve().parents[1]

#: The registry itself and this test hold every spelling by construction; memory keeps history verbatim.
_EXEMPT = ('src/lab_commons/hpc/retired.py', 'tests/test_hpc_retired.py')
_HISTORY = '.claude/memory/'


def test_the_old_cluster_verb_is_refused_by_name_with_its_remedy(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        hpc_main.main(['verdict', 'submit', '--sha', 'a' * 40])
    err = capsys.readouterr().err
    assert '`lab_commons.hpc verdict` is retired' in err
    assert 'run submit|gather' in err


def test_the_old_part_verb_is_refused_by_name_with_its_remedy(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        platformparts.main(['record-linux', 'r.json', '--tier', 'heavy'])
    err = capsys.readouterr().err
    assert '`platformparts record-linux` is retired' in err
    assert 'platformparts post <run-record>' in err


@pytest.mark.parametrize('flag', ['--trunk-tier', '--ledger', '--gap'])
def test_the_ledger_admission_flags_are_refused_by_name(tmp_path, flag: str, capsys) -> None:
    """Admission reads the forge: the ledger, its tiers and its gap record are retired as admission inputs."""
    with pytest.raises(SystemExit):
        admission.main(['--root', str(tmp_path), '--trunk-ref', 'none', '--remote-ref', 'r', flag, 'x'])
    assert 'is retired' in capsys.readouterr().err


def test_the_ledger_part_verb_is_refused_by_name(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        platformparts.main(['record', 'r.json.gz'])
    assert '`platformparts record` is retired' in capsys.readouterr().err


def test_a_live_verb_is_not_a_refusal() -> None:
    assert refusal('lab_commons.hpc', 'run') is None


def test_no_retired_spelling_survives_in_the_tracked_tree() -> None:
    """Prose included: a retired spelling survives longest in a comment explaining the retirement."""
    files = subprocess.run(
        [shutil.which('git') or 'git', 'ls-files', '-z'],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding='utf-8',
        check=True,
    ).stdout.split('\0')
    scanned = [f for f in files if f and f not in _EXEMPT and not f.startswith(_HISTORY)]
    assert len(scanned) > 100, f'the scan read only {len(scanned)} files -- a floor, so an empty scan is not a pass'
    found = []
    for name in scanned:
        try:
            text = (ROOT / name).read_text(encoding='utf-8')
        except (UnicodeDecodeError, FileNotFoundError):
            continue
        found += [f'{name}: {spelling!r} -> {remedy}' for spelling, remedy in RETIRED.items() if spelling in text]
    assert not found, 'retired spellings (replace each with its remedy):\n' + '\n'.join(found)
