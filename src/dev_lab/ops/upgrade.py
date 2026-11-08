"""``upgrade``: install dev-lab into ``[ops] python``'s environment at the tip of the CONFIGURED ref and source.

It takes no argument, so an operator allowed exactly this command (sudo) installs only the configured integration tip --
never a sha or URL of their choosing. Every input is ``[ops.upgrade]`` (:class:`dev_lab.ops.config.Upgrade`).

The ref may be red or carry break-glassed untested code, and this host runs break-glass -- the tool that repairs a bad
tip -- from this very install (user ruling 2026-11-06). So an upgrade PROVES ITSELF OR ROLLS BACK: it records the
installed commit first (refusing to install when none is recordable), installs the tip, then self-checks in a fresh
``[ops] python`` (:func:`checks`); a failed check reinstalls the recorded commit from the same source.

THE LOCK IS THE ONE SOURCE OF THE FAMILY'S REVISIONS (2026-11-08). dev-lab is installed at the exact commit the ref
names, together with every git package dev-lab's own ``uv.lock`` pins AT THAT COMMIT (lab-commons, ai-lab), passed as
uv overrides derived from the lock (:func:`locked_family`). A hand-written override file was a second source: the
hosts pinned an old lab-commons the upgraded dev-lab could not import, and the judge died. A rollback reinstalls the
old commit with the old commit's lock.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import tomllib
from collections.abc import Callable, Sequence
from pathlib import Path

import lab_commons.launch as _door

from dev_lab.dev.netverb import run_network_verb
from dev_lab.ops.config import OpsConfig

__all__ = ['checks', 'command', 'commit', 'fetch_lock', 'locked_family', 'run', 'run_check']

#: Runs a command line; its exit code and stdout.
type Runner = Callable[[Sequence[str]], tuple[int, str]]

#: ``(source, ref)`` -> the commit the ref names and dev-lab's ``uv.lock`` text at that commit.
type Fetcher = Callable[[str, str], tuple[str, str]]

#: Seconds one self-check may take before it counts as failed.
CHECK_TIMEOUT = 120

#: The package this upgrade installs itself; every OTHER git package of its lock is pinned by override.
_SELF = 'dev-lab'
_GIT = re.compile(r'^(?P<url>[^?#]+)(?:\?[^#]*)?#(?P<sha>[0-9a-f]{40})$')

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


def locked_family(lock: str) -> list[str]:
    """The ``name @ git+url@sha`` override lines for every git-sourced package of *lock* but dev-lab itself."""
    lines = []
    for package in tomllib.loads(lock).get('package', []):
        git = package.get('source', {}).get('git', '')
        if package.get('name') == _SELF or not (found := _GIT.match(git)):
            continue
        lines.append(f'{package["name"]} @ git+{found["url"]}@{found["sha"]}')
    return sorted(lines)


def fetch_lock(source: str, ref: str) -> tuple[str, str]:
    """The commit *ref* names in *source* and dev-lab's ``uv.lock`` there: a shallow fetch into a scratch repo."""
    with tempfile.TemporaryDirectory(prefix='dev-lab-upgrade-') as scratch:
        git = ['git', '-C', scratch]
        _door.run([*git, 'init', '-q'], check=True, capture_output=True)
        report = run_network_verb([*git, 'fetch', '-q', '--depth', '1', source, ref])
        if not report.ok:
            raise ValueError(report.remedy)
        sha = _door.run(
            [*git, 'rev-parse', 'FETCH_HEAD'], check=True, capture_output=True, text=True, encoding='utf-8'
        ).stdout.strip()
        lock = _door.run(
            [*git, 'show', 'FETCH_HEAD:uv.lock'], check=True, capture_output=True, text=True, encoding='utf-8'
        ).stdout
    return sha, lock


def command(config: OpsConfig, ref: str | None = None, override: Path | None = None) -> list[str]:
    """The exact ``uv pip install`` line ``[ops.upgrade]`` declares, at ``ref`` (default: the configured ref).

    *override* is the uv override file holding the lock's family pins (:func:`locked_family`). Refuses a config
    with no such table.
    """
    role = config.upgrade
    if role is None:
        msg = f'{config.path} enables no [ops.upgrade]'
        raise ValueError(msg)
    uv = role.uv or shutil.which('uv') or 'uv'
    extras = f'[{",".join(role.extras)}]' if role.extras else ''
    line = [uv, 'pip', 'install', '--python', config.python, '--reinstall-package', 'dev-lab']
    line += ['--override', str(override)] if override is not None else []
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


def _install_locked(config: OpsConfig, ref: str, install: Runner, fetch: Fetcher) -> tuple[int, str]:
    """Install dev-lab at the commit *ref* names, with that commit's locked family as overrides."""
    if config.upgrade is None:
        msg = f'{config.path} enables no [ops.upgrade]'
        raise ValueError(msg)
    sha, lock = fetch(config.upgrade.source, ref)
    with tempfile.TemporaryDirectory(prefix='dev-lab-overrides-') as scratch:
        override = Path(scratch) / 'family.txt'
        override.write_text(''.join(f'{line}\n' for line in locked_family(lock)), encoding='utf-8')
        return install(command(config, sha, override))


def run(
    config: OpsConfig, *, install: Runner = _install, probe: Runner = run_check, fetch: Fetcher = fetch_lock
) -> tuple[int, str]:
    """Install the tip, self-check it, roll back to the recorded commit on failure; the exit code and what happened."""
    if config.upgrade is None:
        msg = f'{config.path} enables no [ops.upgrade]'
        raise ValueError(msg)
    old = commit(config, probe)
    if not old:
        return 2, 'refused: no installed dev-lab commit is recordable (direct_url.json), so no rollback is possible'
    code, out = _install_locked(config, config.upgrade.ref, install, fetch)
    if code != 0:
        return code, out.strip()
    new = commit(config, probe) or 'unknown'
    failed = _failed_check(config, probe)
    if not failed:
        return 0, f'dev-lab {old} -> {new}'
    code, out = _install_locked(config, old, install, fetch)
    again = _failed_check(config, probe) if code == 0 else 'reinstall'
    if again:
        return 1, f'self-check {failed} FAILED on tip {new}; rollback to {old} ALSO FAILED ({again}): {out.strip()}'
    return 1, f'self-check {failed} FAILED on tip {new}; restored {old}'
