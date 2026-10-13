"""The ``Forge-Host`` commit-msg stamp: written once, replaced not duplicated, and never blocking."""

from __future__ import annotations

from pathlib import Path

from lab_commons.dev import forgeorigin


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
