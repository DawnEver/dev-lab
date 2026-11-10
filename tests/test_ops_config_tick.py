"""``config tick`` applies a merged routine change by itself and parks a boundary change for consent, once."""

from __future__ import annotations

from pathlib import Path

from _ops_fixtures import config

from dev_lab.ops.configdoor import tick
from dev_lab.ops.install import files

LIVE = """\
[cycle]
interval_s = 60

[ops]
home = "/var/lib/ops"
python = "/opt/dev-lab/.venv/bin/python"
"""


def _ok(_path: Path) -> object:
    return None


def _green(_argv: list[str]) -> tuple[int, str]:
    return 0, 'ok'


def _run(tmp_path: Path, candidate: str, notes: list[str]) -> str:
    return tick(
        tmp_path / 'supervise.toml', candidate, pending=tmp_path / 'pending', notify=notes.append,
        loads=_ok, checks={}, run=_green,
    )  # fmt: skip


def _live(tmp_path: Path) -> Path:
    path = tmp_path / 'supervise.toml'
    path.write_text(LIVE, encoding='utf-8')
    return path


def test_a_routine_change_applies_without_anyone(tmp_path: Path) -> None:
    live, notes = _live(tmp_path), []
    assert _run(tmp_path, LIVE.replace('= 60', '= 90'), notes) == 'applied'
    assert '= 90' in live.read_text(encoding='utf-8')
    assert notes == []


def test_a_boundary_change_waits_for_consent_and_says_so_once(tmp_path: Path) -> None:
    live, notes = _live(tmp_path), []
    candidate = LIVE.replace('/opt/dev-lab', '/srv/dev-lab')
    assert _run(tmp_path, candidate, notes) == 'needs-consent'
    assert _run(tmp_path, candidate, notes) == 'needs-consent'
    assert live.read_text(encoding='utf-8') == LIVE
    assert len(notes) == 1
    assert 'ops.python' in notes[0]
    assert 'config apply --credential' in notes[0]


def test_nothing_to_do_clears_a_parked_change(tmp_path: Path) -> None:
    _live(tmp_path)
    (tmp_path / 'pending').write_text('x', encoding='utf-8')
    assert _run(tmp_path, LIVE, []) == 'unchanged'
    assert not (tmp_path / 'pending').exists()


def test_a_schedule_renders_a_root_tick_timer(tmp_path: Path) -> None:
    extra = (
        '[ops.config]\nsource = "https://forge.example/o/cfg.git"\npath = "hosts/h.toml"\n'
        'token_file = "/etc/dev-lab/cfg.token"\nschedule = "hourly"\n'
    )
    rendered = files(config(tmp_path, [], extra=extra))
    assert 'OnCalendar=hourly' in rendered['etc/systemd/system/dev-lab-ops-config-tick.timer']
    service = rendered['etc/systemd/system/dev-lab-ops-config-tick.service']
    assert 'config tick' in service
    assert 'User=' not in service  # it writes the root-owned live file


def test_no_schedule_renders_no_tick(tmp_path: Path) -> None:
    extra = '[ops.config]\nsource = "https://forge.example/o/cfg.git"\npath = "h.toml"\ntoken_file = "/t"\n'
    assert not any('config-tick' in path for path in files(config(tmp_path, [], extra=extra)))
