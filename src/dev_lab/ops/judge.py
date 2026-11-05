"""THE JUDGE HOST'S PASS: per configured repo, ``forge review judge`` with that forge's judge token.

The judging is :func:`dev_lab.dev.forgereview_bundle.judge_pending`, never re-derived here: this role only runs it
once per ``[ops.judge] repos`` URL, each in its own process so one repo's crash is that repo's line. A nonzero exit
is a failure the door alerts through ``[alerts]``; the repos after it are judged all the same.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

import lab_commons.launch as _door
from lab_commons.log import emit

from dev_lab.ops.config import OpsConfig

__all__ = ['Outcome', 'command', 'run']

#: Runs one judge command line; its exit code.
type Runner = Callable[[Sequence[str]], int]


@dataclass(frozen=True)
class Outcome:
    """One repo's pass: ``judged`` or ``failed``, with the exit code."""

    repo: str
    state: str
    detail: str = ''


def command(config: OpsConfig, url: str) -> list[str]:
    """The ``forge review judge`` line for *url*, with its forge's judge credential (an App's key, else a token)."""
    if config.judge is None:
        msg = f'{config.path} enables no [ops.judge]'
        raise ValueError(msg)
    return [config.python, '-m', 'dev_lab.dev.forge', 'review', 'judge', '--url', url, *config.judge.credential(url)]


def _subprocess(argv: Sequence[str]) -> int:
    return _door.run(list(argv), check=False).returncode


def run(config: OpsConfig, *, runner: Runner | None = None) -> list[Outcome]:
    """Judge every configured repo, one line each; a failure in one never stops the next."""
    if config.judge is None:
        msg = f'{config.path} enables no [ops.judge]'
        raise ValueError(msg)
    runner = runner or _subprocess
    outcomes = []
    for url in config.judge.repos:
        try:
            code = runner(command(config, url))
        except OSError as unrunnable:
            outcomes.append(Outcome(url, 'failed', str(unrunnable)))
            continue
        outcomes.append(
            Outcome(url, 'judged') if code == 0 else Outcome(url, 'failed', f'forge review judge exit {code}')
        )
    for outcome in outcomes:
        emit(f'[ops judge] {outcome.repo}: {outcome.state} {outcome.detail}'.rstrip())
    return outcomes
