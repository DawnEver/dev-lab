"""The git hook SCRIPTS the family ships, and the mechanism that makes them reachable without a copy.

WHY A PAYLOAD AND NOT A DOCUMENTED FILE TO COPY. ``bump-version.sh`` existed twice -- once in
motronics-studio, once in wdg-lab -- and the two had drifted for months in one direction only: every
fix landed in the copy whose author hit the defect. A "shared" script each repo copies is the fork
it claims to remove, wearing a new name, so the shared thing here is an INSTALLED FILE. A consumer
declares ``lab-commons[dev]`` and names a MODULE:

    python -m lab_commons.dev.githooks bump-version

That line resolves through the interpreter already running, cannot go stale against a checkout it
never reads, and updates with the dependency. There is no path for a consumer to write down and no
copy for a fix to miss.

WHY A SUBPACKAGE RATHER THAN A ``.sh`` BESIDE THE MODULES. The payload has to travel in the wheel,
and a data file inside a package directory does; a loose script beside ``src/`` does not. The
directory is also the answer to "which hooks are shipped" -- :data:`HOOKS` is derived from what is
on disk, so a hook that is added is shipped and a hook that is deleted stops being advertised,
rather than either being a list somebody maintains.

WHAT THE SCRIPTS MAY NOT DO is assume a repo. Every repo-specific decision a hook needs arrives as
an environment variable with a working default, and each script's own header names them. A hook that
branched on a repo name would be the fork again, one indirection along.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Final

__all__ = [
    'HOOKS',
    'HOOK_SUFFIX',
    'HookNotShipped',
    'NoBash',
    'bash_executable',
    'hook_path',
    'main',
    'run_hook',
]

#: Every shipped hook is a bash script; the suffix is what :data:`HOOKS` is derived through.
HOOK_SUFFIX: Final = '.sh'

_HERE: Final = Path(__file__).resolve().parent

#: The shipped hooks, BY NAME, derived from the directory rather than written down. Sorted so the
#: error message a typo produces is stable enough to be diffed.
HOOKS: Final[tuple[str, ...]] = tuple(sorted(p.stem for p in _HERE.glob(f'*{HOOK_SUFFIX}')))


class HookNotShipped(LookupError):
    """A hook was asked for by a name this package does not ship.

    Its own class rather than ``KeyError`` because the caller it is aimed at is a consumer's
    ``.pre-commit-config.yaml``, and the fix is to correct the name or to ship the hook here -- not
    to guard the lookup.
    """


class NoBash(RuntimeError):
    """No bash interpreter could be resolved on this box.

    ASSERTED RATHER THAN SKIPPED, for the reason motronics' own tag-hook guard gives: every hook
    entry in this family starts with ``bash``, so a box without one runs no hooks at all. That is a
    finding, not a reason to report success.
    """


def hook_path(name: str) -> Path:
    """The absolute path of a shipped hook script, as installed.

    Args:
        name: The hook's name without its suffix, e.g. ``'bump-version'``.

    Raises:
        HookNotShipped: When *name* is not in :data:`HOOKS`.

    """
    candidate = _HERE / f'{name}{HOOK_SUFFIX}'
    if name not in HOOKS or not candidate.is_file():
        msg = f'{name!r} is not a hook this package ships; shipped: {", ".join(HOOKS) or "(none)"}'
        raise HookNotShipped(msg)
    return candidate


def bash_executable() -> str:
    """Resolve bash: ``PATH`` first, then the one git itself installs.

    On Windows ``bash`` is frequently absent from ``PATH`` while ``git`` is present, and Git for
    Windows ships its own at ``<git>/../bin/bash.exe``. Looked up rather than spelled, so the
    subprocess call below carries an absolute path instead of resolving against whatever ``PATH``
    the caller happened to have.

    Raises:
        NoBash: When neither route resolves.

    """
    found = shutil.which('bash')
    if found:
        return found
    git = shutil.which('git')
    if git:
        for relative in ('../bin/bash.exe', '../../bin/bash.exe'):
            candidate = (Path(git).parent / relative).resolve()
            if candidate.is_file():
                return str(candidate)
    msg = "no bash could be resolved (PATH, then git's own installation); this box can run no hook"
    raise NoBash(msg)


def run_hook(name: str, args: Sequence[str] = (), *, cwd: Path | None = None) -> int:
    """Run a shipped hook and return ITS exit code, unaltered.

    The code is returned rather than raised on: a hook decides its own policy about blocking the
    operation it is attached to, and a wrapper that converted a 0 into an exception -- or the
    reverse -- would be making that decision from outside the file that documents it.
    """
    done = subprocess.run(
        [bash_executable(), str(hook_path(name)), *args],
        cwd=None if cwd is None else str(cwd),
        check=False,
    )
    return done.returncode


def main(argv: Sequence[str] | None = None) -> int:
    """``python -m lab_commons.dev.githooks <hook> [args...]`` -- the consumer-side entry point."""
    parser = argparse.ArgumentParser(
        prog='python -m lab_commons.dev.githooks',
        description='Run, or locate, a git hook script shipped by lab-commons.',
    )
    parser.add_argument('hook', nargs='?', help=f'which hook ({", ".join(HOOKS) or "none shipped"})')
    parser.add_argument('args', nargs=argparse.REMAINDER, help='arguments forwarded to the hook')
    parser.add_argument('--path', action='store_true', help='print the script path instead of running it')
    parser.add_argument('--list', action='store_true', help='print every shipped hook, one per line')
    parsed = parser.parse_args(argv)

    if parsed.list:
        sys.stdout.write('\n'.join(HOOKS) + '\n')
        return 0
    if not parsed.hook:
        parser.error('a hook name is required (or --list)')
    if parsed.path:
        sys.stdout.write(f'{hook_path(parsed.hook)}\n')
        return 0
    return run_hook(parsed.hook, parsed.args)
