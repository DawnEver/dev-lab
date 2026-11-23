"""What a forge write tells the bound rem task: the PR-head advice, and the opened PR or issue it journals.

Split from :mod:`dev_lab.dev.forgecli`, which calls both around every ``issue``/``pr`` verb.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from lab_commons.log import emit

from dev_lab.dev import taskgate, taskledger
from dev_lab.dev.forgework import Issue, PullRequest

if TYPE_CHECKING:
    import argparse
    from collections.abc import Mapping

__all__ = ['head_advice', 'record']


def head_advice(head: str, root: Path) -> tuple[str, ...]:
    """A checkout on a task branch is told its PR heads are ``pr/<task>/<feature>`` (:func:`taskledger.task_of`)."""
    try:
        task = taskledger.task_of(root)
    except (ValueError, LookupError):
        return ()
    said = None if task is None else taskledger.head_advice(head, taskledger.slug_of(task))
    return () if said is None else (said,)


def record(args: argparse.Namespace, result: object, root: Path, env: Mapping[str, str]) -> None:
    """An opened PR or issue is appended to the journal of *root*'s task (:func:`taskgate.record`)."""
    if (args.noun, args.verb) not in {('pr', 'create'), ('issue', 'create')}:
        return
    if (
        isinstance(result, (PullRequest, Issue))
        and (url := result.url)
        and (said := taskgate.record(root, args.noun, url, read=taskgate.reader_for(env, Path.home())))
    ):
        emit(f'[forge] {said}', err=True)  # the task names its own PRs and issues
