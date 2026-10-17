"""Retired spellings of the test-run surface: refused by name, and found nowhere else in the tree."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from lab_commons.dev import forgecli, platformparts, pushgate, workstation
from lab_commons.hpc import __main__ as hpc_main
from lab_commons.hpc.retired import RETIRED, refusal, refuse_retired_keys

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
        pushgate.main(['--root', str(tmp_path), '--trunk-ref', 'none', '--remote-ref', 'r', flag, 'x'])
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


@pytest.mark.parametrize('flag', ['--install', '--needs'])
def test_the_build_flags_of_run_submit_are_refused_by_name(flag: str, capsys: pytest.CaptureFixture[str]) -> None:
    """How a cluster env is built is the commit's own [tool.lab_commons.hpc] declaration, read at --sha."""
    with pytest.raises(SystemExit):
        hpc_main.main(['run', 'submit', '--sha', 'a' * 40, f'{flag}=uv sync'])
    err = capsys.readouterr().err
    assert f'`run submit {flag}` is retired' in err
    assert '[tool.lab_commons.hpc]' in err


def test_a_retired_machine_file_key_is_refused_by_name() -> None:
    """PLANTED CONTROL: the same table without the retired key passes."""
    with pytest.raises(ValueError, match=r'\[serve\] own_weight is retired: .*own_reserve'):
        refuse_retired_keys('serve', {'own_weight': 2, 'repos': ['a']})
    refuse_retired_keys('serve', {'repos': ['a']})


@pytest.mark.parametrize('argv', [['serve', '--mode', 'integrate'], ['tick', '--mode', 'develop', '--json']])
def test_a_serve_mode_is_refused_by_name_every_host_serves_every_class(argv: list[str], capsys) -> None:
    assert forgecli.main(argv) == 2
    assert f'`forge {argv[0]} --mode` is retired' in capsys.readouterr().err


def test_the_workstation_task_with_a_mode_is_refused_naming_the_redeploy(capsys) -> None:
    assert workstation.main(['serve', '--mode', 'integrate']) == 2
    assert 'take no mode' in capsys.readouterr().err


@pytest.mark.parametrize('verb', ['reserve', 'release'])
def test_a_lease_verb_is_refused_by_name_nothing_is_reserved(verb: str, capsys) -> None:
    """Reservations, leases, lending and preemption are deleted (user ruling 2026-10-14)."""
    assert forgecli.main([verb, 'G', 'cpu=2']) == 2
    assert f'`forge {verb}` is retired' in capsys.readouterr().err


def test_a_workstation_delegate_is_refused_by_name(capsys) -> None:
    assert workstation.main(['deploy', '--delegates', 'bob']) == 2
    assert '`workstation --delegates` is retired' in capsys.readouterr().err
