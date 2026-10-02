"""A published repo: no tracked file may name a machine, a person, a home path or a chat id.

The scan is the kit's `lab_commons.dev.privatemarkers`; it runs under `make verify` (and so in CI) because verify
runs this suite. The machine-local denylist `~/.claude/private-markers` adds this host's private
values without committing them.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lab_commons.dev.privatemarkers import load_markers, scan_text, scan_tree

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


def test_only_the_declared_authorship_lines_may_name_the_author(tmp_path: Path) -> None:
    """The author is named on purpose in LICENSE and pyproject; the same name anywhere else still reds."""
    markers = tmp_path / 'private-markers'
    markers.write_text('Jane Author\n', encoding='utf-8')
    compiled = load_markers(markers)
    assert scan_text('Copyright (c) 2026 Jane Author', compiled, path='LICENSE') == []
    assert scan_text('authors = [{ name = "Jane Author" }]', compiled, path='pyproject.toml') == []
    assert scan_text('Copyright (c) 2026 Jane Author', compiled, path='README.md')
    assert scan_text('# by Jane Author', compiled, path='pyproject.toml')
    assert scan_text('authors = [{ name = "J", email = "j' + '@uni.ac.uk" }]', (), path='pyproject.toml')


def test_the_apache_appendix_copyright_line_is_an_authorship_line(tmp_path: Path) -> None:
    """Apache-2.0's appendix indents the notice; the shape is the same line, and only in LICENSE."""
    markers = tmp_path / 'private-markers'
    markers.write_text('Jane Author\n', encoding='utf-8')
    compiled = load_markers(markers)
    assert scan_text('   Copyright (c) 2026 Jane Author', compiled, path='LICENSE') == []
    assert scan_text('   Copyright (c) 2026 Jane Author', compiled, path='NOTICE.md')


def test_a_name_the_repo_publishes_on_purpose_is_masked_and_nothing_else_is(tmp_path: Path) -> None:
    """A published repo's OWN name cannot be private to it; a marker inside that name still fires elsewhere."""
    markers = tmp_path / 'private-markers'
    markers.write_text('some\n/other[-_]repo/\nSecretHost\n', encoding='utf-8')
    compiled = load_markers(markers)
    public = ('some-repo', 'other_repo')
    assert scan_text('some-repo and OTHER_REPO', compiled, public=public) == []
    assert scan_text('some-repo by some person', compiled, public=public) == [(1, 'private marker', '<redacted>')]
    assert scan_text('other-repo', compiled, public=public) == [(1, 'private marker', '<redacted>')]


def test_a_home_named_after_a_public_name_is_a_service_account_and_not_a_person() -> None:
    """``/home/<repo>`` is a deploy user named after the published repo; any other home still reds."""
    assert scan_text('cd /' + 'home/some-repo/lib', public=('some-repo',)) == []
    assert scan_text('cd /' + 'home/someone/lib', public=('some-repo',))


def test_a_diff_marker_before_a_decorator_is_not_an_address() -> None:
    """A local part needs a letter or digit first: ``+@pytest.mark`` is a diff line, not an e-mail."""
    assert scan_text('+@pytest' + '.mark.parametrize') == []
    assert scan_text('x+tag@' + 'uni.ac.uk')
