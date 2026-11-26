"""A forge write refused for a private marker names its rule and its door, and the walls ledger records both.

Measured 2026-11-17: ``forge pr create`` refused a body naming a private value as ``[forge] PRIVATE-MARKERS: ...;
rewrite the text neutrally ... and re-run.`` and the ledger recorded rule ``unknown`` with ``remedy_present: false``:
the ``[forge]`` prefix hid the rule id from :func:`walls.rule_of` and the door shared the cause's line, so
:func:`walls.has_remedy` saw none. The fix is the shape forge sync took: ``PRIVATE-MARKERS: <cause>``, ``Door: ...``
on a line of its own, recorded through :func:`walls.refused_text`. Fixture markers are invented names only.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path

import pytest
from _forge_fake import run_git

from dev_lab.dev import privatemarkers, walls
from dev_lab.dev.forgecli import issue_and_pr
from dev_lab.dev.forgehosts import public_siblings
from dev_lab.dev.privatemarkers import main

_MARKERS = (re.compile('zorblaxhost', re.IGNORECASE),)


def test_the_refusal_leads_with_its_rule_and_puts_its_door_on_a_line_of_its_own() -> None:
    text = privatemarkers.text_refusal('ran on zorblaxhost', 'PR body', _MARKERS)
    assert text is not None
    lines = text.splitlines()
    assert lines[0].startswith('PRIVATE-MARKERS: '), text
    assert lines[1].startswith('Door: '), text
    assert "'zorblaxhost'" in text, 'the refusal names the token that tripped it'
    assert '/zorblaxhost/' in text, 'and the declared entry it matched'
    assert walls.rule_of(text) == 'PRIVATE-MARKERS'
    assert walls.has_remedy(text)
    assert not walls.has_remedy(' '.join(lines[:2])), 'PLANTED CONTROL: folded onto one line, no door'


def test_a_clean_body_is_not_refused() -> None:
    assert privatemarkers.text_refusal('ran on a build host', 'PR body', _MARKERS) is None


def test_the_create_door_records_the_wall_with_its_rule_and_a_door(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run_git(tmp_path, 'init', '-q')
    denylist = tmp_path / 'private-markers'
    denylist.write_text('ZorblaxHost\n', encoding='utf-8')
    monkeypatch.setattr(privatemarkers, 'MARKERS_FILE', denylist)
    argv = ['pr', 'create', '--title', 't', '--body', 'ran on zorblaxhost', '--head', 'x', '--base', 'y']
    assert issue_and_pr(argv, cwd=tmp_path, env={}) == 1
    err = capsys.readouterr().err
    lines = err.splitlines()
    assert any(line.startswith('PRIVATE-MARKERS: ') for line in lines), err
    assert not any(line.startswith('[forge] PRIVATE-MARKERS') for line in lines), err
    rows = [json.loads(line) for line in walls.ledger(tmp_path).read_text(encoding='utf-8').splitlines()]
    assert [(row['rule'], row['remedy_present']) for row in rows] == [('PRIVATE-MARKERS', True)]


def test_a_public_sibling_named_in_the_text_is_not_a_private_marker() -> None:
    """A public sibling named in a public text is not a private marker (dev-lab#791 wall 3).

    A PR title naming a public sibling repo was refused: the machine denylist names every family repo and the TEXT
    scans masked no public name. PLANTED CONTROLS: the same entry, not published, still refuses; a private value
    beside the public name on the same line still refuses.
    """
    markers = (re.compile('zorblax-lab', re.IGNORECASE), re.compile('quuxhost', re.IGNORECASE))
    assert privatemarkers.text_refusal('relock zorblax-lab', 'PR title', markers, public=('zorblax-lab',)) is None
    assert privatemarkers.text_refusal('relock zorblax-lab', 'PR title', markers) is not None
    assert (
        privatemarkers.text_refusal('relock zorblax-lab on quuxhost', 'PR title', markers, public=('zorblax-lab',))
        is not None
    )


class _Owner:
    """A forge client whose owner publishes two repos and keeps one private."""

    repo = '/repos/someone/zorblax-lab'

    def __init__(self) -> None:
        self.paths: list[str] = []

    def call(self, method: str, path: str) -> object:
        self.paths.append(path)
        return [
            {'name': 'zorblax-lab', 'private': False},
            {'name': 'flimflam-lab', 'private': False},
            {'name': 'secret-lab', 'private': True},
        ]


def test_the_public_siblings_are_the_owners_repos_the_forge_says_are_public() -> None:
    client = _Owner()
    assert public_siblings(client) == ('zorblax-lab', 'flimflam-lab')
    assert client.paths
    assert client.paths[0].startswith('/users/someone/repos')


# The walls of 2026-11-26: a commit message naming a PUBLIC family repo was refused (the message scans masked no
# public name), the refusal named neither the token nor its set, and a one-letter host trailer passed unseen.
# Fixture names are invented; the denylist entries mirror the real kinds (a host, a product, a public sibling).
_DENYLIST = 'quuxhost\nzorblax-lab\nsecret-lab\n'
_PUBLIC = ('zorblax-lab', 'flimflam-lab')


@pytest.fixture
def judged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> Callable[[str], tuple[int, str]]:
    """Judge a commit message with the commit-msg row; ``(exit code, stderr)``. The forge says: public, two siblings."""
    denylist = tmp_path / 'private-markers'
    denylist.write_text(_DENYLIST, encoding='utf-8')
    monkeypatch.setattr(privatemarkers, 'repo_is_private', lambda *_, **__: (False, ''))
    monkeypatch.setattr(privatemarkers, 'public_names', lambda *_, **__: _PUBLIC)

    def judge(message: str) -> tuple[int, str]:
        msg = tmp_path / 'COMMIT_EDITMSG'
        msg.write_text(message, encoding='utf-8')
        code = main(['--root', str(tmp_path), '--markers', str(denylist), '--commit-msg-file', str(msg)])
        return code, capsys.readouterr().err

    return judge


def test_a_commit_message_naming_a_public_sibling_is_not_refused(judged: Callable[[str], tuple[int, str]]) -> None:
    assert judged('fix(dep): relock zorblax-lab and flimflam-lab\n') == (0, '')


@pytest.mark.parametrize(
    ('message', 'token', 'declared'),
    [
        ('ran on quuxhost\n', "'quuxhost'", '/quuxhost/'),
        ('port secret-lab next\n', "'secret-lab'", r'/secret\-lab/'),
        ('see C:' + r'\Users\someone\repo' + '\n', 'someone', 'windows home path'),
        ('fix: x\n\nForge-Host: G\n', 'Forge-Host: G', 'one-letter host trailer'),
    ],
)
def test_a_commit_message_naming_a_private_value_is_refused_and_names_it(
    judged: Callable[[str], tuple[int, str]], message: str, token: str, declared: str
) -> None:
    """PLANTED CONTROLS: a host, a private product, a private path and a one-letter host trailer each refuse.

    The refusal names the token and the declared set (a denylist entry or a generic kind) it matched.
    """
    code, err = judged(message)
    assert code == 1, err
    assert token in err, err
    assert declared in err, err


def test_a_public_name_beside_a_private_one_still_refuses(judged: Callable[[str], tuple[int, str]]) -> None:
    code, err = judged('relock zorblax-lab on quuxhost\n')
    assert code == 1
    assert 'quuxhost' in err
    assert 'zorblax-lab' not in err


def test_a_hashed_host_trailer_passes(judged: Callable[[str], tuple[int, str]]) -> None:
    assert judged('fix: x\n\nForge-Host: host-0123456789ab\n') == (0, '')
