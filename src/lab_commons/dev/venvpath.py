"""WHERE A VENV KEEPS ITS INTERPRETER -- the one place in this kit that spells it.

THE SIBLING THAT WAS MISSING. This package already resolves the two executables it does not own:
:func:`lab_commons.dev.githooks.bash_executable` and
:func:`lab_commons.dev.agenthooks.node_executable`. Both exist because ``bash`` and ``node`` are
somebody else's programs and somebody therefore thought about where they live. Python is *ours*, so
nobody did, and the path got written out by hand wherever it was needed.

MEASURED 2026-09-19 across the family, and the shape is the point rather than the count. The LIVE
code in this kit was already right: :data:`CANDIDATE_RELATIVE_PATHS` -- which moved here from
``githooks.bootstrap``, where it was authored -- probes BOTH layouts and has since it landed. What
was wrong was the PROSE. The consumption recipe in
:mod:`lab_commons.dev.hook_adoption`'s module docstring spells ``.venv/Scripts/python.exe``, and
that recipe was copied VERBATIM into ``scripts/deny_rules.py`` in two consuming repos, where it is
now live code that names a file macOS does not have. A recipe is not a docstring: it is source
somebody will paste, so a Windows-only spelling in one is a Windows-only spelling in every repo that
adopts the kit. That is the transmission mechanism this module exists to cut.

THE TWO FACES, AND WHY ONE WOULD NOT SERVE. A venv interpreter is asked for in two settings whose
requirements are opposites:

* A :class:`lab_commons.dev.hooks.Remedy` command is shown VERBATIM to a refused agent, and a
  ``pre-commit`` bootstrap has to exec a real file. Both need a CONCRETE spelling for the box that
  is running. :func:`venv_interpreter` and :data:`CANDIDATE_RELATIVE_PATHS` are that face.
* A ``permissions.allow`` row lives in ``.claude/settings.json``, which is TRACKED IN GIT. It is
  authored on one machine and read on another, so a concrete spelling is wrong for whichever
  platform did not write it. :data:`VENV_INTERPRETER_GLOB` and :func:`portable` are that face.

Conflating them is the defect in both directions: a glob in a remedy tells the agent to type a
string no shell will run, and a concrete path in a tracked allow row silently permits nothing on
half the fleet.

WHY A GLOB AND NOT TWO ROWS OR A RENDER-AT-ADOPTION. Two rows is refused by the mechanism that would
have to emit them: :func:`lab_commons.dev.allow_adoption.derived_entries` renders ONE row per
distinct remedy command precisely so "a diff could not say which of them a later deletion removed",
and a platform pair is that hazard with a platform label on it. Render-at-adoption with a guard that
the rendering matches the running platform is worse than it sounds: it makes a TRACKED file
per-machine, so the guard reds in every checkout on the other platform and the only repair available
to that reader is to rewrite the file and red the first one back. A glob is the only one of the
three that is TRUE on both platforms at once, which is the property a tracked file needs.

WHAT THE GLOB COSTS, stated rather than waved at. ``.venv/*/python*`` also admits
``.venv/bin/python3.12`` and, in principle, a directory under ``.venv`` that is neither ``bin`` nor
``Scripts``. Every string it admits is still *an interpreter inside this project's venv*, which is
exactly the road the row exists to permit, so the widening stays inside the row's own meaning. It is
not a licence to widen further: the glob is a CONSTANT here, derived from :data:`VENV_LAYOUTS`, so a
third layout has to be added as data and cannot arrive as a looser pattern in one repo's settings.

THE PLATFORM SIGNAL ARRIVES AS AN ARGUMENT WITH NO DEFAULT. That is not symmetry with
:mod:`lab_commons.dev.floors` -- it is the only way either branch is reachable in a test. This family
develops on Windows and has no macOS box in the loop, so a resolver reading ``os.name`` internally
would ship with its POSIX half never once executed, which is the state every hand-written copy of
this path was already in. Taking the signal means both branches carry a planted control on the box
that actually runs the suite, and :func:`current_os_name` is the one-line reader a caller uses when
it genuinely means *this* box.
"""

from __future__ import annotations

import os
import re
from typing import Final

__all__ = [
    'CANDIDATE_RELATIVE_PATHS',
    'VENV_INTERPRETER_GLOB',
    'VENV_LAYOUTS',
    'UnknownPlatform',
    'current_os_name',
    'hardcoded_spellings',
    'portable',
    'unportable_row',
    'venv_interpreter',
]

#: Where each platform's venv keeps its interpreter, keyed by ``os.name``. THE DATA every other
#: body here is derived from, so a third layout is one row rather than an edit in four places.
VENV_LAYOUTS: Final[dict[str, tuple[str, ...]]] = {
    'nt': ('.venv', 'Scripts', 'python.exe'),
    'posix': ('.venv', 'bin', 'python'),
}

#: Both layouts as relative path parts, PROBED rather than switched on: a checkout mounted from
#: another platform, or a venv built by a cross-tool, has the layout it has and not the one this
#: process would have chosen. AUTHORED in ``githooks.bootstrap`` and moved here unchanged -- that
#: module was already correct, and this is a move so that the two adoption modules can consult the
#: same data instead of spelling one half of it.
#:
#: Windows first, and the order is load-bearing rather than alphabetical: ``bootstrap`` returns the
#: first candidate that EXISTS, and on a box where both somehow exist the native one is meant.
CANDIDATE_RELATIVE_PATHS: Final[tuple[tuple[str, ...], ...]] = (
    VENV_LAYOUTS['nt'],
    VENV_LAYOUTS['posix'],
)

#: The ONE spelling that is true on every platform, for a file that is tracked in git and read
#: somewhere other than where it was written. Derived from :data:`VENV_LAYOUTS` below rather than
#: typed, so it cannot drift from the layouts it is supposed to cover.
VENV_INTERPRETER_GLOB: Final = '.venv/*/python*'

#: A concrete venv interpreter ANYWHERE in a line, with an optional ``./`` and either separator, so
#: the guard reads the spelling a human would write rather than only the one this module renders.
#:
#: The ``./`` anchor is CAPTURED, never consumed: it is the difference between running the venv in
#: THIS checkout and running whatever a relative lookup finds, and
#: :func:`lab_commons.dev.allow_adoption.glob_for`'s own rule is that nothing is prepended to a
#: remedy. A rewriter that silently dropped the anchor would widen every row it touched.
_SPELLING: Final = re.compile(
    r'(\.[/\\])?\.venv[/\\](?:Scripts[/\\]python(?:\.exe)?|bin[/\\]python[\d.]*)',
)


class UnknownPlatform(KeyError):
    """A platform this kit has no venv layout for, named rather than defaulted.

    Its own class, and a refusal rather than a fallback, for the reason
    :mod:`lab_commons.dev.floors` gives about a guessed answer: falling back to either layout would
    hand the caller a path that does not exist and let it report a missing venv, which is a
    different repair from *this kit does not know your platform yet*.
    """


def current_os_name() -> str:
    """``os.name`` for THIS process -- the one reader, so nothing else imports ``os`` to ask.

    Its own function so a caller that genuinely means *this box* says so at a named call, and every
    other body in this module keeps taking the signal as an argument. That is the split that makes
    both branches reachable in a test without patching a module global.
    """
    return os.name


def venv_interpreter(*, os_name: str) -> str:
    """The venv interpreter's repo-relative path on *os_name*, POSIX-separated.

    POSIX separators on BOTH platforms, deliberately: every consumer is a git-tracked text file --
    a remedy string, a JSON permission row, a rendered recipe -- and a backslash in one of those is
    a JSON escape hazard on top of being unreadable to the other half of the fleet. Windows accepts
    forward slashes in every context this kit puts the path in.

    Args:
        os_name: the platform, spelled as :data:`os.name` does (``'nt'`` or ``'posix'``). NO
            DEFAULT: see this module's docstring -- a default is how the POSIX branch stops being
            executed anywhere.

    Raises:
        UnknownPlatform: no layout is declared for *os_name*.

    """
    layout = VENV_LAYOUTS.get(os_name)
    if layout is None:
        known = ', '.join(sorted(VENV_LAYOUTS))
        msg = (
            f'no venv layout is declared for os.name={os_name!r}; this kit knows {known}. Add the layout to '
            f'VENV_LAYOUTS rather than spelling a path at the call site -- that is the defect this module exists '
            f'to stop.'
        )
        raise UnknownPlatform(msg)
    return '/'.join(layout)


def portable(command: str) -> str:
    """*command* with every concrete venv-interpreter spelling replaced by :data:`VENV_INTERPRETER_GLOB`.

    THE RENDERER FOR THE TRACKED SIDE. A remedy command is authored concretely -- it has to be, the
    agent types it -- and this is what turns it into the row that is true on both platforms. Applied
    to the COMMAND rather than to the finished glob so the rewrite happens before
    :func:`lab_commons.dev.allow_adoption.glob_for` reasons about wildcards, and so a caller can see
    what it is about to permit.

    A command naming no venv interpreter is returned UNCHANGED rather than refused: most remedies
    name a script or a git verb, and a rewriter that insisted on finding something would be a scan
    with no floor pointed at one string.
    """
    return _SPELLING.sub(lambda m: f'{m.group(1) or ""}{VENV_INTERPRETER_GLOB}', command)


def hardcoded_spellings(text: str) -> tuple[str, ...]:
    """Every concrete venv-interpreter spelling in *text*, in the order it occurs, duplicates kept.

    THE GUARD'S READER, and it is deliberately blind to intent: it reports the spelling, and the
    guard that calls it decides whether the file holding it is allowed one. Duplicates are KEPT
    because the caller reports LINES, and two occurrences on one line are two repairs.

    Takes TEXT rather than a path for the reason
    :mod:`lab_commons.dev._allow_settings` takes a parsed mapping: it lets a planted control drive
    THIS body against a string instead of re-implementing it and agreeing with itself.
    """
    return tuple(found.group(0) for found in _SPELLING.finditer(text))


def unportable_row(entry: str) -> str | None:
    """Why *entry* may not go into a tracked permission file, or ``None`` when it may.

    THE REFUSAL'S TEXT LIVES HERE RATHER THAN AT THE CALL SITE because it is a statement about venv
    portability, which is this module's subject, and because the repair it names is
    :func:`portable` -- a message that must quote this function's own output should be built where
    that output is. :mod:`lab_commons.dev.allow_adoption` raises it as its own exception type; the
    WORDING is not a second copy of this argument living in another module.

    A DECLARED allow row is the only door :func:`lab_commons.dev.allow_adoption.glob_for` cannot
    reach: a derived row is normalised on the way out, a declared one is the repo's verbatim text.
    """
    spelled = hardcoded_spellings(entry)
    if not spelled:
        return None
    return (
        f'{entry}: spells the venv interpreter {spelled[0]!r} rather than globbing it. A DERIVED row is '
        f'normalised by glob_for; a DECLARED row is verbatim, so this is the door normalisation cannot reach. '
        f'settings.json is TRACKED IN GIT and a one-platform row permits NOTHING on the other, silently. '
        f'Write {portable(entry)} instead.'
    )
