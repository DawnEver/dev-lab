"""Stand in for rem binding a session: write the binding file exactly as rem's prompt hook does.

rem owns the binding and is its only writer (its ``hooks/task-authority.js``, on the user's ``task: <slug>`` prompt);
dev-lab only reads it (:mod:`dev_lab.dev.taskbinding`). The contract is rem's ``skills/rem/reference/tasks.md``
section "The binding file", pinned on rem's side by ``tests/task-bind.test.mjs``. This helper writes that shape --
``<ledger>/.bindings/<session>.json`` = ``{"session": <id>, "task": "<slug>@<authority>"}`` -- and nothing else.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from dev_lab.dev import taskbinding

if TYPE_CHECKING:
    from pathlib import Path


def bind_as_rem(root: Path, session: str, slug: str) -> str:
    """Bind *session* to the OPEN task *slug* of *root*'s ledger as rem would; the task id written."""
    task = taskbinding.task_id(root, slug)
    target = taskbinding.ledger(root) / taskbinding.BINDINGS / f'{session}.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({'session': session, 'task': task}), encoding='utf-8')
    return task
