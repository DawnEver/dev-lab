"""The ``Forge-Host`` commit-msg stamp: written once, replaced not duplicated, and never blocking."""

from __future__ import annotations

import re
from pathlib import Path

from lab_commons.hpc.account import ClusterAccount

from dev_lab.dev import forgehosts, forgeorigin, privatemarkers


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
        monkeypatch.setattr(forgeorigin, 'repo_is_private', lambda _root: (True, ''))
        monkeypatch.setattr(forgeorigin, 'MARKERS_FILE', tmp_path / 'no-markers')
        message.write_text('feat: x\n', encoding='utf-8')
        assert forgeorigin.main([str(message)]) == 0
        assert f'Forge-Host: {named}' in message.read_text(encoding='utf-8')
        assert forgehosts.this_host() == named


def test_a_name_a_private_marker_matches_is_stamped_as_its_host_id(monkeypatch, tmp_path: Path) -> None:
    """The stamp must never refuse its own push. PLANTED CONTROL: an unmatched name in a private repo stays raw."""
    markers = tmp_path / 'private-markers'
    markers.write_text('secretbox\n', encoding='utf-8')
    monkeypatch.setattr(forgeorigin, 'MARKERS_FILE', markers)
    monkeypatch.setattr(forgeorigin, 'repo_is_private', lambda _root: (True, ''))
    message = tmp_path / 'COMMIT_EDITMSG'
    for machine, named in (('SecretBox-7', forgehosts.host_id('SecretBox-7')), ('plainbox', 'plainbox')):
        monkeypatch.setattr(forgehosts, 'this_seat', lambda: None)
        monkeypatch.setenv('HARNESS_MACHINE', machine)
        message.write_text('feat: x\n', encoding='utf-8')
        assert forgeorigin.main([str(message)], root=tmp_path) == 0
        text = message.read_text(encoding='utf-8')
        assert f'Forge-Host: {named}' in text
        assert privatemarkers.scan_text(text, privatemarkers.load_markers(markers)) == []


def test_a_public_repo_stamps_the_host_id(monkeypatch, tmp_path: Path) -> None:
    """Public: no raw name even unmatched. PLANTED CONTROL: the same name in a private repo is raw."""
    for private, named in ((False, forgehosts.host_id('plainbox')), (True, 'plainbox')):
        monkeypatch.setattr(forgeorigin, 'repo_is_private', lambda _root, private=private: (private, ''))
        assert forgeorigin.stamped_name('plainbox', tmp_path, (re.compile('secretbox', re.IGNORECASE),)) == named
