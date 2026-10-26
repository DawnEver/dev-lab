"""THE TOOLCHAIN'S OWN BASELINE -- every refusal and every hand action on one JSONL per kind, and one read of them.

Plan P0 (lab-commons ``.claude/memory/2026/10/21/PLAN-a-short-robust-toolchain.md``): the metrics every later
phase is judged by need a record of what the tools did to people, not of what people remember. So the places
that refuse or that a human drives append one line here, through ONE writer (:func:`record`):

* ``refusal`` -- a git hook stage that refused (:mod:`dev_lab.dev.githooks.runner`), the agent guard denying a
  command (``deny-commands.js`` calls ``python -m dev_lab.dev.metrics_report record refusal``), a promotion refused;
* ``bypass`` -- a refusal's own override used (a ``Break-Glass`` trailer admitted by the session-branch guard);
* ``push`` -- every pre-push stage run, refused or not: the denominator of refusals per push, naming the
  branch it pushes (``vcs.ref.head.name``) -- a branch's first push is where its edit starts;
* ``hand_action`` -- a forge verb a person or integrator ran by hand (:data:`HAND_VERBS`, :mod:`forgecli`,
  ``integrate promote``), and every ``Break-Glass:`` commit the session-branch guard admits onto the
  integration branch (:func:`break_glass`: its branch, sha and reason);
* ``host_failure`` -- an alarm a serving host raised (:func:`dev_lab.dev.forgealarm.sound`), or a ``forge
  serve`` that failed before it posted anything: a failure that reached nobody as a status on a pull request.

A TEST NEVER WRITES THE LIVE LOG. Every writer takes its *root* explicitly; the test suite's conftest gives
each test a checkout of its own for any root that resolves to the real one, and the agent-guard engine
logs a refusal only for the tool's own calls, never for a probe (:func:`dev_lab.dev.agenthooks.run_engine`).

WHERE. Regenerable program output, so the checkout's dated tree: :func:`log_file` --
``<checkout>/output/logs/<yy>/<mm>/<dd>/metrics/<kind>.jsonl`` -- the ONE path the writer and the read share.
The checkout is the repository's MAIN worktree (:func:`checkout`), so every lane of one repository logs into
one place. It was ``<config dir>/metrics/`` once (``~/.config/lab-commons/metrics/``), and that wrote
``tests/metrics/`` into a tracked tree in any repo whose tests point ``LAB_COMMONS_CONFIG`` under ``tests/``.
NO COMPAT: the read never opens that location, so a line an older kit still appends there is not counted.

THREE MODULES, ONE CONCEPT EACH: this one RECORDS (the kinds, the one writer, the raw read of a kind's lines);
:mod:`dev_lab.dev.metrics_compute` COMPUTES the plan's figures from those lines, forge pulls and git landings;
:mod:`dev_lab.dev.metrics_report` REPORTS them, and is the CLI (``record`` included).

THE READ (``python -m dev_lab.dev.metrics_report``) covers every repository of the family -- the machine file's
``[serve] repos`` under its ``root``, the list the serving host itself walks (:func:`family`) -- over one
window with both bounds. What LANDED is read from git, not the log: a PR whose head branch a first-parent
``Merged-Branch:`` merge of the integration branch names is merged at that commit's time
(:func:`landings`), however it was closed, and a ``Break-Glass:`` landing is a hand action on the PR it
carries whether or not a guard logged it.

ONE ``O_APPEND`` WRITE PER LINE, fsynced. Not :func:`lab_commons.compute.durable.durable_write`: that publishes
a whole file by rename, and two hooks appending at once through it would each rewrite the file and lose the
other's line. A single append of one whole line never tears against another (the same discipline as
:mod:`lab_commons.hpc.pytest_item`); a torn tail after a crash is skipped on read.

Field names follow OpenTelemetry's semantic conventions where one exists (``event.name``,
``vcs.repository.url.full``, ``vcs.ref.head.revision``, ``vcs.ref.head.name``, ``vcs.change.id``,
``error.type``, ``enduser.id``); the check that refused is ``lab.rule.id``, the verb ``lab.action``.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import lab_commons.launch as _door

from dev_lab.dev.datedlog import date_parts

__all__ = [
    'BREAK_GLASS_ACTION',
    'BYPASS',
    'HAND_ACTION',
    'HAND_VERBS',
    'HOST_FAILURE',
    'KINDS',
    'PUSH',
    'REFUSAL',
    'break_glass',
    'checkout',
    'hand_action',
    'log_file',
    'read',
    'record',
    'repo_of',
]  # fmt: skip

REFUSAL: Final = 'refusal'
BYPASS: Final = 'bypass'
PUSH: Final = 'push'
HAND_ACTION: Final = 'hand_action'
HOST_FAILURE: Final = 'host_failure'
KINDS: Final = (REFUSAL, BYPASS, PUSH, HAND_ACTION, HOST_FAILURE)

#: The forge verbs that are a hand action when a CLI runs them: ``(noun, verb)`` of ``python -m dev_lab.dev.forge``.
HAND_VERBS: Final = frozenset({
    ('status', 'post'), ('pr', 'create'), ('pr', 'close-landed'), ('pr', 'close-superseded'),
    ('issue', 'close'), ('issue', 'comment'), ('cancel-stuck', ''),
})  # fmt: skip

_GIT: Final = shutil.which('git') or 'git'
_SHA: Final = re.compile(r'^[0-9a-f]{7,40}$')
_SESSION_ENV: Final = 'LAB_SESSION'
#: The ``lab.action`` of an admitted ``Break-Glass:`` commit (:func:`break_glass`).
BREAK_GLASS_ACTION: Final = 'break-glass'


#: Where under :func:`checkout` the dated tree starts, and the kind directory beneath the date.
BASE: Final = Path('output', 'logs')
LOG_KIND: Final = 'metrics'


def checkout(root: Path) -> Path:
    """The main worktree of the repository holding *root*; *root* itself when git names none."""
    try:
        done = _door.run(
            [_GIT, '-C', str(root), 'rev-parse', '--path-format=absolute', '--git-common-dir'],
            capture_output=True, text=True, encoding='utf-8', check=False, timeout=30,
        )  # fmt: skip
    except OSError:
        return root
    common = done.stdout.strip()
    return Path(common).parent if done.returncode == 0 and common else root


def log_file(root: Path, kind: str, day: tuple[str, str, str] | None = None) -> Path:
    """``<checkout>/output/logs/<yy>/<mm>/<dd>/metrics/<kind>.jsonl`` for *day* (today); ``'*'`` parts glob."""
    if kind not in KINDS:
        msg = f'unknown metrics kind {kind!r}; the kinds are {list(KINDS)}'
        raise ValueError(msg)
    return checkout(root).joinpath(BASE, *(day or date_parts()), LOG_KIND, f'{kind}.jsonl')


def repo_of(root: Path) -> str:
    """*root*'s ``origin`` URL as git holds it; the checkout's path when it has none."""
    try:
        done = _door.run(
            [_GIT, '-C', str(root), 'config', '--get', 'remote.origin.url'],
            capture_output=True, text=True, encoding='utf-8', check=False, timeout=30,
        )  # fmt: skip
    except OSError:
        return str(root)
    return done.stdout.strip() or str(root)


def record(kind: str, *, root: Path, repo: str, rule: str = '', reason: str = '', **attributes: str) -> Path:
    """Append one *kind* line naming *repo* (and its *rule* and *reason* class) to *root*'s :func:`log_file`; its file.

    *attributes* are OpenTelemetry field names spelled with ``_`` for ``.`` (``vcs_ref_head_revision``).
    """
    target = log_file(root, kind)
    line: dict[str, str] = {
        'time': datetime.now(UTC).isoformat(),
        'event.name': f'lab.{kind}',
        'vcs.repository.url.full': repo,
        'enduser.id': os.environ.get(_SESSION_ENV, ''),
    }
    if rule:
        line['lab.rule.id'] = rule
    if reason:
        line['error.type'] = reason
    line |= {name.replace('_', '.'): value for name, value in attributes.items() if value}
    target.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(target, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, (json.dumps(line, sort_keys=True) + '\n').encode('utf-8'))
        os.fsync(fd)
    finally:
        os.close(fd)
    return target


def read(kind: str, *, root: Path) -> list[dict[str, str]]:
    """Every *kind* line under *root*'s checkout, oldest day first; an unreadable line (a torn tail) is skipped."""
    base = checkout(root)
    found: list[dict[str, str]] = []
    for path in sorted(base.glob(log_file(base, kind, ('*', '*', '*')).relative_to(base).as_posix())):
        for raw in path.read_text(encoding='utf-8').splitlines():
            try:
                found.append(json.loads(raw))
            except ValueError:
                continue
    return found


def hand_action(root: Path, argv: Sequence[str]) -> Path | None:
    """Record *argv* (a ``forge`` command line that succeeded) when it is a :data:`HAND_VERBS` verb; its file."""
    noun, verb = [*argv, '', ''][:2]
    if (noun, verb) not in HAND_VERBS and (noun, '') not in HAND_VERBS:
        return None
    action = f'{noun} {verb}' if (noun, verb) in HAND_VERBS else noun
    rest = list(argv)[2 if (noun, verb) in HAND_VERBS else 1 :]
    positional = next((word for word in rest if not word.startswith('-')), '')
    head = rest[rest.index('--head') + 1] if '--head' in rest[:-1] else ''
    return record(
        HAND_ACTION, root=root, repo=repo_of(root), lab_action=action,
        vcs_ref_head_revision=positional if _SHA.match(positional) else '',
        vcs_change_id=positional if positional.isdigit() else '', vcs_ref_head_name=head,
    )  # fmt: skip


def break_glass(root: Path, *, repo: str, sha: str, branch: str, reason: str) -> Path:
    """Record one admitted ``Break-Glass:`` commit *sha* of the integration branch, merging *branch*; its file."""
    return record(
        HAND_ACTION, root=root, repo=repo, lab_action=BREAK_GLASS_ACTION, vcs_ref_head_revision=sha,
        vcs_ref_head_name=branch, lab_reason=reason,
    )  # fmt: skip
