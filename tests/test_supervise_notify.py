"""The check-in the manager reads, over a protocol small enough to be worth having twice.

THE SOCKET IS A DOUBLE AND THAT IS THE POINT RATHER THAN A CONCESSION. `AF_UNIX` does not exist on
every platform this kit runs tests on, so a test that bound a real socket would SKIP exactly where
the code path most needs exercising -- and a guard that skips on a developer's box is a guard that
was never run when the module was written. What is being asserted is this module's own work: the
payload, the address it is sent to, and the two answers for "nobody is listening".
"""

from __future__ import annotations

from pathlib import Path
from typing import Self

import pytest

from dev_lab.supervise import notify

_ADDRESS = '/run/systemd/notify'

#: Every datagram the double was asked to send, as ``(payload, address)``. Module level rather than
#: a class attribute, because a mutable class attribute is a default every instance shares.
_SENT: list[tuple[bytes, str]] = []


class _FakeSocket:
    """Records what a datagram socket was asked to send, without a socket."""

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        pass

    def sendto(self, payload: bytes, address: str) -> None:
        """Record one datagram."""
        _SENT.append((payload, address))

    def __enter__(self) -> Self:
        """Enter the context manager."""
        return self

    def __exit__(self, *_exc: object) -> None:
        """Leave the context manager."""


@pytest.fixture(autouse=True)
def _no_socket_left_behind() -> None:
    """Let each test see only its own datagrams."""
    _SENT.clear()


def _installed(monkeypatch: pytest.MonkeyPatch, factory: type = _FakeSocket) -> None:
    """Make the module's socket a recorder, with `AF_UNIX` present whether or not the box has it."""
    monkeypatch.setattr(notify.socket, 'socket', factory)
    monkeypatch.setattr(notify.socket, 'AF_UNIX', 1, raising=False)
    monkeypatch.setattr(notify.socket, 'SOCK_DGRAM', 2, raising=False)


def test_no_manager_means_nothing_is_sent_and_nobody_is_told_otherwise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE THIRD ANSWER MUST NOT EXIST.

    Reporting a check-in that went nowhere is the one outcome that turns a watchdog into a
    reassurance, so `False` has to mean exactly that.
    """
    monkeypatch.delenv(notify.NOTIFY_SOCKET, raising=False)
    _installed(monkeypatch)
    assert notify.ready() is False
    assert notify.watchdog() is False
    assert _SENT == [], 'a datagram was sent with no manager to receive it'


def test_the_check_in_is_the_line_the_manager_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    """The protocol is a payload and an address, and this asserts both."""
    monkeypatch.setenv(notify.NOTIFY_SOCKET, _ADDRESS)
    _installed(monkeypatch)

    assert notify.ready() is True
    assert notify.watchdog() is True
    assert _SENT == [(b'READY=1', _ADDRESS), (b'WATCHDOG=1', _ADDRESS)]


def test_an_abstract_socket_is_addressed_with_a_nul(monkeypatch: pytest.MonkeyPatch) -> None:
    """THE SUBTLE HALF, AND THE ONE THAT FAILS SILENTLY.

    systemd spells an abstract socket `@/org/freedesktop/systemd1/notify` and the kernel wants a
    leading NUL. Passing the `@` through addresses a PATH that does not exist -- and a datagram that
    reaches nobody has nowhere to report that, so the daemon would look wired and check in with
    nobody forever.
    """
    monkeypatch.setenv(notify.NOTIFY_SOCKET, '@/org/freedesktop/systemd1/notify')
    _installed(monkeypatch)

    assert notify.watchdog() is True
    sent_to = _SENT[0][1]
    assert sent_to == '\0/org/freedesktop/systemd1/notify'
    assert not sent_to.startswith('@')


def test_an_unusable_socket_is_a_no_and_not_a_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    """A box with no `AF_UNIX` has no manager, which is an answer rather than a failure.

    Measured: `socket.AF_UNIX` does not exist on this development platform, so the lookup raises
    before any socket is made. Letting that out of `ready()` would kill every local run of the
    daemon for a reason that has nothing to do with what it was checking.
    """
    monkeypatch.setenv(notify.NOTIFY_SOCKET, _ADDRESS)
    monkeypatch.delattr(notify.socket, 'AF_UNIX', raising=False)
    assert notify.ready() is False


class _Refusing(_FakeSocket):
    """A socket that exists and will not send."""

    def sendto(self, payload: bytes, address: str) -> None:
        """Refuse."""
        reason = 'connection refused'
        raise OSError(reason)


def test_a_socket_that_cannot_send_is_also_a_no(monkeypatch: pytest.MonkeyPatch) -> None:
    """A manager was addressed and did not take the datagram, which is still nobody being told."""
    monkeypatch.setenv(notify.NOTIFY_SOCKET, _ADDRESS)
    _installed(monkeypatch, _Refusing)
    assert notify.watchdog() is False


def test_the_real_socket_module_answers_rather_than_raising(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """NOT A DOUBLE THIS TIME, and both platforms reach False by different routes.

    Where `AF_UNIX` is absent -- this development box -- the lookup raises. Where it is present and
    `/run/systemd/notify` does not exist -- any host with no manager on that path -- the send raises.
    Either way the answer is the same and it is False, which is what makes the module safe to leave
    wired in everywhere. The address is one that CANNOT exist: `/run/systemd/notify` is live on a
    systemd host such as a CI runner, where the datagram is taken and the answer is rightly True.
    """
    monkeypatch.setenv(notify.NOTIFY_SOCKET, str(tmp_path / 'no-manager' / 'notify'))
    assert notify.watchdog() is False
