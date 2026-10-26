"""THE TOOLCHAIN'S OWN BASELINE -- every refusal and every hand action on one JSONL per kind, and one read of them.

Plan P0 (lab-commons ``.claude/memory/2026/10/21/PLAN-a-short-robust-toolchain.md``): the metrics every later
phase is judged by need a record of what the tools did to people, not of what people remember. So the places
that refuse or that a human drives append one line here, through ONE writer (:func:`record`):

* ``refusal`` -- a git hook stage that refused (:mod:`dev_lab.dev.githooks.runner`), the agent guard denying a
  command (``deny-commands.js`` calls ``python -m dev_lab.dev.metrics record refusal``), a promotion refused;
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

THE READ (``python -m dev_lab.dev.metrics``) covers every repository of the family -- the machine file's
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

import argparse
import json
import os
import re
import shutil
import statistics
import subprocess
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final

import lab_commons.launch as _door
from lab_commons.config import config_path, section
from lab_commons.log import emit

from dev_lab.dev.datedlog import date_parts
from dev_lab.dev.forgepulls import pages
from dev_lab.dev.forgework import client_for
from dev_lab.dev.lanepolicy import Policy, policy_at

__all__ = [
    'BREAK_GLASS_ACTION',
    'BYPASS',
    'HAND_ACTION',
    'HAND_VERBS',
    'HOST_FAILURE',
    'KINDS',
    'PUSH',
    'REFUSAL',
    'Landing',
    'Metrics',
    'break_glass',
    'checkout',
    'compute',
    'family',
    'hand_action',
    'landings',
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


# ------------------------------------------------------------------------------------------------- the read


@dataclass(frozen=True)
class Landing:
    """One first-parent commit of the integration branch: the *branch* it merges (or ``''``), its Break-Glass reason."""

    sha: str
    time: datetime
    branch: str
    break_glass: str = ''


_MERGED: Final = re.compile(r'^Merged-Branch:\s*(\S+)\s*$', re.MULTILINE)
_GLASS: Final = re.compile(r'^Break-Glass:[ \t]*(\S.*?)\s*$', re.MULTILINE)


def landings(root: Path, ref: str, *, since: datetime, until: datetime) -> list[Landing]:
    """*ref*'s first-parent commits in ``[since, until)`` with ``Merged-Branch:`` or ``Break-Glass:``; oldest first."""
    done = _door.run(
        [_GIT, '-C', str(root), 'log', '--first-parent', '--reverse', '--format=%H%x1f%cI%x1f%B%x1e', ref,
         f'--since={since.isoformat()}', f'--until={until.isoformat()}'],
        capture_output=True, text=True, encoding='utf-8', errors='replace', check=True, timeout=120,
    )  # fmt: skip
    found = []
    for entry in done.stdout.split('\x1e'):
        if not entry.strip():
            continue
        sha, when, body = entry.strip().split('\x1f', 2)
        time = datetime.fromisoformat(when).astimezone(UTC)
        named, glass = _MERGED.findall(body), _GLASS.findall(body)
        if (named or glass) and since <= time < until:
            found.append(Landing(sha, time, named[-1] if named else '', glass[-1] if glass else ''))
    return found


@dataclass(frozen=True)
class Metrics:
    """The plan's metrics over one repository and window; ``None`` where there is nothing to measure."""

    repo: str
    since: str
    until: str
    merged_prs: int
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
    break_glass_commits: int
    landed_without_pr: int


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


def _hand(landing: Landing) -> dict[str, str]:
    """A Break-Glass *landing* as the hand action line :func:`break_glass` writes of it."""
    return {
        'time': landing.time.isoformat(), 'lab.action': BREAK_GLASS_ACTION,
        'vcs.ref.head.name': landing.branch, 'vcs.ref.head.revision': landing.sha,
    }  # fmt: skip


def compute(
    repo: str,
    records: Mapping[str, Iterable[Mapping[str, str]]],
    pulls: Iterable[Mapping[str, Any]],
    *,
    since: datetime,
    until: datetime,
    landings: Iterable[Landing] = (),
) -> Metrics:
    """The metrics of *repo* over ``[since, until)``: logged *records* by kind, forge *pulls*, git *landings*.

    A PR is merged when the forge says so, else at the first landing naming its head branch after it opened
    (a local merge closed by ``pr close-landed``). Edit->merged runs from the first push naming its head
    branch, or the PR's opening when that is earlier. A PR's own ``pr create`` is the session's normal act, not
    a touch; any other hand action naming its number, head commit or head branch is, and so is a Break-Glass
    landing of its branch -- once per sha, logged or not; every Break-Glass commit is counted, and every landed
    branch no PR ever named (a hand path no per-PR figure can see). A refusal is a candidate false positive when a
    bypass of the same rule in the same repository follows it.
    """
    slug = _slug(repo)

    def inside(when: datetime | None) -> bool:
        return when is not None and since <= when < until

    def ours(kind: str) -> list[Mapping[str, str]]:
        return [line for line in records.get(kind, ()) if _slug(line.get('vcs.repository.url.full', '')) == slug]

    def mine(kind: str) -> list[Mapping[str, str]]:
        return [line for line in ours(kind) if inside(_when(line.get('time')))]

    landed = sorted(landings, key=lambda one: one.time)
    pushes = sorted((when, line.get('vcs.ref.head.name')) for line in ours(PUSH) if (when := _when(line.get('time'))))

    def merged_at(pull: Mapping[str, Any]) -> datetime | None:
        if pull.get('merged_at'):
            return _when(pull['merged_at'])
        opened, ref = _when(pull.get('created_at')), (pull.get('head') or {}).get('ref')
        return next((one.time for one in landed if one.branch == ref and (opened is None or one.time >= opened)), None)

    def started(pull: Mapping[str, Any], end: datetime) -> datetime:
        opened, ref = _when(pull.get('created_at')) or end, (pull.get('head') or {}).get('ref')
        first = next((when for when, name in pushes if name == ref and when <= end), None)
        return min(opened, first) if first else opened

    listed = list(pulls)
    heads = {(p.get('head') or {}).get('ref') for p in listed}
    merged = [(p, end) for p in listed if (end := merged_at(p)) is not None and inside(end)]
    logged = [a for a in mine(HAND_ACTION) if a.get('lab.action') != 'pr create']
    glass = {a.get('vcs.ref.head.revision'): a for a in logged if a.get('lab.action') == BREAK_GLASS_ACTION}
    hands = [a for a in logged if a.get('lab.action') != BREAK_GLASS_ACTION] + list(glass.values())
    hands += [_hand(one) for one in landed if one.break_glass and one.sha not in glass and inside(one.time)]
    touched = [sum(_touches(a, p) for a in hands) for p, _ in merged]
    hours = [(end - started(p, end)).total_seconds() / 3600 for p, end in merged]
    refusals, bypasses = mine(REFUSAL), mine(BYPASS)
    candidates = sum(
        any(b.get('lab.rule.id') == r.get('lab.rule.id') and b['time'] > r['time'] for b in bypasses) for r in refusals
    )
    pushed = len(mine(PUSH))
    return Metrics(
        repo=repo,
        since=since.isoformat(),
        until=until.isoformat(),
        merged_prs=len(merged),
        median_edit_to_merged_h=statistics.median(hours) if hours else None,
        hand_actions_per_pr=_ratio(sum(touched), len(merged)),
        share_merged_untouched=_ratio(sum(1 for n in touched if not n), len(merged)),
        refusals=len(refusals),
        pushes=pushed,
        refusals_per_push=_ratio(len(refusals), pushed),
        candidate_false_positives=candidates,
        false_positive_share=_ratio(candidates, len(refusals)),
        open_prs=sum(1 for p in listed if p.get('state') == 'open'),
        host_failures_without_status=len(mine(HOST_FAILURE)),
        break_glass_commits=len(
            {a.get('vcs.ref.head.revision') for a in hands if a.get('lab.action') == BREAK_GLASS_ACTION}
        ),
        landed_without_pr=len({one.branch for one in landed if one.branch and inside(one.time)} - heads),
    )


def family(table: Mapping[str, Any] | None = None) -> list[Path]:
    """Every family checkout: the machine file's ``[serve] repos`` under its ``root`` (*table*, default that table)."""
    table = section('serve') if table is None else table
    repos, root = table.get('repos'), table.get('root')
    if not (isinstance(repos, list) and repos and isinstance(root, str)):
        msg = f'no [serve] repos and root in {config_path()}: the family is declared there (`workstation deploy`)'
        raise ValueError(msg)
    return [Path(root) / name for name in repos]


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


def _integration_ref(root: Path) -> str:
    """``origin/<integration>`` as *root*'s ``HEAD`` declares it; the default name when it declares none."""
    try:
        name = policy_at(root, 'HEAD').integration
    except (ValueError, OSError, subprocess.CalledProcessError):
        name = Policy().integration
    return f'origin/{name}'


def _measure(root: Path, *, since: datetime, until: datetime) -> Metrics:
    client = client_for(root)
    pulls = pages(client, f'{client.repo}/pulls', {'state': 'all'})
    landed = landings(root, _integration_ref(root), since=since, until=until)
    records = {kind: read(kind, root=root) for kind in KINDS}
    return compute(repo_of(root), records, pulls, since=since, until=until, landings=landed)


def _cli_read(args: argparse.Namespace) -> int:
    until = args.until or datetime.now(UTC)
    since = args.since or until - timedelta(days=args.days)
    found = {root.name: asdict(_measure(root, since=since, until=until)) for root in family()}
    if args.json:
        emit(json.dumps(found, indent=2))
        return 0
    emit(f'window [{since.isoformat()}, {until.isoformat()})')
    names = list(found)
    emit(f'{"":<30}' + ''.join(f'{name:>17}' for name in names))
    for field in next(iter(found.values()), {}):
        if field in {'repo', 'since', 'until'}:
            continue
        cells = [found[name][field] for name in names]
        shown = ['-' if v is None else round(v, 3) if isinstance(v, float) else v for v in cells]
        emit(f'{field:<30}' + ''.join(f'{cell!s:>17}' for cell in shown))
    return 0


def _instant(text: str) -> datetime:
    when = datetime.fromisoformat(text)
    return when if when.tzinfo else when.replace(tzinfo=UTC)


def main(argv: Sequence[str] | None = None) -> int:
    """``python -m dev_lab.dev.metrics [--since T] [--until T] [--days N] [--json]``; ``record <kind> ...`` appends."""
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.metrics', description=__doc__.splitlines()[0])
    parser.add_argument('--since', type=_instant, help='the window opens here (ISO 8601); default --until - --days')
    parser.add_argument('--until', type=_instant, help='the window closes here, exclusive (ISO 8601); default now')
    parser.add_argument('--days', type=float, default=30.0, help='the window length when --since is not given')
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
