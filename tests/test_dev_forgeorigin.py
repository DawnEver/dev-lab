"""The ``Forge-Host`` commit-msg stamp: written once, replaced not duplicated, and never blocking."""

from __future__ import annotations

from pathlib import Path

from lab_commons.hpc.account import ClusterAccount

from dev_lab.dev import forgehosts, forgeorigin


def test_the_stamp_appends_the_host_trailer_and_replaces_an_earlier_one(tmp_path: Path) -> None:
    message = tmp_path / 'COMMIT_EDITMSG'
    message.write_text('feat: x\n\nClaude-Session: s\n', encoding='utf-8')
    forgeorigin.stamp(str(message), 'G')
    forgeorigin.stamp(str(message), 'H')
    text = message.read_text(encoding='utf-8')
    assert text.count('Forge-Host:') == 1
    assert 'Forge-Host: H' in text
    assert 'Claude-Session: s' in text


def test_the_hook_never_blocks_a_commit(tmp_path: Path) -> None:
    assert forgeorigin.main([str(tmp_path / 'missing' / 'MSG')]) == 0
    assert forgeorigin.main([]) == 0


def test_on_a_cluster_login_node_the_stamp_is_the_card_name(monkeypatch, tmp_path: Path) -> None:
    """The stamp and the card share one name (forgehosts.this_host). PLANTED CONTROL: off a cluster, the machine."""
    message = tmp_path / 'COMMIT_EDITMSG'
    monkeypatch.setenv('HARNESS_MACHINE', 'login1')
    for seat, named in ((ClusterAccount('ada', 'alice'), 'ada/alice'), (None, 'login1')):
        monkeypatch.setattr(forgehosts, 'this_seat', lambda seat=seat: seat)
        message.write_text('feat: x\n', encoding='utf-8')
        assert forgeorigin.main([str(message)]) == 0
        assert f'Forge-Host: {named}' in message.read_text(encoding='utf-8')
        assert forgehosts.this_host() == named
