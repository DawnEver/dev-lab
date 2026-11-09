"""A FAKE ``ssh`` for test_dev_sshhold: checks the askpass answer, then runs framed commands until EOF.

It asks ``$SSH_ASKPASS`` for the keyboard-interactive answer exactly as ssh would and refuses one that is not
``$FAKESSH_CODE``. Each framed command is read up to its marker line; its body runs in the platform shell, and
the reply ends on the marker with the status, as ``bash -s`` would print it. ``__drop__`` exits mid-session.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys

_MARKER = re.compile(r"printf '\\n(__SSHHOLD_\w+_)%s\\n'")


def main() -> int:
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
        done = subprocess.run(  # noqa: S602 -- the fake IS a remote shell: it runs the framed body as one
            body, shell=True, capture_output=True, text=True, encoding='utf-8', timeout=60, check=False
        )
        said = f'{done.stdout}{done.stderr}'.replace('\r\n', '\n')  # a bash remote ends lines on LF alone
        sys.stdout.buffer.write(f'{said}\n{found.group(1)}{done.returncode}\n'.encode())
        sys.stdout.buffer.flush()
    return 0


if __name__ == '__main__':
    sys.exit(main())
