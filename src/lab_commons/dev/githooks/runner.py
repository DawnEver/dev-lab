"""Run one git hook stage: every hook :mod:`lab_commons.dev.githooks.table` declares for it.

``python -m lab_commons.dev.githooks run <stage> [git's hook arguments]`` -- what each installed
``.git/hooks/<stage>`` shim execs, in the repo's own venv (:mod:`lab_commons.dev.hook_install`).

WHAT A STAGE HANDS A HOOK IS GIT'S OWN CONTRACT, read here once:

* ``pre-commit`` -- the STAGED paths (``git diff --cached``, added/copied/modified/renamed). A hook
  selects among them with ``files``/``exclude``, gets them appended when ``pass_files``, and is skipped
  when it selects none unless ``always_run``. A hook that changes the working tree FAILS, so a
  formatter's rewrite is seen and staged by a person rather than committed unseen. Nothing is stashed:
  a hook reads the working tree as it stands.
* ``commit-msg`` -- git's one argument, the message file, appended to every hook's ``run``.
* ``pre-push`` -- git's ref lines (``<local ref> <local sha> <remote ref> <remote sha>``) read from
  stdin ONCE and piped to every hook's stdin; a hook with ``refs`` runs only when a pushed remote ref
  matches and sees only those lines. Paths are the ones the pushed commits change, selected as above.

Every hook runs; the stage fails when any hook failed. Exit codes are each hook's own.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from lab_commons.dev.githooks.table import STAGES, Hook, hook_table
from lab_commons.log import emit

__all__ = [
    'ZERO_SHA',
    'PushLine',
    'parse_push_lines',
    'pushed_paths',
    'resolve',
    'run_stage',
    'staged_paths',
    'worktree_diff',
]

#: The object name git writes for the absent side of a ref: a deleted ref, or one the remote lacks.
ZERO_SHA: Final = '0' * 40

#: The fields of one pre-push line: local ref, local sha, remote ref, remote sha.
_PUSH_FIELDS: Final = 4

_GIT: Final = shutil.which('git') or 'git'
_GIT_TIMEOUT_S: Final = 120

#: How many characters of path arguments one invocation carries -- under Windows' 32k command line.
_ARG_BUDGET: Final = 24_000


@dataclass(frozen=True)
class PushLine:
    """One ref a push updates, as git's pre-push protocol states it."""

    local_ref: str
    local_sha: str
    remote_ref: str
    remote_sha: str

    @property
    def deleted(self) -> bool:
        """The push deletes *remote_ref*: git writes the zero sha on the local side."""
        return self.local_sha == ZERO_SHA

    @property
    def line(self) -> str:
        """The line as git wrote it."""
        return f'{self.local_ref} {self.local_sha} {self.remote_ref} {self.remote_sha}'


def parse_push_lines(text: str) -> tuple[PushLine, ...]:
    """Git's pre-push stdin, one :class:`PushLine` per four-field line; anything else is not a ref line."""
    return tuple(
        PushLine(*fields) for fields in (line.split() for line in text.splitlines()) if len(fields) == _PUSH_FIELDS
    )


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        [_GIT, '-C', str(root), *args],
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        check=True,
        timeout=_GIT_TIMEOUT_S,
    ).stdout


def staged_paths(root: Path) -> tuple[str, ...]:
    """The paths a commit would add or change -- deletions name no file a hook could read."""
    out = _git(root, 'diff', '--cached', '--name-only', '--diff-filter=ACMR', '-z')
    return tuple(path for path in out.split('\0') if path)


def pushed_paths(root: Path, lines: Sequence[PushLine], remote: str) -> tuple[str, ...]:
    """The paths the pushed commits change: from the remote's sha when it has one, else what *remote* lacks."""
    found: dict[str, None] = {}
    for line in lines:
        if line.deleted:
            continue
        if line.remote_sha != ZERO_SHA and _has_commit(root, line.remote_sha):
            out = _git(root, 'diff', '--name-only', '--diff-filter=ACMR', '-z', line.remote_sha, line.local_sha)
        else:
            exclude = [f'--remotes={remote}'] if remote else []
            out = _git(
                root, 'log', '--name-only', '--diff-filter=ACMR', '-z', '--format=', line.local_sha, '--not', *exclude
            )
        found.update(dict.fromkeys(path.strip() for path in out.split('\0') if path.strip()))
    return tuple(found)


def _has_commit(root: Path, sha: str) -> bool:
    done = subprocess.run(
        [_GIT, '-C', str(root), 'cat-file', '-e', f'{sha}^{{commit}}'],
        capture_output=True,
        check=False,
        timeout=_GIT_TIMEOUT_S,
    )
    return done.returncode == 0


def worktree_diff(root: Path) -> str:
    """The working tree's unstaged diff -- what a hook must not change during a commit."""
    return _git(root, 'diff', '--no-color', '--binary')


def resolve(run: Sequence[str], python: str = sys.executable) -> list[str]:
    """*run* with its first word made absolute: ``python`` is *python*; a tool is looked up beside it first."""
    first, *rest = run
    if first == 'python':
        return [python, *rest]
    found = shutil.which(first, path=str(Path(python).parent)) or shutil.which(first)
    return [found or first, *rest]


def _chunks(paths: Sequence[str]) -> list[list[str]]:
    out: list[list[str]] = [[]]
    size = 0
    for path in paths:
        if out[-1] and size + len(path) + 1 > _ARG_BUDGET:
            out.append([])
            size = 0
        out[-1].append(path)
        size += len(path) + 1
    return out


Runner = Callable[[list[str], Path, str | None, Mapping[str, str]], int]


def _subprocess_runner(argv: list[str], cwd: Path, stdin: str | None, env: Mapping[str, str]) -> int:
    return subprocess.run(
        argv, cwd=cwd, input=stdin, text=True, encoding='utf-8', check=False, env={**os.environ, **env}
    ).returncode


def _argvs(hook: Hook, stage: str, git_args: Sequence[str], chosen: Sequence[str]) -> list[list[str]]:
    base = resolve(hook.run)
    if stage == 'commit-msg':
        return [[*base, *git_args[:1]]]
    if hook.pass_files and chosen:
        return [[*base, *chunk] for chunk in _chunks(chosen)]
    return [base]


def _run_hook(hook: Hook, argvs: list[list[str]], root: Path, stdin: str | None, runner: Runner) -> int:
    """Each argv in turn, stopping at the first failure; at pre-commit a rewrite of the tree fails too."""
    before = worktree_diff(root) if hook.stage == 'pre-commit' else ''
    for argv in argvs:
        if code := runner(argv, root, stdin, hook.env):
            return code
    if hook.stage == 'pre-commit' and worktree_diff(root) != before:
        emit(f'[githooks] pre-commit {hook.id}: it changed the working tree; review, stage, commit again')
        return 1
    return 0


def _selected(stage: str, root: Path, hooks: Sequence[Hook] | None, push: Sequence[PushLine]) -> tuple[Hook, ...]:
    """The hooks of *stage* to run -- none for a pre-push with no ref line.

    Git's protocol: a push whose every ref is already up to date (a retry after an attempt that
    landed) still runs pre-push, with no ref line. It publishes nothing, so nothing is judged.
    """
    if stage == 'pre-push' and not push:
        emit('[githooks] pre-push: no ref line on stdin -- this push publishes nothing, so nothing is judged')
        return ()
    return tuple(hook_table(root).get(stage, ()) if hooks is None else hooks)


def run_stage(
    stage: str,
    git_args: Sequence[str] = (),
    *,
    root: Path,
    stdin: str = '',
    hooks: Sequence[Hook] | None = None,
    runner: Runner = _subprocess_runner,
) -> int:
    """Run every hook of *stage* in *root*; ``0`` when all passed or were skipped, else ``1``.

    Args:
        stage: one of :data:`~lab_commons.dev.githooks.table.STAGES`.
        git_args: the arguments git passed the hook (commit-msg: the message file; pre-push: remote, url).
        root: the checkout's top level; every hook runs there.
        stdin: what git wrote on the hook's stdin (pre-push: the ref lines).
        hooks: the hooks to run; the merged table of *root* when omitted.
        runner: runs ``(argv, cwd, stdin, env)`` and returns the exit code; injected for tests only.

    """
    if stage not in STAGES:
        msg = f'unknown hook stage {stage!r}; the family runs {list(STAGES)}'
        raise ValueError(msg)
    push = parse_push_lines(stdin) if stage == 'pre-push' else ()
    selected_hooks = _selected(stage, root, hooks, push)
    paths: tuple[str, ...] = ()
    if stage == 'pre-commit':
        paths = staged_paths(root)
    failed: list[str] = []
    for hook in selected_hooks:
        lines = push
        if hook.refs is not None:
            lines = tuple(line for line in push if not line.deleted and re.search(hook.refs, line.remote_ref))
            if not lines:
                emit(f'[githooks] {stage} {hook.id}: skipped -- no pushed ref matches {hook.refs!r}')
                continue
        if stage == 'pre-push':
            paths = pushed_paths(root, lines, git_args[0] if git_args else '')
        chosen = [path for path in paths if hook.selects(path)]
        if stage != 'commit-msg' and not chosen and not hook.always_run:
            emit(f'[githooks] {stage} {hook.id}: skipped -- no path selected')
            continue
        hook_stdin = ''.join(f'{line.line}\n' for line in lines) if stage == 'pre-push' else None
        code = _run_hook(hook, _argvs(hook, stage, git_args, chosen), root, hook_stdin, runner)
        emit(f'[githooks] {stage} {hook.id}: {"passed" if code == 0 else f"FAILED (exit {code})"}')
        if code:
            failed.append(hook.id)
    if failed:
        emit(f'[githooks] {stage}: {len(failed)} hook(s) failed: {", ".join(failed)}', err=True)
        return 1
    return 0


def main(stage: str, git_args: Sequence[str]) -> int:
    """The ``run`` subcommand: the checkout's top level from git, stdin read once when the stage has one."""
    root = Path(_git(Path.cwd(), 'rev-parse', '--show-toplevel').strip())
    stdin = sys.stdin.read() if stage == 'pre-push' and not sys.stdin.isatty() else ''
    return run_stage(stage, git_args, root=root, stdin=stdin)
