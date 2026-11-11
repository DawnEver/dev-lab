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
from typing import Final

import lab_commons.launch as _door

from dev_lab.dev._dep_project import follow_pin
from dev_lab.dev.gitenv import unlocated
from dev_lab.dev.netverb import run_network_verb
from dev_lab.ops import configdoor
from dev_lab.ops.config import OpsConfig

__all__ = ['checks', 'command', 'commit', 'failed_check', 'fetch_lock', 'locked_family', 'run', 'run_check']

#: Runs a command line; its exit code and stdout.
type Runner = Callable[[Sequence[str]], tuple[int, str]]

#: ``(source, ref)`` -> the commit the ref names and dev-lab's ``uv.lock`` text at that commit.
type Fetcher = Callable[[str, str], tuple[str, str]]

#: Seconds one self-check may take before it counts as failed.
CHECK_TIMEOUT = 120

#: The judge's reviewer package; a judge host installs it, pinned by dev-lab's lock (:func:`locked_family`).
REVIEWER = 'ai-lab'

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
        env = unlocated()
        _door.run([*git, 'init', '-q'], check=True, capture_output=True, env=env)
        report = run_network_verb([*git, 'fetch', '-q', '--depth', '1', source, ref], env=env)
        if not report.ok:
            raise ValueError(report.remedy)
        sha = _door.run(
            [*git, 'rev-parse', 'FETCH_HEAD'], check=True, capture_output=True, text=True, encoding='utf-8', env=env
        ).stdout.strip()
        lock = _door.run(
            [*git, 'show', 'FETCH_HEAD:uv.lock'], check=True, capture_output=True, text=True, encoding='utf-8', env=env
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
    return [*line, f'dev-lab{extras} @ git+{role.source}@{ref or role.ref}', *role.packages, *_reviewer(config)]


def _reviewer(config: OpsConfig) -> list[str]:
    """``ai-lab`` on a judge host that names no reviewer itself: the judge role implies it, the lock pins its rev."""
    packages = config.upgrade.packages if config.upgrade is not None else ()
    named = any(package.split('@')[0].split('[')[0].strip() == REVIEWER for package in packages)
    return [REVIEWER] if config.judge is not None and not named else []


def checks(config: OpsConfig, file: Path | None = None) -> dict[str, list[str]]:
    """The self-check, by name: each runs in a fresh ``[ops] python`` and must exit 0.

    ``loads`` imports ``dev_lab.ops`` and loads this host's own config, so every role it declares parses;
    ``breakglass`` runs the break-glass verb's ``--help`` -- the repair tool's door, with no side effect.
    """
    path = str(file or config.path)
    return {
        'loads': [config.python, '-c', _LOADS, path],
        'breakglass': [config.python, '-m', 'dev_lab.ops', '--config', path, 'breakglass', '--help'],
    }


def run_check(argv: Sequence[str]) -> tuple[int, str]:
    """Run one self-check *argv* in a fresh process; its exit code (124 on timeout) and stdout."""
    try:
        done = _door.run(
            list(argv), check=False, capture_output=True, text=True, encoding='utf-8', timeout=CHECK_TIMEOUT
        )
    except subprocess.TimeoutExpired:
        return 124, f'timed out after {CHECK_TIMEOUT} s'
    said = done.stdout if done.returncode == 0 else f'{done.stdout}{done.stderr}'  # a failure names its cause
    return done.returncode, said


def _install(argv: Sequence[str]) -> tuple[int, str]:
    report = run_network_verb(argv)
    return report.returncode, report.attempts[-1].output if report.attempts else ''


#: Prints the uv pin of the dev-lab the ``[ops] python`` imports -- the NEW one, right after an install.
PIN_PROBE: Final = 'from dev_lab.dev.lockcheck import uv_version; print(uv_version())'


def follow_uv(config: OpsConfig, probe: Runner = run_check) -> str:
    """Move the host's uv to the pin of the dev-lab just installed (:func:`~dev_lab.dev._dep_project.follow_pin`).

    ``''`` once it is there; else why it is not -- the upgrade stands, and the line says the uv did not follow.
    """
    code, out = probe([config.python, '-c', PIN_PROBE])
    if code != 0 or not out.strip():
        return 'the new pin is unreadable; uv left as it is'
    role = config.upgrade
    uv = (role.uv if role is not None else '') or shutil.which('uv')
    return follow_pin(uv, out.strip()) if uv else 'this host has no uv on PATH'


def commit(config: OpsConfig, probe: Runner = run_check) -> str:
    """The installed dev-lab's vcs commit (its ``direct_url.json``); empty when none is recordable."""
    code, out = probe([config.python, '-c', _COMMIT])
    return out.strip() if code == 0 else ''


def failed_check(config: OpsConfig, probe: Runner, file: Path | None = None) -> str:
    """The first self-check that fails on *file* (default the live one), with its last line (the refused key)."""
    for name, argv in checks(config, file).items():
        code, said = probe(argv)
        if code != 0:
            last = said.strip().splitlines()[-1:] if said.strip() else []
            return f'{name} ({last[0][:300]})' if last else name
    return ''


def reviewed_candidate(config: OpsConfig) -> str | None:
    """The text of the reviewed config the host will run next (``[ops.config]``'s source), else ``None``."""
    if config.config_source is None:
        return None
    return configdoor.fetch(config.config_source, run=configdoor.git_with_env)


def _candidate_loads(config: OpsConfig, probe: Runner, candidate: Callable[[OpsConfig], str | None]) -> str:
    """``''`` when the reviewed candidate passes every self-check under the tip; else why not (``none``: none)."""
    try:
        text = candidate(config)
    except configdoor.ConfigRefused as refused:
        return f'unread ({refused})'
    if text is None:
        return 'none'
    with tempfile.TemporaryDirectory(prefix='dev-lab-candidate-') as scratch:
        file = Path(scratch) / config.path.name
        file.write_text(text, encoding='utf-8')
        return failed_check(config, probe, file)


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
    config: OpsConfig,
    *,
    install: Runner = _install,
    probe: Runner = run_check,
    fetch: Fetcher = fetch_lock,
    follow: Callable[[OpsConfig, Runner], str] | None = None,
    candidate: Callable[[OpsConfig], str | None] | None = None,
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
    failed = failed_check(config, probe)
    if not failed:
        lagging = (follow or follow_uv)(config, probe)
        return 0, f'dev-lab {old} -> {new}' + (f'; {lagging}' if lagging else '')
    if not (pending := _candidate_loads(config, probe, candidate or reviewed_candidate)):
        lagging = (follow or follow_uv)(config, probe)
        said = f'dev-lab {old} -> {new}; config apply pending: the live file does not load under the tip ({failed}); '
        return 0, said + 'run config apply --credential <consent> now' + (f'; {lagging}' if lagging else '')
    failed = f'{failed}; candidate {pending}' if pending != 'none' else failed
    code, out = _install_locked(config, old, install, fetch)
    again = failed_check(config, probe) if code == 0 else 'reinstall'
    if again:
        return 1, f'self-check {failed} FAILED on tip {new}; rollback to {old} ALSO FAILED ({again}): {out.strip()}'
    return 1, f'self-check {failed} FAILED on tip {new}; restored {old}'
