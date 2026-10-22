"""SCARCE-PARTS-BY-REACH -- a PR needs a scarce part only where its diff reaches that part's tests.

User ruling 2026-10-22 ("统一全部"): Windows capacity is scarce (G is the only Windows forge host), so a PR must
not wait on it for tests its change cannot affect. A part is SCARCE when its need-set holds a resource the
repository declares scarce -- ONE table, data, at the judged commit::

    [tool.lab_commons.tests]
    resources = ["femm", "jmag", "matlab", "simba", "windows"]
    scarce = ["femm", "jmag", "matlab", "simba", "windows"]      # a subset of resources

A PR into integration is MERGEABLE (:func:`lab_commons.dev.forgemerge.decide`) when every part its head's
need-set derives stands PASS, EXCEPT a scarce part whose tests no path of ``merge-base..head`` reaches
(:func:`unreached`): that one is WAIVED -- neither produced for the PR
(:func:`lab_commons.dev.forgeschedule.candidates`) nor read for its merge. A REACHED scarce part is required and
is produced for the PR whatever its part's ref filter says. The full scarce parts run on the integration
branch after the merge; a red one there opens ONE ``integration`` issue
naming the merges since its last green and their sessions (:func:`red_alarms`).

REACH is the carry's rule (:mod:`lab_commons.dev.forgecarry`): a scarce part's test files are read from the
record its head's ``base`` part links (every id the base run handed to another part names that part); a part
reaches the diff when any of its files' footprints at the head (:mod:`lab_commons.dev.footprint`) holds a
changed path. ANY DOUBT -- no record, no merge-base, an unreadable declaration -- waives nothing: the part is
required, which only costs the run a waiver would have saved.
"""

from __future__ import annotations

import gzip
import json
import subprocess
from collections.abc import Callable, Mapping, Sequence
from typing import TYPE_CHECKING, Any, Final

import lab_commons.launch as _door
from lab_commons.dev.footprint import Footprints
from lab_commons.dev.forge import _GIT, _GIT_TIMEOUT_S
from lab_commons.dev.forgealarm import INTEGRATION, Alarm
from lab_commons.dev.forgecarry import changed_paths
from lab_commons.dev.forgework import ForgeCallFailed
from lab_commons.dev.platformparts import BASE, derived, part_context, parts_of
from lab_commons.hpc.needsets import scarce_parts, vocabulary_at
from lab_commons.outcomes import Conclusion

if TYPE_CHECKING:
    from pathlib import Path

    from lab_commons.dev.forgestatus import CommitStatus
    from lab_commons.dev.forgework import Client

__all__ = ['GREEN_LOOKBACK', 'SESSION_TRAILERS', 'files_by_part', 'red_alarms', 'unreached']

#: How many first-parent integration commits :func:`red_alarms` reads back for a scarce part's last green.
GREEN_LOOKBACK: Final = 64
#: The trailers naming the session that owns a merged commit (:mod:`lab_commons.dev.labsession`, and prose).
SESSION_TRAILERS: Final = ('Lab-Session', 'Claude-Session')

_SETTLED: Final = frozenset({'success', 'failure'})
_REACHED: dict[tuple[str, str, str], frozenset[str]] = {}  # (root, base, head) -> waived parts, per process


def files_by_part(record: Mapping[str, Any]) -> dict[str, frozenset[str]]:
    """Every OTHER part's test files, read off a run record's ``handed`` map (id -> part)."""
    found: dict[str, set[str]] = {}
    for node, owner in dict(record.get('handed', {})).items():
        found.setdefault(str(owner), set()).add(str(node).split('::', 1)[0])
    return {part: frozenset(files) for part, files in found.items()}


def _record(client: Client, status: CommitStatus) -> Mapping[str, Any] | None:
    """The run record *status* links, ``None`` when it links none or it cannot be read."""
    if not status.url:
        return None
    try:
        return json.loads(gzip.decompress(client.download(status.url)).decode('utf-8'))
    except (ForgeCallFailed, OSError, ValueError, EOFError):
        return None


def unreached(
    root: Path,
    client: Client,
    integration: str,
    head: str,
    statuses: Sequence[CommitStatus],
    *,
    record: Callable[[CommitStatus], Mapping[str, Any] | None] | None = None,
) -> frozenset[str]:
    """The scarce parts PR *head* WAIVES: derived for it, and reached by no path of ``merge-base..head``.

    *statuses* are the head's latest; *record* reads the run record a status links (default: download it).
    Memoized per (root, merge-base, head) for the life of the process. Any doubt waives nothing (module docstring).
    """
    try:
        scarce = frozenset(vocabulary_at(root, head).scarce)
    except (ValueError, subprocess.SubprocessError):
        return frozenset()
    wanted = scarce_parts(derived(statuses), scarce)
    settled = [one for one in statuses if one.context == part_context(BASE) and one.state in _SETTLED]
    base_status = settled[-1] if settled else None  # latest-per-context or oldest-first history: the last
    fork = _git(root, 'merge-base', f'refs/remotes/origin/{integration}', head)
    if not wanted or base_status is None or not fork:
        return frozenset()
    key = (str(root), fork, head)
    if key not in _REACHED:
        _REACHED[key] = _waived(root, fork, head, wanted, (record or (lambda one: _record(client, one)))(base_status))
    return _REACHED[key]


def _waived(
    root: Path, fork: str, head: str, wanted: frozenset[str], record: Mapping[str, Any] | None
) -> frozenset[str]:
    changed = changed_paths(root, fork, head)
    if record is None or changed is None:
        return frozenset()
    files = files_by_part(record)
    try:
        prints = Footprints.at(root, head)
    except (ValueError, subprocess.SubprocessError):
        return frozenset()
    return frozenset(
        part
        for part in wanted
        if part in files and not any(prints.reaches(test, changed) for test in sorted(files[part]))
    )


def red_alarms(
    root: Path, integration: str, repo: str, history: Callable[[str], Sequence[CommitStatus]]
) -> list[Alarm]:
    """ONE ``integration`` alarm when a scarce part is red on *integration*'s tip, else none.

    Per red scarce part: its last green on the first-parent history (within :data:`GREEN_LOOKBACK`), and every
    merge since it with the sessions its merged commits name (:data:`SESSION_TRAILERS`).
    """
    tip = _git(root, 'rev-parse', '--verify', '-q', f'refs/remotes/origin/{integration}')
    if not tip:
        return []
    try:
        scarce = frozenset(vocabulary_at(root, tip).scarce)
    except (ValueError, subprocess.SubprocessError):
        return []
    if not scarce:
        return []
    parts, _ = parts_of(history(tip))
    red = sorted(n for n in scarce_parts(sorted(parts), scarce) if parts[n].result is Conclusion.FAIL)
    if not red:
        return []
    lines = []
    for part in red:
        green = _last_green(root, tip, part, history)
        since = f'since its last green {green[:12]}' if green else f'in the last {GREEN_LOOKBACK} commits'
        lines += [f'- `tests/{part}` is red at {tip[:12]}; the merges {since}:']
        lines += [f'  - {row}' for row in _merges(root, green, tip)] or ['  - none: the red is not a merge']
    subject = f'a scarce part is red on {integration}'
    return [Alarm(INTEGRATION, repo, subject, '\n'.join(lines), about=f'scarce red {integration}@{tip[:12]}')]


def _last_green(root: Path, tip: str, part: str, history: Callable[[str], Sequence[CommitStatus]]) -> str:
    listed = _git(root, 'rev-list', '--first-parent', '-n', str(GREEN_LOOKBACK), tip, '--')
    for sha in listed.splitlines():
        parts, _ = parts_of(history(sha))
        if part in parts and parts[part].result is Conclusion.PASS:
            return sha
    return ''


def _merges(root: Path, green: str, tip: str) -> list[str]:
    span = [f'{green}..{tip}'] if green else ['-n', str(GREEN_LOOKBACK), tip]
    owner = ' '.join(f'%(trailers:key={key},valueonly,separator=%x20)' for key in SESSION_TRAILERS)
    rows = []
    for merge in _git(root, 'rev-list', '--first-parent', '--merges', *span, '--').splitlines():
        subject = _git(root, 'show', '-s', '--format=%s', merge)
        sessions = sorted(set(_git(root, 'log', f'--format={owner}', f'{merge}^1..{merge}^2').split()))
        rows.append(f'{merge[:12]} {subject} -- sessions: {", ".join(sessions) or "none named"}')
    return rows


def _git(root: Path, *args: str) -> str:
    """One git read, stripped; ``''`` when git refuses it."""
    done = _door.run(
        [_GIT, '-C', str(root), *args],
        capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=_GIT_TIMEOUT_S, check=False,
    )  # fmt: skip
    return done.stdout.strip() if done.returncode == 0 else ''
