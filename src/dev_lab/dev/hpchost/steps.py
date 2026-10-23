"""The deployment's changing steps: run-or-print, and the checkout and venv each served repo needs.

Every changing action goes through :class:`Step`, which under ``--dry-run`` only prints it.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import lab_commons.launch as _door
from lab_commons.hpc.builds import Builds, cargo_target, key_of, read_builds
from lab_commons.log import emit

from dev_lab.dev.hpchost.spec import Deployment, Repo, checkout_of

__all__ = ['Step', 'Tools', 'build', 'declared', 'update']


@dataclass(frozen=True)
class Tools:
    """The argv prefix of every program the deploy runs; a test swaps in fakes."""

    git: tuple[str, ...] = ('git',)
    crontab: tuple[str, ...] = ('crontab',)
    uv: tuple[str, ...] = ('uv',)
    sh: tuple[str, ...] = ('bash', '-lc')
    id: tuple[str, ...] = ('id',)
    sacctmgr: tuple[str, ...] = ('sacctmgr',)
    rclone: tuple[str, ...] = ('rclone',)


class Step:
    """Runs or, under ``--dry-run``, only prints each changing action; read-only calls always run."""

    def __init__(self, tools: Tools, *, dry: bool, path: str = '') -> None:
        """Run through *tools*; *dry* prints each changing action instead; *path*, when set, is every change's PATH."""
        self.tools, self.dry, self.path = tools, dry, path

    def read(self, argv: Sequence[str], stdin: str | None = None) -> subprocess.CompletedProcess[str]:
        """Run a READ-ONLY *argv*, also under ``--dry-run``."""
        return _door.run(argv, input=stdin, capture_output=True, text=True, encoding='utf-8', check=False)

    def change(
        self,
        what: str,
        argv: Sequence[str],
        *,
        stdin: str | None = None,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
    ) -> int:
        """Run a CHANGING *argv* and print its tail; under ``--dry-run`` print *what* only."""
        if self.dry:
            emit(f'  [dry-run] {what}')
            return 0
        emit(f'  {what}')
        done = _door.run(
            argv,
            input=stdin,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            check=False,
            cwd=cwd,
            env={**os.environ, **({'PATH': self.path} if self.path else {}), **(env or {})},
        )
        for line in (done.stdout + done.stderr).strip().splitlines()[-20:]:
            emit(f'    | {line}')
        return done.returncode


def _key(step: Step, checkout: Path, paths: Sequence[str], *recipe: str) -> str:
    oids = {}
    for path in paths:
        done = step.read([*step.tools.git, '-C', str(checkout), 'rev-parse', '--verify', '-q', f'HEAD:{path}'])
        oids[path] = done.stdout.strip() if done.returncode == 0 else 'absent'
    return key_of(oids, *recipe)


def declared(checkout: Path) -> Builds:
    """The ``[tool.lab_commons.hpc]`` declaration in *checkout*; empty when it has none."""
    pyproject = checkout / 'pyproject.toml'
    return read_builds(pyproject.read_text(encoding='utf-8')) if pyproject.is_file() else Builds()


def _stamped(path: Path, key: str) -> bool:
    return path.is_file() and path.read_text(encoding='utf-8') == key


def build(step: Step, spec: Deployment, home: Path, repo: Repo) -> int:
    """Build *repo*'s ``.venv`` and native build, each skipped while its input key is unchanged.

    The venv is exactly what the repo's committed lock pins (PIN + FRESHNESS, user ruling 2026-10-17): nothing is
    installed over it, so the lab-commons a repo's producers import is the one its commit was tested with.
    """
    checkout = checkout_of(spec, home, repo)
    if step.dry:
        step.change(f'{repo.name}: build .venv with its [tool.lab_commons.hpc] install (e.g. uv sync --extra dev)', [])
        step.change(f'{repo.name}: its native build, when declared, into {checkout / ".lab-native"}', [])
        return 0
    builds = declared(checkout)
    if not builds.install:
        emit(f'  {repo.name} declares no [tool.lab_commons.hpc] install; refused', err=True)
        return 2
    env = {'UV_PYTHON': spec.python, 'UV_PYTHON_PREFERENCE': 'only-managed', 'UV_CACHE_DIR': str(home / 'ci/uv-cache')}
    inputs = builds.dependency_inputs or ('pyproject.toml', 'uv.lock')
    env_key = _key(step, checkout, inputs, builds.install, spec.python, *builds.needs)
    stamp = checkout / '.venv' / '.lab-deploy-env'
    if _stamped(stamp, env_key):
        emit(f'  {repo.name}: .venv current (key {env_key[:12]})')
    else:
        if rc := step.change(f'{repo.name}: {builds.install}', [*step.tools.sh, builds.install], cwd=checkout, env=env):
            return rc
        stamp.parent.mkdir(parents=True, exist_ok=True)
        stamp.write_text(env_key, encoding='utf-8')
    return _native(step, home, checkout, builds, {**env, 'ENV_KEY': env_key}) if builds.native_build else 0


def _native(step: Step, home: Path, checkout: Path, builds: Builds, env: dict[str, str]) -> int:
    """The repo's native build into ``<checkout>/.lab-native``, in its native key's own cargo target."""
    key = _key(step, checkout, builds.native_inputs, builds.native_build, env['UV_PYTHON'], env.pop('ENV_KEY'))
    out = checkout / '.lab-native'
    stamp = out / '.lab-deploy-native'
    if _stamped(stamp, key):
        emit(f'  {checkout.name}: native build current (key {key[:12]})')
        return 0
    script = f'mkdir -p "$CARGO_TARGET_DIR" && exec 8> "$CARGO_TARGET_DIR.lock" && flock 8 && {builds.native_build}'
    env |= {'LAB_CI_NATIVE': str(out), 'CARGO_TARGET_DIR': str(home / cargo_target(key))}
    if rc := step.change(
        f'{checkout.name}: native {builds.native_build}', [*step.tools.sh, script], cwd=checkout, env=env
    ):
        return rc
    out.mkdir(parents=True, exist_ok=True)
    stamp.write_text(key, encoding='utf-8')
    return 0


def update(step: Step, spec: Deployment, home: Path, repo: Repo) -> int:
    """Clone *repo*, or fetch its ref and check it out; then its submodules at their pinned commits.

    A product consumes its components by path (:mod:`dev_lab.dev.components`), so a checkout
    without its submodules builds a venv that cannot resolve them.
    """
    checkout, git = checkout_of(spec, home, repo), step.tools.git
    if not (checkout / '.git').exists():
        argv = [*git, 'clone', '-q', '-b', repo.ref, repo.url, str(checkout)]
        rc = step.change(f'git clone -b {repo.ref} {repo.url} {checkout}', argv)
    else:
        remote = f'refs/remotes/origin/{repo.ref}'
        rc = step.change(
            f'{repo.name}: git fetch origin {repo.ref}',
            [*git, '-C', str(checkout), 'fetch', '-q', 'origin', f'+refs/heads/{repo.ref}:{remote}'],
        ) or step.change(
            f'{repo.name}: git checkout -B {repo.ref} origin/{repo.ref}',
            [*git, '-C', str(checkout), 'checkout', '-q', '-B', repo.ref, remote],
        )
    if rc or not (checkout / '.gitmodules').is_file():
        return rc
    return step.change(
        f'{repo.name}: git submodule update --init --recursive',
        [*git, '-C', str(checkout), 'submodule', 'update', '-q', '--init', '--recursive'],
    )
