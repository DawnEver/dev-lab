"""A session's background shell lives fifty minutes: the reaper's planted controls, both sides of every line.

A planted process table drives the logic and a recording ``kill`` stands in for the tree-kill: no real
process is ever stopped here. The four controls the 2026-11-15 demand named -- a young shell survives, an
old one is stopped, a seat-holding run of any age survives, a process outside any agent tree survives --
plus the declared longer bound, the serve and declared spares, an orphaned harness shell, and the hook's
rate limit.
"""

from __future__ import annotations

import io
import json
import os
from collections.abc import Callable
from pathlib import Path

import pytest
from lab_commons.census import Process

from dev_lab.dev import shellreaper
from dev_lab.dev.agent_wiring import WIRING
from dev_lab.dev.shelllife import Grants
from dev_lab.dev.shellreaper import shell_roots, sweep

_CLAUDE = r'C:\tools\claude-code\bin\claude.exe'
_BASH = r'C:\Program Files\Git\usr\bin\bash.exe'
_HARNESS = '"bash.exe" -c "source ~/.claude/shell-snapshots/snapshot-bash-1-x.sh && eval \'{cmd}\'"'
_HOUR = 3600.0


def _p(pid: int, ppid: int, exe: str, cmd: str, age: float | None) -> Process:
    return Process(pid=pid, ppid=ppid, executable=exe, command_line=cmd, age_s=age)


def _shell(pid: int, cmd: str, age: float | None, ppid: int = 100) -> Process:
    return _p(pid, ppid, _BASH, _HARNESS.format(cmd=cmd), age)


def _table(*extra: Process) -> list[Process]:
    return [
        _p(1, 0, 'init', 'init', 9 * _HOUR),
        _p(50, 1, r'C:\Windows\explorer.exe', 'explorer.exe', 9 * _HOUR),
        _p(100, 50, _CLAUDE, f'"{_CLAUDE}" --session-id s', 9 * _HOUR),
        *extra,
    ]


def _sweep(
    procs: list[Process],
    *,
    claimed: Callable[[], set[int]] = set,
    spares: tuple[str, ...] = (),
    grants: Grants = lambda _id, _when: None,
) -> tuple[list[int], list[str]]:
    killed: list[int] = []
    lines = sweep(procs, claimed=claimed, spares=spares, kill=killed.append, born=lambda _p: 1, grants=grants)
    return killed, lines


def test_an_old_shell_is_stopped_children_first_and_a_young_one_survives() -> None:
    procs = _table(
        _shell(200, 'until x; do sleep 60; done', 51 * 60.0),
        _p(201, 200, r'C:\bin\sleep.exe', 'sleep 60', 30.0),
        _shell(300, 'forge watch --stream', 49 * 60.0),
    )
    killed, lines = _sweep(procs)
    assert killed == [201, 200], lines
    assert any('stopped 200' in line for line in lines)


_GRANT = '0f0e0d0c-0b0a-4908-8706-050403020100'


def test_only_a_users_grant_lengthens_a_life_and_its_end_is_still_enforced() -> None:
    granted = {_GRANT: ('digest', 6 * _HOUR)}

    def grants(grant_id: str, _when: float) -> tuple[str, float] | None:
        return granted.get(grant_id)

    bare = _table(_shell(200, 'timeout 6h python -m x', 51 * 60.0))
    assert _sweep(bare, grants=grants)[0] == [200], 'an agent-written longer timeout outlived the default'
    young = _table(_shell(200, f'DEV_LAB_LIFETIME_GRANT={_GRANT} timeout 6h python -m x', 2 * _HOUR))
    assert _sweep(young, grants=grants)[0] == []
    old = _table(_shell(200, f'DEV_LAB_LIFETIME_GRANT={_GRANT} timeout 6h python -m x', 7 * _HOUR))
    assert _sweep(old, grants=grants)[0] == [200]
    unknown = _table(_shell(200, f'DEV_LAB_LIFETIME_GRANT={_GRANT[::-1]} timeout 6h x', 51 * 60.0))
    assert _sweep(unknown, grants=grants)[0] == [200]


def test_a_seat_holding_run_of_any_age_survives() -> None:
    procs = _table(_shell(200, 'consumer case run c', 30 * _HOUR), _p(201, 200, 'python.exe', 'python run', 9.0))
    killed, lines = _sweep(procs, claimed=lambda: {201})
    assert killed == []
    assert any('box' in line for line in lines), lines


def test_an_unreadable_ledger_stops_nothing() -> None:
    def broken() -> set[int]:
        msg = 'locked'
        raise OSError(msg)

    killed, lines = _sweep(_table(_shell(200, 'sleep 1d', 2 * _HOUR)), claimed=broken)
    assert killed == []
    assert any('ledger' in line for line in lines)


def test_a_serve_and_a_declared_spare_survive() -> None:
    serve = _table(_shell(200, 'python -m dev_lab.dev.forge serve --lock', 9 * _HOUR))
    assert _sweep(serve)[0] == []
    case = _table(_shell(200, 'uv run consumer case run c', 9 * _HOUR))
    assert _sweep(case, spares=(r'consumer\s+case\s+run',))[0] == []
    assert _sweep(case)[0] == [200]


def test_a_process_outside_any_agent_tree_survives() -> None:
    procs = _table(
        _p(400, 50, _BASH, '"bash.exe" --login -i', 9 * _HOUR),  # the user's own terminal
        _p(401, 400, _BASH, '"bash.exe" -c "sleep 1d"', 9 * _HOUR),
        _p(402, 100, r'C:\Windows\System32\cmd.exe', 'cmd /c npx mcp-server', 9 * _HOUR),  # an MCP server
    )
    assert [p.pid for p in shell_roots(procs)] == []
    assert _sweep(procs)[0] == []


def test_a_harness_shell_whose_session_ended_is_still_an_agent_shell() -> None:
    orphan = _shell(200, 'forge watch --stream', 3 * _HOUR, ppid=999)
    nested = _shell(201, 'inner', 3 * _HOUR, ppid=200)
    assert [p.pid for p in shell_roots(_table(orphan, nested))] == [200]
    assert _sweep(_table(orphan, nested))[0] == [201, 200]


def test_an_unknown_age_is_never_stopped() -> None:
    assert _sweep(_table(_shell(200, 'sleep 1d', None)))[0] == []


def test_the_hook_detaches_one_sweep_per_interval_and_never_blocks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    started: list[Path] = []
    monkeypatch.setattr(shellreaper, 'repo_main', lambda _cwd: tmp_path)
    monkeypatch.setattr(shellreaper, 'common_dir', lambda _root: tmp_path)
    monkeypatch.setattr(shellreaper, 'detach_argv', lambda root, _args: started.append(root))
    payload = json.dumps({'cwd': str(tmp_path)})
    assert shellreaper.main(['--hook'], stdin=io.StringIO(payload)) == 0
    assert shellreaper.main(['--hook'], stdin=io.StringIO(payload)) == 0
    assert started == [tmp_path], 'a second hook within the interval detached another sweep'
    stamp = tmp_path / shellreaper.STAMP_NAME
    old = stamp.stat().st_mtime - shellreaper.SWEEP_INTERVAL_S - 1
    os.utime(stamp, (old, old))
    assert shellreaper.main(['--hook'], stdin=io.StringIO(payload)) == 0
    assert started == [tmp_path, tmp_path]


def test_a_sweep_logs_each_stop_under_the_reaper_kind(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / '.git').mkdir()
    monkeypatch.setattr(shellreaper, 'sweep', lambda _procs, **_kw: ['stopped 200  bash'])
    monkeypatch.setattr(shellreaper, 'processes', list)
    log = shellreaper.run(tmp_path)
    assert log is not None
    assert log.parent.name == 'reaper'
    assert 'stopped 200' in log.read_text(encoding='utf-8')


def test_the_sweep_has_one_trigger_every_stop() -> None:
    """ONE trigger: Stop, the only event that recurs inside a session, so the bound's clock.

    A session's first stop also sweeps what an ended session left, which is all a SessionStart sweep did (measured
    2026-11-16: 37 sweeps and both over-bound stops of the day fell in an 11-hour window with no session start).
    PLANTED CONTROL: no row of the sweep is on SessionStart, and exactly one row names it.
    """
    rows = [w for w in WIRING if w.module == 'dev_lab.dev.shellreaper']
    assert [(w.events, w.argv) for w in rows] == [(('Stop',), ('--hook',))]
    assert not any('SessionStart' in w.events for w in rows)
