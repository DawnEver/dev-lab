"""ONE uv cache per account: every uv the kit runs there shares it and hardlinks from it (2026-11-14).

A census of two serving accounts found two caches each (uv's default under ``~/.cache/uv`` and the forge's
``ci/uv-cache``), ~450 k files apiece: the tick's own env refreshes ran with uv's default. The tick
environment now exports the one cache, the deploy's env build hardlinks from it, and retention retires the
default cache once nothing writes it.
"""

from __future__ import annotations

import shlex
from datetime import UTC, datetime
from pathlib import Path

from dev_lab.dev import retentionplan
from dev_lab.dev.hpcaccount import spec


def test_the_tick_environment_exports_the_one_cache_and_hardlinks(tmp_path: Path) -> None:
    env = spec.tick_environment(tmp_path)
    cache = spec.uv_cache(tmp_path)
    assert f'export UV_CACHE_DIR={shlex.quote(str(cache))}' in env
    assert 'UV_LINK_MODE=hardlink' in env
    # the control: the cache is the forge's own, under the ci root, never uv's default
    assert cache == tmp_path / 'ci' / 'uv-cache'
    assert '.cache/uv' not in env


def test_retention_retires_the_default_cache_and_keeps_the_declared_one(tmp_path: Path) -> None:
    (tmp_path / '.cache' / 'uv').mkdir(parents=True)
    spec.uv_cache(tmp_path).mkdir(parents=True)
    doomed = retentionplan._home_rules(tmp_path, retentionplan.Policy(), datetime.now(UTC))
    paths = {d.path: d.rule for d in doomed}
    assert paths.get(tmp_path / '.cache' / 'uv') == 'uv-default-cache-retired'
    assert spec.uv_cache(tmp_path) not in paths
