"""The family's ONE door for mutating a Python environment, decided by STATE rather than by TEXT.

THE INVARIANT, and everything here is derived from it: **no verdict may cite an environment it did
not run in.** Exactly two hazards follow, and neither of them mentions a tool name:

* **H1 -- mutation DURING a run.** A verdict computes its ``env_key`` when the run ENDS, so a swap at
  minute three of a thirty-minute suite yields a key naming an environment the tests never executed
  in. ``env_key`` STRUCTURALLY cannot catch this, so it must be PREVENTED -- :func:`refuse_if_locked`.
* **H2 -- mutation BETWEEN runs.** Every stored verdict becomes a statement about a dead environment.
  This IS catchable, and the remedy is to RETIRE the verdict anchors -- :func:`retire_anchors`.

WHAT THIS REPLACES, AND WHY A BLOCKLIST COULD NOT DO IT. The instrument before this was a list of
command SPELLINGS (``uv add``, ``pip install``) matched against the text a shell was about to run.
Measured 2026-09-16, it failed in BOTH directions at once, from ONE cause:

* TOO STRICT -- it blocked ``uv pip list`` (read-only), it blocked ``uv run`` inside a SIBLING repo
  with its own independent virtualenv, and it blocked a read-only analysis script merely because the
  words appeared inside a heredoc.
* TOO LOOSE -- ``maturin develop``, ``python setup.py develop``, ``poetry install``, ``conda install``
  and ``make install-dev`` mutate the same environment and match no pattern in it.

The cause of both is the same: the question is about STATE -- which environment is about to move, and
whether a verdict is in flight for THAT environment -- and no amount of pattern is a measurement. So
step 1 here is ``sys.prefix`` of the INVOKING interpreter, never a parsed path and never a repo name.
That is what makes the sibling-repo false positive structurally impossible rather than merely fixed:
a call made from another repo's interpreter carries that repo's prefix, so it is correct by
construction and no later scope bug can reintroduce the failure.

THE TWO-LAYER SHAPE THIS LEAVES BEHIND. PREVENT where prevention is cheap and decidable (the lock),
DETECT where prevention is impossible (the key). An unenumerated spelling that dodges any remaining
blocklist is still caught at verdict time by the key, so the blocklist stops being load-bearing for
CORRECTNESS and becomes a signpost pointing here.

RESOLUTION IS ALLOWED, AND THAT IS THE ONE PLACE THIS DIFFERS FROM THE PRIOR ART IT GENERALISES.
``motronics-studio``'s ``scripts/gate/native_install.py`` installs with ``--no-index --no-deps``,
because its subject is "this must be OUR OWN wheel, built from this checkout, and not a dependency at
all" -- there, resolving is the hazard. For genuine dependency work resolving is the entire POINT, so
:attr:`Mode.RESOLVE` is the default and :attr:`Mode.PINNED` keeps the narrow behaviour available for
a caller whose subject is a local artefact.

THE PORT IS CUT AT WHAT ACTUALLY DIFFERS PER REPO, and the cut is two of four things rather than
four. The prefix is MEASURED here, identically everywhere. The key is COMPUTED here, identically
everywhere, because :mod:`lab_commons.dev.envkey` is a function of the interpreter's own
environment and of nothing repo-shaped. What is left -- where exclusion is RECORDED, and where
verdicts are STORED -- is genuinely per repo, and those are the two callables :class:`Port` takes.
A repo that supplies neither (optimi-lab today) still gets steps 1 and 3; steps 2 and 4 then degrade
HONESTLY, with :data:`LOCK_UNDECLARED` / :data:`NO_ANCHORS_DECLARED` rendered in the report. A silent
skip is the vacuous-green shape this family refuses, so the gap is printed rather than assumed.

THE ORDERING ASYMMETRY IS INHERITED AND IS WHAT MAKES A CRASH SAFE: the lock is checked BEFORE the
change and the anchors are retired AFTER it, so a crash in between leaves anchors that a later
``env=`` comparison refuses anyway. The failure mode is a stale REFUSAL, never a stale PASS.

ONE CORRECTION TO THE PRIOR ART, ON PURPOSE. ``native_install.py`` prints "the environment is
unchanged" when pip exits non-zero and retires nothing. A failed install is not a promise that
nothing moved -- pip can fail after writing files -- so this recomputes the key and retires on a
failure exactly as it does on a success. The claim is then MEASURED instead of assumed.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Final

from lab_commons.dev.envkey import env_key, env_manifest

__all__ = [
    'CHILD_WALL_S',
    'LOCK_UNDECLARED',
    'NO_ANCHORS_DECLARED',
    'HeldEnvironmentError',
    'Mode',
    'Port',
    'Report',
    'Version',
    'current_env_key',
    'mutate',
    'pip_argv',
    'refuse_if_locked',
    'retire_anchors',
]

#: What the report says when a repo supplies no lock adapter. A SENTENCE rather than a silence: H1
#: is unguarded in that repo, and the reader has to be told which half of the door they got.
LOCK_UNDECLARED: Final = (
    'NO LOCK DECLARED: this repo supplies no exclusion adapter, so H1 (a mutation DURING a verdict '
    'run) is UNGUARDED here -- it is not absent, it is unchecked. Remedy: pass Port(holders=...) '
    'naming whatever this repo uses to serialise its runs, or run this only when no verdict is in '
    'flight.'
)

#: The same, for the other half. A moved key with nowhere to remedy it is still a moved key.
NO_ANCHORS_DECLARED: Final = (
    'NO VERDICT ANCHORS DECLARED: this repo stores no verdict for a moved env_key to retire, so H2 '
    'is DETECTED here and not remediable. Remedy: pass Port(anchor_paths=...) once this repo keeps '
    'citable verdicts; until then, treat any verdict taken before this change as void.'
)

#: A HANG DETECTOR on the child process, not a performance bound. Thirty minutes is the wall the
#: family's `gate` tier already declares for a whole verdict run: a dependency change still running
#: past the wall of the tier that would be waiting on it is hung by the family's own definition,
#: whatever an install normally costs. No install here has been timed on an idle box, and a timing
#: from a busy one is not a property of the command.
CHILD_WALL_S: Final = 30 * 60


class HeldEnvironmentError(RuntimeError):
    """A verdict is in flight for this environment, so the environment must not move under it."""


class Mode(Enum):
    """How the change is allowed to reach the index.

    ``RESOLVE`` is the default because a dependency change that cannot resolve is not a dependency
    change. ``PINNED`` is the narrow mode whose subject is a LOCAL artefact -- there ``--no-index``
    makes "no network, no version resolution" a mechanical fact rather than a promise in a docstring.
    """

    RESOLVE = 'resolve'
    PINNED = 'pinned'


class Version(Enum):
    """Whether the artefact's VERSION is an IDENTITY for the bytes being installed.

    THIS IS A SECOND AXIS AND NOT A SHADE OF :class:`Mode`, and conflating the two is what hid the
    defect. ``Mode`` says how the change may reach an index; this says whether pip's
    already-satisfied shortcut is a correct answer for this artefact. They are independent: a pinned
    install of a third party's wheel is genuinely already satisfied, and a resolving install of a
    package whose version repeats would be just as blind.

    ``IDENTIFIES`` is the default and describes every published distribution: two builds carrying one
    version are the same bytes by the publisher's promise, so skipping is right and forcing would
    reinstall for nothing on every call.

    ``REPEATS`` is the case where that promise does not exist -- a package with
    ``dynamic = ["version"]`` reading its number out of a ``Cargo.toml``, rebuilt from a checkout
    whose SOURCE moved while the number did not. MEASURED against the pip this family ships against
    (26.2.1, ``_internal/resolution/resolvelib/resolver.py``): for a LOCAL WHEEL already installed at
    the same version pip logs "is already installed with the same version as the provided wheel. Use
    --force-reinstall to force an installation of the wheel" and ``continue``s -- and then EXITS
    ZERO. So the caller is told the install succeeded, the environment did not move, and ``env_key``
    truthfully agrees that it did not: a no-op that every instrument here reports as a success. Note
    the narrowness pip's own code shows -- a local sdist or directory DOES reinstall -- so this is a
    wheel-shaped hazard specifically, which is exactly what a self-build installs.
    """

    IDENTIFIES = 'identifies'
    REPEATS = 'repeats'


@dataclass(frozen=True, slots=True)
class Port:
    """ONE repo's answers to the two questions that are not measurable from here.

    *holders* answers "who is running a verdict in this environment right now", and ``None`` means
    the repo declares no lock AT ALL -- which is a different fact from "nobody holds it" and is
    reported as :data:`LOCK_UNDECLARED` rather than treated as free. *anchor_paths* answers "which
    files record a verdict about this environment", with the same three-sided distinction: ``None``
    is undeclared, ``()`` is declared and empty.

    *key* has a DEFAULT, and that is the design rather than a convenience: ``env_key`` is a function
    of the interpreter's own installed distributions, so every repo computes it identically and no
    adapter is needed for the half of H2 that does the DETECTING.
    """

    name: str
    holders: Callable[[], Sequence[str]] | None = None
    anchor_paths: Callable[[], Sequence[Path]] | None = None
    key: Callable[[], str] = field(default=lambda: current_env_key())

    def lock_holders(self) -> tuple[str, ...] | None:
        """Live holders, or ``None`` when this repo declares no lock."""
        return None if self.holders is None else tuple(self.holders())

    def anchors(self) -> tuple[Path, ...] | None:
        """Declared verdict anchors, or ``None`` when this repo declares none."""
        return None if self.anchor_paths is None else tuple(self.anchor_paths())

    def env_key(self) -> str:
        """The key of the environment as it is RIGHT NOW -- called once before and once after."""
        return self.key()


def current_env_key() -> str:
    """This interpreter's environment key, read fresh. The shared half of H2, free to every repo."""
    return env_key(env_manifest())


def refuse_if_locked(port: Port) -> None:
    """H1, PREVENTED. Raise while a verdict is in flight for this environment, naming the holder.

    Raises:
        HeldEnvironmentError: *port* reports at least one live holder. The message names every
            holder and the remedy, because "busy" on its own sends a reader to the process table to
            guess, and guessing wrong kills somebody's evidence.

    """
    holders = port.lock_holders()
    if not holders:
        return
    msg = (
        f'{port.name}: a verdict is running here, held by {", ".join(holders)}. Its env_key is '
        f'computed when the run ENDS, so mutating this environment now would make that verdict name '
        f'an environment it never tested. Wait for that run to finish and re-issue; nothing else is '
        f'required.'
    )
    raise HeldEnvironmentError(msg)


def retire_anchors(paths: Sequence[Path]) -> tuple[str, ...]:
    """H2, REMEDIED. Delete every anchor that exists, and return what was retired.

    DELETED rather than rewritten to FAIL: a missing anchor cannot be mistaken for a verdict about
    anything, whereas a synthetic FAIL line would put on record a result that no run produced.
    """
    retired = [path for path in paths if path.exists()]
    for path in retired:
        path.unlink()
    return tuple(str(path) for path in retired)


def pip_argv(
    requirements: Sequence[str],
    *,
    mode: Mode = Mode.RESOLVE,
    version: Version = Version.IDENTIFIES,
    python: str | None = None,
) -> tuple[str, ...]:
    """The command that performs the change, through the INVOKING interpreter's own pip.

    ``sys.executable -m pip`` rather than a bare ``pip`` on ``PATH``: the door's whole claim is about
    the environment it measured, and a ``pip`` resolved from ``PATH`` can belong to a different one.

    THIS IS THE ONE PLACE THE ARGV IS DECIDED, and every flag is derived from a DECLARED enum member
    rather than from a caller's opinion -- which is what makes :attr:`Report.argv` able to be the
    whole truth. A caller that wants a flag declares the FACT that implies it; there is no free-text
    extras parameter, because an argv assembled in two places cannot be reported from one.
    """
    flags = ('--no-index', '--no-deps') if mode is Mode.PINNED else ()
    forced = ('--force-reinstall',) if version is Version.REPEATS else ()
    return (python or sys.executable, '-m', 'pip', 'install', *flags, *forced, *requirements)


@dataclass(frozen=True, slots=True)
class Report:
    """What the door did, in the terms the invariant is stated in -- and what it could not check."""

    repo: str
    prefix: str
    argv: tuple[str, ...]
    returncode: int | None
    before: str
    after: str | None
    retired: tuple[str, ...]
    gaps: tuple[str, ...]

    @property
    def moved(self) -> bool:
        """Did the environment change? ``False`` for a dry run, which changed nothing by construction."""
        return self.after is not None and self.after != self.before

    def render(self) -> str:
        """The lines a caller prints. Every gap is rendered, because a silent skip is a vacuous green."""
        verb = 'would install' if self.returncode is None else 'installed'
        lines = [
            f'{self.repo}: {verb} into {self.prefix}',
            f'  command: {" ".join(self.argv)}',
            f'  env_key: {self.before} -> {self.after or "(unchanged: nothing ran)"}',
        ]
        if self.returncode not in (None, 0):
            lines.append(f'  the command FAILED with exit code {self.returncode}; the checks below still ran')
        lines.extend(f'  retired {path} -- env_key has moved' for path in self.retired)
        if self.moved and not self.retired:
            lines.append('  env_key moved and no anchor existed to retire')
        lines.extend(f'  {gap}' for gap in self.gaps)
        return '\n'.join(lines)


def mutate(
    requirements: Sequence[str],
    *,
    port: Port,
    mode: Mode = Mode.RESOLVE,
    version: Version = Version.IDENTIFIES,
    run: Callable[..., Any] = subprocess.run,
    dry_run: bool = False,
    timeout: float = CHILD_WALL_S,
) -> Report:
    """THE DOOR. Measure the environment, refuse a live verdict, change it, retire what it invalidated.

    *run* is injected so a control can drive this function itself rather than a re-implementation of
    it; it is called exactly as :func:`subprocess.run` is and its ``returncode`` is what is reported.

    **THE SEAM CARRIES THE ARGV AND MUST NOT COMPOSE IT.** *run* receives exactly the list this
    function reports as :attr:`Report.argv`; a *run* that appends a flag on the way past makes that
    attribute a declaration that lies, and the report is the only thing a reader ever sees. That is
    not a rule asking for restraint -- it is why *mode* and *version* are parameters HERE: every
    question a caller has ever needed to answer by wrapping *run* is answerable by naming a fact,
    and :func:`pip_argv` turns the fact into the flag. If a new flag is needed, the deliverable is
    the enum member that implies it.

    A dry run performs every CHECK and no mutation -- including no retirement, because a dry run that
    deleted an anchor would have mutated the very thing it reports on.

    Raises:
        ValueError: *requirements* is empty. A bare ``pip install`` names nothing to change, so
            there is no change whose safety this could be deciding.
        HeldEnvironmentError: a verdict is in flight -- see :func:`refuse_if_locked`.

    """
    if not requirements:
        msg = (
            'a dependency change with no requirement names nothing, so there is nothing whose safety '
            'this door could decide. Name the distributions to install, or make no call.'
        )
        raise ValueError(msg)
    refuse_if_locked(port)
    gaps = [] if port.lock_holders() is not None else [LOCK_UNDECLARED]
    declared = port.anchors()
    if declared is None:
        gaps.append(NO_ANCHORS_DECLARED)
    before = port.env_key()
    argv = pip_argv(requirements, mode=mode, version=version)
    if dry_run:
        return Report(port.name, sys.prefix, argv, None, before, None, (), tuple(gaps))
    completed = run(list(argv), check=False, timeout=timeout)
    after = port.env_key()
    retired = retire_anchors(declared) if declared and after != before else ()
    return Report(port.name, sys.prefix, argv, completed.returncode, before, after, retired, tuple(gaps))
