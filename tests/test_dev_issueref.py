"""The commit-msg issue-reference check: it WARNS on a malformed reference and never blocks.

The derivation in ``lab_commons.dev.forgeissue`` reads ``Refs #N`` / ``Closes #N`` / ``Fixes #N``
from commit messages. A reference it cannot parse is not an error the commit made, it is a link the
issue will never see -- so the check names it, and the commit goes through either way.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lab_commons.dev.issueref import main, malformed

VALID = (
    'feat: add the thing\n\nRefs #12',
    'fix: x\n\nCloses #3',
    'fix: x\n\nFixes #45',
    'fix: x\n\nrefs #7 and closes #8',
    'docs: no reference at all',
    'chore: see issue #12 for context',
    'fix: x\n\nResolves #9',
    'fix: correct 3 typos in the guide',
    'fix 3 typos',
)

MALFORMED = (
    ('fix: x\n\nRefs#12', 'Refs#12'),
    ('fix: x\n\ncloses 12', 'closes 12'),
    ('fix: x\n\nFixes 4', 'Fixes 4'),
    ('fix: x\n\nRefs #12abc', '#12abc'),
    ('fix: x\n\nsee #12abc', '#12abc'),
    ('fix: x\n\nCloses#3', 'Closes#3'),
    ('fix: x\n\nRefs 12, closes #4', 'Refs 12'),
)


@pytest.mark.parametrize('message', VALID)
def test_a_valid_or_absent_reference_is_not_flagged(message: str) -> None:
    assert malformed(message) == ()


@pytest.mark.parametrize(('message', 'token'), MALFORMED)
def test_each_malformed_form_is_named(message: str, token: str) -> None:
    found = malformed(message)
    assert any(token in item for item in found), found


def test_git_comment_lines_and_the_scissors_tail_are_not_read() -> None:
    scissors = '# ------------------------ >8 ------------------------'
    message = f'fix: x\n\nRefs #1\n# closes 12 is in the template\n{scissors}\nRefs#9\n'
    assert malformed(message) == ()


def test_the_hook_warns_and_still_exits_zero(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    msg = tmp_path / 'COMMIT_EDITMSG'
    msg.write_text('fix: x\n\ncloses 12\n', encoding='utf-8')
    assert main([str(msg)]) == 0
    err = capsys.readouterr().err
    assert 'closes 12' in err
    assert 'Refs #N' in err


def test_a_clean_message_is_silent(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    msg = tmp_path / 'COMMIT_EDITMSG'
    msg.write_text('fix: x\n\nCloses #12\n', encoding='utf-8')
    assert main([str(msg)]) == 0
    assert capsys.readouterr().err == ''


def test_an_unreadable_message_file_never_blocks(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main([str(tmp_path / 'missing')]) == 0
    assert 'could not read' in capsys.readouterr().err
    assert main([]) == 0
