"""``upgrade``: install dev-lab into ``[ops] python``'s environment at the tip of the CONFIGURED ref and source.

It takes no argument, so an operator allowed exactly this command (sudo) installs only the configured integration tip --
never a sha or URL of their choosing. Every input is ``[ops.upgrade]`` (:class:`dev_lab.ops.config.Upgrade`).

The ref may be red or carry break-glassed untested code, and this host runs break-glass -- the tool that repairs a bad
tip -- from this very install (user ruling 2026-11-06). So an upgrade PROVES ITSELF OR ROLLS BACK: it records the
installed commit first (refusing to install when none is recordable), installs the tip, then self-checks in a fresh
``[ops] python`` (:func:`checks`); a failed check reinstalls the recorded commit from the same source.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable, Sequence

import lab_commons.launch as _door

from dev_lab.dev.netverb import run_network_verb
from dev_lab.ops.config import OpsConfig

__all__ = ['checks', 'command', 'commit', 'run', 'run_check']

#: Runs a command line; its exit code and stdout.
type Runner = Callable[[Sequence[str]], tuple[int, str]]

#: Seconds one self-check may take before it counts as failed.
CHECK_TIMEOUT = 120

_COMMIT = (
    'import importlib.metadata as m, json\n'
    "try: d = m.distribution('dev-lab').read_text('direct_url.json')\n"
    'except m.PackageNotFoundError: d = None\n'
    "print(json.loads(d).get('vcs_info', {}).get('commit_id', '') if d else '')"
)
_LOADS = (
    'import sys\nfrom pathlib import Path\nimport dev_lab.ops\nfrom dev_lab.ops.config import load\n'
    'load(Path(sys.argv[1]))'
)


def command(config: OpsConfig, ref: str | None = None) -> list[str]:
    """The exact ``uv pip install`` line ``[ops.upgrade]`` declares, at ``ref`` (default: the configured ref).

    Refuses a config with no such table.
    """
    role = config.upgrade
    if role is None:
        msg = f'{config.path} enables no [ops.upgrade]'
        raise ValueError(msg)
    uv = role.uv or shutil.which('uv') or 'uv'
    extras = f'[{",".join(role.extras)}]' if role.extras else ''
    line = [uv, 'pip', 'install', '--python', config.python, '--reinstall-package', 'dev-lab']
    line += ['--override', role.overrides] if role.overrides else []
    return [*line, f'dev-lab{extras} @ git+{role.source}@{ref or role.ref}', *role.packages]


def checks(config: OpsConfig) -> dict[str, list[str]]:
    """The self-check, by name: each runs in a fresh ``[ops] python`` and must exit 0.

    ``loads`` imports ``dev_lab.ops`` and loads this host's own config, so every role it declares parses;
    ``breakglass`` runs the break-glass verb's ``--help`` -- the repair tool's door, with no side effect.
    """
    file = str(config.path)
    return {
        'loads': [config.python, '-c', _LOADS, file],
        'breakglass': [config.python, '-m', 'dev_lab.ops', '--config', file, 'breakglass', '--help'],
    }


def run_check(argv: Sequence[str]) -> tuple[int, str]:
    """Run one self-check *argv* in a fresh process; its exit code (124 on timeout) and stdout."""
    try:
        done = _door.run(
            list(argv), check=False, capture_output=True, text=True, encoding='utf-8', timeout=CHECK_TIMEOUT
        )
    except subprocess.TimeoutExpired:
        return 124, f'timed out after {CHECK_TIMEOUT} s'
    return done.returncode, done.stdout


def _install(argv: Sequence[str]) -> tuple[int, str]:
    report = run_network_verb(argv)
    return report.returncode, report.attempts[-1].output if report.attempts else ''


def commit(config: OpsConfig, probe: Runner = run_check) -> str:
    """The installed dev-lab's vcs commit (its ``direct_url.json``); empty when none is recordable."""
    code, out = probe([config.python, '-c', _COMMIT])
    return out.strip() if code == 0 else ''


def _failed_check(config: OpsConfig, probe: Runner) -> str:
    """The first self-check that fails, else empty."""
    return next((name for name, argv in checks(config).items() if probe(argv)[0] != 0), '')


def run(config: OpsConfig, *, install: Runner = _install, probe: Runner = run_check) -> tuple[int, str]:
    """Install the tip, self-check it, roll back to the recorded commit on failure; the exit code and what happened."""
    line = command(config)
    old = commit(config, probe)
    if not old:
        return 2, 'refused: no installed dev-lab commit is recordable (direct_url.json), so no rollback is possible'
    code, out = install(line)
    if code != 0:
        return code, out.strip()
    new = commit(config, probe) or 'unknown'
    failed = _failed_check(config, probe)
    if not failed:
        return 0, f'dev-lab {old} -> {new}'
    code, out = install(command(config, old))
    again = _failed_check(config, probe) if code == 0 else 'reinstall'
    if again:
        return 1, f'self-check {failed} FAILED on tip {new}; rollback to {old} ALSO FAILED ({again}): {out.strip()}'
    return 1, f'self-check {failed} FAILED on tip {new}; restored {old}'
