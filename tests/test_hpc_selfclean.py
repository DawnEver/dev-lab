"""A FAILED STEP CLEANS ITS OWN HALF-BUILT OUTPUT (user ruling 2026-11-22).

PLANTED CONTROLS: the current venv, a good checkout and a healthy cache entry are untouched by every cleanup.
"""

from __future__ import annotations

import sys
from pathlib import Path

from dev_lab.dev import venvpointer
from dev_lab.dev.hpcaccount import selfclean, steps
from dev_lab.dev.hpcaccount.spec import Repo
from dev_lab.dev.hpcaccount.steps import Step, Tools

SHA = 'a1b2c3d4e5f60718293a4b5c6d7e8f9012345678'
UV_GIT_FAILURE = (
    f'error: Failed to download and build `lab-commons @ git+https://forge.example/lab-commons.git@{SHA}`\n'
    '  Caused by: Git operation failed\n'
    f"  Caused by: process didn't exit successfully: `git reset --hard {SHA}` (exit status: 128)\n"
)
#: A fake ``sh``: appends its run to argv[1]; fails printing argv[2]'s text while argv[3] (a flag file) exists,
#: leaving a uv temporary behind; on success makes the env uv was told to build.
FAKE_SH = """
import os, pathlib, sys
log, text, flag = sys.argv[1:4]
open(log, 'a').write('run\\n')
cache = pathlib.Path(os.environ['UV_CACHE_DIR'])
if os.path.exists(flag):
    (cache / '.tmpXYZ').mkdir(parents=True, exist_ok=True)
    os.remove(flag) if 'once' in open(flag).read() else None
    print(open(text).read()); sys.exit(1)
pathlib.Path(os.environ['UV_PROJECT_ENVIRONMENT']).mkdir(parents=True)
"""


def _cache(tmp_path: Path) -> Path:
    cache = tmp_path / 'cache' / 'uv'
    (cache / 'git-v0' / 'checkouts' / 'repo1' / SHA[:7]).mkdir(parents=True)
    (cache / 'git-v0' / 'checkouts' / 'repo1' / 'ffffff0').mkdir(parents=True)  # PLANTED CONTROL: another commit
    (cache / 'archive-v0' / 'healthy').mkdir(parents=True)  # PLANTED CONTROL: a healthy entry
    return cache


def test_a_damaged_uv_git_checkout_is_removed_alone(tmp_path: Path) -> None:
    cache = _cache(tmp_path)
    assert selfclean.damaged_git(cache, UV_GIT_FAILURE) == [cache / 'git-v0' / 'checkouts' / 'repo1' / SHA[:7]]
    assert (cache / 'git-v0' / 'checkouts' / 'repo1' / 'ffffff0').is_dir()
    assert (cache / 'archive-v0' / 'healthy').is_dir()


def test_planted_control_a_failure_not_on_the_git_cache_removes_nothing(tmp_path: Path) -> None:
    cache = _cache(tmp_path)
    assert selfclean.damaged_git(cache, 'error: No solution found when resolving dependencies') == []
    assert (cache / 'git-v0' / 'checkouts' / 'repo1' / SHA[:7]).is_dir()


def _build(tmp_path: Path, flag: str) -> tuple[Path | int, Path, Path, Path]:
    cache, checkout, log = _cache(tmp_path), tmp_path / 'repos' / 'app', tmp_path / 'log'
    live = checkout / '.venvs' / 'live'
    live.mkdir(parents=True)
    venvpointer_link = checkout / venvpointer.POINTER
    venvpointer_link.mkdir()  # PLANTED CONTROL: the current venv
    text, flagfile = tmp_path / 'text', tmp_path / 'flag'
    text.write_text(UV_GIT_FAILURE, encoding='utf-8')
    flagfile.write_text(flag, encoding='utf-8')
    fake = tmp_path / 'sh.py'
    fake.write_text(FAKE_SH, encoding='utf-8')
    step = Step(Tools(sh=(sys.executable, str(fake), str(log), str(text), str(flagfile))), dry=False)
    built = steps._beside(step, 'app', checkout, 'uv sync', {'UV_CACHE_DIR': str(cache)})
    return built, checkout, cache, log


def test_a_build_failing_on_the_git_cache_cleans_and_retries_once(tmp_path: Path) -> None:
    built, checkout, cache, log = _build(tmp_path, 'once')
    assert isinstance(built, Path)
    assert built.is_dir()
    assert log.read_text(encoding='utf-8').count('run') == 2
    assert not list(cache.glob('.tmp*')), 'the failed run left its uv temporary'
    assert (checkout / '.venvs' / 'live').is_dir()
    assert (checkout / '.venv').is_dir(), 'the current venv is untouched'


def test_a_build_that_keeps_failing_leaves_no_half_built_env(tmp_path: Path) -> None:
    built, checkout, cache, log = _build(tmp_path, 'always')
    assert built == 1
    assert log.read_text(encoding='utf-8').count('run') == 2, 'retried once, never more'
    assert sorted(p.name for p in (checkout / '.venvs').iterdir()) == ['live'], 'only the env it did not build stays'
    assert not list(cache.glob('.tmp*'))
    assert (cache / 'archive-v0' / 'healthy').is_dir()


def test_a_failed_fresh_clone_leaves_no_directory_and_a_good_checkout_stays(tmp_path: Path) -> None:
    fake = tmp_path / 'git.py'
    fake.write_text(
        'import pathlib, sys\nif "clone" in sys.argv:\n    pathlib.Path(sys.argv[-1], "half").mkdir(parents=True)\n'
        '    sys.exit(128)\n',
        encoding='utf-8',
    )
    step = Step(Tools(git=(sys.executable, str(fake))), dry=False)
    spec = steps.Deployment(host='h', root=tmp_path.as_posix(), python='3.13', repos=())
    repo = Repo('app', 'https://forge.example/app.git', 'main')
    assert steps.update(step, spec, tmp_path, repo) == 128
    assert not steps.checkout_of(spec, repo).exists()
    good = steps.checkout_of(spec, Repo('kit', 'https://forge.example/kit.git', 'main'))
    (good / '.git').mkdir(parents=True)  # PLANTED CONTROL: a good checkout is fetched, never removed
    assert steps.update(step, spec, tmp_path, Repo('kit', 'https://forge.example/kit.git', 'main')) == 0
    assert (good / '.git').is_dir()
