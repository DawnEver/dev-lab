"""``python -m dev_lab.dev.hpchost allocate`` -- write, show or clear the ONE expiring allocation record.

The record, its reader and the share it sets are :mod:`lab_commons.hpc.allocation` -- a runtime fact every
submitter reads (:func:`lab_commons.hpc.allocation.resolve`, through :func:`dev_lab.dev.forgerecords.read_allocation`).
This is only its WRITER: the verb deciding shares -- and the ONLY cross-borrow between research and verify accounts,
``--borrow research->verify|verify->research`` (user ruling 2026-10-30: none by default) -- and the store it lives
in (the forge's records home).
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from typing import Protocol

import lab_commons.launch as _door
from lab_commons.hpc.allocation import BORROWS, RECORD, Allocation, parse, parse_shares, render
from lab_commons.hpc.grants import Session
from lab_commons.log import emit

__all__ = ['Store', 'allocate', 'allocation_store']


class Store(Protocol):
    """Where the one allocation record lives: read it, replace it, delete it."""

    def read(self) -> str | None:
        """The record's text; ``None`` when there is none."""

    def write(self, text: str) -> None:
        """Replace the record with *text*."""

    def clear(self) -> None:
        """Delete the record."""


class _ForgeStore:
    """:data:`RECORD` on the records home of the checkout's forge, through ``forge records get|put|rm``.

    The forge is reached through its own CLI, launched by the one door, exactly as a person reads the record.
    """

    def _records(self, verb: str, stdin: str | None = None) -> str:
        argv = [sys.executable, '-m', 'dev_lab.dev.forge', 'records', verb, RECORD]
        done = _door.run(argv, input=stdin, capture_output=True, text=True, encoding='utf-8', check=False)
        if done.returncode:
            msg = f'forge records {verb} {RECORD} failed (exit {done.returncode}): {done.stderr.strip()}'
            raise RuntimeError(msg)
        return done.stdout

    def read(self) -> str | None:
        return self._records('get') or None

    def write(self, text: str) -> None:
        self._records('put', text)

    def clear(self) -> None:
        self._records('rm')


def allocation_store() -> Store:
    """The store every submitter reads -- the forge's."""
    return _ForgeStore()


def allocate(argv: list[str]) -> int:
    """``allocate --until <iso> [name=cpus/mem_gb ...] [--borrow <direction>] | --show | --clear``."""
    parser = argparse.ArgumentParser(prog='dev_lab.dev.hpchost allocate', description='the one expiring HPC allocation')
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--until', help='UTC expiry, ISO 8601 with a zone (2026-10-18T09:00Z)')
    mode.add_argument('--show', action='store_true', help='print the record, or say the share is derived')
    mode.add_argument('--clear', action='store_true', help='delete the record: every share is derived again')
    parser.add_argument('shares', nargs='*', help='name=cpus/mem_gb, one per session')
    parser.add_argument(
        '--borrow',
        action='append',
        choices=sorted(BORROWS),
        default=[],
        help='allow this cross-borrow until --until (none by default, user ruling 2026-10-30); repeatable',
    )
    args = parser.parse_args(argv)
    store = allocation_store()
    if args.show:
        text = store.read()
        now = datetime.now(UTC)
        if text is None or parse(text).expires <= now:
            emit(
                'no allocation in force: every session share is derived from Slurm (max-min over active sessions); '
                'research and verify accounts borrow nothing from each other'
            )
        else:
            emit(render(parse(text)))
        return 0
    if args.clear:
        store.clear()
        emit('[allocate] cleared: every session share is derived from Slurm, and nothing is borrowed')
        return 0
    if not args.shares and not args.borrow:
        parser.error('name at least one share (name=cpus/mem_gb) or one --borrow direction')
    try:
        expires = datetime.fromisoformat(args.until)
        shares: dict[str, Session] = parse_shares(args.shares)
    except ValueError as bad:
        parser.error(str(bad))
    if expires.tzinfo is None:
        parser.error(f'--until {args.until!r} names no timezone; write it in UTC (...Z)')
    if expires <= datetime.now(UTC):
        parser.error(f'--until {args.until} is already past')
    text = render(Allocation(expires, shares, frozenset(args.borrow)))
    store.write(text)
    emit(text)
    return 0
