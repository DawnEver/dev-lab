"""The shell-path helper answers for EVERY ``sh`` spelling a Windows host has, not only one beside ``cygpath``."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from _sh_native import native


def _spellings() -> list[str]:
    """The PATH's ``sh`` and, on Git for Windows, the wrapper ``<git>/bin/sh.exe`` that has no ``cygpath`` beside it."""
    sh = shutil.which('sh')
    assert sh, 'every host the kit serves has a POSIX sh'
    found = [sh]
    for parent in Path(sh).parents:
        wrapper = parent / 'bin' / 'sh.exe'
        if wrapper.is_file() and not wrapper.with_name('cygpath.exe').exists() and wrapper != Path(sh):
            found.append(str(wrapper))
            break
    return found


@pytest.mark.parametrize('sh', _spellings())
def test_a_path_the_shell_printed_is_the_directory_it_named(tmp_path: Path, sh: str) -> None:
    printed = subprocess.run(
        [sh, '-c', 'cd "$1" && pwd', 'sh', tmp_path.as_posix()],
        capture_output=True, text=True, encoding='utf-8', check=True, timeout=60,
    ).stdout.strip()  # fmt: skip
    assert Path(native(printed, sh)).samefile(tmp_path)


def test_off_windows_the_answer_is_the_shells_own() -> None:
    assert native('/srv/x', 'no-such-sh', windows=False) == '/srv/x'


def test_a_windows_spelling_is_left_alone() -> None:
    assert native('C:/srv/x', 'no-such-sh', windows=True) == 'C:/srv/x'
