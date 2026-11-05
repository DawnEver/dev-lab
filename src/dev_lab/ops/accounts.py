"""Host accounts as the kernel judges access: who an account is, and whether it may enter a directory."""

from __future__ import annotations

import stat
import sys
from dataclasses import dataclass

if sys.platform != 'win32':  # the host accounts: POSIX only
    import grp
    import pwd

__all__ = ['Account', 'account_of', 'may_enter']


@dataclass(frozen=True)
class Account:
    """A host account as the kernel judges access: its uid and every gid it holds (primary and supplementary)."""

    uid: int
    gids: frozenset[int]


def account_of(user: str) -> Account | None:
    """*user*'s :class:`Account` on this host, ``None`` where it does not exist yet (or the host has no ``pwd``)."""
    if sys.platform == 'win32':  # a Windows render has no accounts to judge
        return None
    try:
        entry = pwd.getpwnam(user)
    except KeyError:
        return None
    supplementary = {group.gr_gid for group in grp.getgrall() if user in group.gr_mem}
    return Account(entry.pw_uid, frozenset({entry.pw_gid, *supplementary}))


def may_enter(mode: int, uid: int, gid: int, account: Account | None) -> bool:
    """Whether *account* may enter a directory of *mode* owned ``uid:gid``: ONE class decides, as the kernel does.

    Root enters anything; the owner is judged by the owner bits alone, a member of the group by the group bits, anyone
    else by the other bits. An account not made yet (``None``) holds no ownership or membership: the other bits.
    """
    if account is None:
        return bool(mode & stat.S_IXOTH)
    if account.uid == 0:
        return True
    if account.uid == uid:
        return bool(mode & stat.S_IXUSR)
    if gid in account.gids:
        return bool(mode & stat.S_IXGRP)
    return bool(mode & stat.S_IXOTH)
