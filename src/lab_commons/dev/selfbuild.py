"""Installing a wheel THIS workspace built -- the one environment mutation that is not a dependency change.

THE DISTINCTION THIS MODULE EXISTS TO MAKE, and it is the one :mod:`lab_commons.dev.dep` names and
then declines. That door decides WHEN an environment may move (no verdict in flight) and retires what
the move invalidated. It is deliberately agnostic about WHAT is being installed, because for genuine
dependency work resolving an index is the entire point. A native extension rebuilt from the checkout
you are standing in is the opposite case in every respect:

* it is not a dependency change at all -- the source is in this tree at this sha, so "a human step
  (pyproject plus a deliberate reinstall)" is an argument about somebody else's package;
* it must not resolve ANYTHING. :attr:`~lab_commons.dev.dep.Mode.PINNED` makes that mechanical --
  pip cannot reach an index it is forbidden to consult -- so no transitive dependency can move under
  another lane even in principle;
* and its VERSION IS NOT AN IDENTITY. A crate taking ``dynamic = ["version"]`` out of its
  ``Cargo.toml`` carries the same number across two builds of different source, and pip skips a
  local wheel already installed at the same version -- logging the remedy, and exiting ZERO. That
  turns "installed" into a no-op that ``env_key`` truthfully reports as no movement, so this module
  declares :attr:`~lab_commons.dev.dep.Version.REPEATS` and the argv carries ``--force-reinstall``;
* and the wheel must be OURS. Without that check ``Mode.PINNED`` is a loaded gun with the safety on:
  it stops an index being read, and does nothing at all about ``pip install ./scipy-*.whl`` arriving
  through the one door the blocklist was told to allow.

SO THE CHECK IS "DO WE BUILD THIS", AND THE ANSWER IS READ FROM THE TREE. Not a name spelled in a
guard -- a spelled name is a second declaration of the same fact, and the two drift the first time a
crate is renamed. :func:`declared_distributions` reads ``[project] name`` out of the manifests the
caller hands in, which for a PyO3 workspace is its ``rust/pybind/*/pyproject.toml`` glob. WHERE those
manifests live is the one repo-shaped fact here, so it is an argument; everything else -- the PEP
503 folding, the wheel-filename grammar, the refusal and its wording -- is identical in every repo
that ships a compiled extension.

THE EMPTY CASE IS A REFUSAL AND NOT AN EMPTY ALLOWLIST. A caller whose glob matched nothing has
proved that this workspace builds NOTHING, and an allowlist of nothing must refuse every wheel rather
than be compared against vacuously. That is the floor: finding no manifest cannot read as "no
problem found".

MOTRONICS-STUDIO HELD THE ONLY COPY (``scripts/gate/native_install.py``); ``wdg-lab`` has ``rust/``
and a PyO3 extension. The half that repo cannot share is which distributions it builds, and that half
never enters this file.
"""

from __future__ import annotations

import subprocess
import tomllib
from collections.abc import Callable, Collection, Iterable, Sequence
from pathlib import Path
from typing import Any

from lab_commons.dev.dep import CHILD_WALL_S, Mode, Port, Report, Version, mutate

__all__ = [
    'ForeignDistributionError',
    'NothingBuiltError',
    'declared_distributions',
    'install_self_build',
    'normalise_distribution',
    'refuse_foreign_wheel',
    'wheel_distribution',
]


class ForeignDistributionError(RuntimeError):
    """The wheel is not a distribution this workspace builds -- i.e. it is a dependency change."""


class NothingBuiltError(ForeignDistributionError):
    """This workspace declares no distribution at all, so no wheel can be sanctioned as its own.

    A subclass, because every caller that wants to refuse a foreign wheel wants to refuse this too --
    but the two are different facts, and a caller whose manifest glob has quietly stopped matching
    deserves to be able to tell "your wheel is somebody else's" from "I could not find your crates".
    """


def normalise_distribution(name: str) -> str:
    """PEP 503-ish folding, so one project has one spelling.

    ``motronics-native`` and ``motronics_native`` are ONE project, and a comparison that says
    otherwise refuses the very install this module exists to permit.
    """
    return name.strip().lower().replace('-', '_').replace('.', '_')


def wheel_distribution(wheel: Path) -> str:
    """The distribution name a wheel FILENAME declares -- everything before the first ``-``.

    A wheel filename is ``{distribution}-{version}(-{build})?-{python}-{abi}-{platform}.whl`` where
    every field is ALREADY ESCAPED -- PEP 427 requires ``-`` to become ``_`` in the distribution
    field, which is what makes the first field positionally unambiguous and is why splitting on the
    first ``-`` is a reading rather than a guess. Reading the metadata inside the zip would be no
    stronger: pip installs under the name the filename claims either way, and a file whose name
    disagrees with its own metadata is refused by pip itself.

    A HAND-RENAMED FILE THEREFORE REFUSES, and that is the correct direction. ``motronics-native-0.4.1
    -...whl`` is not a legal wheel name; this reads ``motronics`` from it, no manifest declares that,
    and the install is refused. Fail-closed on a malformed filename is the one outcome that cannot
    install the wrong thing -- so the folding below exists for the MANIFEST side, where
    ``name = "motronics-native"`` is both legal and idiomatic.
    """
    return normalise_distribution(wheel.name.split('-')[0])


def declared_distributions(manifests: Iterable[Path]) -> frozenset[str]:
    """Every ``[project] name`` declared by *manifests*, folded -- what this workspace BUILDS.

    READ FROM THE TREE AT THE CURRENT SHA rather than spelled in a guard: the set is then a fact
    about the checkout instead of a second declaration that has to be kept in step with one. A
    manifest that is missing or declares no name contributes nothing, which is why the empty result
    is a refusal at the point of use rather than a silent pass.
    """
    names: set[str] = set()
    for manifest in sorted(manifests):
        if not manifest.is_file():
            continue
        data = tomllib.loads(manifest.read_text(encoding='utf-8'))
        name = data.get('project', {}).get('name')
        if isinstance(name, str) and name:
            names.add(normalise_distribution(name))
    return frozenset(names)


def refuse_foreign_wheel(wheel: Path, built: Collection[str], *, workspace: str) -> None:
    """Raise unless *wheel* names one of the distributions *built* by *workspace*.

    Raises:
        NothingBuiltError: *built* is empty. An empty allowlist refuses everything; comparing
            against it would let any wheel through on a glob that stopped matching.
        ForeignDistributionError: the wheel names something else -- which makes it a DEPENDENCY
            CHANGE, and dependency changes go through :func:`lab_commons.dev.dep.mutate` with a
            resolving mode and a human behind them.

    """
    if not built:
        empty = (
            f'{workspace} declares no distribution of its own, so it builds nothing and no install '
            f'can be sanctioned here. Either the manifest paths handed in matched no file, or the '
            f'manifests declare no [project] name -- both are read failures, not permissions.'
        )
        raise NothingBuiltError(empty)
    name = wheel_distribution(wheel)
    if name not in set(built):
        foreign = (
            f'{name!r} is not built by {workspace} (which builds: {", ".join(sorted(built))}). '
            f'Installing it is a DEPENDENCY CHANGE -- a deliberate human step through the resolving '
            f'door -- not a rebuild. This route exists only for an extension whose source is in this '
            f'checkout at this sha.'
        )
        raise ForeignDistributionError(foreign)


def install_self_build(
    wheel: Path,
    *,
    manifests: Sequence[Path],
    port: Port,
    workspace: str | None = None,
    dry_run: bool = False,
    run: Callable[..., Any] = subprocess.run,
    timeout: float = CHILD_WALL_S,
) -> Report:
    """Refuse a foreign wheel, then install it through the dependency door in PINNED mode.

    THE ORDER IS THE POINT, and it is the ordering asymmetry :mod:`~lab_commons.dev.dep` already
    holds, with one step in front of it: ownership is decided BEFORE anything is measured or locked,
    because a foreign wheel must be refused whether or not the box happens to be free; the lock is
    then checked before the change and the anchors retired after it, so a crash in between leaves
    anchors a later ``env=`` comparison refuses anyway. The failure mode is a stale REFUSAL, never a
    stale PASS.

    ``Mode.PINNED`` is not a parameter here, and neither is ``Version.REPEATS``. A flag that could
    select a resolving install would make this the general dependency door wearing an ownership
    check, and the general door already exists; a flag that could select ``Version.IDENTIFIES``
    would be a flag for "this wheel's version tells two builds apart", which is false of every wheel
    that can legally arrive here -- the ownership check above has already established that the
    source is in THIS tree at THIS sha, which is precisely the situation in which the version is
    not an identity.

    Args:
        wheel: a LOCAL wheel built from this checkout.
        manifests: this workspace's own project manifests -- the repo-shaped fact.
        port: the repo's lock and verdict-anchor adapters. See :class:`lab_commons.dev.dep.Port`.
        workspace: what to call this workspace in a refusal. Defaults to ``port.name``.
        dry_run: run every check and mutate nothing.
        run: injected so a control can drive THIS function rather than a re-implementation.
        timeout: the child's hang detector.

    Raises:
        FileNotFoundError: *wheel* is not a file. Checked here rather than left to pip, because a
            missing local wheel is a typo and not an environment decision.
        ForeignDistributionError: see :func:`refuse_foreign_wheel`.
        lab_commons.dev.dep.HeldEnvironmentError: a verdict is in flight for this environment.

    """
    if not wheel.is_file():
        raise FileNotFoundError(f'no such wheel: {wheel}')
    refuse_foreign_wheel(wheel, declared_distributions(manifests), workspace=workspace or port.name)
    return mutate(
        [str(wheel)],
        port=port,
        mode=Mode.PINNED,
        version=Version.REPEATS,
        run=run,
        dry_run=dry_run,
        timeout=timeout,
    )
