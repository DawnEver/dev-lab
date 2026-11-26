"""The deploy's ``femm`` phase: an account declaring ``[capabilities.femm]`` gets the family's ONE FEMM 5 release.

User ruling 2026-11-25: "install it through the deploy". WHAT is :data:`dev_lab.dev.toolrelease.FEMM_QT` -- femm-qt
at its pinned tag, the tag's commit checked before anything is built. FEMM 5 publishes no Linux binary, so it is
built from source: ``femm_headless`` and the four solvers it spawns, with Qt disabled (the headless engine needs
none), into ``<tools>/femm/<version>/bin`` under the toolchain's managed tool root (:func:`lab_commons.home.tools`).
femm-qt resolves its solvers, ``python/`` staging and material libraries from its own directory, so the build's
whole ``bin/`` goes there, and beside it femm-qt's build stamp ``generated/version.env``
(:data:`lab_commons.compute.toolchecks.FEMM_VERSION_FILE`): on Linux that file IS the version lab_commons reads.

WHERE IT RUNS: on the login node, in the tick's environment (cron's PATH, then the grant's ``setup``, which loads
the cluster's compiler) -- like every venv and native build of this deploy, at :data:`BUILD_JOBS` parallel jobs.
``git``, ``make``, ``gcc`` and ``g++`` must run there (``--version``) or the phase is refused by name; a missing
``cmake`` is installed through its one installer (:data:`~dev_lab.dev.hpcaccount.checks.INSTALLERS`).

VERIFIED BY THE SAME READER AS EVERY PROBE: the install is current when lab_commons reads the pinned version back
(:func:`~lab_commons.compute.toolchecks.femm_version`), its smoke check passes, and ``femm_headless --version`` runs
in the tick's environment -- where a job runs it. A current install is skipped by name.

NO HALF INSTALL: the build runs in a scratch directory and is assembled in a staged one beside the final, verified
there, and only then moved into place; the install it replaces, and any other version under the tool's directory,
is kept until that moment and removed after it. A failure removes the
scratch and the stage, keeps the build log (``~/.cache/dev-lab/<yy>/<mm>/<dd>/deploy-femm/build.log``) and is
refused naming it. The deploy goes on for the repos: a refused FEMM install never leaves them unserved.
"""

from __future__ import annotations

import re
import shlex
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

from lab_commons.compute.toolchecks import (
    CHECKS,
    FEMM_HEADLESS,
    FEMM_VERSION_FILE,
    VersionUnreadable,
    femm_version,
)
from lab_commons.log import emit
from lab_commons.temp import TEMP_PREFIX

from dev_lab.dev.datedlog import dated_log
from dev_lab.dev.diskusage import remove_tree
from dev_lab.dev.hpcaccount.checks import INSTALLERS, runs
from dev_lab.dev.hpcaccount.steps import Step
from dev_lab.dev.toolrelease import FEMM_QT, SourceRelease

__all__ = ['BUILD_JOBS', 'BUILD_TOOLS', 'TARGETS', 'build_script', 'install', 'install_dir', 'verified']

#: The tools a build runs, each proven by ``--version`` in the tick's environment first.
BUILD_TOOLS: Final = ('git', 'cmake', 'make', 'gcc', 'g++')

#: The femm-qt targets the headless engine needs: itself and the solvers it spawns from its own directory.
TARGETS: Final = ('femm_headless', 'fkn', 'belasolv', 'hsolv', 'csolv')

#: Parallel compile jobs: a login node is shared, so the build takes a few cores, never all of them.
BUILD_JOBS: Final = 4

#: The OS the deploy runs on: a cluster account is Linux, where FEMM's version is its version file.
_PLATFORM: Final = 'linux'
_BINARY: Final = FEMM_HEADLESS[_PLATFORM][0]

#: An install directory's name: a dotted version.
_VERSION: Final = re.compile(r'\d+(\.\d+)+')

#: Where the build log goes under the account's home, beside every deploy-fleet log.
_LOG_BASE: Final = '.cache/dev-lab'
_LOG_KIND: Final = 'deploy-femm'


def install_dir(tools_root: Path, pin: SourceRelease = FEMM_QT) -> Path:
    """The install of *pin* under the managed *tools_root*: ``<tools>/<name>/<version>`` (its binaries in ``bin``)."""
    return tools_root / pin.name / pin.version


def verified(step: Step, bin_dir: Path, environment: str, pin: SourceRelease = FEMM_QT) -> str:
    """``''`` when *bin_dir* holds *pin*'s install as lab_commons reads it and it runs in *environment*; else why."""
    binary = bin_dir / _BINARY
    whole, detail = CHECKS[pin.name].smoke(binary)
    if not whole:
        return detail
    try:
        _source, version = femm_version(binary, platform=_PLATFORM)
    except VersionUnreadable as why:
        return str(why)
    if version != pin.version:
        return f'{binary} states {version}, not the pinned {pin.version}'
    if not runs(step.tools.sh, environment, str(binary)):
        return f"{binary} --version does not run in the tick's environment (`{environment}`), where a job runs it"
    return ''


def build_script(pin: SourceRelease = FEMM_QT, jobs: int = BUILD_JOBS) -> str:
    """The shell build of *pin*: clone at its tag, refuse a moved tag, build :data:`TARGETS`, stage ``bin``.

    The directories come from the environment (``FEMM_SRC``, ``FEMM_BUILD``, ``FEMM_STAGE``). A blob-less clone keeps
    the history femm-qt's build number counts (``git rev-list --count HEAD``) without every old file.
    """
    src, build, stage = '"$FEMM_SRC"', '"$FEMM_BUILD"', '"$FEMM_STAGE"'
    moved = shlex.quote(f'{pin.tag} is not the pinned commit {pin.commit}: refused, nothing built')
    return '\n'.join([
        'set -e',
        f'git clone -q --filter=blob:none --branch {shlex.quote(pin.tag)} {shlex.quote(pin.url)} {src}',
        f'if [ "$(git -C {src} rev-parse HEAD)" != {pin.commit} ]; then echo {moved} >&2; exit 3; fi',
        f'cmake -S {src} -B {build} -DCMAKE_BUILD_TYPE=Release -DCMAKE_DISABLE_FIND_PACKAGE_Qt6=ON',
        f'cmake --build {build} --parallel {jobs} --target {" ".join(TARGETS)}',
        f'mkdir -p {stage}/bin',
        f'cp -R {build}/bin/. {stage}/bin/',
        f'cp {build}/generated/version.env {stage}/bin/{FEMM_VERSION_FILE}',
    ])  # fmt: skip


def _build_tools(step: Step, environment: str) -> list[str]:
    """The :data:`BUILD_TOOLS` that do not run in *environment* and could not be installed here."""
    missing = []
    for tool in BUILD_TOOLS:
        if runs(step.tools.sh, environment, tool):
            continue
        script = INSTALLERS.get(tool)
        if script is None or step.change(f'install {tool}: {script}', [*step.tools.sh, f'{environment}; {script}']):
            missing.append(tool)
    return missing


def _refuse(why: str) -> int:
    emit(f'  femm: refused -- {why}', err=True)
    return 2


def _publish(staged: Path, final: Path) -> None:
    """Move the verified *staged* install to *final*; what it replaces goes only once the new one is in place.

    That is the install at *final* and every other VERSION beside it (``<tools>/<name>/<a.b.c>``): one release is
    installed. Nothing else under the tool's directory is touched, nor any install outside the managed root.
    """
    aside = final.with_name(f'{TEMP_PREFIX}old-{final.name}')
    remove_tree(aside)
    if final.exists():
        final.rename(aside)
    try:
        staged.rename(final)
    except OSError:
        if aside.exists():
            aside.rename(final)
        raise
    remove_tree(aside)
    for superseded in sorted(final.parent.iterdir()):
        if superseded != final and _VERSION.fullmatch(superseded.name):
            remove_tree(superseded)
            emit(f'  femm: removed the superseded {superseded}')


def install(
    step: Step,
    machine: Mapping[str, Any],
    *,
    environment: str,
    tools_root: Path,
    home: Path,
    pin: SourceRelease = FEMM_QT,
) -> int:
    """Install *pin* where *machine* declares ``[capabilities.<name>]``: 0 current, installed or undeclared, else 2."""
    emit(f'[femm] FEMM {pin.version} where the machine file declares [capabilities.{pin.name}]')
    if pin.name not in machine.get('capabilities', {}):
        emit(f'  no [capabilities.{pin.name}] here: nothing to install')
        return 0
    final = install_dir(tools_root, pin)
    if not (stale := verified(step, final / 'bin', environment, pin)):
        emit(f'  femm {pin.version}: current at {final}; skipped')
        return 0
    emit(f'  femm {pin.version}: not current ({stale})')
    if missing := _build_tools(step, environment):
        return _refuse(
            f'{", ".join(missing)} does not run (`--version`) in the tick environment (`{environment}`) and the deploy '
            "cannot install it: add the module providing it to this account's [[hpc.grant]] setup in the family "
            'file, and re-run'
        )
    what = f'build femm-qt {pin.tag} ({pin.commit[:12]}) from {pin.url}, {" ".join(TARGETS)}, into {final}'
    if step.dry:
        step.change(what, [])
        return 0
    return _build(step, final, what, environment=environment, home=home, pin=pin)


def _build(step: Step, final: Path, what: str, *, environment: str, home: Path, pin: SourceRelease) -> int:
    """Build *pin* beside *final*, verify the stage, then publish it; 2, its log named, when either fails."""
    scratch = final.with_name(f'{TEMP_PREFIX}build-{pin.version}')
    staged = final.with_name(f'{TEMP_PREFIX}new-{pin.version}')
    for leftover in (scratch, staged):  # an interrupted deploy's
        remove_tree(leftover)
    scratch.mkdir(parents=True)
    log = dated_log(home, 'build.log', base=_LOG_BASE, kind=_LOG_KIND)
    env = {'FEMM_SRC': str(scratch / 'src'), 'FEMM_BUILD': str(scratch / 'build'), 'FEMM_STAGE': str(staged)}
    try:
        rc = step.change(what, [*step.tools.sh, f'{environment}; {build_script(pin)}'], env=env)
        log.write_text(step.output, encoding='utf-8')
        if rc:
            return _refuse(f'the build exited {rc}; the install in place is kept; its log: {log}')
        if why := verified(step, staged / 'bin', environment, pin):
            return _refuse(f'the build does not verify: {why}; the install in place is kept; its log: {log}')
        _publish(staged, final)
    finally:
        remove_tree(scratch)
        remove_tree(staged)
    emit(f'  femm: installed {pin.version} at {final} (lab_commons reads it back); its log: {log}')
    return 0
