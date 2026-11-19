"""A dispatcher killed mid-run loses nothing it was handed (HOOK-UNDER-FIVE-SECONDS, user ruling D24).

The harness kills a hook at its timeout, with no cleanup. Measured 2026-11-17 on a cold, starved workstation the
dispatcher ran up to 4.8 s, and it queued its detached rows only after its inline rows had run: a kill there meant
the session start's background rows never ran. So the queue is written FIRST -- the detached rows as a job, the
inline rows as a write-ahead record -- and the runner adopts the record of a dispatcher that died.

The kill is the hardest there is: the interpreter running the dispatcher is terminated by its own pid, inside its first
inline row.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

#: The first inline row: on its first run it records the dispatcher's pid, then blocks when its checkout holds a
#: ``block`` file, so the test can kill the dispatcher inside it; run a second time it only says so.
_FIRST = """import json, os, pathlib, sys, time


def main(argv):
    json.load(sys.stdin)
    here = pathlib.Path(__file__).with_name
    if here('first-started').is_file():
        here('first-rerun').write_text('done', encoding='utf-8')
        return 0
    here('first-started').write_text(str(os.getpid()), encoding='utf-8')
    if here('block').is_file():
        time.sleep(60)
    return 0
"""

_MARK = """import json, pathlib, sys


def main(argv):
    json.load(sys.stdin)
    pathlib.Path(__file__).with_name('{marker}').write_text('done', encoding='utf-8')
    return 0
"""

_EVENT = 'PreCompact'  # an event the family serves no row on, so only the planted rows run


def _consumer(root: Path, *, block: bool) -> Path:
    (root / '.git').mkdir(parents=True)
    rows = [
        ('planted_killed_first', f'events = ["{_EVENT}"]', _FIRST),
        ('planted_killed_second', f'events = ["{_EVENT}"]', _MARK.format(marker='second-done')),
        ('planted_killed_bg', f'events = ["{_EVENT}"]\ndetached = true', _MARK.format(marker='bg-done')),
    ]
    (root / 'pyproject.toml').write_text(
        ''.join(f'[[tool.dev_lab.agent_hooks]]\nmodule = "{module}"\n{row}\n\n' for module, row, _ in rows),
        encoding='utf-8',
    )
    for module, _row, body in rows:
        (root / f'{module}.py').write_text(body, encoding='utf-8')
    if block:
        (root / 'block').write_text('', encoding='utf-8')
    return root


def _start(root: Path) -> subprocess.Popen[str]:
    dispatcher = subprocess.Popen(
        [sys.executable, '-m', 'dev_lab.dev.hookdispatch', _EVENT],
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True, encoding='utf-8',
        cwd=root, env={**os.environ, 'CLAUDE_PROJECT_DIR': str(root)},
    )  # fmt: skip
    assert dispatcher.stdin is not None
    dispatcher.stdin.write(json.dumps({'session_id': 'killed', 'cwd': str(root), 'hook_event_name': _EVENT}))
    dispatcher.stdin.close()
    return dispatcher


def _wait(*paths: Path, within: float) -> bool:
    deadline = time.monotonic() + within
    while time.monotonic() < deadline and not all(path.is_file() for path in paths):
        time.sleep(0.25)
    return all(path.is_file() for path in paths)


def _kill(pid: int) -> None:
    """Terminate the interpreter *pid* with no cleanup: TerminateProcess on Windows, SIGKILL elsewhere."""
    os.kill(pid, signal.SIGTERM if sys.platform == 'win32' else signal.SIGKILL)


def _seen(root: Path) -> list[str]:
    return sorted(path.name for path in root.iterdir() if path.suffix != '.py')


def test_a_dispatcher_killed_inside_its_first_inline_row_loses_no_row(tmp_path: Path) -> None:
    """The detached row and the inline rows -- the killed one again, the one not yet started -- all complete."""
    root = _consumer(tmp_path / 'consumer', block=True)
    dispatcher = _start(root)
    try:
        assert _wait(root / 'first-started', within=30), 'the first inline row never started'
        _kill(int((root / 'first-started').read_text(encoding='utf-8')))
    finally:
        dispatcher.wait(timeout=30)
    assert _wait(root / 'bg-done', root / 'second-done', root / 'first-rerun', within=60), _seen(root)


def test_a_dispatcher_that_finishes_runs_each_inline_row_once(tmp_path: Path) -> None:
    """PLANTED CONTROL: unkilled, the write-ahead record is settled, so no inline row runs a second time.

    The rerun marker is the instrument the kill arm reads; here it must stay absent while the detached row completes.
    """
    root = _consumer(tmp_path / 'consumer', block=False)
    assert _start(root).wait(timeout=60) == 0
    assert (root / 'second-done').is_file(), 'the inline rows ran inline'
    assert _wait(root / 'bg-done', within=60), _seen(root)
    time.sleep(2)  # past the runner's adoption check: a settled record must not be adopted late
    assert not (root / 'first-rerun').exists(), _seen(root)
