"""SSHHOLD STATE: where a held session is recorded and every verb is audited -- the files, never the connection.

One private JSON state file per dest (it carries the holder's token) and one append-only JSONL audit, both
under ``<machine home>/state/sshhold``. Read by the client (:mod:`dev_lab.dev.sshhold`), the holder
(:mod:`dev_lab.dev._sshholder`) and the plan remote (:mod:`dev_lab.dev.planremote`).
"""

from __future__ import annotations

import contextlib
import json
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from lab_commons.home import part

from dev_lab.ops.totp import write_private

__all__ = ['Session', 'audit', 'audit_path', 'forget', 'read_session', 'state_dir', 'state_path', 'write_session']


@dataclass(frozen=True)
class Session:
    """One live holder as its state file records it."""

    dest: str
    pid: int
    port: int
    token: str
    opened: float
    expires: float


def state_dir() -> Path:
    """``<machine home>/state/sshhold``: one state file per dest, and the audit."""
    return part('state') / 'sshhold'


def state_path(dest: str) -> Path:
    """The state file of *dest*, its name made filesystem-safe."""
    return state_dir() / f'{re.sub(r"[^A-Za-z0-9._-]", "_", dest)}.json'


def audit_path() -> Path:
    """The append-only JSONL audit of every open, run and close."""
    return state_dir() / 'audit.jsonl'


def write_session(session: Session) -> None:
    """Record *session* private (it carries the token)."""
    write_private(state_path(session.dest), json.dumps(asdict(session)))


def forget(dest: str) -> None:
    """Remove *dest*'s state file; already gone, or being removed by the other side (Windows: delete pending), is fine.

    The client and the ending holder both remove it, so one of them loses that race with PermissionError.
    """
    with contextlib.suppress(FileNotFoundError, PermissionError):
        state_path(dest).unlink()


def read_session(dest: str) -> Session | None:
    """The recorded session of *dest*, or ``None``."""
    path = state_path(dest)
    try:
        return Session(**json.loads(path.read_text(encoding='utf-8')))
    except (OSError, ValueError, TypeError):
        return None


def audit(
    verb: str, dest: str, *, command: str = '', status: int | None = None, duration_s: float = 0.0, **fields: object
) -> None:
    """Append one audit line: what the caller passes, never more. A secret is never a field (a digest may be)."""
    line = {'time': time.time(), 'dest': dest, 'verb': verb, 'command': command, 'status': status, **fields}
    line['duration_s'] = round(duration_s, 3)
    state_dir().mkdir(parents=True, exist_ok=True)
    with audit_path().open('a', encoding='utf-8') as out:
        out.write(json.dumps(line) + '\n')
