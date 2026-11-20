"""An HPC account's own tool paths live once, in its file's ``[env]``, and every tick exports them (#621)."""

from __future__ import annotations

import shlex
from pathlib import Path

import pytest

from dev_lab.dev import accounthost
from dev_lab.dev.hpcaccount import spec

_DEPLOY = {'host': 'h', 'root': '/r', 'repos': [{'name': 'dev-lab', 'url': 'https://x/dev-lab', 'ref': 'main'}]}


def test_the_account_env_is_parsed_and_exported_in_every_tick(tmp_path: Path) -> None:
    parsed = spec.parse({'deploy': _DEPLOY, 'env': {'FEMM_DIR': '~/opt/femm', 'TOOL': '/abs/tool'}}, tmp_path)
    assert parsed is not None
    assert parsed.env == (('FEMM_DIR', '~/opt/femm'), ('TOOL', '/abs/tool'))
    line = spec.tick_environment(tmp_path, tmp_path.as_posix(), (), (), parsed.env)
    assert f'FEMM_DIR={shlex.quote(str(tmp_path / "opt/femm"))}' in line
    assert 'TOOL=/abs/tool' in line
    assert 'UV_LINK_MODE=hardlink' in line


def test_an_account_without_env_exports_nothing_more(tmp_path: Path) -> None:
    """PLANTED CONTROL: no [env], no extra export -- the tick line is what it was."""
    parsed = spec.parse({'deploy': _DEPLOY}, tmp_path)
    assert parsed is not None
    assert parsed.env == ()
    assert spec.tick_environment(tmp_path, tmp_path.as_posix(), (), (), parsed.env) == spec.tick_environment(
        tmp_path, tmp_path.as_posix()
    )


@pytest.mark.parametrize('bad', [{'femm_dir': '/x'}, {'FEMM DIR': '/x'}, {'FEMM_DIR': 5}])
def test_a_malformed_env_is_refused_by_name(tmp_path: Path, bad: dict[str, object]) -> None:
    with pytest.raises(ValueError, match=r'\[env\]'):
        spec.parse({'deploy': _DEPLOY, 'env': bad}, tmp_path)


def test_an_account_file_may_declare_env() -> None:
    assert 'env' in accounthost.TABLES
