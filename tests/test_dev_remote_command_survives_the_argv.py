"""The remote command reaches the host byte for byte, however deeply it nests its quotes.

Measured 2026-11-27: ``deploy-fleet --account ezxmw9`` died remotely with ``bash: -c: line 0: unexpected EOF while
looking for matching `''``. The deploy line (four levels of ``shlex.quote``) parsed under ``bash -n`` from a file,
yet not once passed as ONE argv element on Windows: the ssh on PATH is Git's MSYS ssh, whose runtime re-splits a
command line from a native process and treats ``'`` as a quote, so a long line dense with ``'"'"'`` arrived
re-cut. The argv element therefore carries no ``'`` at all: the command travels base64-encoded and the login shell
decodes it.
"""

from __future__ import annotations

import base64
import shlex
import shutil
import subprocess

from dev_lab.dev import remote

#: Nested quoting as the deploy line builds it: bash -lc of bash -c of sbatch --wrap.
NESTED = 'echo "a b"; ' + shlex.join(['bash', '-lc', shlex.join(['bash', '-c', "printf '%s' \"x'y\" ; true"])]) * 40


def test_the_ssh_argv_element_carries_no_single_quote_and_decodes_to_the_command() -> None:
    """PLANTED CONTROL: the command itself is dense with ``'``; the element sent holds none of them."""
    assert "'" in NESTED
    tail = remote.ssh_argv('dev@other.example', NESTED, batch=True)[-1]
    assert "'" not in tail
    encoded = tail.split('printf %s ', 1)[1].split(' ', 1)[0]
    assert base64.b64decode(encoded).decode('utf-8') == NESTED


def test_the_element_survives_a_native_argv_into_a_posix_shell() -> None:
    """Through the same CreateProcess path the ssh takes (Windows) or execve (POSIX), the shell decodes it intact."""
    tail = remote.ssh_argv('dev@other.example', NESTED, batch=True)[-1]
    shown = tail.replace('bash -lc ', 'printf %s ', 1)  # print what the login shell would run, instead of running it
    bash = shutil.which('bash')
    assert bash is not None, 'a POSIX bash is the remote shell this test stands in for'
    done = subprocess.run([bash, '-c', shown], capture_output=True, text=True, check=True)
    assert done.stdout == NESTED
