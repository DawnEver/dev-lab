"""THE INTEGRATOR IS A SESSION OR TASK ROLE, PROVED BY A CONSENT CREDENTIAL -- never a host's (2026-11-12, -13).

A host file declares only what its MACHINE may reach (``[dev] hpc``, rendered as ``[hpc] reach``). Verification
accounts are reached by a SESSION holding the integrator role, on a machine whose reach is not empty: the family
declares ``[hpc] session_reach = { integrator = ["verification"] }`` and ``[hpc] session_verifier`` naming
:func:`roles`, which :func:`lab_commons.hpc.grants.load_grants` calls -- so the ``lab_commons.hpc`` door and every
``dev_lab.dev.hpcaccount`` verb (all of which load through it) check the role before they touch an account.

THE ROLE IS NEVER SELF-CLAIMED. It is a consent credential of :mod:`dev_lab.ops.consent` the user grants with one
TOTP code, held by one of two identities:

* a SESSION -- :data:`ACTION`, subject = ``$CLAUDE_CODE_SESSION_ID``, a day at most;
* a TASK -- :data:`TASK_ACTION`, subject = the task id ``<slug>@<authority>``, a week at most. A task is a directory
  ``.claude/tasks/<slug>/`` of the checkout whose ``TASK.md`` the user's own task-open wrote with the ``authority``
  minted then: a task closed and reopened under the same slug is a new id, so an old grant never carries over.

A SESSION WORKS ON A TASK ONLY BY THE USER'S WORD. A prompt whose first line is ``task: <slug>`` binds the session
receiving it to that open task: the ``UserPromptSubmit`` hook (:func:`bind`) writes the binding from the harness's
own payload (its ``session_id``, the user's ``prompt``) into the consent state, which no agent tool may write
(CONSENT-CODE-FROM-THE-USER, :mod:`dev_lab.dev.consentguard`). An agent can name a worktree or a branch after a task
and can set an environment variable; it cannot author the user's prompt, so neither of those binds.

:func:`held` verifies OFFLINE on every load -- signature, registry row, expiry, subject, and for a task the
session's binding -- so an expired credential, another session's or task's, or a session never bound grants nothing.

Granting it (the code is the USER's, CONSENT-CODE-FROM-THE-USER)::

    python -m dev_lab.dev.hpcaccount.session request [--task SLUG] [--hours H] > <request.json>
    python -m dev_lab.ops.consent grant <request.json> --code <the user's code>
    python -m dev_lab.dev.hpcaccount.session status      # which identity gives this session the role
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final, TextIO

from lab_commons.log import emit

from dev_lab.dev.consentguard import state_dir
from dev_lab.dev.sessionprs import SESSION_ENV
from dev_lab.ops.consent.actions import ACTIONS
from dev_lab.ops.consent.client import public_key
from dev_lab.ops.consent.credential import ConsentRefused, verify

__all__ = [
    'ACTION', 'BIND_PROMPT', 'INTEGRATOR', 'TASK_ACTION', 'bind', 'bound_task', 'held', 'holder', 'main', 'request',
    'roles', 'task_id',
]  # fmt: skip

#: The role this module proves.
INTEGRATOR: Final = 'integrator'
#: The consent action granting it to one session (:data:`dev_lab.ops.consent.actions.ACTIONS`).
ACTION: Final = 'session.integrator'
#: The consent action granting it to one task, inherited by the sessions the user bound to it.
TASK_ACTION: Final = 'task.integrator'
#: Where the session -> task bindings live, below the consent state directory no agent tool writes.
BINDINGS: Final = 'tasks'
_SLUG: Final = r'[a-z0-9]+(?:-[a-z0-9]+)*'
#: The user's binding prompt: its FIRST line is exactly ``task: <slug>``.
BIND_PROMPT: Final = re.compile(rf'\A[ \t]*task:[ \t]*({_SLUG})[ \t]*(?:\r?\n|\Z)')


def task_id(root: Path, slug: str) -> str:
    """The id ``<slug>@<authority>`` of the OPEN task *slug* under *root*'s ``.claude/tasks``; ValueError otherwise."""
    if not re.fullmatch(_SLUG, slug):
        msg = f'{slug!r} is not a task slug'
        raise ValueError(msg)
    path = root / '.claude' / 'tasks' / slug / 'TASK.md'
    try:
        head = path.read_text(encoding='utf-8').split('---')[1]
    except (OSError, IndexError):
        msg = f'no task {slug} at {path.as_posix()}'
        raise ValueError(msg) from None
    fields = dict(line.split(':', 1) for line in head.splitlines() if ':' in line)
    authority, status = fields.get('authority', '').strip(), fields.get('status', '').strip()
    if status != 'open' or not authority:
        msg = f'task {slug} is not open with a user authority (status {status or "none"})'
        raise ValueError(msg)
    return f'{slug}@{authority}'


def _checkout_root(cwd: Path) -> Path:
    """The main checkout of the repository at *cwd* -- where its tasks live, from any of its worktrees."""
    common = subprocess.run(
        [shutil.which('git') or 'git', 'rev-parse', '--path-format=absolute', '--git-common-dir'],
        cwd=cwd, capture_output=True, text=True, check=True,
    ).stdout.strip()  # fmt: skip
    return Path(common).parent


def _binding(session: str, home: Path | None) -> Path:
    return state_dir(home) / BINDINGS / f'{session}.json'


def bind(payload: Mapping[str, Any], *, home: Path | None = None, root: Path | None = None) -> str | None:
    """Bind the payload's session to the task its USER prompt names; the task id bound, or ``None``.

    Only a ``UserPromptSubmit`` payload reaches here: the prompt is the user's, the session id the harness's.
    """
    session, prompt = str(payload.get('session_id') or ''), str(payload.get('prompt') or '')
    found = BIND_PROMPT.match(prompt)
    if not found or not re.fullmatch(r'[\w.-]+', session):
        return None
    try:
        where = _checkout_root(Path(str(payload.get('cwd') or '.'))) if root is None else root
        task = task_id(where, found.group(1))
    except (ValueError, OSError, subprocess.CalledProcessError):
        return None
    target = _binding(session, home)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({'session': session, 'task': task}), encoding='utf-8')
    return task


def bound_task(session: str, *, home: Path | None = None) -> str | None:
    """The task the user bound *session* to, or ``None``."""
    if not re.fullmatch(r'[\w.-]+', session):
        return None
    try:
        record = json.loads(_binding(session, home).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    return record.get('task') if record.get('session') == session else None


def holder(
    *,
    session: str | None = None,
    home: Path | None = None,
    now: float | None = None,
    table: Mapping[str, Any] | None = None,
) -> str | None:
    """Which identity gives *session* (default: this one) the role -- ``session <id>`` or ``task <id>``; fail closed.

    No session id, no issuer key, or no credential verifying for this session or the task the user bound it to: None.
    """
    session = os.environ.get(SESSION_ENV, '') if session is None else session
    if not session:
        return None
    try:
        key = public_key(table)
    except ConsentRefused:
        return None
    when = time.time() if now is None else now
    wanted = {(ACTION, session): f'session {session}'}
    task = bound_task(session, home=home)
    if task:
        wanted[(TASK_ACTION, task)] = f'task {task}'
    for path in sorted(state_dir(home).glob('*.json')):
        try:
            found = verify(json.loads(path.read_text(encoding='utf-8')), key, now=when)
        except (ConsentRefused, ValueError, OSError):
            continue
        if (found.action, found.subject) in wanted:
            return wanted[(found.action, found.subject)]
    return None


def held(
    *,
    session: str | None = None,
    home: Path | None = None,
    now: float | None = None,
    table: Mapping[str, Any] | None = None,
) -> frozenset[str]:
    """The roles *session* holds, by its own credential or its bound task's (:func:`holder`)."""
    found = holder(session=session, home=home, now=now, table=table)
    return frozenset({INTEGRATOR}) if found else frozenset()


def roles() -> frozenset[str]:
    """The current session's verified roles -- the ``[hpc] session_verifier`` lab-commons calls."""
    return held()


def request(session: str, hours: float | None = None, *, task: str | None = None) -> dict[str, Any]:
    """The consent request granting the role to *task* (a task id) if given, else to *session*, for *hours*."""
    if task is None and not session:
        msg = f'no session id (${SESSION_ENV}): the integrator role is granted to one session or task, never a machine'
        raise ValueError(msg)
    action, subject = (ACTION, session) if task is None else (TASK_ACTION, task)
    ttl = ACTIONS[action].default_ttl if hours is None else hours * 3600
    return {'action': action, 'subject': subject, 'ttl': ttl}


def _hook(stdin: TextIO) -> int:
    """The ``UserPromptSubmit`` hook: bind on a ``task: <slug>`` prompt; never fails the prompt."""
    try:
        task = bind(json.load(stdin))
    except (ValueError, OSError, AttributeError):
        return 0
    if task:
        emit(f'this session works on task {task}: it holds what the task holds (hpcaccount.session status)')
    return 0


def main(argv: list[str] | None = None, *, stdin: TextIO | None = None) -> int:
    """``request [--task SLUG] [--hours H]`` prints a request; ``status`` the holder; ``bind`` is the prompt hook."""
    parser = argparse.ArgumentParser(
        prog='python -m dev_lab.dev.hpcaccount.session', description=__doc__.splitlines()[0]
    )
    verbs = parser.add_subparsers(dest='verb', required=True)
    asking = verbs.add_parser('request')
    asking.add_argument('--hours', type=float, default=None)
    asking.add_argument('--task', default=None, help='grant the open task SLUG of this checkout, not this session')
    verbs.add_parser('status')
    verbs.add_parser('bind')
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    if args.verb == 'bind':
        return _hook(stdin or sys.stdin)
    session = os.environ.get(SESSION_ENV, '')
    if args.verb == 'status':
        task = bound_task(session) if session else None
        found = holder(session=session)
        role = f'integrator, by {found}' if found else 'no session role'
        emit(f'session {session or "(none)"} (task {task or "none bound"}) holds {role}')
        return 0
    try:
        task = task_id(_checkout_root(Path.cwd()), args.task) if args.task else None
        emit(json.dumps(request(session, args.hours, task=task)))
    except (ValueError, subprocess.CalledProcessError) as refused:
        emit(f'hpcsession refused: {refused}', err=True)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
