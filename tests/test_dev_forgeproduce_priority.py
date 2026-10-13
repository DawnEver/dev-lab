"""A PRODUCER RUNS BELOW NORMAL PRIORITY, so an interactive run on the same box stays responsive.

User ruling 2026-10-13 (light runs never queue): a light run is admitted beside a heavy part, and the
OS scheduler is what keeps it responsive there. MEASURED, not asserted from the spawn arguments: a real
child is started through :func:`lab_commons.dev.forgeproduce.below_normal` and its priority is read
back from the OS. PLANTED CONTROL: the same child started plainly reads normal priority.
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from collections.abc import Callable
from typing import Any

from lab_commons.dev.forgeproduce import BELOW_NORMAL_NICE, below_normal

_SLEEP = [sys.executable, '-c', 'import time; time.sleep(60)']
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_NORMAL_PRIORITY_CLASS = 0x0020
_BELOW_NORMAL_PRIORITY_CLASS = 0x4000


def _priority(pid: int) -> int:
    """The OS's own reading: Windows' priority class, else the POSIX niceness."""
    if sys.platform != 'win32':
        return os.getpriority(os.PRIO_PROCESS, pid)
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel32.OpenProcess.restype = ctypes.c_void_p
    handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, 0, pid)  # 0: a Win32 BOOL, not inherited
    assert handle, f'cannot open pid {pid}: {ctypes.get_last_error()}'
    try:
        return kernel32.GetPriorityClass(ctypes.c_void_p(handle))
    finally:
        kernel32.CloseHandle(ctypes.c_void_p(handle))


def _read(start: Callable[..., Any]) -> int:
    child = start(_SLEEP, stdout=subprocess.DEVNULL)
    try:
        return _priority(child.pid)
    finally:
        child.kill()
        child.wait(timeout=30)


def test_a_producer_child_reads_below_normal_priority_from_the_os() -> None:
    """THE CHECK, with its planted control: the plain child is normal, the producer child is below it."""
    if sys.platform == 'win32':
        assert _read(subprocess.Popen) == _NORMAL_PRIORITY_CLASS
        assert _read(lambda argv, **kw: below_normal(subprocess.Popen, argv, **kw)) == _BELOW_NORMAL_PRIORITY_CLASS
    else:
        own = os.getpriority(os.PRIO_PROCESS, 0)
        assert _read(subprocess.Popen) == own
        lowered = _read(lambda argv, **kw: below_normal(subprocess.Popen, argv, **kw))
        assert lowered == max(own, BELOW_NORMAL_NICE)
