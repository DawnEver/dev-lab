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

__all__ = ['BANNER', 'argv', 'step', 'workspaces']

BANNER: Final = '--- cargo test ---\n'


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
    name = f'cargo test {manifest}'
    handle.write(BANNER)
    if cargo is None or tee is None:
        why = f'{name}: no cargo on this host -- install the toolchain rust-toolchain.toml pins (rustup), then re-run'
        return StepReport(name=name, truncated=(why,))
    code = tee(argv(cargo, manifest), cwd=root, handle=handle)
    return StepReport(name=name, reported=(name,), failures=(name,) if code else ())
