"""What a forge write tells the bound rem task: the PR-head advice, and the opened PR or issue it journals.

Split from :mod:`dev_lab.dev.forgecli`, which calls both around every ``issue``/``pr`` verb.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from lab_commons.log import emit

from dev_lab.dev import taskbinding, taskgate
from dev_lab.dev.forgework import Issue, PullRequest

if TYPE_CHECKING:
    import argparse
    from collections.abc import Mapping

__all__ = ['head_advice', 'record']


def head_advice(head: str, env: Mapping[str, str] | None) -> tuple[str, ...]:
    """A session bound to a task is told its PR heads are ``pr/<task>/<feature>`` (:mod:`dev_lab.dev.taskbinding`)."""
    try:
        task = taskbinding.session_task(os.environ if env is None else env)
    except ValueError:
        return ()
    said = None if task is None else taskbinding.head_advice(head, taskbinding.slug_of(task))
    return () if said is None else (said,)


def record(args: argparse.Namespace, result: object, root: Path, env: Mapping[str, str]) -> None:
    """An opened PR or issue is appended to the bound rem task's journal (:func:`taskgate.record`)."""
    if (args.noun, args.verb) not in {('pr', 'create'), ('issue', 'create')}:
        return
    if (
        isinstance(result, (PullRequest, Issue))
        and (url := result.url)
        and (said := taskgate.record(root, args.noun, url, env=env, read=taskgate.reader_for(env, Path.home())))
    ):
        emit(f'[forge] {said}', err=True)  # the task names its own PRs and issues
