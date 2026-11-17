"""IDLE-HEADS-REPORTED (user ruling D25, 2026-11-17): the safety net beside the merge's own head delete.

Real git (a bare ``origin`` and a clone) and the stateful fake forge. An unmerged ``pr/*`` head idle past
``idle_report_days`` is REPORTED to its PR's owner and kept; PLANTED CONTROLS beside it: the same head inside the
window is untouched and unreported, and a landed one is the landed sweep's -- swept, never reported.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from _branch_repos import advance, clone_pair
from _forge_fake import git_out, run_git
from _forge_state import StateForge

from dev_lab.dev.branchdelete import sweep
from dev_lab.dev.branchidle import report
from dev_lab.dev.forge import fetch_origin
from dev_lab.dev.forgealarm import STALE_BRANCH, Alarm

_MANIFEST = """[project]
name = "planted"
version = "0"

[tool.dev_lab.branchset]
trunk = "main"
sessions = []

[tool.dev_lab.integrator]
integration = "integrate/main"
"""


def _repo(tmp_path: Path) -> Path:
    _, work = clone_pair(tmp_path)
    (work / 'pyproject.toml').write_text(_MANIFEST, encoding='utf-8')
    return work


def _report(work: Path, forge: StateForge, *, days: float) -> tuple[tuple[str, ...], list[Alarm]]:
    alarms: list[Alarm] = []
    run_git(work, 'fetch', '-q', 'origin')
    now = datetime.now(UTC) + timedelta(days=days)
    return report(work, forge, now=now, say=lambda _s: None, alarm=alarms.append), alarms


def _on_origin(work: Path, branch: str) -> bool:
    return bool(git_out(work, 'ls-remote', '--heads', 'origin', branch))


def test_an_unmerged_idle_pr_head_is_reported_to_its_owner_and_kept(tmp_path: Path) -> None:
    work = _repo(tmp_path)
    forge = StateForge()
    number = forge.add_pull('pr/idle', 'integrate/main', sha=advance(work, 'pr/idle', 'o.txt', 'o\n'))
    lines, alarms = _report(work, forge, days=2)
    (line,) = lines
    assert line.startswith(f'pr/idle (#{number} by ')
    assert 'idle 2.0 d' in line
    assert [a.kind for a in alarms] == [STALE_BRANCH]
    assert _on_origin(work, 'pr/idle'), 'reported only: never deleted'


def test_a_fresh_pr_head_is_untouched_and_unreported(tmp_path: Path) -> None:
    work = _repo(tmp_path)
    forge = StateForge()
    forge.add_pull('pr/fresh', 'integrate/main', sha=advance(work, 'pr/fresh', 'f.txt', 'f\n'))
    assert _report(work, forge, days=0.5) == ((), [])
    assert _on_origin(work, 'pr/fresh')


def test_a_merged_pr_head_is_swept_and_never_reported(tmp_path: Path) -> None:
    work = _repo(tmp_path)
    tip = advance(work, 'integrate/main', 'i.txt', 'i\n')
    run_git(work, 'push', '-q', '--no-verify', 'origin', f'{tip}:refs/heads/pr/merged')
    assert _report(work, StateForge(), days=5) == ((), [])
    said: list[str] = []
    sweep(work, client=StateForge(), session='s', fetch=fetch_origin, say=said.append, alarm=lambda _a: None)
    assert not _on_origin(work, 'pr/merged'), said
