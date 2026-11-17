"""THE HOOK HAND-OFF: what a hook cannot finish inside its budget runs to completion in the background, once.

User ruling D24 (2026-11-17, ``HOOK-UNDER-FIVE-SECONDS``): every hook source on one event shares five seconds, and
ending inside them must not mean not executing -- work that can take longer moves to the background. So the
dispatcher (:mod:`dev_lab.dev.hookdispatch`) never cuts or skips a row: a ``detached`` row, and an inline row the
budget ran out on, is HANDED OFF here.

* :func:`hand_off` writes one job (the event, the payload, the row names, the repo root) into the queue in the git
  dir of the payload's ``cwd`` -- whole, through a rename, so a reader never sees half a job -- and starts the
  runner only when no live one holds the queue (several sessions firing at once start one runner, not one each);
* THE QUEUE IS WRITTEN FIRST (measured 2026-11-17: a cold dispatcher on a starved box ran 4.8 s, and the harness
  kills a hook at its timeout with no cleanup). Before any inline row runs, the dispatcher hands its detached rows
  off and records its inline rows with :func:`write_ahead`; when they have run, :func:`settle` drops the record or
  turns the rows that did not finish into a job. A record whose writer died is ADOPTED by the runner, which waits
  for a live writer's record to settle (at most :data:`ADOPT_WAIT_S`), so a killed dispatcher loses no row;
* the RUNNER (``python -m dev_lab.dev.hookdispatch --background <job>``, :func:`drain`) holds the queue's lock,
  runs every queued job oldest first, removes each when it has run (a runner killed mid-job leaves it for the
  next), and re-checks the queue after letting go, so a job queued while it was finishing is never stranded;
* a job's answer -- context, messages, notes, and a guard's refusal demoted to a note -- is :func:`defer`-red to
  the session, and the session's next context event takes it, once (:func:`take_deferred`).

Every read here is defensive: a torn or foreign file is skipped, never a crash on the hook path. Outside a checkout
the queue lives under the user's temp dir, the one place such a payload can be written.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from lab_commons.liveness import creation_stamp, still_the_same_process

from dev_lab.dev.backgroundrun import detach_argv
from dev_lab.dev.gitdirs import git_dir

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Sequence

    from dev_lab.dev.agent_wiring import Wire

__all__ = [
    'DEFERRED_DIR',
    'HANDOFF_DIR',
    'RUNNER_LOCK',
    'defer',
    'detach',
    'drain',
    'hand_off',
    'runner_alive',
    'settle',
    'state_dir',
    'take_deferred',
    'write_ahead',
]

#: The queue of handed-off jobs, in the git dir.
HANDOFF_DIR: Final = 'dev-lab-hook-handoff'
#: One file of deferred answers per session, in the git dir.
DEFERRED_DIR: Final = 'dev-lab-hook-deferred'
#: The runner's lock in the queue: its pid and creation stamp, so a recycled pid reads as gone.
RUNNER_LOCK: Final = 'runner.lock'
#: The suffix of a write-ahead record: the inline rows of a dispatcher still running them.
PENDING: Final = '.pending'
#: The longest a runner waits for a live dispatcher's record: past the harness's kill at five seconds.
ADOPT_WAIT_S: Final = 10.0
_JOB: Final = '*.json'
_POLL_S: Final = 0.2
_UNSAFE: Final = re.compile(r'[^\w.-]')


def state_dir(cwd: Path) -> Path:
    """Where the hand-off state of *cwd* lives: its git dir, else the user's temp dir."""
    return git_dir(cwd) or Path(tempfile.gettempdir()) / 'dev-lab-hooks'


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        found = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    return found if isinstance(found, dict) else None


def _alive(held: object) -> bool:
    """Whether *held* (``{'pid', 'created'}``) names a live process; a recycled pid, or anything torn, does not."""
    try:
        return isinstance(held, dict) and still_the_same_process(int(held['pid']), held.get('created'))
    except (KeyError, TypeError, ValueError):
        return False


def runner_alive(queue: Path) -> bool:
    """Whether a live runner holds *queue*'s lock (a dead or recycled pid, or a torn lock, reads as none)."""
    return _alive(_read_json(queue / RUNNER_LOCK))


def detach(root: Path, job: Path) -> None:
    """Start the runner for *job*'s queue in *root*, outliving the hook and opening no window."""
    detach_argv(root, ['-m', 'dev_lab.dev.hookdispatch', '--background', str(job)])


def hand_off(cwd: Path, event: str, text: str, wires: Sequence[Wire], root: Path | None = None) -> Path:
    """Queue *wires* of *event* on payload *text* for the background and start a runner unless one is live.

    Raises:
        OSError: the queue cannot be written or the runner cannot start; the caller names the rows.

    """
    job = _write(cwd, event, text, wires, root=root, suffix='.json')
    if not runner_alive(job.parent):
        detach(root or cwd, job)
    return job


def _write(cwd: Path, event: str, text: str, wires: Sequence[Wire], *, root: Path | None, suffix: str) -> Path:
    """One whole queue file of *wires*, through a rename; a write-ahead record also names its writer."""
    queue = state_dir(cwd) / HANDOFF_DIR
    queue.mkdir(parents=True, exist_ok=True)
    path = queue / f'{time.time_ns()}-{os.getpid()}-{_UNSAFE.sub("_", event)}{suffix}'
    body: dict[str, Any] = {'event': event, 'payload': text, 'rows': [w.name for w in wires], 'root': str(root or cwd)}
    if suffix == PENDING:
        body['writer'] = {'pid': os.getpid(), 'created': creation_stamp(os.getpid())}
    part = path.with_suffix('.part')
    part.write_text(json.dumps(body), encoding='utf-8')
    part.replace(path)
    return path


def write_ahead(cwd: Path, event: str, text: str, wires: Sequence[Wire], root: Path | None = None) -> Path | None:
    """Record *wires*, the inline rows about to run, before they run; ``None`` when there are none.

    Raises:
        OSError: the record cannot be written; the caller names the rows.

    """
    return _write(cwd, event, text, wires, root=root, suffix=PENDING) if wires else None


def settle(record: Path | None, late: Sequence[Wire], root: Path) -> None:
    """The inline rows of *record* have run: drop it, or hand *late* -- the rows that did not finish -- off.

    Raises:
        OSError: the job cannot be written or the runner cannot start; the caller names the rows.

    """
    if record is None:
        return
    body = _read_json(record) if late else None
    if body is not None:
        body.pop('writer', None)
        body['rows'] = [wire.name for wire in late]
        _adopt(record, body)
        if not runner_alive(record.parent):
            detach(root, record.with_suffix('.json'))
    record.unlink(missing_ok=True)


def _adopt(record: Path, body: dict[str, Any]) -> None:
    """*record* becomes a job holding *body*, through a rename, and is gone."""
    part = record.with_suffix('.part')
    part.write_text(json.dumps(body), encoding='utf-8')
    part.replace(record.with_suffix('.json'))
    record.unlink(missing_ok=True)


def _orphans(queue: Path) -> bool:
    """Adopt every record whose writer died (a torn one is dropped); whether a live writer's record remains."""
    live = False
    for record in sorted(queue.glob(f'*{PENDING}')):
        body = _read_json(record)
        if body is not None and _alive(body.get('writer')):
            live = True
        elif body is not None:
            body.pop('writer', None)
            _adopt(record, body)
        else:
            record.unlink(missing_ok=True)
    return live


@contextlib.contextmanager
def _runner(queue: Path) -> Iterator[bool]:
    lock = queue / RUNNER_LOCK
    me = {'pid': os.getpid(), 'created': creation_stamp(os.getpid())}
    for _ in range(2):
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if runner_alive(queue):
                yield False
                return
            lock.unlink(missing_ok=True)  # a dead runner's: taken over
            continue
        except OSError:
            break
        os.write(fd, json.dumps(me).encode())
        os.close(fd)
        try:
            yield True
        finally:
            if (_read_json(lock) or {}).get('pid') == me['pid']:
                lock.unlink(missing_ok=True)
        return
    yield False


def drain(queue: Path, run: Callable[[dict[str, Any]], None]) -> None:
    """Run every job queued in *queue* through *run*, oldest first, while holding its runner lock.

    A job is removed once it has run; a torn job is removed unrun. A write-ahead record whose dispatcher died is
    adopted as a job; a live one's is waited for, at most :data:`ADOPT_WAIT_S`. After letting go of the lock the queue
    is read again, so a job queued while this runner was finishing is run by it or by the runner that job started.
    """
    deadline = time.monotonic() + ADOPT_WAIT_S
    while True:
        with _runner(queue) as mine:
            if not mine:
                return
            while True:
                for job in sorted(queue.glob(_JOB)):
                    found = _read_json(job)
                    if found is not None:
                        run(found)
                    job.unlink(missing_ok=True)
                waiting = _orphans(queue)
                if any(queue.glob(_JOB)):
                    continue
                if not waiting or time.monotonic() > deadline:
                    break
                time.sleep(_POLL_S)
        if not any(queue.glob(_JOB)):
            return


def _deferred(cwd: Path, session: str) -> Path:
    return state_dir(cwd) / DEFERRED_DIR / f'{_UNSAFE.sub("_", session) or "_"}.jsonl'


def defer(cwd: Path, session: str, event: str, text: str) -> None:
    """Keep *text*, what *event*'s background rows said, for *session*'s next context event: one whole line."""
    path = _deferred(cwd, session)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = (json.dumps({'event': event, 'text': text}) + '\n').encode('utf-8')
    fd = os.open(path, os.O_CREAT | os.O_APPEND | os.O_WRONLY)
    try:
        os.write(fd, line)
    finally:
        os.close(fd)


def take_deferred(cwd: Path, session: str) -> list[str]:
    """*session*'s deferred answers, each once; ``[]`` when there are none or another reader holds them."""
    path = _deferred(cwd, session)
    if not path.is_file():
        return []
    taking = path.with_name(f'{path.name}.{os.getpid()}.taking')
    try:
        path.replace(taking)  # the claim: a second reader, or a writer holding it open, leaves it for next time
        raw = taking.read_text(encoding='utf-8', errors='replace')
        taking.unlink()
    except OSError:
        return []
    said = []
    for line in raw.splitlines():
        with contextlib.suppress(ValueError, KeyError, TypeError):  # a torn or foreign line is skipped
            one = json.loads(line)
            said.append(f'[deferred from {one["event"]}] {one["text"]}')
    return said
