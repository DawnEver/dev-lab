"""Run the public Commitizen CLI repeatedly without restarting Python for each message.

The shell hook still owns Git selection, exemption validation and aggregate admission. Its stdin
protocol is one line of already validated exempt SHAs, then the selected SHAs in Git order. Bodies
never enter argv: the same private file receives Git's complete raw ``%B`` stdout each time.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path

from commitizen.cli import commitizen_excepthook
from commitizen.cli import main as commitizen_main
from commitizen.exceptions import CommitizenException
from lab_commons.log import emit

__all__ = ['check_file', 'check_messages', 'main']


def check_file(path: Path) -> int:
    """Call the installed public CLI with its ordinary exception/exit-code semantics."""
    argv, excepthook = sys.argv, sys.excepthook
    try:
        sys.argv = ['cz', 'check', '--commit-msg-file', str(path)]
        try:
            commitizen_main()
        except CommitizenException as exc:
            commitizen_excepthook(type(exc), exc, exc.__traceback__)
    except SystemExit as exc:
        return int(exc.code or 0)
    else:
        return 0
    finally:
        sys.argv, sys.excepthook = argv, excepthook


def check_messages(path: Path, shas: Iterable[str], exempt: set[str]) -> int:
    """Check every selected nonexempt commit, retaining any failure and continuing in order."""
    status = 0
    git = shutil.which('git')
    if git is None:
        msg = 'cz-push-range: missing TOOL git; no commits checked'
        raise FileNotFoundError(msg)
    for sha in shas:
        if sha in exempt:
            emit(f'[cz-push-range] exempt {sha} (LAB_CZ_EXEMPT)')
            continue
        raw = subprocess.run(
            [git, 'log', '-1', '--format=%B', sha, '--'],
            capture_output=True,
            check=True,
        ).stdout
        path.write_bytes(raw)
        if check_file(path):
            status = 1
    return status


def main(argv: Sequence[str] | None = None) -> int:
    """Consume the shell-selected SHA stream; the shell owns and cleans the private file."""
    args = list(sys.argv[1:] if argv is None else argv)
    path = Path(args[0])
    exempt = set(sys.stdin.readline().split())
    return check_messages(path, (line.strip() for line in sys.stdin if line.strip()), exempt)


if __name__ == '__main__':
    raise SystemExit(main())
