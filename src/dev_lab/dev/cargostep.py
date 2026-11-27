"""THE CARGO PART -- ``cargo fmt --check``, ``cargo clippy -D warnings`` and ``cargo test``, run natively beside pytest.

User ruling 2026-11-24 (T8). A repo's Rust suite runs one step per workspace and :data:`COMMANDS` entry, each with
its own :class:`~dev_lab.dev.reports.StepReport` and so its own result in the verdict: a red names
``cargo <command> <manifest>``. Formatting and lint drift are reds of their own (dev-lab#1033: an unformatted
writer landed on integration and two later merges each re-formatted it), and the part is produced by a hosted
Actions job (:func:`dev_lab.dev.jobparts.rows`), so merge-ready waits on it as on ``tests/base``.
ON GITEA THE CLUSTER PRODUCES IT (user ruling 2026-11-27, architecture v2 (a)). No Actions job derives the part
there, so the candidate source does (:func:`dev_lab.dev.forgeschedule.candidates`, :func:`workspaces_at`): a Gitea
commit tracking a workspace needs ``tests/cargo``. Its cluster producer is an ITEM KIND of the lab-commons array --
:data:`ITEM_ENTRY` run once per :func:`items` entry, returning ``{'exit': code}`` -- and until the array takes a
part's entry and items (:data:`CLUSTER_GAP`) a cluster seat posts the part ``error`` naming that gap
(:func:`cluster_gap`), never leaving it silently absent; ``class=environment``, so it is no author's wait.
A pytest test that shells out to cargo hides the Rust suite inside one Python node id, prices a cargo build as
one test, and is retired.

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

import lab_commons.launch as _door
from lab_commons.hpc.shell import FULL
from lab_commons.hpc.testcells import upgraded
from lab_commons.log import emit

from dev_lab.dev.harness import child_env
from dev_lab.dev.platformparts import part_context, record_directory
from dev_lab.dev.producer import Owner, ProducerExit, full_suite_refusal, unreachable
from dev_lab.dev.reports import StepReport

__all__ = [
    'BANNER',
    'CLUSTER_GAP',
    'COMMANDS',
    'ITEM_ENTRY',
    'PART',
    'argv',
    'cluster_gap',
    'handed',
    'items',
    'node',
    'produce',
    'run_item',
    'step',
    'tracked_workspaces',
    'workspaces',
    'workspaces_at',
]

BANNER: Final = '--- cargo test ---\n'
#: The forge part the Rust suite posts as, ``tests/cargo``: its own result, never inside a pytest part.
PART: Final = 'cargo'
#: Each workspace's commands, cheapest first: formatting, lints (``-D warnings``), then the tests.
COMMANDS: Final = ('fmt', 'clippy', 'test')
#: The lab-commons array entry (``module:function``) that runs one :func:`items` entry on a compute node.
ITEM_ENTRY: Final = 'dev_lab.dev.cargostep:run_item'
#: What the cluster path lacks to produce :data:`PART`: the lab-commons interface it needs, named.
CLUSTER_GAP: Final = (
    'no cluster producer: lab_commons.hpc.run.submit_run runs only pytest items -- it needs a per-part entry and '
    f'items (entry={ITEM_ENTRY!r}, items=cargostep.items(tree, sha)) and gather reading each item result '
    "{'exit': code} as the cell 'cargo <command> <manifest>'"
)


def node(manifest: str, command: str) -> str:
    """The cell id one workspace's *command* run is recorded under."""
    return f'cargo {command} {manifest}'


def handed(root: Path, tracked: Iterable[str]) -> dict[str, str]:
    """Every workspace's cell ids -> :data:`PART`: what a pytest part HANDS, so the forge discovers ``tests/cargo``."""
    return dict.fromkeys((node(one, command) for one in workspaces(root, tracked) for command in COMMANDS), PART)


def tracked_workspaces(root: Path) -> tuple[str, ...]:
    """The :func:`workspaces` of *root*'s tracked files; none when *root* is no git checkout."""
    git = shutil.which('git') or 'git'
    listed = _door.run([git, '-C', str(root), 'ls-files', '-z'], capture_output=True, text=True, encoding='utf-8')
    if listed.returncode:
        return ()
    return workspaces(root, [one for one in listed.stdout.split('\0') if one])


def workspaces_at(root: Path, sha: str) -> tuple[str, ...]:
    """The :func:`workspaces` commit *sha* of *root* tracks, read from git alone; none when *sha* is unreadable."""
    git = shutil.which('git') or 'git'

    def read(*args: str) -> str | None:
        done = _door.run([git, '-C', str(root), *args], capture_output=True, text=True, encoding='utf-8')
        return None if done.returncode else done.stdout

    listed = read('ls-tree', '-r', '-z', '--name-only', sha)
    if listed is None:
        return ()
    manifests = [one for one in listed.split('\0') if PurePosixPath(one).name == 'Cargo.toml']
    found = [one for one in manifests if 'workspace' in _table(read('show', f'{sha}:{one}'))]
    if not found and 'Cargo.toml' in manifests:
        found.append('Cargo.toml')
    return tuple(sorted(found))


def _table(text: str | None) -> dict[str, object]:
    try:
        return tomllib.loads(text or '')
    except tomllib.TOMLDecodeError:
        return {}


def workspaces(root: Path, tracked: Iterable[str]) -> tuple[str, ...]:
    """The tracked manifests under *root* declaring a ``[workspace]``; else a root package manifest; else none."""
    manifests = sorted(path for path in tracked if PurePosixPath(path).name == 'Cargo.toml')
    found: list[str] = []
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


def argv(cargo: str, manifest: str, command: str) -> list[str]:
    """The cargo argv of one :data:`COMMANDS` entry for *manifest*'s workspace."""
    tail = {
        'fmt': ['--all', '--', '--check'],
        'clippy': ['--workspace', '--all-targets', '--locked', '--', '-D', 'warnings'],
        'test': ['--workspace', '--locked'],
    }[command]
    return [cargo, command, '--manifest-path', manifest, *tail]


def items(root: Path, sha: str) -> list[dict[str, str]]:
    """The array items of commit *sha*'s cargo part: one per workspace and :data:`COMMANDS` entry, cheapest first."""
    return [{'manifest': one, 'command': command} for one in workspaces_at(root, sha) for command in COMMANDS]


def run_item(item: dict[str, str]) -> dict[str, object]:
    """:data:`ITEM_ENTRY`: run one :func:`items` entry in the task's tree (its cwd); ``{'exit': code, 'node': id}``.

    The array reads a non-zero ``exit`` as the item's ERROR (:mod:`lab_commons.hpc.worker`); no cargo on the node
    raises, so the item is an ERROR naming the toolchain, never a pass.
    """
    cargo = shutil.which('cargo')
    if cargo is None:
        msg = 'no cargo on this compute node -- install the toolchain rust-toolchain.toml pins (rustup)'
        raise FileNotFoundError(msg)
    manifest, command = item['manifest'], item['command']
    code = _door.run(argv(cargo, manifest, command), check=False).returncode
    return {'exit': code, 'node': node(manifest, command)}


def cluster_gap() -> str:
    """The ``tests/cargo`` ``error`` description a cluster seat posts while :data:`CLUSTER_GAP` stands."""
    return f'no cluster producer: the lab-commons array runs only pytest items ({ITEM_ENTRY}, cargostep.CLUSTER_GAP)'


def step(
    root: Path,
    manifest: str,
    command: str,
    *,
    handle: IO[str],
    tee: Callable[..., int] | None,
    cargo: str | None = shutil.which('cargo'),
) -> StepReport:
    """Run *command* on *manifest*'s workspace, teed into *handle*; its own report, red by name on a non-zero exit."""
    name = node(manifest, command)
    handle.write(BANNER)
    if cargo is None or tee is None:
        why = f'{name}: no cargo on this host -- install the toolchain rust-toolchain.toml pins (rustup), then re-run'
        return StepReport(name=name, truncated=(why,))
    code = tee(argv(cargo, manifest, command), cwd=root, handle=handle)
    return StepReport(name=name, reported=(name,), failures=(name,) if code else ())


def produce(root: Path, *, run: Callable[..., int] | None = None, cargo: str | None = None) -> int:
    """``verify --part cargo``: run every workspace and post ``tests/cargo`` at HEAD; the producer contract's exit.

    One cell per workspace and command (:func:`node`), passed on exit 0, failed otherwise. A repo with no workspace
    has no cargo part (USAGE); no cargo on the host is UNREACHABLE -- it says nothing about the code. Outside the
    producer ``forge serve`` spawned for the part it is refused, as verify's full suite is.
    """
    from dev_lab.dev.localpart import local_record, post_local  # noqa: PLC0415 -- localpart imports this module

    if (refused := full_suite_refusal('verify', child_env(), part_context(PART))) is not None:
        emit(refused, err=True)
        return ProducerExit.USAGE
    found = tracked_workspaces(root)
    if not found:
        emit(f'verify: refused -- part {PART}: this checkout holds no cargo workspace', err=True)
        return ProducerExit.USAGE
    git = shutil.which('git') or 'git'
    cargo = cargo or shutil.which('cargo')
    if cargo is None:
        return unreachable('no cargo on this host -- install the toolchain rust-toolchain.toml pins', Owner.ENVIRONMENT)

    def spawn(command: list[str]) -> int:
        return _door.run(command, cwd=root, check=False).returncode

    launch = run or spawn
    codes = {node(one, command): launch(argv(cargo, one, command)) for one in found for command in COMMANDS}
    sha = _door.run(
        [git, '-C', str(root), 'rev-parse', 'HEAD'], capture_output=True, text=True, encoding='utf-8', check=True
    )
    cells = {
        name: cell
        for name, code in codes.items()
        if (cell := upgraded('passed') if code == 0 else upgraded('failed', f'{name} exited {code}')) is not None
    }
    head = sha.stdout.strip()
    record = local_record(
        root, sha=head, part=PART, scope=FULL, req='cargo', cells=cells, owned=dict.fromkeys(cells, PART)
    )
    emit(post_local(root, record, record_directory(root, head)))
    return ProducerExit.PASS if not any(codes.values()) else ProducerExit.FAIL
