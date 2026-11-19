"""GITHOOKS-GIT-FAILED: a git query of the hook runner itself failed, said with its rule, git's words and the door.

The runner asks git what a stage changes; when that query fails (an unfinished merge, a missing object) the stage
would otherwise die on a bare traceback naming no rule (O21). PURE: formats one message.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import subprocess

__all__ = ['git_failed']


def git_failed(stage: str, failed: subprocess.CalledProcessError) -> str:
    """A git query of the runner itself failed (O21): the rule, git's command and its own words, and the door."""
    argv = [str(word) for word in (failed.cmd if isinstance(failed.cmd, (list, tuple)) else [failed.cmd])]
    shown = ' '.join(['git', *argv[argv.index('-C') + 2 :]] if '-C' in argv else argv)
    said = (failed.stderr or '').strip() if isinstance(failed.stderr, str) else ''
    return (
        f'[githooks] {stage}: GITHOOKS-GIT-FAILED -- `{shown}` exited {failed.returncode}'
        f'{": " + said if said else ""}. The hooks could not read what this {stage} changes. '
        f'Door: make that git command succeed in this checkout (`git status` names an unfinished merge, '
        f'cherry-pick or a missing object), then re-run the {stage}.'
    )
