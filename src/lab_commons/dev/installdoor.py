"""Every INSTALL DOOR in a repo must deliver the DECLARED build of a floating requirement.

THE DECLARATION THIS DEFENDS. The family pins nothing first-party: ``lab-commons @
git+https://github.com/DawnEver/lab-commons.git`` carries no ``rev=``, no ``tag=``, and the lock
file is deliberately NOT tracked (user ruling 2026-09-17). The requirement therefore SAYS "whatever
that URL holds now", and a repo held at anything older stops being told when a shared rule moved.
That is a declaration, and this module is the mechanism that makes it true.

THE DEFECT, MEASURED 2026-09-17 ACROSS FOUR CHECKOUTS. Three reverts in one session, twice misread
as two agents fighting over one venv. ``wdg-lab`` went dev35 -> dev26 -> dev40 -> dev26 while the
declared build was dev42, and a consumer's import vanished under a running agent twice. The cause is
not the package cache and not the install command everybody suspected -- it is the untracked
``uv.lock``, which pins a git requirement to the sha of whenever that lock was FIRST written, and
which every lock-consuming command then serves. Measured the same day: ``wdg-lab/uv.lock`` and
``optimi-lab/uv.lock`` both pinned ``0.2.2.dev26+gba3bf6de``, the exact build the revert landed on.

SO THE CLASSIFICATION IS MEASURED RATHER THAN ASSUMED, and that matters because the two tools
disagree on the same requirement string -- which is precisely why the defect hid behind a command
that looked identical to a correct one. Against ``uv 0.12.5`` and ``pip 25.0.1``, with a venv
holding dev40 and the remote at dev42:

===================================================  ==========================================
door                                                 delivered
===================================================  ==========================================
``uv pip install '<name> @ git+<url>'``              dev42 -- re-resolved, replacing dev40
``uv pip install -e .`` (requirement is transitive)  dev42 -- re-resolved, replacing dev40
``python -m pip install '<name> @ git+<url>'``       dev42 -- pip re-clones a direct URL
``uv sync``           against a lock pinning dev40   dev40 -- REVERTED
``uv run <anything>`` against a lock pinning dev40   dev40 -- REVERTED by the implicit sync
``uv sync -P <name>`` against that same lock         dev42 -- re-resolved, and the lock rewritten
``uv run --no-sync <anything>``                      unchanged -- it is not an install door at all
===================================================  ==========================================

**A LOCK-CONSUMING COMMAND IS AN INSTALL DOOR EVEN WHEN NOBODY CALLS IT ONE.** The worst offender
found was not a Makefile target: it was ``entry: uv run python -m ...`` in a pre-push hook, which
mutated the environment on every push, and a changelog hook that did the same on every commit. A
door is what MOVES the environment, not what is named ``install``.

WHAT IS REFUSED, and it is one sentence: a command that consults a lock either NAMES the floating
requirement for re-resolution (``-P``/``--upgrade-package``, or ``-U``) or does not touch the
environment at all (``--no-sync``). Commands that re-resolve by construction -- ``uv pip install``,
``pip install`` -- are already correct and are deliberately NOT changed; a fix applied where there
is no defect costs the next reader the reason.

WHY THE REPO'S OWN MANIFEST DECIDES WHAT COUNTS AS FLOATING rather than a hard-coded package name:
the rule is about the SHAPE of a requirement, not about one distribution. A repo that declares no
direct-URL-without-a-ref requirement has nothing a stale lock could hold back, so for it every
command here is :attr:`Delivery.INERT`. lab-commons is that repo today, since it IS the kit -- and
the guard is still pointed at its own manifest and its own door files rather than waived, because
the subject can ARRIVE: the day a bare ``git+`` requirement is declared here, the ``uv sync`` in this
repo's CI stops being inert and reds. A waiver would have had to be noticed and removed by hand.
"""

from __future__ import annotations

import re
import shlex
import tomllib
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Final

__all__ = [
    'LOCK_CONSUMING',
    'PREFIX_TOKENS',
    'Delivery',
    'Door',
    'RevertingDoorsError',
    'VacuousDoorScanError',
    'assert_doors_deliver',
    'classify',
    'commands',
    'floating_requirements',
    'reverting',
    'scan_doors',
]

#: The ``uv`` verbs that read ``uv.lock`` and make the environment match it. ``run`` is in this set
#: and is the one that surprises people: it performs an implicit sync before running anything, so a
#: git hook spelled ``uv run ...`` silently reinstalls whatever the lock pins, on every commit.
LOCK_CONSUMING: Final = frozenset({'add', 'export', 'remove', 'run', 'sync'})

#: What may stand in front of a program token on a line and still leave it a program. Declared as
#: data because the alternative -- "any token anywhere on the line" -- makes every sentence that
#: MENTIONS a command into a door, which is the too-loose half of the blocklist this family already
#: retired once (see :mod:`lab_commons.dev.dep`).
PREFIX_TOKENS: Final = frozenset(
    {
        '!',
        '&&',
        ';',
        '-',
        '@',
        '||',
        # A shell GROUP opens a command: `cmd() { uv run ...; }` is how one of the two reverting
        # hooks measured on 2026-09-17 was actually written, and without this the scan read the
        # whole function body as arguments to `cmd()` and found no door in it at all.
        '{',
        'command',
        'do',
        'else',
        'entry:',
        'env',
        'exec',
        'if',
        'nohup',
        'run:',
        'then',
        'time',
        'timeout',
    }
)

#: A requirement is FLOATING when it is a direct git URL carrying no ref of any kind. ``@<ref>``
#: after the path, ``?rev=``/``?tag=``/``?branch=`` and a ``#`` fragment are all refs; anything with
#: one is pinned and is not this rule's subject.
_DIRECT_GIT: Final = re.compile(r'^\s*(?P<name>[A-Za-z0-9._-]+)\s*(?:\[[^\]]*\])?\s*@\s*git\+(?P<url>\S+)\s*$')

#: How ``-P``/``--upgrade-package`` is spelled, in both the split and the ``=`` form.
_UPGRADE_FLAGS: Final = frozenset({'-P', '--upgrade-package'})


class Delivery(Enum):
    """What a command does to the DECLARED build of a floating requirement.

    Three values rather than two, because "does not deliver it" splits into two different facts and
    conflating them would make the remedy unnameable. :attr:`INERT` is a command that moves no
    environment -- there is nothing for it to deliver stale. :attr:`REVERTS` is a command that DOES
    move the environment and serves whatever an earlier resolution left in a lock.
    """

    RESOLVES = 'resolves'
    REVERTS = 'reverts'
    INERT = 'inert'


class RevertingDoorsError(AssertionError):
    """At least one install door serves a stale build of a floating requirement."""


class VacuousDoorScanError(AssertionError):
    """The scan read fewer doors than its floor -- finding nothing proves nothing."""


@dataclass(frozen=True, slots=True)
class Door:
    """One command found in one file, with what it delivers and where a reader can go look."""

    path: str
    line: int
    command: str
    delivery: Delivery

    def describe(self) -> str:
        """``path:line -- <command>``, the spelling an editor can jump to."""
        return f'{self.path}:{self.line} -- {self.command}'


def floating_requirements(pyproject: Path) -> tuple[str, ...]:
    """Every distribution this project requires by a direct git URL carrying NO ref.

    Required and optional in one sequence, sorted and deduplicated: an extra is as much of a
    declaration as the base table, and the defect was found in a repo whose kit arrives through one.

    Raises:
        OSError: *pyproject* is not there. A missing manifest must raise rather than answer "no
            floating requirements", which is the reading under which every door passes.

    """
    table = tomllib.loads(pyproject.read_text(encoding='utf-8'))
    project = table.get('project', {})
    specs: list[str] = list(project.get('dependencies', ()))
    for extra in project.get('optional-dependencies', {}).values():
        specs.extend(extra)
    found = {match.group('name') for spec in specs if (match := _DIRECT_GIT.match(spec)) and _is_floating(match['url'])}
    return tuple(sorted(found))


def _is_floating(url: str) -> bool:
    """Answer whether this ``git+`` URL carries NO ref: ``@sha``, ``?rev=``, ``?tag=``, ``?branch=`` are refs."""
    body, _, _fragment = url.partition('#')
    path, _, query = body.partition('?')
    pinned_by_query = any(key in query for key in ('rev=', 'tag=', 'branch=', 'commit='))
    return '@' not in path.rsplit('/', 1)[-1] and not pinned_by_query


def _upgrades(argv: list[str], names: tuple[str, ...]) -> bool:
    """Answer whether *argv* names every one of *names* for re-resolution, or asks for a blanket upgrade."""
    if '-U' in argv or '--upgrade' in argv:
        return True
    named: set[str] = set()
    for index, token in enumerate(argv):
        if token in _UPGRADE_FLAGS and index + 1 < len(argv):
            named.add(argv[index + 1])
        elif token.startswith(('-P=', '--upgrade-package=')):
            named.add(token.split('=', 1)[1])
    return bool(names) and set(names) <= named


def _verb(argv: list[str]) -> str:
    """Return the first token of *argv* that is not a flag -- ``uv --native-tls sync`` is still ``sync``."""
    return next((token for token in argv if not token.startswith('-')), '')


def _pip_delivery(rest: list[str]) -> Delivery:
    """Decide what a ``pip`` invocation delivers. MEASURED: pip re-clones a direct URL every time."""
    return Delivery.RESOLVES if _verb(rest) == 'install' else Delivery.INERT


def _uv_delivery(rest: list[str], names: tuple[str, ...]) -> Delivery:
    """Decide what a ``uv`` invocation delivers, which is the whole question this module exists for."""
    verb = _verb(rest)
    if verb == 'pip':
        return _pip_delivery(rest[rest.index('pip') + 1 :])
    if verb == 'lock':
        return Delivery.RESOLVES if _upgrades(rest, names) else Delivery.INERT
    if verb not in LOCK_CONSUMING or '--no-sync' in rest:
        return Delivery.INERT
    return Delivery.RESOLVES if _upgrades(rest, names) else Delivery.REVERTS


def classify(argv: list[str], names: tuple[str, ...]) -> Delivery:
    """Decide what this command delivers for the floating requirements *names*.

    Pure over its arguments, so a planted control drives THIS function rather than a second
    implementation that would agree with it by construction. Every branch is a row of the measured
    table in this module's docstring; none of it is inferred from a flag's name.
    """
    if not argv or not names:
        return Delivery.INERT
    program = Path(argv[0]).name.removesuffix('.exe').lower()
    rest = argv[1:]
    if program in {'pip', 'pip3'}:
        return _pip_delivery(rest)
    if program.startswith('python') and rest[:2] == ['-m', 'pip']:
        return _pip_delivery(rest[2:])
    if program == 'uv':
        return _uv_delivery(rest, names)
    # `uvx` lands here with everything else: it runs a tool in its own ephemeral environment.
    return Delivery.INERT


def commands(text: str) -> tuple[tuple[int, list[str]], ...]:
    """Every ``(line number, argv)`` in *text* that invokes an installer-capable program.

    A token counts as a program only at a COMMAND START: the beginning of the line, just after one
    of :data:`PREFIX_TOKENS`, or still inside a wrapper's own flags and numbers (``timeout 900 uv
    sync`` runs uv). Anywhere else it is an argument, so a command QUOTED inside another command is
    not mistaken for a door -- the too-loose half of a spelling blocklist, refused. Comments are cut
    first: a Makefile that argues for its own shape must not read as running what it describes.
    """
    out: list[tuple[int, list[str]]] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        line = re.sub(r'(^|\s)#.*$', '', raw).strip()
        if not line:
            continue
        try:
            tokens = shlex.split(line, comments=False)
        except ValueError:
            continue
        start = True
        for index, token in enumerate(tokens):
            if start and _is_program(token):
                out.append((number, tokens[index:]))
                start = False
            elif token in PREFIX_TOKENS:
                start = True
            elif not (start and (token.startswith('-') or token.replace('.', '', 1).isdigit())):
                start = False
    return tuple(out)


def _is_program(token: str) -> bool:
    """Answer whether this token names a program that can install into an environment."""
    name = Path(token).name.removesuffix('.exe').lower()
    # EXACT rather than a prefix: `python-versions:` is a YAML key, and reading it as an interpreter
    # is how a scan starts reporting doors that do not exist -- measured against this repo's own CI.
    return name in {'uv', 'uvx', 'pip', 'pip3'} or bool(re.fullmatch(r'python[0-9.]*', name))


def scan_doors(root: Path, paths: list[str], names: tuple[str, ...]) -> tuple[Door, ...]:
    """Every installer-capable command in *paths*, classified. *paths* are repo-relative.

    A path that is not there is SKIPPED rather than raising, because the door set is declared per
    repo and repos legitimately differ -- and the floor in :func:`assert_doors_deliver` is what
    stops a list of typos from reading as a clean tree.
    """
    doors: list[Door] = []
    for relative in paths:
        path = root / relative
        if not path.is_file():
            continue
        text = path.read_text(encoding='utf-8', errors='replace')
        doors.extend(Door(relative, number, shlex.join(argv), classify(argv, names)) for number, argv in commands(text))
    return tuple(doors)


def reverting(doors: tuple[Door, ...]) -> tuple[Door, ...]:
    """Return the doors that move an environment and serve a stale build."""
    return tuple(door for door in doors if door.delivery is Delivery.REVERTS)


def assert_doors_deliver(root: Path, paths: list[str], names: tuple[str, ...], floor: int) -> tuple[Door, ...]:
    """Refuse unless every declared door delivers *names*, and unless the scan actually read some.

    THE GUARD.

    Returns the doors it read, so a caller can pin the named set rather than a count.

    Raises:
        VacuousDoorScanError: fewer than *floor* commands were read. A repo whose door files moved or
            were renamed would otherwise report a clean result having read nothing.
        RevertingDoorsError: at least one door serves a stale build, named with its file, its line and
            the remedy that applies to it.

    """
    doors = scan_doors(root, paths, names)
    if len(doors) < floor:
        msg = (
            f'read {len(doors)} installer commands from {len(paths)} declared door files, below the '
            f'floor of {floor}. Finding no reverting door in a set that was not read is vacuous. '
            f'Either a door file was renamed -- repoint the declared paths -- or the scan stopped '
            f'recognising a command, which is a defect in this scan and not a clean tree.'
        )
        raise VacuousDoorScanError(msg)
    stale = reverting(doors)
    if stale:
        listed = '\n  '.join(door.describe() for door in stale)
        msg = (
            f'these install doors serve whatever uv.lock pins rather than the declared build of '
            f'{", ".join(names)}:\n  {listed}\n'
            f'The lock is an untracked per-box artefact, so what they deliver is whatever the last '
            f'resolution on THIS box left behind. Two remedies, and which one applies is decided by '
            f'whether the command is supposed to move the environment at all: a real install door '
            f'adds `--upgrade-package {names[0]}` (which implies --refresh-package), and a git hook '
            f'or a tool invocation adds `--no-sync`, because a hook that reinstalls the environment '
            f'on every commit is an install door nobody declared.'
        )
        raise RevertingDoorsError(msg)
    return doors
