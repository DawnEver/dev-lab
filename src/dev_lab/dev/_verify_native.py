"""The verify steps BESIDE pytest: the declared script tests, ``baselines verify`` and each cargo workspace.

:mod:`dev_lab.dev.verifysteps` runs them through :func:`native_steps`, handing in its own tee so every step streams
into the one run log the same way.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path
from typing import IO, Final

from dev_lab.dev import baselines, cargostep
from dev_lab.dev._verify_address import _git_z
from dev_lab.dev.commandtests import declared_command, selected_command
from dev_lab.dev.jsrun import NoEngine, node_path
from dev_lab.dev.reports import StepReport
from dev_lab.dev.selection import is_targeted
from dev_lab.dev.testtemp import script_temp_env

__all__ = ['SCRIPTS_BANNER', 'native_steps', 'script_step']

#: The banner before the declared command's run of the selected script tests.
SCRIPTS_BANNER: Final = '--- script tests ---\n'


def script_step(root: Path, paths: tuple[str, ...], *, handle: IO[str], tee: Callable[..., int]) -> StepReport:
    """The selected script tests (``.mjs``/``.cjs``/``.js``), run by the repo's DECLARED command, judged by its exit.

    The command is the command-part producer's (:mod:`dev_lab.dev.commandtests`), cut to *paths*: exit 0 passes,
    any other exit FAILS each selected path. No declaration, a command that cannot be cut, or one that cannot start
    measures nothing -- truncated, by name and door, so the run is INCONCLUSIVE rather than a guessed verdict.
    """
    name = f'script tests {" ".join(paths)}'
    handle.write(SCRIPTS_BANNER)
    try:
        declared = declared_command((root / 'pyproject.toml').read_text(encoding='utf-8'))
    except OSError:
        declared = None
    if declared is None:
        return StepReport(
            name=name,
            truncated=(
                (
                    f'{name}: no test command is declared -- declare it as the producer in pyproject.toml: '
                    f'[tool.lab_commons.tests] produce = ["-m", "dev_lab.dev.commandpart", "{{part}}", "--", <cmd...>]'
                ),
            ),
        )
    command = selected_command(root, declared, paths)
    if isinstance(command, str):
        return StepReport(name=name, truncated=(f'{name}: {command}',))
    try:
        # `node` is the LOCKED engine (:mod:`dev_lab.dev.jsrun`), never the host's; any other program is resolved
        # on PATH (Windows: `npm` is `npm.cmd`, which a bare name cannot start).
        program = str(node_path()) if command[0] == 'node' else shutil.which(command[0]) or command[0]
        with script_temp_env({}) as temp:
            code = tee([program, *command[1:]], cwd=root, handle=handle, extra_env=temp)
    except (OSError, NoEngine) as cannot:
        return StepReport(name=name, truncated=(f'{name}: cannot start {command[0]!r} here: {cannot}',))
    return StepReport(name=name, reported=(name, *paths), failures=() if code == 0 else paths)


def native_steps(
    root: Path,
    pytest_args: tuple[str, ...],
    scripts: tuple[str, ...],
    *,
    handle: IO[str],
    cargo: bool,
    tee: Callable[..., int],
) -> list[StepReport]:
    """The steps beside pytest: script tests, then on an untargeted run ``baselines verify`` and cargo.

    ``baselines verify`` is H2's; each cargo workspace's own step (T8) runs only outside a producer, whose part
    hands it to ``tests/cargo``.
    """
    steps = [script_step(root, scripts, handle=handle, tee=tee)] if scripts else []
    if scripts or is_targeted(root, pytest_args):  # a selection (pytest or script) judges itself, not the tree
        return steps
    steps.append(baselines.step(root))
    if not cargo:
        return steps
    tracked = _git_z(root, 'ls-files', '-z') or ()
    return [
        *steps,
        *(
            cargostep.step(root, one, command, handle=handle, tee=tee)
            for one in cargostep.workspaces(root, tracked)
            for command in cargostep.COMMANDS
        ),
    ]
