"""The remote command reaches the host byte for byte, however deeply it nests its quotes.

Measured 2026-11-27, twice. ``deploy-fleet --account ezxmw9`` died remotely with ``unexpected EOF while looking for
matching `''``, then (with ``bash -lc "$(... | base64 -d)"``) with ``... matching `)'``: the ssh on PATH is Git's
MSYS ssh, whose runtime re-splits a command line from a native process and drops quote characters, so any ``'`` or
``"`` in the element is lost. The element therefore holds NO quote at all: the command travels base64-encoded into a
temporary file the login shell runs, so the command's own stdin (``crontab -``, a piped script) stays its own.
"""

from __future__ import annotations

import base64
import os
import shlex
import shutil
import subprocess
from pathlib import Path

from dev_lab.dev import remote

#: Where Git's MSYS runtime cut an element holding a space (measured 2026-11-27: 8186 characters kept).
CUT = 8186

#: Nested quoting as the deploy line builds it (bash -lc of bash -c of sbatch --wrap), reading its stdin, and long:
#: longer than the MSYS cut (CUT).
NESTED = 'cat; echo "a b"; ' + shlex.join(['bash', '-lc', shlex.join(['bash', '-c', "printf '%s' \"x'y\""])]) * 120


def _tail() -> list[str]:
    """What follows the destination in the ssh argv: the elements the MSYS runtime re-splits."""
    argv = remote.ssh_argv('dev@other.example', NESTED, batch=True)
    return argv[argv.index('dev@other.example') + 1 :]


def _msys_bash() -> str:
    """The shell whose argv parsing IS the ssh's: Git's MSYS runtime beside the ssh on Windows, else bash."""
    ssh = shutil.which('ssh')
    beside = Path(ssh).with_name('bash.exe') if ssh and os.name == 'nt' else None
    found = str(beside) if beside is not None and beside.is_file() else shutil.which('bash')
    assert found is not None, 'a POSIX bash is the remote shell this test stands in for'
    return found


def test_no_element_holds_a_quote_or_is_both_spaced_and_long_and_they_decode_to_the_command() -> None:
    """PLANTED CONTROL: the command is dense with ``'`` and ``"`` and longer than the MSYS cut; no element is."""
    assert "'" in NESTED
    assert '"' in NESTED
    assert len(NESTED) > CUT
    tail = _tail()
    assert not [element for element in tail if "'" in element or '"' in element]
    assert not [element for element in tail if ' ' in element and len(element) >= CUT]
    assert base64.b64decode(''.join(tail[1:-1])).decode('utf-8') == NESTED


def test_the_elements_cross_an_msys_argv_intact() -> None:
    """The path that broke: from a native process into the MSYS runtime every element arrives whole and alone."""
    tail = _tail()
    printed = subprocess.run(
        [_msys_bash(), '-c', 'printf "%s\n" "$#" "$@"', '_', *tail],
        capture_output=True,
        text=True,
        encoding='utf-8',
        check=True,
    )
    assert printed.stdout == ''.join(f'{line}\n' for line in [str(len(tail)), *tail])


def test_the_login_shell_runs_the_command_with_its_own_stdin(tmp_path: Path) -> None:
    """The elements joined as ssh joins them, run as sshd runs them: the command runs, reading its stdin.

    The joined line is past the cut itself, so it reaches the shell as a file (as sshd hands it over), never argv.
    """
    line = ' '.join(_tail()).replace('bash -l ', 'bash ', 1)  # a test host's login profile is not the subject
    script = tmp_path / 'line.sh'
    script.write_bytes(line.encode('ascii'))
    done = subprocess.run(
        [_msys_bash(), script.as_posix()], input='fed\n', capture_output=True, text=True, encoding='utf-8', check=True
    )
    assert done.stdout.startswith('fed\na b\n')
