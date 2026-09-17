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
directory is also the answer to "which scripts are shipped" -- :data:`SCRIPTS` is derived from what
is on disk, so a script that is added is shipped and one that is deleted stops being advertised,
rather than either being a list somebody maintains.

WHAT THE SCRIPTS MAY NOT DO is assume a repo. Every repo-specific decision a hook needs arrives as
an environment variable, and each script's own header names them. A hook that branched on a repo
name would be the fork again, one indirection along. A decision that is DERIVABLE here carries a
default (the release branch reads from the remote's HEAD); a decision that is a FACT ABOUT ONE REPO
carries none, and the script refuses when it is missing -- ``branch-push-only.sh``'s protected ref
and ``cz-push-range.sh``'s base ref are both of that second kind, because a default would hand every
other repo one repo's answer while looking like it worked.

AND THE CONSUMER-SIDE BOOTSTRAP IS :mod:`lab_commons.dev.githooks.bootstrap`, which is what makes the
paragraph above true for pre-commit and not only for a caller that already has an interpreter. A
``.pre-commit-config.yaml`` entry is exec'd rather than evaluated, so its first token must already be
runnable -- and measured against a real ``pre-commit.exe``, a ``language: system`` hook inherits a
PATH with no venv on it at all. That module ships as the ``lab-with-venv`` console script and is
reached under ``language: python``, where pre-commit supplies the interpreter in front of it; it then
resolves the CONSUMER's own venv and hands the command over, so the environment pre-commit caches
stays a launcher rather than becoming a second install of this package.

NOT EVERY SHIPPED SCRIPT IS A HOOK, and the distinction is enforced rather than left to a reader.
``with-venv.sh`` is a WRAPPER -- it takes the command to run as its arguments -- and
``git-env-repair.sh`` is a FRAGMENT that must be SOURCED, so running it is a no-op that exits 0 and
reads exactly like a hook that passed. :data:`KINDS` is the registry, :data:`SCRIPTS` is derived from
the directory, and :func:`undeclared` is two-sided: a script shipped without a row and a row naming
no script are both named. :func:`run_hook` refuses a fragment for the same reason the kinds exist.
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
    'FRAGMENT',
    'HOOK',
    'HOOKS',
    'HOOK_SUFFIX',
    'KINDS',
    'SCRIPTS',
    'WRAPPER',
    'HookNotShipped',
    'NoBash',
    'NotRunnable',
    'bash_executable',
    'hook_path',
    'kind',
    'main',
    'run_hook',
    'scripts_of_kind',
    'undeclared',
]

#: Every shipped script is a bash script; the suffix is what :data:`SCRIPTS` is derived through.
HOOK_SUFFIX: Final = '.sh'

#: Runnable as a git hook entry: pre-commit invokes it and reads its exit code.
HOOK: Final = 'hook'
#: Takes the command to run as its arguments; a hook entry wraps a real command in it.
WRAPPER: Final = 'wrapper'
#: Must be SOURCED into a running shell. Executing one does nothing and exits 0, which is why
#: :func:`run_hook` refuses it: a no-op that exits 0 is indistinguishable from a hook that passed.
FRAGMENT: Final = 'fragment'

_HERE: Final = Path(__file__).resolve().parent

#: Every shipped script, BY NAME, derived from the directory rather than written down, so a script
#: that is added is shipped and a script that is deleted stops being advertised. Sorted so the error
#: message a typo produces is stable enough to be diffed.
SCRIPTS: Final[tuple[str, ...]] = tuple(sorted(p.stem for p in _HERE.glob(f'*{HOOK_SUFFIX}')))

#: What each shipped script IS. The registry owns this; the directory owns which scripts exist, and
#: :func:`undeclared` is where the two are made to agree in both directions.
KINDS: Final[dict[str, str]] = {
    'branch-push-only': WRAPPER,
    'bump-version': HOOK,
    'cz-push-range': HOOK,
    'git-env-repair': FRAGMENT,
    'with-venv': WRAPPER,
}

#: The subset that is wired as a git hook entry -- derived from both, so a script whose kind changes
#: leaves this set without anyone editing it.
HOOKS: Final[tuple[str, ...]] = tuple(name for name in SCRIPTS if KINDS.get(name) == HOOK)


class HookNotShipped(LookupError):
    """A hook was asked for by a name this package does not ship.

    Its own class rather than ``KeyError`` because the caller it is aimed at is a consumer's
    ``.pre-commit-config.yaml``, and the fix is to correct the name or to ship the hook here -- not
    to guard the lookup.
    """


class NotRunnable(TypeError):
    """A shipped script was asked to RUN that is not run at all.

    Only ``FRAGMENT`` reaches this today, and the refusal is the point: sourcing is the contract, so
    executing the file returns 0 having done nothing, which a caller reads as a hook that passed.
    """


class NoBash(RuntimeError):
    """No bash interpreter could be resolved on this box.

    ASSERTED RATHER THAN SKIPPED, for the reason motronics' own tag-hook guard gives: every hook
    entry in this family starts with ``bash``, so a box without one runs no hooks at all. That is a
    finding, not a reason to report success.
    """


def hook_path(name: str) -> Path:
    """The absolute path of a shipped script, as installed.

    Args:
        name: The script's name without its suffix, e.g. ``'bump-version'``.

    Raises:
        HookNotShipped: When *name* is not in :data:`SCRIPTS`.

    """
    candidate = _HERE / f'{name}{HOOK_SUFFIX}'
    if name not in SCRIPTS or not candidate.is_file():
        msg = f'{name!r} is not a script this package ships; shipped: {", ".join(SCRIPTS) or "(none)"}'
        raise HookNotShipped(msg)
    return candidate


def kind(name: str) -> str:
    """What a shipped script IS -- :data:`HOOK`, :data:`WRAPPER` or :data:`FRAGMENT`.

    Raises:
        HookNotShipped: When *name* is not shipped, or is shipped with no row in :data:`KINDS`.
            An undeclared script is refused rather than defaulted to ``HOOK``: guessing is what
            would let a fragment be run as a hook, which is the failure the registry exists for.

    """
    hook_path(name)
    declared = KINDS.get(name)
    if declared is None:
        msg = f'{name!r} is shipped with no row in KINDS; declare what it is before it can be reached'
        raise HookNotShipped(msg)
    return declared


def scripts_of_kind(wanted: str) -> tuple[str, ...]:
    """Every shipped script declared as *wanted*, in :data:`SCRIPTS` order."""
    return tuple(name for name in SCRIPTS if KINDS.get(name) == wanted)


def undeclared(
    shipped_scripts: Sequence[str] | None = None,
    declared_kinds: dict[str, str] | None = None,
) -> tuple[str, ...]:
    """Both sides of the registry: a script with no row, and a row naming no script.

    Returned rather than raised so a test can assert it empty, and PURE over its arguments so a
    planted control drives THIS function rather than a second implementation that would agree with
    it by construction. An empty result over an EMPTY directory would be vacuous, which is why the
    caller binds a floor on :data:`SCRIPTS` instead of trusting this alone.

    Args:
        shipped_scripts: What is on disk; :data:`SCRIPTS` when omitted.
        declared_kinds: What the registry says; :data:`KINDS` when omitted.

    """
    shipped = set(SCRIPTS if shipped_scripts is None else shipped_scripts)
    kinds = KINDS if declared_kinds is None else declared_kinds
    declared = set(kinds)
    out = [f'{name}: shipped with no row in KINDS' for name in sorted(shipped - declared)]
    out += [f'{name}: declared in KINDS, and no such script is shipped' for name in sorted(declared - shipped)]
    out += [
        f'{name}: declared as {kinds[name]!r}, which is not one of {HOOK!r}, {WRAPPER!r}, {FRAGMENT!r}'
        for name in sorted(shipped & declared)
        if kinds[name] not in {HOOK, WRAPPER, FRAGMENT}
    ]
    return tuple(out)


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

    Raises:
        NotRunnable: When *name* is a :data:`FRAGMENT`. It is sourced, so running it would exit 0
            having done nothing -- a pass the caller cannot tell from a real one.

    """
    if kind(name) == FRAGMENT:
        msg = (
            f'{name!r} is a {FRAGMENT}: it is SOURCED into a shell (`. "$(python -m '
            f'lab_commons.dev.githooks --path {name})"`), never run. Running it would exit 0 having '
            f'done nothing, which reads exactly like a hook that passed.'
        )
        raise NotRunnable(msg)
    done = subprocess.run(
        [bash_executable(), str(hook_path(name)), *args],
        cwd=None if cwd is None else str(cwd),
        check=False,
    )
    return done.returncode


def main(argv: Sequence[str] | None = None) -> int:
    """``python -m lab_commons.dev.githooks <script> [args...]`` -- the consumer-side entry point."""
    parser = argparse.ArgumentParser(
        prog='python -m lab_commons.dev.githooks',
        description='Run, or locate, a git hook script shipped by lab-commons.',
    )
    parser.add_argument('hook', nargs='?', help=f'which script ({", ".join(SCRIPTS) or "none shipped"})')
    parser.add_argument('args', nargs=argparse.REMAINDER, help='arguments forwarded to the script')
    parser.add_argument('--path', action='store_true', help='print the script path instead of running it')
    parser.add_argument('--list', action='store_true', help='print every shipped script, one per line')
    parser.add_argument(
        '--kind',
        choices=(HOOK, WRAPPER, FRAGMENT),
        help=f'with --list, only scripts of this kind; a {FRAGMENT} is sourced rather than run',
    )
    parsed = parser.parse_args(argv)

    if parsed.list:
        listed = SCRIPTS if parsed.kind is None else scripts_of_kind(parsed.kind)
        sys.stdout.write('\n'.join(listed) + '\n')
        return 0
    if not parsed.hook:
        parser.error('a script name is required (or --list)')
    if parsed.path:
        sys.stdout.write(f'{hook_path(parsed.hook)}\n')
        return 0
    return run_hook(parsed.hook, parsed.args)
