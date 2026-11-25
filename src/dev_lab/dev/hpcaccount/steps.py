"""The deployment's changing steps: run-or-print, and the checkout and venv each served repo needs.

Every changing action goes through :class:`Step`, which under ``--dry-run`` only prints it.
"""

from __future__ import annotations

import shlex
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import lab_commons.launch as _door
from lab_commons.hpc.builds import Builds, cargo_target, key_of, read_builds
from lab_commons.log import emit

from dev_lab.dev import boxmigrate, venvcurrent, venvpointer
from dev_lab.dev.harness import child_env
from dev_lab.dev.hpcaccount import selfclean
from dev_lab.dev.hpcaccount.checkout import clone, converge
from dev_lab.dev.hpcaccount.checks import LOGIN_MARK, login_files, login_line
from dev_lab.dev.hpcaccount.spec import MARK, Deployment, Repo, checkout_of, merge_crontab, uv_cache

__all__ = ['Step', 'Tools', 'build', 'crontab', 'declared', 'login', 'prune_uv', 'update']


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
        self.output = ''  # the last change's stdout and stderr: what a failed step reads to clean after itself

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
            env=child_env({'PATH': self.path} if self.path else {}, env or {}),
        )
        self.output = done.stdout + done.stderr
        for line in self.output.strip().splitlines()[-20:]:
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


def build(step: Step, spec: Deployment, _home: Path, repo: Repo) -> int:
    """Build *repo*'s ``.venv`` and native build, each skipped while its input key is unchanged.

    The venv is exactly what the repo's committed lock pins (PIN + FRESHNESS, user ruling 2026-10-17): nothing is
    installed over it, so the lab-commons a repo's producers import is the one its commit was tested with.

    A changed key BUILDS BESIDE (:func:`dev_lab.dev.venvcurrent.fresh`) and is published only after the install
    succeeded: a tick running from the live environment never sees it rewritten under it, and a failed build is
    abandoned with the live one untouched. The passed-over environment is left for ``venvprune``.
    """
    checkout = checkout_of(spec, repo)
    if step.dry:
        step.change(f'{repo.name}: build .venv with its [tool.lab_commons.hpc] install (e.g. uv sync --extra dev)', [])
        step.change(f'{repo.name}: its native build, when declared, into {checkout / ".lab-native"}', [])
        step.change(f'{repo.name}: box ledger migration, when its lab-commons provides the verb', [])
        return 0
    builds = declared(checkout)
    if not builds.install:
        emit(f'  {repo.name} declares no [tool.lab_commons.hpc] install; refused', err=True)
        return 2
    env = {
        'UV_PYTHON': spec.python,
        'UV_PYTHON_PREFERENCE': 'only-managed',
        'UV_CACHE_DIR': str(uv_cache(spec.root)),
        'UV_LINK_MODE': 'hardlink',
    }
    inputs = builds.dependency_inputs or ('pyproject.toml', 'uv.lock')
    env_key = _key(step, checkout, inputs, builds.install, spec.python, *builds.needs)
    live = venvpointer.current(checkout)  # the one rule (dev-lab #641): the env a launch there takes
    env['UV_PROJECT_ENVIRONMENT'] = str(live)
    if _stamped(live / '.lab-deploy-env', env_key):
        emit(f'  {repo.name}: {live.name} current (key {env_key[:12]})')
    else:
        beside = _beside(step, repo.name, checkout, builds.install, env)
        if isinstance(beside, int):
            return beside
        beside.mkdir(parents=True, exist_ok=True)
        (beside / '.lab-deploy-env').write_text(env_key, encoding='utf-8')
        try:
            emit(f'  {repo.name}: {venvcurrent.publish(checkout, beside)}')
            for line in venvcurrent.reclaim(checkout):  # superseded envs go at the switch; a held one is kept
                emit(f'  {repo.name}: {line}')
        except venvcurrent.PublishRefused as refused:
            emit(f'  {repo.name}: REFUSED: {refused}')
            return 1
    # LEDGER-MIGRATES-ON-INSTALL: every deploy, idempotent, so a venv stamped before the verb existed migrates too
    if rc := boxmigrate.migrate(str(venvpointer.current(checkout) / 'bin' / 'python')):
        return rc
    return _native(step, spec.root, checkout, builds, {**env, 'ENV_KEY': env_key}) if builds.native_build else 0


def _beside(step: Step, name: str, checkout: Path, install: str, env: dict[str, str]) -> Path | int:
    """Build a fresh env beside the live one; a failure removes its own output (:mod:`.selfclean`), its rc returned.

    A failure on the uv git cache removes the damaged checkout of the failing commit and builds once more.
    """
    cache = Path(env['UV_CACHE_DIR'])
    for attempt in range(2):
        beside = venvcurrent.fresh(checkout)
        env['UV_PROJECT_ENVIRONMENT'] = str(beside)
        if not (rc := step.change(f'{name}: {install}', [*step.tools.sh, install], cwd=checkout, env=env)):
            return beside
        venvcurrent.abandon(beside)
        for path in selfclean.uv_temporaries(cache):
            emit(f'  {name}: removed the failed build -- its uv temporary {path}')
        damaged = selfclean.damaged_git(cache, step.output) if attempt == 0 else []
        for path in damaged:
            emit(f'  {name}: removed the damaged uv git checkout {path}; building once more')
        if not damaged:
            return rc
    return rc


def prune_uv(step: Step, spec: Deployment) -> int:
    """``uv cache prune`` of the account's ONE cache after the venvs: what no env links any more goes now."""
    cache = str(uv_cache(spec.root))
    step.change(f'uv cache prune --cache-dir {cache}', [*step.tools.uv, 'cache', 'prune', '--cache-dir', cache])
    return 0  # a prune that failed frees nothing; retention prunes again


def _native(step: Step, root: str, checkout: Path, builds: Builds, env: dict[str, str]) -> int:
    """The repo's native build into ``<checkout>/.lab-native``, in its native key's own cargo target."""
    key = _key(step, checkout, builds.native_inputs, builds.native_build, env['UV_PYTHON'], env.pop('ENV_KEY'))
    out = checkout / '.lab-native'
    stamp = out / '.lab-deploy-native'
    if _stamped(stamp, key):
        emit(f'  {checkout.name}: native build current (key {key[:12]})')
        return 0
    script = f'mkdir -p "$CARGO_TARGET_DIR" && exec 8> "$CARGO_TARGET_DIR.lock" && flock 8 && {builds.native_build}'
    env |= {'LAB_CI_NATIVE': str(out), 'CARGO_TARGET_DIR': str(Path(root) / cargo_target(key))}
    if rc := step.change(
        f'{checkout.name}: native {builds.native_build}', [*step.tools.sh, script], cwd=checkout, env=env
    ):
        return rc
    out.mkdir(parents=True, exist_ok=True)
    stamp.write_text(key, encoding='utf-8')
    return 0


def update(step: Step, spec: Deployment, _home: Path, repo: Repo) -> int:
    """Clone *repo*, or converge its checkout on the declared ref; then its submodules at their pinned commits.

    An existing checkout is made the ref whatever an interrupted deploy left (:func:`.checkout.converge`); one that
    holds a commit or a tracked change of its own is refused by name. A product consumes its components by path
    (:mod:`dev_lab.dev.components`), so a checkout without its submodules builds a venv that cannot resolve them.
    """
    checkout, git = checkout_of(spec, repo), step.tools.git
    rc = converge(step, checkout, repo) if (checkout / '.git').exists() else clone(step, checkout, repo)
    if rc or not (checkout / '.gitmodules').is_file():
        return rc
    return step.change(
        f'{repo.name}: git submodule update --init --recursive',
        [*git, '-C', str(checkout), 'submodule', 'update', '-q', '--init', '--recursive'],
    )


def crontab(step: Step, lines: Sequence[str]) -> int:
    """Replace this tool's marked crontab lines with *lines*, every other line kept; each line dropped is printed."""
    listed = step.read([*step.tools.crontab, '-l'])
    current = listed.stdout if listed.returncode == 0 else ''
    if listed.returncode and 'no crontab' not in listed.stderr:
        emit(f'  crontab -l exited {listed.returncode}: {listed.stderr.strip()}', err=True)
        return 2
    wanted = merge_crontab(current, lines)
    if wanted == current:
        emit(f'  crontab: the {len(lines)} marked line(s) are already in place')
        return 0
    for line in current.splitlines():
        if MARK in line and line not in lines:
            emit(f'  crontab: remove {line}')
    return step.change(
        f'crontab: write {len(lines)} marked line(s), every other line kept', [*step.tools.crontab, '-'], stdin=wanted
    )


def login(step: Step, home: Path, root: str) -> int:
    """The ONE marked :func:`login_line` in each of :func:`login_files`, each file backed up first.

    A marked line that differs (an older line, another root) is replaced in place, never kept beside the new one.
    """
    emit("[login] the login shell's PATH names the tick's user installs and LAB_ROOT the declared root")
    line = login_line(home, root)
    for path in login_files(home):
        text = path.read_text(encoding='utf-8', errors='replace') if path.is_file() else ''
        marked = [one for one in text.splitlines() if LOGIN_MARK in one]
        if marked == [line]:
            emit(f'  {path}: current')
            continue
        file, backup = shlex.quote(str(path)), shlex.quote(f'{path}.lab-deploy.bak')
        keep = f'[ ! -e {file} ] || [ -e {backup} ] || cp -p {file} {backup}'
        drop = f'{{ [ ! -e {file} ] || sed -i {shlex.quote(f"/{LOGIN_MARK}/d")} {file}; }}'
        script = f'{{ {keep}; }} && {drop} && echo {shlex.quote(line)} >> {file}'
        if rc := step.change(f'{path}: back up, then append {line}', [*step.tools.sh, script]):
            return rc
    return 0
