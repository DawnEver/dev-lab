"""A FAKE ``ssh`` for test_dev_sshhold: checks the askpass answer, then runs framed commands until EOF.

It asks ``$SSH_ASKPASS`` for the keyboard-interactive answer exactly as ssh would and refuses one that is not
``$FAKESSH_CODE``. Each framed command is read up to its marker line; its body runs in the platform shell, and
the reply ends on the marker with the status, as ``bash -s`` would print it. ``__drop__`` exits mid-session.
A ``git credential approve`` heredoc is answered as bash and git would: its data lines are written to
``$FAKESSH_CRED_OUT``, or, when ``$FAKESSH_HELPER_FILE`` holds no helper, the remote's refusal with status 3.
The fake's own argv goes to ``$FAKESSH_ARGV_OUT``.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

_MARKER = re.compile(r"printf '\\n(__SSHHOLD_\w+_)%s\\n'")
_HEREDOC = re.compile(r"git credential approve <<'(?P<end>\w+)'\n(?P<data>.*?)\n(?P=end)\n", re.DOTALL)


def _shell(body: str) -> str | list[str]:
    """The platform shell running *body*, as a remote ``bash -s`` would: cmd.exe takes one command line."""
    if sys.platform == 'win32':
        return f'{os.environ.get("COMSPEC", "cmd.exe")} /d /c {body}'
    return ['/bin/sh', '-c', body]


def _credential(body: str) -> tuple[str, int] | None:
    """The answer to a credential frame, as bash and git give it; ``None`` for any other body."""
    found = _HEREDOC.search(body + '\n')
    if found is None:
        return None
    helper = os.environ.get('FAKESSH_HELPER_FILE')
    if helper and not Path(helper).read_text(encoding='utf-8').strip():
        return 'sshhold: no git credential helper is configured on this account\n', 3
    Path(os.environ['FAKESSH_CRED_OUT']).write_bytes((found['data'].removesuffix('\n') + '\n').encode())
    return '', 0


def _run(body: str) -> tuple[str, int]:
    done = subprocess.run(_shell(body), capture_output=True, text=True, encoding='utf-8', timeout=60, check=False)
    return f'{done.stdout}{done.stderr}'.replace('\r\n', '\n'), done.returncode  # a bash remote ends lines on LF


def main() -> int:
    if path := os.environ.get('FAKESSH_ARGV_OUT'):
        Path(path).write_text(json.dumps(sys.argv), encoding='utf-8')
    answer = subprocess.run(
        [os.environ['SSH_ASKPASS'], 'Verification code: '],
        capture_output=True,
        text=True,
        encoding='utf-8',
        timeout=30,
        check=False,
    ).stdout.strip()
    if answer != os.environ.get('FAKESSH_CODE', ''):
        sys.stderr.write('Permission denied (keyboard-interactive).\n')
        return 255
    lines: list[str] = []
    for raw in sys.stdin:
        lines.append(raw)
        found = _MARKER.search(raw)
        if not found:
            continue
        body = ''.join(lines)[len('{ ') :].split('\n} 2>&1', 1)[0]
        lines.clear()
        if body.strip() == '__drop__':
            return 255
        said, status = _credential(body) or _run(body)
        sys.stdout.buffer.write(f'{said}\n{found.group(1)}{status}\n'.encode())
        sys.stdout.buffer.flush()
    return 0


if __name__ == '__main__':
    sys.exit(main())
