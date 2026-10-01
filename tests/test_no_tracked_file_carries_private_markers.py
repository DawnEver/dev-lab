"""A published repo: no tracked file may name a machine, a person, a home path or a chat id.

The scan is `tests/_private_markers.py`; it runs under `make verify` (and so in CI) because verify
runs this suite. The machine-local denylist `~/.claude/private-markers` adds this host's private
values without committing them.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests._private_markers import load_markers, scan_text, scan_tree

_ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize(
    'planted',
    [
        # Assembled from halves so this file does not plant a hit in the tree scan below.
        'see C:' + r'\Users\someone\repo',
        'cd /' + 'Users/someone/src',
        'cd /' + 'home/someone/src',
        'mail person' + '@university.ac.uk now',
        'chat -100' + '1234567890',
        'D:' + r'\OneDrive' + ' - Some Org',
    ],
)
def test_a_planted_private_value_is_found(planted: str) -> None:
    assert scan_text(planted), planted


@pytest.mark.parametrize(
    'clean',
    [
        r'C:\Users\<user>\repo',
        '/Users/<user>/src and $HOME/x',
        'user@example.com, git@forge.example.org, a@b.invalid, 1+x@users.noreply.github.com',
        r"'import pytest\n@pytest.mark.xfail'",
        'OneDrive - <Org>',
        'chat -100 or -100123',
    ],
)
def test_a_neutral_value_is_not_found(clean: str) -> None:
    assert scan_text(clean) == [], clean


def test_the_private_denylist_reads_literals_regexes_and_comments(tmp_path: Path) -> None:
    markers = tmp_path / 'private-markers'
    markers.write_text('# a comment\n\nSecretHost\n/proj-\\d+/\n', encoding='utf-8')
    compiled = load_markers(markers)
    assert len(compiled) == 2
    assert scan_text('on secrethost today', compiled) == [(1, 'private marker', '<redacted>')]
    assert scan_text('see PROJ-42', compiled) == [(1, 'private marker', '<redacted>')]
    assert scan_text('a comment, proj-x', compiled) == []


def test_an_absent_denylist_is_silent(tmp_path: Path) -> None:
    assert load_markers(tmp_path / 'missing') == ()


def test_no_tracked_file_carries_a_private_marker() -> None:
    hits = scan_tree(_ROOT, load_markers())
    assert hits == [], 'private values in tracked files:\n' + '\n'.join(hits)
