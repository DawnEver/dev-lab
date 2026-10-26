"""THE TOOLCHAIN'S METRICS, COMPUTED: what landed (read from git) and the plan's figures over one window.

The recorded lines are :mod:`dev_lab.dev.metrics`'s; the report and CLI are :mod:`dev_lab.dev.metrics_report`.
What LANDED is read from git, not the log: a PR whose head branch a first-parent ``Merged-Branch:`` merge of the
integration branch names is merged at that commit's time (:func:`landings`), however it was closed, and a
``Break-Glass:`` landing is a hand action on the PR it carries whether or not a guard logged it.
"""

from __future__ import annotations

import re
import shutil
import statistics
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final

import lab_commons.launch as _door

from dev_lab.dev.metrics import BREAK_GLASS_ACTION, BYPASS, HAND_ACTION, HOST_FAILURE, PUSH, REFUSAL

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ['Landing', 'Metrics', 'compute', 'landings']

_GIT: Final = shutil.which('git') or 'git'


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
