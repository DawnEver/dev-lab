"""THE USER'S AUTHORITY TO OPEN OR CLOSE A TASK: granted only by the user's own prompt, spent once (ruling 2026-11-23).

Opening or closing a task is REFUSED BY DEFAULT and DETECTABLE WHEN BYPASSED -- not preventable: this hook and the
agent's shell run as one OS user, so the agent could write the store too (prevention needs a privilege boundary).

ONE append-only JSONL store per task ledger, in machine-home state (:func:`store`, keyed by the ledger's resolved
path), holding four events:

* ``requested`` -- an agent's ``python -m dev_lab.dev.task request <slug> "<goal>"`` (:func:`request`): a short code
  the user may approve. It grants nothing by itself;
* ``granted`` -- written ONLY by the ``UserPromptSubmit`` hook row (``python -m dev_lab.dev.taskauthority hook``,
  :func:`main`) when the WHOLE prompt is ``/task open|close <slug> ...`` or ``approve <code>`` naming a live request
  (:func:`grant_from_prompt`). A grant lives :data:`TTL_S` and names exactly one verb and slug;
* ``consumed`` -- :func:`consume`, by the task door's open/close: the newest live unspent grant for exactly that verb
  and slug, under a lock; its id goes into ``TASK.md`` ``authority:`` and the opened/closed journal line;
* ``folded`` history from the retired rem store arrives verbatim (:func:`fold`, the migration's).

:func:`problem` is the detection: an id the history does not hold as granted and consumed is an error; no history at
all (another machine) is only a warning.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import re
import secrets
import sys
import time
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Final

from lab_commons.home import part
from lab_commons.log import emit

__all__ = [
    'TTL_S',
    'AuthorityRefused',
    'consume',
    'events',
    'fold',
    'grant_from_prompt',
    'key_of',
    'main',
    'problem',
    'request',
    'store',
]

#: How long a grant or request lives, in seconds.
TTL_S: Final = 30 * 60
_COMMAND: Final = re.compile(r'^\s*/task\s+(open|close)\s+([a-z0-9]+(?:-[a-z0-9]+)*)(?:\s|$)')
_APPROVE: Final = re.compile(
    r'^\s*(?:/task\s+)?(?:approve|\u6279\u51c6|\u540c\u610f)\s+([0-9a-f]{6})\s*$',
    re.IGNORECASE,
)
_LOCK_WAIT_S: Final = 30.0


class AuthorityRefused(PermissionError):
    """No live, unspent grant of the user's for this verb and slug."""


def key_of(ledger: Path) -> str:
    """The store's key for *ledger*: the first 16 hex of the SHA-256 of its resolved path."""
    return hashlib.sha256(str(ledger.resolve()).encode('utf-8')).hexdigest()[:16]


def store(ledger: Path) -> Path:
    """The one authority history of *ledger*: ``<machine home>/state/task-authority/<key>.jsonl``."""
    return part('state') / 'task-authority' / f'{key_of(ledger)}.jsonl'


@contextlib.contextmanager
def _locked(file: Path) -> Iterator[None]:
    from dev_lab.dev.servelock import held  # noqa: PLC0415 -- the prompt hook imports nothing it does not use

    deadline = time.monotonic() + _LOCK_WAIT_S
    while True:
        with held(file.with_suffix('.lock')) as mine:
            if mine:
                yield
                return
        if time.monotonic() > deadline:
            msg = f'the authority store {file.as_posix()} stayed locked {_LOCK_WAIT_S:g} s; retry'
            raise TimeoutError(msg)
        time.sleep(0.02)


def events(ledger: Path) -> list[dict[str, object]]:
    """Every event of *ledger*'s history, in order; an unreadable line is skipped."""
    try:
        text = store(ledger).read_text(encoding='utf-8')
    except OSError:
        return []
    out: list[dict[str, object]] = []
    for line in text.splitlines():
        with contextlib.suppress(ValueError):
            if isinstance(event := json.loads(line), dict):
                out.append(event)
    return out


def _append(file: Path, event: dict[str, object]) -> None:
    file.parent.mkdir(parents=True, exist_ok=True)
    with file.open('a', encoding='utf-8', newline='\n') as out:
        out.write(json.dumps(event, ensure_ascii=False) + '\n')


def request(ledger: Path, verb: str, slug: str, goal: str = '', *, now: float | None = None) -> str:
    """Record an agent's request to *verb* task *slug*; the code the user approves with ``approve <code>``."""
    file, code = store(ledger), secrets.token_hex(3)
    with _locked(file):
        _append(file, {'event': 'requested', 'code': code, 'verb': verb, 'slug': slug, 'goal': goal,
                       'at': time.time() if now is None else now})  # fmt: skip
    return code


def grant_from_prompt(ledger: Path, prompt: str, session: str = '', *, now: float | None = None) -> dict | None:
    """The grant the user's *prompt* makes (written to the store), or ``None`` for any other prompt."""
    at = time.time() if now is None else now
    if command := _COMMAND.match(prompt):
        verb, slug, code = command[1], command[2], None
    elif approve := _APPROVE.match(prompt):
        code = approve[1].lower()
        history = events(ledger)
        used = {e.get('code') for e in history if e.get('event') == 'granted'}
        asked = [e for e in history if e.get('event') == 'requested' and e.get('code') == code and code not in used
                 and at - float(e.get('at', 0)) < TTL_S]  # fmt: skip
        if not asked:
            return None
        verb, slug = str(asked[-1]['verb']), str(asked[-1]['slug'])
    else:
        return None
    grant = {
        'event': 'granted', 'id': secrets.token_hex(6), 'verb': verb, 'slug': slug, 'session': session,
        'promptHash': hashlib.sha256(prompt.encode('utf-8')).hexdigest()[:16], 'at': at,
        **({'code': code} if code else {}),
    }  # fmt: skip
    file = store(ledger)
    with _locked(file):
        _append(file, grant)
    return grant


def consume(ledger: Path, verb: str, slug: str, *, now: float | None = None) -> str:
    """Spend the newest live unspent grant for exactly *verb* and *slug*; its id. :class:`AuthorityRefused` else."""
    at, file = time.time() if now is None else now, store(ledger)
    with _locked(file):
        history = events(ledger)
        spent = {e.get('id') for e in history if e.get('event') == 'consumed'}
        live = [e for e in history if e.get('event') == 'granted' and e.get('id') not in spent and e.get('verb') == verb
                and e.get('slug') == slug and at - float(e.get('at', 0)) < TTL_S]  # fmt: skip
        if not live:
            msg = (
                f"no user authority to {verb} task {slug}: a grant comes only from the user's own prompt, live "
                f'{TTL_S // 60} min.\nDoor: the user types `/task {verb} {slug}`, or run `python -m dev_lab.dev.task '
                f'request {slug} "<goal>"` and the user replies `approve <code>`'
            )
            raise AuthorityRefused(msg)
        hit = max(live, key=lambda e: float(e.get('at', 0)))
        _append(file, {'event': 'consumed', 'id': hit['id'], 'verb': verb, 'slug': slug, 'at': at})
    return str(hit['id'])


def problem(ledger: Path, slug: str, authority: str) -> tuple[str, str] | None:
    """``(level, why)`` when *authority* does not hold up for opening *slug*; ``None`` when it does."""
    history = events(ledger)
    if not history:
        return 'warning', 'no local authority history for this ledger -- cannot be checked on this machine'
    mine = [e for e in history if e.get('id') == authority]
    if not any(e.get('event') == 'granted' for e in mine):
        return 'error', f'authority {authority} is not in the authority history'
    if not any(e.get('event') == 'consumed' and e.get('verb') == 'open' and e.get('slug') == slug for e in mine):
        return 'error', f'authority {authority} was not consumed by opening {slug}'
    return None


def fold(ledger: Path, lines: Sequence[str]) -> int:
    """Append each JSON event line of a retired history not already in the store; how many were added."""
    file = store(ledger)
    with _locked(file):
        have = {json.dumps(e, sort_keys=True) for e in events(ledger)}
        added = 0
        for line in lines:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict) and (canon := json.dumps(event, sort_keys=True)) not in have:
                _append(file, event)
                have.add(canon)
                added += 1
    return added


def main(argv: Sequence[str] | None = None, *, stdin: object = None) -> int:
    """``hook``: the ``UserPromptSubmit`` row -- a prompt that IS a task command grants; always exit 0."""
    del argv
    from dev_lab.dev.taskledger import LedgerUnresolvedError, ledger  # noqa: PLC0415

    try:
        payload = json.load(stdin or sys.stdin)  # type: ignore[arg-type]
        prompt = payload.get('prompt') if isinstance(payload, dict) else None
        if isinstance(prompt, str) and (_COMMAND.match(prompt) or _APPROVE.match(prompt)):
            grant = grant_from_prompt(ledger(), prompt, str(payload.get('session_id', '')))
            if grant is not None:
                verb, slug = grant['verb'], grant['slug']
                emit(f'[task] the user granted {verb} {slug} (authority {grant["id"]}, {TTL_S // 60} min): '
                     f'python -m dev_lab.dev.task {verb} {slug} ...')  # fmt: skip
    except (ValueError, OSError, LedgerUnresolvedError, TimeoutError) as failed:
        emit(f'[task] the task command was not granted: {failed}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
