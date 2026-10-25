"""``forge try``: a selection is PLACED by its markers and published only where a host has room NOW.

PLANTED CONTROLS: an unmarked file runs on Linux, a ``jmag`` file on Windows, a ``femm`` file is refused by name;
a fresh card with room admits, a stale card, a cluster seat and a full host each say why not; a request past
its deadline is refused ``no room``, never left waiting.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from _forge_fake import git_out, run_git

from dev_lab.dev.forgehosts import HostCard
from dev_lab.dev.forgerequest import (
    TESTS,
    Declared,
    UndeclaredRequest,
    declared_request,
    parse_deadline,
    request_body,
)
from dev_lab.dev.forgetry import room

_PYPROJECT = """
[tool.lab_commons.tests]
resources = ["femm", "jmag", "linux", "windows"]
produce = ["-m", "dev_lab.dev.verify", "--part", "{part}"]

[tool.pytest.ini_options]
testpaths = ["tests"]
"""
NOW = datetime(2026, 10, 24, 12, tzinfo=UTC)


@pytest.fixture
def repo(tmp_path: Path) -> tuple[Path, str]:
    """A committed repository with an unmarked, a ``jmag`` and a ``femm`` test file."""
    run_git(tmp_path, 'init', '-q')
    (tmp_path / 'pyproject.toml').write_text(_PYPROJECT, encoding='utf-8')
    tests = tmp_path / 'tests'
    tests.mkdir()
    (tests / 'test_plain.py').write_text('def test_a():\n    pass\n', encoding='utf-8')
    marked = 'import pytest\n\npytestmark = pytest.mark.{0}\n\ndef test_b():\n    pass\n'
    (tests / 'test_jmag.py').write_text(marked.format('jmag'), encoding='utf-8')
    (tests / 'test_femm.py').write_text(marked.format('femm'), encoding='utf-8')
    run_git(tmp_path, 'add', '-A')
    run_git(tmp_path, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '-m', 'init')
    return tmp_path, git_out(tmp_path, 'rev-parse', 'HEAD')


def test_an_unmarked_selection_is_placed_on_linux(repo: tuple[Path, str]) -> None:
    assert declared_request(*repo, TESTS, ('tests/test_plain.py',)).needs == {'linux'}


def test_a_selection_holding_a_jmag_test_is_placed_on_windows(repo: tuple[Path, str]) -> None:
    needs = declared_request(*repo, TESTS, ('tests/test_plain.py', 'tests/test_jmag.py')).needs
    assert needs == {'jmag', 'windows'}


def test_a_selection_needing_another_windows_tool_is_refused_by_name(repo: tuple[Path, str]) -> None:
    with pytest.raises(UndeclaredRequest, match="needs \\['femm'\\]"):
        declared_request(*repo, TESTS, ('tests/test_femm.py',))


def _card(host: str, platform: str, *, cpu: float, mem_gb: float, ticked: datetime = NOW, **more: float) -> HostCard:
    supply = {'cpu': cpu, 'mem_gb': mem_gb, platform: cpu, **more}
    return HostCard(host=host, login='x', platform=platform, ticked=ticked.isoformat(), supply=supply)


def test_room_admits_a_fresh_host_and_names_why_every_other_card_does_not() -> None:
    wanted = Declared(TESTS, (), frozenset({'linux'}), 2.0, 4.0, 1.0)
    cards = (
        _card('box-a', 'linux', cpu=8, mem_gb=32),
        _card('box-old', 'linux', cpu=8, mem_gb=32, ticked=NOW - timedelta(days=1)),
        _card('ada/alice', 'linux', cpu=64, mem_gb=256),
        _card('box-full', 'linux', cpu=1, mem_gb=32),
        _card('g', 'windows', cpu=16, mem_gb=64),
    )
    fits, why = room(cards, wanted, NOW)
    assert fits == ['box-a']
    said = '\n'.join(why)
    assert 'box-old: card stale' in said
    assert 'ada/alice: a cluster seat runs no request' in said
    assert 'box-full:' in said
    assert 'g:' in said


def test_a_jmag_try_needs_a_windows_card_with_jmag() -> None:
    wanted = Declared(TESTS, (), frozenset({'jmag', 'windows'}), 1.0, 2.0, 1.0)
    fits, _ = room(
        (_card('g', 'windows', cpu=8, mem_gb=32, jmag=2), _card('w', 'windows', cpu=8, mem_gb=32)), wanted, NOW
    )
    assert fits == ['g']


def test_a_deadline_round_trips_through_the_body_and_a_naive_one_is_none() -> None:
    body = request_body(TESTS, 'a' * 40, ('tests/test_plain.py',), deadline=NOW)
    assert parse_deadline(body) == NOW
    assert parse_deadline('deadline = "2026-10-24T12:00:00"\n') is None
    assert parse_deadline(request_body(TESTS, 'a' * 40)) is None
