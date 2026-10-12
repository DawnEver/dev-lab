"""The serve lock: one ``forge serve`` per host, a second one exits 0 doing nothing; and the stop notes."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

from lab_commons.dev import forgecli
from lab_commons.dev.servelock import default_lock, held, note_stopped, was_stopped

_HOLD = (
    'import sys, time\n'
    'from pathlib import Path\n'
    'from lab_commons.dev.servelock import held\n'
    'with held(Path(sys.argv[1])) as mine:\n'
    '    print("held" if mine else "busy", flush=True)\n'
    '    time.sleep(30 if mine else 0)\n'
)


def test_a_second_holder_is_refused_while_the_first_lives_and_admitted_after(tmp_path: Path) -> None:
    lock = tmp_path / 'deep' / 'serve.lock'
    first = subprocess.Popen(
        [sys.executable, '-c', _HOLD, str(lock)], stdout=subprocess.PIPE, text=True, encoding='utf-8'
    )
    try:
        assert first.stdout is not None
        assert first.stdout.readline().strip() == 'held'
        with held(lock) as mine:
            assert not mine
    finally:
        first.kill()
        first.wait(timeout=30)
    assert _free_within(lock, seconds=10), 'the OS frees a dead holder lock (on Windows, shortly after exit)'


def _free_within(lock: Path, *, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        with held(lock) as mine:
            if mine:
                return True
        time.sleep(0.1)
    return False


def test_the_default_lock_lives_in_the_per_user_cache() -> None:
    path = default_lock()
    assert path.parts[-2:] == ('lab-forge', 'serve.lock')
    assert path.is_absolute()


def test_a_stop_note_is_read_once(tmp_path: Path) -> None:
    assert not was_stopped(4242, root=tmp_path)
    note_stopped(4242, root=tmp_path)
    assert was_stopped(4242, root=tmp_path)
    assert not was_stopped(4242, root=tmp_path)


def test_a_second_serve_on_a_held_lock_exits_zero_doing_nothing(monkeypatch, tmp_path: Path, capsys) -> None:
    called: list[list[str]] = []
    monkeypatch.setattr(forgecli.forgeserve, 'main', lambda argv: called.append(argv) or 0)
    lock = tmp_path / 'serve.lock'
    with held(lock) as mine:
        assert mine
        assert forgecli.main(['serve', '--mode', 'integrate', '--lock', str(lock)]) == 0
    assert called == []
    assert 'another forge serve holds' in capsys.readouterr().err
    assert forgecli.main(['serve', '--mode', 'integrate', '--lock', str(lock)]) == 0
    assert called == [['--mode', 'integrate']]
