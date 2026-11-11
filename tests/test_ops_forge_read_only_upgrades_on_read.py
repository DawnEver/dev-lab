"""A pre-#402 ``[ops.forge] read_only`` is UPGRADED ON READ (FORMATS-UPGRADE-ON-READ), never refused.

forge-a1, 2026-11-10: ``ops upgrade`` to the tip carrying #402 self-checked the host's CURRENT file, which still says
``read_only = ["server-reader"]``; the new reader refused it and the old reader refuses the new
``[ops.forge.accounts]`` file, so no order upgraded the host. The old list named no repositories (``account ensure``
took them as ``--read`` arguments), so an upgraded reader reads the host's own served Gitea repositories.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dev_lab.ops import upgrade
from dev_lab.ops.config import load

_HEAD = """
[ops]
home = "{home}"
python = "/opt/dev-lab/.venv/bin/python"
repos = ["https://forge.example/team/alpha.git", "https://forge.example/team/beta.git", "https://github.com/o/gamma.git"]
[ops.forge]
api = "http://127.0.0.1:9000"
admin = "admin"
"""
_OLD = _HEAD + 'read_only = ["reader"]\n'
_NEW = _HEAD + '[ops.forge.accounts.reader]\nrole = "read"\nrepos = ["team/alpha", "team/beta"]\n'


def _write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text.format(home=(tmp_path / 'home').as_posix()), encoding='utf-8')
    return path


def test_the_old_read_only_list_loads_as_its_new_shape_twin(tmp_path: Path) -> None:
    old = load(_write(tmp_path, 'old.toml', _OLD), environ={})
    new = load(_write(tmp_path, 'new.toml', _NEW), environ={})
    assert old.forge is not None
    assert new.forge is not None
    assert old.forge.accounts == new.forge.accounts
    assert old.forge.accounts['reader'] == {'role': 'read', 'repos': ['team/alpha', 'team/beta']}


def test_a_file_holding_both_shapes_is_refused(tmp_path: Path) -> None:  # PLANTED CONTROL
    both = _NEW.replace('admin = "admin"\n', 'admin = "admin"\nread_only = ["reader"]\n')
    with pytest.raises(ValueError, match=r'read_only.*accounts'):
        load(_write(tmp_path, 'both.toml', both), environ={})


def test_a_failed_self_check_names_what_its_load_refused(tmp_path: Path) -> None:
    """``self-check loads FAILED`` alone hid the refused key on forge-a1; the check's last line is named."""
    host = load(_write(tmp_path, 'new.toml', _NEW), environ={})
    said = 'Traceback ...\nValueError: [ops.forge] holds both read_only (retired by #402) and accounts\n'
    assert upgrade.failed_check(host, lambda _argv: (1, said)) == f'loads ({said.strip().splitlines()[-1]})'
    assert upgrade.failed_check(host, lambda _argv: (1, '')) == 'loads', 'a silent failure is still named'
    assert not upgrade.failed_check(host, lambda _argv: (0, 'ok'))
