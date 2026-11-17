"""IDLE-HEADS-REPORTED: an unmerged ephemeral head idle past its window is reported to its owner, never deleted.

User ruling D25 (2026-11-17), the safety net beside the merge itself (:func:`dev_lab.dev.forgemergecall.merge`
deletes an ephemeral head with the merge). A ``pr/*`` head integration already contains is the landed sweep's
(:func:`dev_lab.dev.branchdelete.sweep`, the lossless judgement); one it does NOT contain, idle -- its tip's
committer date -- longer than ``[tool.dev_lab.branchset] idle_report_days``, is named with its open PR and that
PR's author in ONE ``stale-branch`` alarm per pass. It is never archived (D22: no archive tags) and never deleted:
its commits exist nowhere else. The serve tick runs it (:func:`serve_report`).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Final

from dev_lab.dev.branchdelete import ORIGIN, landed
from dev_lab.dev.branchset import BranchSetNotDeclared, declared_branchset
from dev_lab.dev.checkout import git_out
from dev_lab.dev.forgealarm import STALE_BRANCH, Alarm
from dev_lab.dev.forgefailure import ForgeCallFailed
from dev_lab.dev.forgepulls import ListingIncomplete, pr_list
from dev_lab.dev.lanepolicy import load_policy

if TYPE_CHECKING:
    from dev_lab.dev.forgework import Client

__all__ = ['report', 'serve_report']

_DAY_S: Final = 86400.0


def report(
    root: Path, client: Client, *, now: datetime, say: Callable[[str], None], alarm: Callable[[Alarm], object]
) -> tuple[str, ...]:
    """One line per unlanded ephemeral origin head of *root* idle past the window at *now*; alarmed once, kept.

    Reads the fetched refs; the refs must be fetched already.
    """
    branchset = declared_branchset(root)
    policy = load_policy(root)
    listed = git_out(root, 'for-each-ref', '--format=%(refname)%09%(committerdate:unix)', ORIGIN)
    if listed is None:
        msg = f'git could not list the origin refs of {root}; nothing was reported'
        raise OSError(msg)
    opened = {pr.head: pr for pr in pr_list(client)}
    lines: list[str] = []
    for row in listed.splitlines():
        ref, stamp = row.split('\t')
        name = ref.removeprefix(ORIGIN)
        days = (now - datetime.fromtimestamp(int(stamp), UTC)).total_seconds() / _DAY_S
        if not branchset.is_ephemeral(name) or days < branchset.idle_report_days:
            continue
        if not landed(root, policy, ref).refused:
            continue  # integration holds it: the landed sweep deletes it
        pr = opened.get(name)
        owner = f'#{pr.number} by {pr.author}' if pr else 'no open PR'
        lines.append(f'{name} ({owner}) idle {days:.1f} d, not merged: land it or close it -- kept, never deleted')
    if lines:
        body = '\n'.join(lines)
        say(body)
        alarm(Alarm(STALE_BRANCH, client.forge.repo, f'{len(lines)} unmerged PR head(s) idle on origin', body))
    return tuple(lines)


def serve_report(root: Path, client: Client, *, say: Callable[[str], None], alarm: Callable[[Alarm], object]) -> None:
    """The serve pass's step: :func:`report` now, over the refs the tick fetched; a failure only alarms."""
    try:
        report(root, client, now=datetime.now(UTC), say=say, alarm=alarm)
    except (BranchSetNotDeclared, ForgeCallFailed, ListingIncomplete, OSError, ValueError) as failed:
        alarm(Alarm(STALE_BRANCH, client.forge.repo, 'the idle PR-head report failed', str(failed)))
