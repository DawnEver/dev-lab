"""Real git repositories for the branch-flow tests: a bare ``origin`` and a clone with trunk + integration."""

from __future__ import annotations

from pathlib import Path

from _forge_fake import git_out, run_git


def commit(repo: Path, name: str, text: str, message: str | None = None) -> str:
    """Write *name* with *text*, commit it, return the new HEAD."""
    (repo / name).write_text(text, encoding='utf-8')
    run_git(repo, 'add', name)
    run_git(repo, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '--no-verify', '-m', message or name)
    return git_out(repo, 'rev-parse', 'HEAD')


def clone_pair(tmp_path: Path) -> tuple[Path, Path]:
    """``(bare origin, clone)``: main and integrate/main at one root commit, both pushed."""
    bare = tmp_path / 'origin.git'
    run_git(tmp_path, 'init', '-q', '--bare', '-b', 'main', str(bare))
    work = tmp_path / 'work'
    run_git(tmp_path, 'clone', '-q', str(bare), str(work))
    run_git(work, 'config', 'user.name', 't')
    run_git(work, 'config', 'user.email', 't@t')
    run_git(work, 'checkout', '-q', '-b', 'main')
    commit(work, 'base.txt', 'base\n')
    run_git(work, 'push', '-q', '--no-verify', 'origin', 'main', 'main:integrate/main')
    run_git(work, 'fetch', '-q', 'origin')
    return bare, work


def advance(work: Path, branch: str, name: str, text: str) -> str:
    """Commit *name* on origin's *branch* from *work* (via a detached worktree-free push); returns the sha."""
    run_git(work, 'checkout', '-q', '-B', f'tmp-{branch.replace("/", "-")}', f'origin/{branch}')
    sha = commit(work, name, text)
    run_git(work, 'push', '-q', '--no-verify', 'origin', f'HEAD:refs/heads/{branch}')
    run_git(work, 'fetch', '-q', 'origin')
    return sha
