"""Measure a rebuilt native extension WITHOUT installing it -- and never report a kernel as a wall.

THE CONSTRAINT THAT SHAPES EVERY LINE: the venv is SHARED. Every worktree on a box borrows one
environment, so the obvious rebuild -- ``maturin develop``, or any ``pip install`` of the fresh
wheel -- mutates the interpreter that another lane's verdict is running in. That is not a style
preference; it is the same hazard :mod:`lab_commons.dev.dep` exists for, arriving through a build
tool instead of through a package manager, and a build tool takes no lock and asks nobody.

SO NOTHING HERE INSTALLS. It BUILDS a wheel (``maturin build``, which only writes its output
directory), UNPACKS it -- a wheel is a zip, so no package manager is involved at all -- and puts the
unpack directory on ``PYTHONPATH``, where it SHADOWS the installed copy. ``PYTHONPATH`` precedes
site-packages, so the fresh build wins while every other dependency still resolves from the shared
venv, which is only ever READ. Measured in motronics-studio 2026-09-04: under the shadow the
extension resolved to the shadow directory and ``numpy`` still imported at 2.5.2 from the venv.

THE REGION GUARD IS DERIVED, NEVER SPELLED. :func:`shared_venv_root` reads ``sys.prefix``, so the
refusal stays correct in a worktree, on another box, and under an environment that is not called
``.venv`` -- a guard that located its region by a spelling would stop firing the moment the spelling
changed, which is the failure mode of every hard-coded path that ever looked fine.

A/B/A/B, NEVER A BLOCK PER ARM. A box shared with concurrent runs DRIFTS, and a block design charges
all of that drift to whichever arm happened to run during it. :func:`interleaved` alternates and
:class:`Comparison` reports MEDIANS with the raw samples beside them, because a single timing off a
busy box is an anecdote.

AND THE NUMBER IT REFUSES TO COMPUTE IS THE POINT. This measures a KERNEL. The end-to-end ceiling is
that ratio weighted by the kernel's measured share of wall clock, and that share is a property of
the CASE and of the consuming repo -- so :class:`Comparison` carries ``speedup`` and has no
``end_to_end`` at all. Stating a kernel speedup as a wall-clock one is the declaration-that-lies
defect; the ceiling also tells you when a measurement is NOT ATTRIBUTABLE, since an end-to-end gain
EXCEEDING its own bound means the box moved rather than the code. Measured in motronics-studio
2026-09-04: a port measured +3.07 % end to end against a 1.8 % bound.

WHY IT IS HERE. motronics-studio held the only copy (``scripts/gate/native_ab.py``), and ``wdg-lab``
has ``rust/``, a PyO3 extension and a recorded ``LNK1104`` from overlapping ``maturin`` invocations
-- which is the linker refusing a write to an output file another build already holds, the exact
collision a build into a private directory does not have.
"""

from __future__ import annotations

import os
import statistics
import subprocess
import sys
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Final

__all__ = [
    'Comparison',
    'SharedVenvWriteError',
    'build_wheel',
    'interleaved',
    'refuse_shared_venv_write',
    'shadow_env',
    'shared_venv_root',
    'time_once',
    'unpack_wheel',
]

#: The DEFAULT ceiling on a child, in seconds. A HANG DETECTOR rather than a performance bound, and
#: the distinction is why it is a keyword on every call that spawns one: a consumer that has a
#: measured build time, or a tier whose own wall is the meaningful bound, passes it and does not
#: inherit a number chosen here. Thirty minutes is the widest dev tier this family declares, so a
#: child still running past it is hung by the family's own definition, whatever a build costs.
DEFAULT_CHILD_WALL_S: Final = 30 * 60


class SharedVenvWriteError(RuntimeError):
    """An output path landed inside the shared environment. REFUSED, never repaired.

    Its own class rather than ``ValueError`` because the caller it is aimed at has a real choice to
    make -- build somewhere else -- and a refusal a caller can act on should be catchable by the
    thing it is about.
    """


def shared_venv_root() -> Path:
    """The environment THIS interpreter runs from: the region no output may enter.

    Derived from ``sys.prefix`` rather than from a ``.venv`` spelling, so the guard is correct in a
    worktree, on another box, and under a differently-named environment.
    """
    return Path(sys.prefix).resolve()


def refuse_shared_venv_write(target: Path) -> None:
    """Refuse *target* when it lands inside the shared environment.

    RESOLVED ON BOTH SIDES BEFORE COMPARING. ``.venv/../.venv/Lib`` names the region as surely as
    ``.venv/Lib`` does, and a guard defeated by a dotted spelling is not a guard. The root itself is
    refused as well as everything under it, so ``--out .venv`` is not a hole.

    Raises:
        SharedVenvWriteError: *target* is the shared environment or sits inside it.

    """
    root = shared_venv_root()
    resolved = Path(target).resolve()
    if resolved == root or root in resolved.parents:
        msg = (
            f'{resolved} is inside the shared environment at {root}. Nothing here installs: every '
            f'worktree on this box borrows that environment, and a mid-run write to it changes the '
            f"interpreter another party's verdict is being measured in. Build to a directory "
            f'OUTSIDE it and shadow it via PYTHONPATH.'
        )
        raise SharedVenvWriteError(msg)


def build_wheel(
    manifest: Path,
    out_dir: Path,
    *,
    wall_s: float = DEFAULT_CHILD_WALL_S,
    release: bool = True,
    python: str | None = None,
) -> Path:
    """``maturin build`` the crate at *manifest* into *out_dir*, and return the wheel it wrote.

    ``build``, NEVER ``develop``: build writes only its output directory, while develop installs
    into the shared environment. That is the whole distinction this module exists to hold, so it is
    not a parameter -- a flag that could select ``develop`` would be the hole with a friendly name.

    IT VERIFIES THAT A WHEEL APPEARED. ``maturin`` exiting 0 having written nothing is
    indistinguishable from a successful build at every later point, and the run would then time the
    INSTALLED extension twice and report a speedup of 1.0 -- a measurement of nothing, wearing the
    shape of a result.

    Args:
        manifest: the crate's ``Cargo.toml``.
        out_dir: where the wheel goes. Refused if inside the shared environment.
        wall_s: the child's ceiling -- a hang detector, see :data:`DEFAULT_CHILD_WALL_S`.
        release: build with optimisations. A debug build measured as if it were a release one is the
            most common way this harness has been observed to produce a meaningless ratio.
        python: the interpreter to run ``maturin`` under. Defaults to the invoking one, so the wheel
            is built for the environment it will be measured against rather than for whichever
            interpreter ``PATH`` offers.

    Returns:
        The newest wheel in *out_dir*.

    Raises:
        SharedVenvWriteError: *out_dir* is inside the shared environment.
        RuntimeError: ``maturin`` reported success and wrote no wheel.

    """
    refuse_shared_venv_write(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    argv = [python or sys.executable, '-m', 'maturin', 'build', '-m', str(manifest), '-o', str(out_dir)]
    if release:
        argv.insert(4, '--release')
    subprocess.run(argv, check=True, timeout=wall_s)
    wheels = sorted(out_dir.glob('*.whl'))
    if not wheels:
        msg = (
            f'maturin exited 0 and wrote no wheel into {out_dir}. A build that produced nothing is '
            f'not a build to measure: shadowing an empty directory times the INSTALLED extension on '
            f'both arms and reports a speedup of 1.0, which is a measurement of nothing wearing the '
            f'shape of a result.'
        )
        raise RuntimeError(msg)
    return wheels[-1]


def unpack_wheel(wheel: Path, shadow_dir: Path) -> Path:
    """Unpack *wheel* into *shadow_dir* and return it. A wheel is a zip; no package manager runs.

    Raises:
        SharedVenvWriteError: *shadow_dir* is inside the shared environment.

    """
    refuse_shared_venv_write(shadow_dir)
    shadow_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(wheel) as archive:
        # Our own build output, produced two calls ago by `build_wheel`, not a downloaded archive.
        archive.extractall(shadow_dir)
    return shadow_dir


def shadow_env(shadow: Path | None, *, base: dict[str, str] | None = None) -> dict[str, str]:
    """The environment for one arm: *shadow* on ``PYTHONPATH``, or ``None`` for the installed arm.

    THE BASELINE ARM STRIPS ``PYTHONPATH`` ENTIRELY rather than leaving it alone. A caller that
    already had one -- a lane pointing at its own sources, a previous run of this very harness --
    would otherwise have its baseline silently shadowed too, and the two arms would measure the same
    code while reporting a ratio. That is the failure this function exists to make impossible, and
    it is why the two arms are built HERE rather than by each caller.
    """
    env = dict(os.environ if base is None else base)
    if shadow is None:
        env.pop('PYTHONPATH', None)
    else:
        env['PYTHONPATH'] = str(shadow)
    return env


def time_once(probe: Path, shadow: Path | None, *, wall_s: float = DEFAULT_CHILD_WALL_S) -> float:
    """Run *probe* once under the arm *shadow* selects, and return its wall time in seconds.

    A FAILING PROBE RAISES rather than contributing a time. A child that died early is FAST, so
    swallowing its exit code would feed the fastest possible sample into the arm that is broken --
    the one direction an error must never be allowed to move a benchmark.

    Raises:
        subprocess.CalledProcessError: the probe exited non-zero.
        subprocess.TimeoutExpired: the probe outlived *wall_s*.

    """
    env = shadow_env(shadow)
    started = time.perf_counter()
    subprocess.run([sys.executable, str(probe)], check=True, env=env, timeout=wall_s)
    return time.perf_counter() - started


@dataclass(frozen=True, slots=True)
class Comparison:
    """Two arms of one probe: the raw samples, and the medians derived from them.

    THERE IS NO ``end_to_end`` FIELD AND THAT IS THE DESIGN. What this measured is a KERNEL; the
    end-to-end ceiling is this ratio weighted by that kernel's share of wall clock, and the share is
    a property of the consuming repo's CASES, which this module cannot see. A field here would be a
    number the caller's data owns, computed by code that does not have it.
    """

    installed_s: tuple[float, ...]
    shadow_s: tuple[float, ...]

    @property
    def median_installed_s(self) -> float:
        return statistics.median(self.installed_s)

    @property
    def median_shadow_s(self) -> float:
        return statistics.median(self.shadow_s)

    @property
    def speedup(self) -> float | None:
        """Installed over shadow, or ``None`` when the shadow arm measured zero.

        ``None`` rather than ``inf`` or a swallowed zero: a zero-second median means the probe did
        not do the work, and "I cannot say" is the honest report of that. A number here would be
        read as a result.
        """
        shadow = self.median_shadow_s
        return self.median_installed_s / shadow if shadow else None


def interleaved(
    probe: Path,
    shadow: Path,
    *,
    repeat: int,
    wall_s: float = DEFAULT_CHILD_WALL_S,
) -> Comparison:
    """Time *probe* on both arms, A/B/A/B, and return both sample sets.

    ALTERNATED, NEVER BLOCKED. A box shared with concurrent runs drifts -- another lane's gate
    starts, a vendor engine takes the cores -- and a block design charges all of that drift to
    whichever arm was running while it happened. Alternating spreads it across both, which does not
    remove the noise but stops it being ATTRIBUTED to one arm.

    Args:
        probe: the script to time. It is run as a child, so it measures a cold import too.
        shadow: the unpacked wheel directory.
        repeat: pairs to run. Must be positive -- see below.
        wall_s: each child's ceiling.

    Raises:
        ValueError: *repeat* is not positive. Zero pairs produce two empty sample sets, and a median
            of nothing raises somewhere further away from the mistake than here.

    """
    if repeat <= 0:
        msg = (
            f'repeat={repeat} runs no pair at all, so there is nothing to compare. A benchmark that '
            f'collected no sample must refuse HERE rather than hand two empty sets to a median.'
        )
        raise ValueError(msg)
    installed: list[float] = []
    shadowed: list[float] = []
    for _ in range(repeat):
        installed.append(time_once(probe, None, wall_s=wall_s))
        shadowed.append(time_once(probe, shadow, wall_s=wall_s))
    return Comparison(installed_s=tuple(installed), shadow_s=tuple(shadowed))
