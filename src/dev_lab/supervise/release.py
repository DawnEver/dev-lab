"""The algebra of a release: what is known good, what is being tried, and what has failed.

Pure -- no git, no service manager, no clock it did not receive. A deployment's state machine is
the part worth testing exhaustively, and the predecessor's could only be tested by standing up two
worktrees and a service, which is why its rollback path was exercised for the first time in
production.

WHAT THE PREDECESSOR GOT WRONG HERE, and the reason this module exists rather than being folded
into the component:

* known-good was a SINGLE value. Rolling back from a bad release left nowhere to roll back TO if
  the previous one had also been superseded, so a second failure had no floor. It is a bounded
  HISTORY here, and a rollback steps back through it.
* a failed release was remembered by the commit set alone, so two different failures of the same
  commits counted as one -- the circuit breaker could not reach its threshold and the retry loop
  the user asked for had no way to say "this has now failed five times".
* nothing recorded WHEN a release became good, so a report could not say how long the current one
  had been serving.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

__all__ = [
    'DEFAULT_KEEP',
    'DEFAULT_TOLERANCE',
    'Snapshot',
    'failure_streak',
    'history',
    'record_failure',
    'record_success',
    'target_of',
]

#: How many verified-good snapshots are kept. Two is the floor that makes a rollback meaningful --
#: one to be wrong about and one to step back to -- and more costs nothing but a line of JSON.
DEFAULT_KEEP: Final = 3

#: How many consecutive failures of ONE release the circuit breaker tolerates before it escalates.
#: The predecessor's number, kept because it was measured: three attempts is enough to ride out a
#: flake and short enough that a genuinely broken commit does not own the afternoon.
DEFAULT_TOLERANCE: Final = 3


@dataclass(frozen=True)
class Snapshot:
    """One state of the target that was verified good.

    Attributes:
        main: the main repository's commit.
        libs: the other repositories' commits, rendered as ``name=sha`` pairs sorted by name, so
            two snapshots of the same state compare equal.
        at: when it was verified, ISO-8601.

    """

    main: str
    libs: str
    at: str

    @property
    def key(self) -> str:
        """Return the identity a failure is remembered by.

        Returns:
            The commits, without the timestamp -- the same code failing twice is the same failure
            however long apart the attempts were.

        """
        return f'{self.main}|{self.libs}'


def target_of(commits: dict[str, str]) -> Snapshot:
    """Build the snapshot a set of fetched commits describes.

    Args:
        commits: repository name to commit.

    Returns:
        The snapshot, with ``at`` empty because nothing has verified it yet.

    """
    main = commits.get('main', '')
    libs = ','.join(f'{name}={sha}' for name, sha in sorted(commits.items()) if name != 'main')
    return Snapshot(main=main, libs=libs, at='')


def history(state: dict[str, Any]) -> list[Snapshot]:
    """Return the verified-good snapshots, oldest first.

    Args:
        state: the run's state.

    Returns:
        The snapshots. Empty on a target that has never had a verified release.

    """
    slice_ = state.get('releases')
    if not isinstance(slice_, list):
        return []
    return [
        Snapshot(main=str(entry.get('main', '')), libs=str(entry.get('libs', '')), at=str(entry.get('at', '')))
        for entry in slice_
        if isinstance(entry, dict)
    ]


def record_success(state: dict[str, Any], snapshot: Snapshot, *, keep: int = DEFAULT_KEEP) -> None:
    """Append *snapshot* to the verified-good history, and clear the failure record.

    A release that worked clears the failures of the one before it: the count exists to notice a
    release that keeps failing, and a success means the question is settled.

    Args:
        state: the run's state.
        snapshot: what was verified.
        keep: how many snapshots to retain, newest last.

    """
    kept = [entry for entry in history(state) if entry.key != snapshot.key]
    kept.append(snapshot)
    state['releases'] = [{'main': entry.main, 'libs': entry.libs, 'at': entry.at} for entry in kept[-max(1, keep) :]]
    state['release_failures'] = []


def record_failure(
    state: dict[str, Any], snapshot: Snapshot, reason: str, *, tolerance: int = DEFAULT_TOLERANCE
) -> int:
    """Record that *snapshot* failed to deploy, and return its consecutive failure count.

    Args:
        state: the run's state.
        snapshot: the release that failed.
        reason: why, for the escalation message.
        tolerance: the threshold a caller may compare the count against.

    Returns:
        How many consecutive times this exact release has now failed.

    """
    entries = state.get('release_failures')
    if not isinstance(entries, list):
        entries = []
        state['release_failures'] = entries
    streak = 0
    for entry in reversed(entries):
        if not isinstance(entry, dict) or entry.get('key') != snapshot.key:
            break
        streak += 1
    entries.append({'key': snapshot.key, 'reason': reason, 'tolerance': tolerance})
    del entries[:-50]
    return streak + 1


def failure_streak(state: dict[str, Any], snapshot: Snapshot) -> int:
    """Return how many consecutive times *snapshot* has failed, without recording anything.

    Args:
        state: the run's state.
        snapshot: the release being asked about.

    Returns:
        The streak, 0 when it has not failed.

    """
    entries = state.get('release_failures')
    if not isinstance(entries, list):
        return 0
    streak = 0
    for entry in reversed(entries):
        if not isinstance(entry, dict) or entry.get('key') != snapshot.key:
            break
        streak += 1
    return streak
