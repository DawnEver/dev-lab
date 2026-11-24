"""CARGO TEST IS A VERIFY STEP OF ITS OWN -- run natively beside pytest, never wrapped in a pytest test.

User ruling 2026-11-24 (T8). A repo's Rust tests run as ``cargo test --manifest-path <ws> --workspace --locked``,
one step per workspace, with its own :class:`~dev_lab.dev.reports.StepReport` and so its own result in the verdict:
a red names ``cargo test <manifest>``. A pytest test that shells out to cargo hides the Rust suite inside one
Python node id, prices a cargo build as one test, and is retired.

WHICH workspaces is derived, never declared: every tracked ``Cargo.toml`` holding a ``[workspace]`` table, else
a root ``Cargo.toml`` package (:func:`workspaces`). A crate that is a member of a workspace, or a planted crate a
test builds on purpose, is not a workspace and runs no step. No cargo on the host truncates the step by name, so
the run is INCONCLUSIVE rather than a silent green.
"""

from __future__ import annotations

import shutil
import tomllib
from collections.abc import Callable, Iterable
from pathlib import Path, PurePosixPath
from typing import IO, Final

from dev_lab.dev.reports import StepReport

__all__ = ['BANNER', 'PART', 'argv', 'handed', 'node', 'produce', 'step', 'workspaces']

BANNER: Final = '--- cargo test ---\n'
#: The forge part the Rust suite posts as, ``tests/cargo``: its own result, never inside a pytest part.
PART: Final = 'cargo'


def node(manifest: str) -> str:
    """The cell id one workspace's run is recorded under."""
    return f'cargo test {manifest}'


def handed(root: Path, tracked: Iterable[str]) -> dict[str, str]:
    """Every workspace's cell id -> :data:`PART`: what a pytest part HANDS, so the forge discovers ``tests/cargo``."""
    return dict.fromkeys((node(one) for one in workspaces(root, tracked)), PART)


def workspaces(root: Path, tracked: Iterable[str]) -> tuple[str, ...]:
    """The tracked manifests under *root* declaring a ``[workspace]``; else a root package manifest; else none."""
    manifests = sorted(path for path in tracked if PurePosixPath(path).name == 'Cargo.toml')
    found = []
    for manifest in manifests:
        try:
            table = tomllib.loads((root / manifest).read_text(encoding='utf-8'))
        except (OSError, tomllib.TOMLDecodeError):
            continue
        if 'workspace' in table:
            found.append(manifest)
    if not found and 'Cargo.toml' in manifests:
        found.append('Cargo.toml')
    return tuple(found)


def argv(cargo: str, manifest: str) -> list[str]:
    """The one cargo command a workspace's step runs."""
    return [cargo, 'test', '--manifest-path', manifest, '--workspace', '--locked']


def step(
    root: Path,
    manifest: str,
    *,
    handle: IO[str],
    tee: Callable[..., int] | None,
    cargo: str | None = shutil.which('cargo'),
) -> StepReport:
    """Run *manifest*'s workspace tests, teed into *handle*; its own report, red by its own name on a non-zero exit."""
    name = node(manifest)
    handle.write(BANNER)
    if cargo is None or tee is None:
        why = f'{name}: no cargo on this host -- install the toolchain rust-toolchain.toml pins (rustup), then re-run'
        return StepReport(name=name, truncated=(why,))
    code = tee(argv(cargo, manifest), cwd=root, handle=handle)
    return StepReport(name=name, reported=(name,), failures=(name,) if code else ())


def produce(root: Path, *, run: Callable[..., int] | None = None, cargo: str | None = None) -> int:
    """``verify --part cargo``: run every workspace and post ``tests/cargo`` at HEAD; the producer contract's exit.

    One cell per workspace (:func:`node`), passed on exit 0, failed otherwise. A repo with no workspace has no
    cargo part (USAGE); no cargo on the host is UNREACHABLE -- it says nothing about the code. Outside the
    producer ``forge serve`` spawned for the part it is refused, as verify's full suite is.
    """
    import os  # noqa: PLC0415 -- the producer half is imported only by verify --part cargo

    import lab_commons.launch as _door  # noqa: PLC0415
    from lab_commons.hpc.shell import FULL  # noqa: PLC0415
    from lab_commons.hpc.testcells import upgraded  # noqa: PLC0415
    from lab_commons.log import emit  # noqa: PLC0415

    from dev_lab.dev.localpart import local_record, post_local  # noqa: PLC0415
    from dev_lab.dev.platformparts import part_context, record_directory  # noqa: PLC0415
    from dev_lab.dev.producer import Owner, ProducerExit, full_suite_refusal, unreachable  # noqa: PLC0415

    if (refused := full_suite_refusal('verify', os.environ, part_context(PART))) is not None:
        emit(refused, err=True)
        return ProducerExit.USAGE
    git = shutil.which('git') or 'git'
    listed = _door.run([git, '-C', str(root), 'ls-files', '-z'], capture_output=True, text=True, check=True)
    found = workspaces(root, [one for one in listed.stdout.split('\0') if one])
    if not found:
        emit(f'verify: refused -- part {PART}: this checkout holds no cargo workspace', err=True)
        return ProducerExit.USAGE
    cargo = cargo or shutil.which('cargo')
    if cargo is None:
        return unreachable('no cargo on this host -- install the toolchain rust-toolchain.toml pins', Owner.ENVIRONMENT)
    launch = run or (lambda command: _door.run(command, cwd=root, check=False).returncode)
    codes = {node(one): launch(argv(cargo, one)) for one in found}
    sha = _door.run([git, '-C', str(root), 'rev-parse', 'HEAD'], capture_output=True, text=True, check=True)
    cells = {
        name: upgraded('passed') if code == 0 else upgraded('failed', f'{name} exited {code}')
        for name, code in codes.items()
    }
    head = sha.stdout.strip()
    record = local_record(
        root, sha=head, part=PART, scope=FULL, req='cargo', cells=cells, owned=dict.fromkeys(cells, PART)
    )
    emit(post_local(root, record, record_directory(root, head)))
    return ProducerExit.PASS if not any(codes.values()) else ProducerExit.FAIL
