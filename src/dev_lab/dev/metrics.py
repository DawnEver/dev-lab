"""THE TOOLCHAIN'S OWN BASELINE -- every refusal and every hand action on one JSONL per kind, and one read of them.

Plan P0 (lab-commons ``.claude/memory/2026/10/21/PLAN-a-short-robust-toolchain.md``): the metrics every later
phase is judged by need a record of what the tools did to people, not of what people remember. So the places
that refuse or that a human drives append one line here, through ONE writer (:func:`record`):

* ``refusal`` -- a git hook stage that refused (:mod:`dev_lab.dev.githooks.runner`), the agent guard denying a
  command (``deny-commands.js`` calls ``python -m dev_lab.dev.metrics record refusal``), a promotion refused;
* ``bypass`` -- a refusal's own override used (a ``Break-Glass`` trailer admitted by the session-branch guard);
* ``push`` -- every pre-push stage run, refused or not: the denominator of refusals per push;
* ``hand_action`` -- a forge verb a person or integrator ran by hand (:data:`HAND_VERBS`, :mod:`forgecli`,
  ``integrate promote``);
* ``host_failure`` -- an alarm a serving host raised (:func:`dev_lab.dev.forgealarm.sound`): a failure that
  reached a person by alarm, not as a status on a pull request.

WHERE. Regenerable program output, so the checkout's dated tree: :func:`log_file` --
``<checkout>/output/logs/<yy>/<mm>/<dd>/metrics/<kind>.jsonl`` -- the ONE path the writer and the read share.
The checkout is the repository's MAIN worktree (:func:`checkout`), so every lane of one repository logs into
one place. It was ``<config dir>/metrics/`` once, and that wrote ``tests/metrics/`` into a tracked tree in any
repo whose tests point ``LAB_COMMONS_CONFIG`` at a file under ``tests/``; nothing reads that location.

ONE ``O_APPEND`` WRITE PER LINE, fsynced. Not :func:`lab_commons.compute.durable.durable_write`: that publishes
a whole file by rename, and two hooks appending at once through it would each rewrite the file and lose the
other's line. A single append of one whole line never tears against another (the same discipline as
:mod:`lab_commons.hpc.pytest_item`); a torn tail after a crash is skipped on read.

Field names follow OpenTelemetry's semantic conventions where one exists (``event.name``,
``vcs.repository.url.full``, ``vcs.ref.head.revision``, ``vcs.ref.head.name``, ``vcs.change.id``,
``error.type``, ``enduser.id``); the check that refused is ``lab.rule.id``, the verb ``lab.action``.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import statistics
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final

import lab_commons.launch as _door
from lab_commons.log import emit

from dev_lab.dev.datedlog import date_parts
from dev_lab.dev.forgepulls import pages
from dev_lab.dev.forgework import client_for

__all__ = [
    'BYPASS',
    'HAND_ACTION',
    'HAND_VERBS',
    'HOST_FAILURE',
    'KINDS',
    'PUSH',
    'REFUSAL',
    'Metrics',
    'checkout',
    'compute',
    'hand_action',
    'log_file',
    'main',
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


# ------------------------------------------------------------------------------------------------- the read


@dataclass(frozen=True)
class Metrics:
    """The plan's metrics over one repository and window; ``None`` where there is nothing to measure."""

    repo: str
    since: str
    median_edit_to_merged_h: float | None
    hand_actions_per_pr: float | None
    share_merged_untouched: float | None
    refusals: int
    pushes: int
    refusals_per_push: float | None
    candidate_false_positives: int
    false_positive_share: float | None
    open_prs: int
    host_failures_without_status: int


def _slug(url: str) -> str:
    """``owner/repo`` of any spelling of a remote; the text itself when it names none."""
    tail = re.sub(r'\.git$', '', url.rstrip('/')).replace(':', '/').split('/')
    return '/'.join(tail[-2:]).lower()


def _when(text: str | None) -> datetime | None:
    return datetime.fromisoformat(text) if text else None


def _touches(action: Mapping[str, str], pull: Mapping[str, Any]) -> bool:
    head = pull.get('head') or {}
    return (
        action.get('vcs.change.id') == str(pull.get('number'))
        or (bool(sha := action.get('vcs.ref.head.revision')) and str(head.get('sha', '')).startswith(sha or '-'))
        or (bool(action.get('vcs.ref.head.name')) and action['vcs.ref.head.name'] == head.get('ref'))
    )  # fmt: skip


def _ratio(part: float, whole: float) -> float | None:
    return part / whole if whole else None


def compute(
    repo: str,
    records: Mapping[str, Iterable[Mapping[str, str]]],
    pulls: Iterable[Mapping[str, Any]],
    *,
    since: datetime,
) -> Metrics:
    """The metrics of *repo* since *since* from the logged *records* (by kind) and the forge's raw *pulls*.

    Edit->merged runs from a PR's opening to its merge (the forge holds no earlier edit time). A PR's own
    ``pr create`` is the session's normal act, not a touch; any other hand action naming its number, head
    commit or head branch is. A refusal is a candidate false positive when a bypass of the same rule in the
    same repository follows it.
    """
    slug = _slug(repo)

    def mine(kind: str) -> list[Mapping[str, str]]:
        return [
            line for line in records.get(kind, ())
            if _slug(line.get('vcs.repository.url.full', '')) == slug and (_when(line.get('time')) or since) >= since
        ]  # fmt: skip

    listed = list(pulls)
    merged = [p for p in listed if p.get('merged_at') and (_when(p['merged_at']) or since) >= since]
    hands = [a for a in mine(HAND_ACTION) if a.get('lab.action') != 'pr create']
    touched = [sum(_touches(a, p) for a in hands) for p in merged]
    spans = [(_when(p['merged_at']) or since) - (_when(p.get('created_at')) or since) for p in merged]
    hours = [span.total_seconds() / 3600 for span in spans]
    refusals, bypasses = mine(REFUSAL), mine(BYPASS)
    candidates = sum(
        any(b.get('lab.rule.id') == r.get('lab.rule.id') and b['time'] > r['time'] for b in bypasses) for r in refusals
    )
    pushes = len(mine(PUSH))
    return Metrics(
        repo=repo,
        since=since.isoformat(),
        median_edit_to_merged_h=statistics.median(hours) if hours else None,
        hand_actions_per_pr=_ratio(sum(touched), len(merged)),
        share_merged_untouched=_ratio(sum(1 for n in touched if not n), len(merged)),
        refusals=len(refusals),
        pushes=pushes,
        refusals_per_push=_ratio(len(refusals), pushes),
        candidate_false_positives=candidates,
        false_positive_share=_ratio(candidates, len(refusals)),
        open_prs=sum(1 for p in listed if p.get('state') == 'open'),
        host_failures_without_status=len(mine(HOST_FAILURE)),
    )


def _cli_record(args: argparse.Namespace) -> int:
    record(
        args.kind,
        root=Path.cwd(),
        repo=args.repo or repo_of(Path.cwd()),
        rule=args.rule,
        reason=args.reason,
        vcs_ref_head_revision=args.sha,
    )
    return 0


def _cli_read(args: argparse.Namespace) -> int:
    root = Path.cwd()
    client = client_for(root)
    pulls = pages(client, f'{client.repo}/pulls', {'state': 'all'})
    since = datetime.now(UTC) - timedelta(days=args.days)
    found = compute(repo_of(root), {kind: read(kind, root=root) for kind in KINDS}, pulls, since=since)
    if args.json:
        emit(json.dumps(asdict(found), indent=2))
    else:
        for name, value in asdict(found).items():
            emit(f'{name:<30} {"-" if value is None else round(value, 3) if isinstance(value, float) else value}')
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """``python -m dev_lab.dev.metrics [--days N] [--json]`` reads; ``record <kind> ...`` appends one line."""
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.metrics', description=__doc__.splitlines()[0])
    parser.add_argument('--days', type=float, default=30.0, help='the window, counted back from now')
    parser.add_argument('--json', action='store_true')
    verbs = parser.add_subparsers(dest='verb')
    one = verbs.add_parser('record', help='append one line (the agent guard engine calls this)')
    one.add_argument('kind', choices=KINDS)
    one.add_argument('--repo', default='', help="the repository's URL; this checkout's origin by default")
    one.add_argument('--rule', default='')
    one.add_argument('--reason', default='')
    one.add_argument('--sha', default='')
    args = parser.parse_args(argv)
    return _cli_record(args) if args.verb == 'record' else _cli_read(args)


if __name__ == '__main__':
    raise SystemExit(main())
