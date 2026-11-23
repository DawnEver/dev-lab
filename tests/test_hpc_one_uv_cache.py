"""THE GARBAGE IS NOT PRODUCED (user ruling 2026-11-22): every uv the kit starts on an account writes the ONE cache.

The retired default ``~/.cache/uv`` held 313k files on one account. Each place that started uv without the declared
``UV_CACHE_DIR`` -- the first install, the kit refresh, the login shell, a ``[tools]`` install -- now names it.
PLANTED CONTROL: the default cache's path appears in none of them.
"""

from __future__ import annotations

from pathlib import Path

from lab_commons.hpc.grants import Grant

from dev_lab.dev.hpcaccount.checks import login_line
from dev_lab.dev.hpcaccount.fleet import Target, first_install, refresh_kit

ROOT = '/scratch/alice/lab'
CACHE = f'UV_CACHE_DIR={ROOT}/cache/uv'
TARGET = Target('login02.example', ROOT, repos=(('dev-lab', 'https://forge.example/dev-lab.git', 'main'),))


def _grant() -> Grant:
    return Grant(user='alice', hosts=('login02.example',), slurm_account='acct', cluster_name='c1')


def test_the_login_shell_exports_the_one_cache(tmp_path: Path) -> None:
    line = login_line(tmp_path, ROOT)
    assert CACHE in line.replace('\\', '/')
    assert '.cache/uv' not in line


def test_the_first_install_and_the_kit_refresh_use_the_one_cache() -> None:
    for line in (first_install(_grant(), TARGET), refresh_kit(_grant(), TARGET)):
        assert CACHE in line
        assert '.cache/uv' not in line
