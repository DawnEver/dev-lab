"""AN EXPLICITLY USER-APPROVED CONTROLLER, STOPPED BY EXACT IDENTITY -- not by a recognized signature.

Split from :mod:`dev_lab.dev.stoprun` (2026-11-15, module-size band); reached through its
``--approved-created --approved-command-sha256 --approved-user-words`` arguments. It stops the verified
actual controller FIRST, so its child cannot launch the next step, and rechecks the bounded original
subtree before every stop; any uncertainty reports partial completion. A member that is gone after a
proved-stopped original ancestor exited WITH it (a Windows job object closes with its launcher): it is
recorded, never killed, so a recycled pid is never touched. Neither session ownership nor atomic control;
see ``docs-src/dev/auto-doors.md``.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from lab_commons.proc import descendants

from dev_lab.dev.proctable import subtree, unstoppable
from dev_lab.dev.stopsignatures import SERVE, orphan_role, orphaned_worker, why_stoppable

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from lab_commons.liveness import CreationClock

    from dev_lab.dev.proctable import Proc

__all__ = ['ApprovedRun', 'stop_approved']


@dataclass(frozen=True)
class ApprovedRun:
    """The caller's explicit user authorization and exact root identity, not proof of ownership.

    Select the actual Python controller, not a venv launcher that merely waits for it. All facts
    are mandatory and single-use observations: execution rechecks them, even after a dry run.
    """

    created: int
    command_sha256: str
    user_words: str

    def __post_init__(self) -> None:
        """Reject an incomplete authorization before any process is observed or stopped."""
        if type(self.created) is not int or self.created <= 0:
            msg = 'approved created must be a positive exact integer creation stamp'
            raise ValueError(msg)
        if not isinstance(self.command_sha256, str) or re.fullmatch(r'[0-9a-f]{64}', self.command_sha256) is None:
            msg = 'approved command_sha256 must name the exact complete command line as lowercase SHA256'
            raise ValueError(msg)
        if not isinstance(self.user_words, str) or not self.user_words.strip():
            msg = 'approved user_words must contain the actual explicit user authorization'
            raise ValueError(msg)


def ordinary_lifecycle_door(pid: int) -> str:
    return (
        f'{pid} has an existing lifecycle; use the ordinary '
        f'python -m dev_lab.dev.stoprun --pid {pid} without approved arguments'
    )


def command_hash(command: str) -> str:
    return hashlib.sha256(command.encode('utf-8')).hexdigest()


@dataclass
class _ApprovedTree:
    """One bounded original process snapshot and the parents this invocation proved stopped."""

    root: int
    table: Mapping[int, Proc]
    members: frozenset[int]
    stamps: dict[int, int | None]
    stopped: set[int]

    @classmethod
    def capture(
        cls,
        pid: int,
        table: Mapping[int, Proc],
        approved: ApprovedRun,
        born: CreationClock,
        *,
        signatures: tuple[str, ...],
        orphans: tuple[str, ...],
    ) -> _ApprovedTree:
        """Reuse the process owner's refuted-edge closure, then require positive identity proof."""
        stamps: dict[int, int | None] = {}

        def observed(member: int) -> int | None:
            if member not in stamps:
                stamps[member] = born(member)
            return stamps[member]

        if observed(pid) != approved.created or command_hash(table[pid][1]) != approved.command_sha256:
            msg = 'approved root creation stamp or complete command identity disagrees'
            raise ValueError(msg)
        if why_stoppable(table, pid, signatures, born) is not None:
            raise ValueError(ordinary_lifecycle_door(pid))
        rows = {member: (row[1], row[0]) for member, row in table.items()}
        members = descendants(pid, rows, observed)
        if any(type(observed(member)) is not int or observed(member) <= 0 for member in members):
            msg = 'an approved subtree member has no readable creation stamp'
            raise ValueError(msg)
        if any(not table[member][1].strip() for member in members):
            msg = 'an approved subtree member has no readable complete command'
            raise ValueError(msg)
        for member in members:
            command = table[member][1]
            if (
                SERVE.search(command)
                or orphan_role(command, orphans)
                or orphaned_worker(table, member, born) is not None
            ):
                raise ValueError(ordinary_lifecycle_door(member))
        return cls(pid, dict(table), members, stamps, set())

    def changed(self, fresh: Callable[[], Mapping[int, Proc]], born: CreationClock) -> str | None:
        """Refuse an unreadable fresh census rather than killing against an old observation."""
        try:
            return self._changed(fresh(), born)
        except OSError as exc:
            return f'the fresh process identity is unreadable: {exc}'

    def _below_stopped(self, member: int) -> bool:
        """Whether an ORIGINAL ancestor of *member* inside the approved subtree was proved stopped."""
        seen = {member}
        parent = self.table[member][0]
        while parent in self.members and parent not in seen:
            if parent in self.stopped:
                return True
            seen.add(parent)
            parent = self.table[parent][0]
        return False

    def _changed(self, current: Mapping[int, Proc], born: CreationClock) -> str | None:
        """The exact original members remain; only a proved stopped parent licenses reparenting."""
        for member in self.members - self.stopped:
            if member not in current:
                if not self._below_stopped(member):
                    return f'original member {member} disappeared before its identity could be proved'
                self.stopped.add(member)  # exited with its stopped ancestor: recorded, never killed
                continue
            if never := unstoppable(member, current):
                return never
            if born(member) != self.stamps[member] or command_hash(current[member][1]) != command_hash(
                self.table[member][1]
            ):
                return f'original member {member} changed creation stamp or complete command'
            parent = self.table[member][0]
            if current[member][0] != parent and parent not in self.stopped:
                return f'original member {member} changed parent while its proved parent was not stopped'
        current_rows = {member: (row[1], row[0]) for member, row in current.items()}
        # Keep only the ORIGINAL proved edges through stopped/reparented members. Never walk a
        # new parent. These virtual rows diagnose growth; they never authorize an extra kill.
        current_rows.update({member: (row[1], row[0]) for member, row in self.table.items() if member in self.members})
        growth = (
            descendants(
                self.root,
                current_rows,
                lambda member: self.stamps[member] if member in self.stopped else born(member),
            )
            - self.members
        )
        if growth:
            return (
                f'additional processes below the recorded parent identities: {sorted(growth)}; '
                'no new member is authorized. Inspect them and use their recognized run door or a new exact approval'
            )
        return None


def stop_approved(
    pid: int,
    table: Mapping[int, Proc],
    approved: ApprovedRun,
    *,
    dry_run: bool,
    born: CreationClock,
    fresh: Callable[[], Mapping[int, Proc]],
    kill: Callable[[int], None],
    gone: Callable[[int, float], bool],
    signatures: tuple[str, ...],
    orphans: tuple[str, ...],
) -> tuple[int, list[str]]:
    """Cut the actual controller first; every later uncertainty reports partial, never atomic success."""
    try:
        tree = _ApprovedTree.capture(pid, table, approved, born, signatures=signatures, orphans=orphans)
    except (ValueError, OSError) as exc:
        return 3, [f'refused: {exc}']
    if why := tree.changed(fresh, born):
        return 3, [f'refused: {why}']
    lines = ['user-authorized exact controller identity; this assertion is not session ownership proof']
    order = [pid, *(member for member in subtree(table, pid) if member != pid and member in tree.members)]
    for member in order:
        if why := tree.changed(fresh, born):
            prefix = 'partial: stopped no further process' if tree.stopped else 'refused'
            return 3, [*lines, f'{prefix}: {why}']
        if member in tree.stopped:
            lines.append(f'{member} exited with its stopped parent; nothing was killed')
            continue
        if dry_run:
            lines.append(
                f'would stop {member} created={tree.stamps[member]} command_sha256={command_hash(table[member][1])}'
            )
            continue
        try:
            kill(member)
            exited = gone(member, 2.0)
        except OSError as exc:
            return 3, [*lines, f'partial: stopping {member} was not confirmed: {exc}; no further kill']
        if not exited:
            return 3, [*lines, f'partial: stop requested for {member}, but exit was not confirmed; no further kill']
        tree.stopped.add(member)
        lines.append(f'stopped {member} created={tree.stamps[member]} command_sha256={command_hash(table[member][1])}')
    why = tree.changed(fresh, born)
    return (3, [*lines, f'partial: the original stop sequence ended, but {why}']) if why else (0, lines)
