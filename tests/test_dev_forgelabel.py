"""``forge label create`` -- one label through the family door, against a REAL loopback server.

The evidence is what the server recorded. Both forges share one table of cases: the verb and its answer are the
same, only the colour spelling differs (Gitea takes ``#rrggbb``, GitHub ``rrggbb``).
"""

from __future__ import annotations

from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
from _forge_fake import Loopback as _Loopback
from _forge_fake import Recorder as _Recorder
from _forge_fake import answer as _answer
from _forge_fake import client as _client
from _forge_fake import credential_env, serve
from _forge_fake import make_repo as _repo

from dev_lab.dev import forgecli, forgelabel
from dev_lab.dev.forge import Forge
from dev_lab.dev.forgelabel import label_create


@pytest.fixture
def server() -> Iterator[ThreadingHTTPServer]:
    yield from serve()


CASES = (
    pytest.param(Forge('forge.example.org', 'o', 'r'), '/api/v1/repos/o/r', 'limit', '#d93f0b', id='gitea'),
    pytest.param(Forge('github.com', 'o', 'r'), '/repos/o/r', 'per_page', 'd93f0b', id='github'),
)


@pytest.mark.parametrize(('forge', 'root', 'page', 'color'), CASES)
def test_a_new_label_is_created_in_the_forges_own_colour_spelling(server, forge, root, page, color) -> None:
    _answer('GET', f'{root}/labels?{page}=100', (200, [{'name': 'bug', 'color': 'ee0701'}]))
    _answer('POST', f'{root}/labels', (201, {'name': 'needs-consent', 'color': color}))
    said = label_create(_client(forge, _Loopback(server)), 'needs-consent', '#D93F0B', 'apply needs consent')
    assert said == 'needs-consent: created'
    assert _Recorder.received[-1]['body'] == {
        'name': 'needs-consent', 'color': color, 'description': 'apply needs consent',
    }  # fmt: skip


@pytest.mark.parametrize(('forge', 'root', 'page', 'color'), CASES)
def test_a_label_already_there_is_reported_present_and_nothing_is_written(server, forge, root, page, color) -> None:
    _answer('GET', f'{root}/labels?{page}=100', (200, [{'name': 'Needs-Consent', 'color': color}]))
    said = label_create(_client(forge, _Loopback(server)), 'needs-consent', 'd93f0b', '')
    assert said == 'needs-consent: already present'
    assert [r['method'] for r in _Recorder.received] == ['GET'], 'an existing label is never re-posted'


@pytest.mark.parametrize('bad', ['red', '#12345', 'gggggg', ''])
def test_a_colour_that_is_not_six_hex_digits_is_refused_before_any_call(server, bad) -> None:
    with pytest.raises(ValueError, match='six hex digits'):
        label_create(_client(Forge('github.com', 'o', 'r'), _Loopback(server)), 'x', bad, '')
    assert _Recorder.received == []


def test_the_cli_door_routes_label_create_and_a_bad_colour_exits_nonzero(server, tmp_path: Path, capsys) -> None:
    repo = _repo(tmp_path, 'https://f.example/o/r.git')
    _answer('GET', '/api/v1/repos/o/r/labels?limit=100', (200, []))
    _answer('POST', '/api/v1/repos/o/r/labels', (201, {'name': 'n'}))
    argv = ['create', '--name', 'n', '--color', '00ff00']
    env, transport = credential_env(tmp_path), _Loopback(server)

    assert forgelabel.main(argv, cwd=repo, env=env, transport=transport) == 0
    assert capsys.readouterr().out.strip() == 'n: created'
    assert forgelabel.main([*argv[:-1], 'green'], cwd=repo, env=env, transport=transport) == 1
    assert 'six hex digits' in capsys.readouterr().err
    assert forgecli.NOUNS['label'] is forgelabel.main, 'the forge door routes the label noun here'
