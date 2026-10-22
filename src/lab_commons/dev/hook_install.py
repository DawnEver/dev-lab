"""HOOKS-ARE-WIRED: is every stage a repo declares backed by a live shim in the directory git consults?

THE GAP THIS CLOSES, AND IT IS NOT HYPOTHETICAL IN ANY OF THESE TREES. A hook table is a
DECLARATION; installing is a separate act on a separate machine; nothing links the two. Measured in
consumer-a on 2026-08-12: two checkouts declared pre-push hooks and ZERO hook files existed on disk
in either -- every push had run none of them, while the tree read as guarded. Measured again on
2026-09-16 in two more repos, each with every hook declared and none installed.

WHAT IS INSTALLED IS A SHIM, ONE PER STAGE, and the shim holds no decision. It finds THIS checkout's
venv interpreter (the layouts of :data:`lab_commons.dev.venvpath.CANDIDATE_RELATIVE_PATHS`) and execs
``python -m lab_commons.dev.githooks run <stage>``, which reads the hook table
(:mod:`lab_commons.dev.githooks.table`) at that moment. So a hook added to the table is live at the
next commit with nothing re-installed, and the shim text is a constant per stage -- INSTALLED means
byte-equal to :func:`shim`, and anything else in a declared slot is STALE (an older shim of ours) or
FOREIGN (somebody else's file, which an install refuses to overwrite).

THE HOOKS DIRECTORY IS ASKED OF GIT, never string-built: ``core.hooksPath`` redirects it. Reporting is
read-only; installing is the explicit ``--install`` act, idempotent. In a LINKED worktree the install
first points a worktree-scoped ``core.hooksPath`` at that worktree's OWN git dir
(``.git/worktrees/<name>/hooks``): per-worktree, outside the working tree, so it needs no ignore or
allowlist entry and never touches the shared config. The main checkout keeps git's default.

THE INSTALL ALSO SETS HOW A BRANCH IS PUBLISHED (:data:`BRANCH_DEFAULTS`, the repository's own config). Git's
``branch.autoSetupMerge`` makes a lane cut from ``origin/<integration>`` TRACK integration, so a bare push
aims there; with it off no creation path -- ``worktree add -b``, ``switch -c``, a human's -- tracks another
branch, and ``push.default=current`` + ``push.autoSetupRemote`` publish each branch under its own name and
record that as its upstream. ``PUBLISH-IS-THE-LOCAL-REF`` refuses at pre-push whatever is still mis-tracked.
"""

from __future__ import annotations

import argparse
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Final

import lab_commons.launch as _door
from lab_commons.dev.githooks.table import hook_table
from lab_commons.dev.reports import StepReport
from lab_commons.dev.venvpath import CANDIDATE_RELATIVE_PATHS
from lab_commons.log import emit

__all__ = [
    'ABSENT',
    'BRANCH_DEFAULTS',
    'FOREIGN',
    'HOOKS_STEP',
    'INSTALLED',
    'INSTALL_COMMAND',
    'NOTHING_DECLARED',
    'PROTECTED',
    'SHIM_MARKER',
    'STALE',
    'UNPROTECTED',
    'HookInstallError',
    'InstallReport',
    'StageReport',
    'declared_stages',
    'hook_installation',
    'hooks_dir',
    'install',
    'report_installation',
    'shim',
]

#: The verdict for ONE stage.
INSTALLED: Final = 'installed'
ABSENT: Final = 'declared-but-absent'
STALE: Final = 'present-but-stale'
FOREIGN: Final = 'present-but-not-ours'

#: The three-valued TOP answer. ``NOTHING_DECLARED`` is the absence of a question, never a pass.
PROTECTED: Final = 'protected'
UNPROTECTED: Final = 'unprotected'
NOTHING_DECLARED: Final = 'nothing-declared'

#: The line every shim carries: present means ours (installed or stale), absent means FOREIGN.
SHIM_MARKER: Final = '# lab_commons.dev.githooks shim'

#: The one remedy, a constant: the stage list is read from the table at install time, never restated.
INSTALL_COMMAND: Final = 'python -m lab_commons.dev.hook_install --install'

_GIT: Final = shutil.which('git') or 'git'
_GIT_TIMEOUT_S: Final = 60


@dataclass(frozen=True)
class StageReport:
    """One git hook type: the hook ids the table declares for it, and what is on disk."""

    stage: str
    hook_ids: tuple[str, ...]
    status: str
    detail: str
    path: Path


@dataclass(frozen=True)
class InstallReport:
    """Every declared stage of one repository, plus the three-valued top answer."""

    repo: Path
    hooks_dir: Path
    stages: tuple[StageReport, ...]

    @property
    def verdict(self) -> str:
        """``PROTECTED`` only when EVERY declared stage has a live shim."""
        if not self.stages:
            return NOTHING_DECLARED
        return PROTECTED if all(stage.status == INSTALLED for stage in self.stages) else UNPROTECTED

    @property
    def failing(self) -> tuple[StageReport, ...]:
        """Declared stages whose shim is absent, stale, or somebody else's."""
        return tuple(stage for stage in self.stages if stage.status != INSTALLED)


class HookInstallError(RuntimeError):
    """The install act could not leave the checkout protected, and says which stage and why."""


def hooks_dir(repo: Path) -> Path:
    """The directory git will ACTUALLY consult for hooks in *repo* -- asked of git, never string-built."""
    out = _door.run(
        [_GIT, '-C', str(repo), 'rev-parse', '--git-path', 'hooks'],
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        check=True,
        timeout=_GIT_TIMEOUT_S,
    ).stdout.strip()
    return Path(out) if Path(out).is_absolute() else (repo / out)


def _git(repo: Path, *args: str) -> str:
    return _door.run(
        [_GIT, '-C', str(repo), *args],
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        check=True,
        timeout=_GIT_TIMEOUT_S,
    ).stdout.strip()


def _scope_linked_worktree(repo: Path) -> None:
    """In a linked worktree, point a worktree-scoped ``core.hooksPath`` at its own git dir's ``hooks``."""
    git_dir = Path(_git(repo, 'rev-parse', '--absolute-git-dir'))
    common = Path(_git(repo, 'rev-parse', '--path-format=absolute', '--git-common-dir'))
    if git_dir.resolve() == common.resolve():
        return
    _git(repo, 'config', 'extensions.worktreeConfig', 'true')
    _git(repo, 'config', '--worktree', 'core.hooksPath', (git_dir / 'hooks').as_posix())


#: git config every install sets in the repository: no branch tracks another; a push publishes it as itself.
BRANCH_DEFAULTS: Final = {
    'branch.autoSetupMerge': 'false',
    'push.default': 'current',
    'push.autoSetupRemote': 'true',
}


def _publish_under_own_name(repo: Path) -> None:
    for key, value in BRANCH_DEFAULTS.items():
        _git(repo, 'config', '--local', key, value)


def declared_stages(repo: Path) -> dict[str, tuple[str, ...]]:
    """Map git hook type -> the hook ids *repo*'s merged table declares for it."""
    return {stage: tuple(hook.id for hook in hooks) for stage, hooks in hook_table(repo).items()}


def shim(stage: str) -> str:
    """The ``.git/hooks/<stage>`` file: find this checkout's venv, run the stage's declared hooks there."""
    candidates = ' '.join('/'.join(parts) for parts in CANDIDATE_RELATIVE_PATHS)
    return (
        '#!/bin/sh\n'
        f'{SHIM_MARKER} -- installed by `{INSTALL_COMMAND}`; the hooks are declared in TOML\n'
        '# (lab_commons/dev/githooks/base.toml + [tool.lab_commons.hooks] in pyproject.toml).\n'
        'top=$(git rev-parse --show-toplevel) || exit 1\n'
        f'for rel in {candidates}; do\n'
        '  if [ -x "$top/$rel" ]; then\n'
        f'    exec "$top/$rel" -m lab_commons.dev.githooks run {stage} "$@"\n'
        '  fi\n'
        'done\n'
        f'echo "[githooks] {stage}: no venv interpreter in $top ({candidates}); this checkout ran no hook." >&2\n'
        'echo "[githooks]   Remedy: build the venv (python -m lab_commons.dev.dep --bootstrap <checkout>), '
        'then commit or push again." >&2\n'
        'exit 1\n'
    )


def _inspect(path: Path, stage: str) -> tuple[str, str]:
    if not path.exists():
        return ABSENT, 'no file at this path -- never installed, or removed'
    text = path.read_text(encoding='utf-8', errors='ignore')
    if text == shim(stage):
        return INSTALLED, f'the lab_commons shim for {stage}'
    if SHIM_MARKER in text:
        return STALE, 'a lab_commons shim, but not the current one for this slot'
    return FOREIGN, 'a hook file lab_commons did not write; installing would overwrite it'


def hook_installation(repo: Path) -> InstallReport:
    """Answer, for *repo*, whether every stage its table declares has a live shim."""
    directory = hooks_dir(repo)
    reports = []
    for stage, ids in declared_stages(repo).items():
        path = directory / stage
        status, detail = _inspect(path, stage)
        reports.append(StageReport(stage=stage, hook_ids=ids, status=status, detail=detail, path=path))
    return InstallReport(repo=repo, hooks_dir=directory, stages=tuple(reports))


def install(repo: Path) -> InstallReport:
    """Write the shim of every declared stage of *repo*, idempotently -- the ONE act every bootstrap calls.

    A FOREIGN file in a declared slot is REFUSED before anything is written, never overwritten. The
    returned report is RE-MEASURED after the act, so a write that did not land raises.

    Raises:
        HookInstallError: a foreign hook occupies a declared slot, or the checkout is still unprotected.

    """
    _scope_linked_worktree(repo)
    _publish_under_own_name(repo)
    before = hook_installation(repo)
    if before.verdict != UNPROTECTED:
        return before
    foreign = [stage for stage in before.failing if stage.status == FOREIGN]
    if foreign:
        paths = ', '.join(f'{stage.stage} ({stage.path})' for stage in foreign)
        msg = (
            f'refusing to install over a hook lab_commons did not write: {paths}. Move it aside (or declare '
            f'what it does as a row of [tool.lab_commons.hooks]), then re-run `{INSTALL_COMMAND}`.'
        )
        raise HookInstallError(msg)
    before.hooks_dir.mkdir(parents=True, exist_ok=True)
    for stage in before.failing:
        stage.path.write_text(shim(stage.stage), encoding='utf-8', newline='\n')
        stage.path.chmod(0o755)
    after = hook_installation(repo)
    if after.verdict != PROTECTED:
        listing = ', '.join(f'{stage.stage}={stage.status}' for stage in after.failing)
        msg = f'the shims were written and {after.hooks_dir} is still unprotected: {listing}'
        raise HookInstallError(msg)
    return after


def report_installation(argv: list[str] | None = None) -> int:
    """CLI. Exit 0 = every declared stage is live, 1 = at least one is not, 2 = nothing is declared."""
    parser = argparse.ArgumentParser(description='Are the hooks this repository declares installed?')
    parser.add_argument('--repo', type=Path, default=Path.cwd())
    parser.add_argument('--install', action='store_true', help='write the shims (an EXPLICIT request)')
    args = parser.parse_args(argv)
    root = args.repo.resolve()

    if args.install:
        try:
            done = install(root)
        except HookInstallError as exc:
            emit(f'[hooks-installed] NOT INSTALLED -- {exc}')
            return 1
        emit(f'[hooks-installed] {done.verdict} -- {done.hooks_dir}')
        return 0 if done.verdict == PROTECTED else 2

    report = hook_installation(root)
    emit(f'[hooks-installed] the hooks directory git will use: {report.hooks_dir}')
    if report.verdict == NOTHING_DECLARED:
        emit(f'[hooks-installed] NOTHING DECLARED -- {report.repo} runs no hook stage')
        return 2
    for stage in report.stages:
        emit(f'  {stage.stage:<12} {stage.status:<22} {stage.detail}')
        emit(f'  {"":<12} declares: {", ".join(stage.hook_ids)}')
    if report.verdict == PROTECTED:
        emit('[hooks-installed] OK -- every declared stage has a live shim.')
        return 0
    emit(
        f'[hooks-installed] UNPROTECTED -- {len(report.failing)} of {len(report.stages)} declared stage(s) '
        f'are not live. Every commit or push through this checkout ran none of them.\n'
        f'  Install with:  {INSTALL_COMMAND}'
    )
    return 1


if __name__ == '__main__':
    raise SystemExit(report_installation())


#: The step name the hooks-installed check reports under (user directive 2026-09-23). A STEP rather
#: than a test so that a verify narrowed to one path still runs it: the adoption test only runs when
#: a suite selects it, and the only path that skips this is one where verify is not run at all.
HOOKS_STEP: Final = 'hooks-installed'


def read_hooks(root: Path, *, handle: IO[str]) -> StepReport:
    """The hooks-installed step: a named failure when a declared hook is not live, with its remedy.

    It reads and never installs -- the install act is :func:`lab_commons.dev.hook_install.install`,
    called from each repo's bootstrap. ``nothing-declared`` passes: a repo with no configuration has
    no hook for this step to find missing.
    """
    report = hook_installation(root)
    handle.write(f'$ {HOOKS_STEP}: {report.verdict} ({report.hooks_dir})\n')
    for stage in report.failing:
        handle.write(f'  {stage.stage:<12} {stage.status:<28} {stage.detail}\n')
    if report.verdict == UNPROTECTED:
        handle.write(f'  remedy: {INSTALL_COMMAND}\n')
    handle.flush()
    failed = (HOOKS_STEP,) if report.verdict == UNPROTECTED else ()
    return StepReport(name=HOOKS_STEP, reported=(HOOKS_STEP,), failures=failed)
