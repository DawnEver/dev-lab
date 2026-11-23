"""A DEPLOY NEVER STARTS WHAT CANNOT FIT (user ruling 2026-11-22): the ``[headroom]`` phase, before any write.

PLANTED CONTROL beside each refusal: an account with room deploys, and an unread quota never refuses.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from dev_lab.dev.diskusage import Usage
from dev_lab.dev.hpcaccount import headroom
from dev_lab.dev.hpcaccount.spec import Deployment, Repo, checkout_of
from dev_lab.dev.hpcaccount.steps import Step, Tools

_GB = 1024**3


def _spec(root: Path) -> Deployment:
    repos = (Repo('kit', 'https://forge.example/kit.git', 'main'), Repo('app', 'https://forge.example/app.git', 'main'))
    return Deployment(host='login01', root=root.as_posix(), python='3.13', repos=repos)


def _step(tmp_path: Path) -> tuple[Step, Path]:
    calls = tmp_path / 'calls.log'
    log = tmp_path / 'log.py'
    log.write_text('import sys\nopen(sys.argv[1], "a").write(" ".join(sys.argv[2:]) + "\\n")\n', encoding='utf-8')
    return Step(Tools(sh=(sys.executable, str(log), str(calls))), dry=False), calls


def _usage(files: int) -> Usage:
    return Usage(40 * _GB, 1000 * _GB, files, 2_000_000)


def test_the_estimate_prices_a_venv_from_the_current_one_and_a_missing_clone_by_prior(tmp_path: Path) -> None:
    spec = _spec(tmp_path)
    kit = checkout_of(spec, spec.repos[0])
    (kit / '.git').mkdir(parents=True)
    (kit / '.venv' / 'lib').mkdir(parents=True)
    (kit / '.venv' / 'lib' / 'a.py').write_text('', encoding='utf-8')
    need, said = headroom.estimate(spec)
    assert need == 3 + headroom.VENV_FILES + headroom.CHECKOUT_FILES
    assert said[0].startswith('kit: venv 3 files (measured from ')
    assert said[1] == f'app: venv {headroom.VENV_FILES} files (the prior, no venv yet) + checkout 20000 files'


def test_too_little_file_headroom_is_refused_by_name_with_retention_run_first(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    step, calls = _step(tmp_path)
    rc = headroom.check(step, _spec(tmp_path), tmp_path, read=lambda _home: _usage(1_990_000))
    err = capsys.readouterr().err
    assert rc == 2
    assert f'deploy refused: {headroom.REFUSED}: up to 100000 files to write, 10000 left' in err
    assert 'nothing was written' in err
    assert 'dev_lab.dev.retention --cluster --apply' in calls.read_text(encoding='utf-8'), 'retention ran first'
    assert not (tmp_path / 'repos').exists(), 'a refusal writes nothing'


def test_planted_control_an_account_with_room_deploys_without_retention(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    step, calls = _step(tmp_path)
    rc = headroom.check(step, _spec(tmp_path), tmp_path, read=lambda _home: _usage(400_000))
    out = capsys.readouterr().out
    assert rc == 0
    assert 'usage files 400000/2000000 (20.0%), headroom 1600000 files; bytes ' in out
    assert 'fits: up to 100000 files to write, 1600000 left' in out
    assert not calls.exists(), 'no retention under the warning line'


def test_retention_that_frees_enough_lets_the_deploy_go_on(tmp_path: Path) -> None:
    step, _ = _step(tmp_path)
    reads = iter([_usage(1_950_000), _usage(1_500_000)])
    assert headroom.check(step, _spec(tmp_path), tmp_path, read=lambda _home: next(reads)) == 0


def test_planted_control_an_unread_quota_never_refuses(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    step, _ = _step(tmp_path)
    assert headroom.check(step, _spec(tmp_path), tmp_path, read=lambda _home: None) == 0
    assert 'usage unread' in capsys.readouterr().out
