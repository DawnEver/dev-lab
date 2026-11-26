"""``forge secrets list``: the secret NAMES of a repository or its owner org, read through the family door."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from dev_lab.dev import forgesecretnames, forgesecrets
from dev_lab.dev.family.forgefacts import ClientFacts
from dev_lab.dev.forge import Forge
from dev_lab.dev.forgefailure import ForgeCallFailed
from dev_lab.dev.netverb import Attempt, Diagnosis, Report

if TYPE_CHECKING:
    from pathlib import Path


class _Client:
    """The family client's read surface: ``forge``, ``repo`` and ``call``; a path it was not given is refused."""

    def __init__(self, forge: Forge, answers: dict[str, object], repo: str = '') -> None:
        self.forge = forge
        self.repo = repo or f'/api/v1/repos/{forge.owner}/{forge.repo}'
        self.answers = answers
        self.asked: list[tuple[str, str]] = []

    def call(self, method: str, path: str, body: object = None, durable: object = None) -> object:
        del body, durable
        self.asked.append((method, path))
        if path not in self.answers:
            missing = Attempt(1, 404, 'not found', Diagnosis.FORGE_REFUSED)
            raise ForgeCallFailed(Report((method, path), (missing,), 1))
        return self.answers[path]


_TEA = Forge('forge.example', 'team', 'tea')
_TEA_SECRETS = '/api/v1/repos/team/tea/actions/secrets'


def _run(client: _Client, argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    code = forgesecrets.main(['list', *argv], client=lambda _root: client)
    out, err = capsys.readouterr()
    return code, out, err


def test_a_repo_s_secret_names_are_listed_one_per_line(capsys: pytest.CaptureFixture[str]) -> None:
    client = _Client(_TEA, {_TEA_SECRETS: [{'name': 'B_KEY'}, {'name': 'A_KEY'}]})
    code, out, _ = _run(client, [], capsys)
    assert code == 0
    assert out.splitlines() == ['A_KEY', 'B_KEY']
    assert client.asked == [('GET', _TEA_SECRETS)]


def test_the_org_s_names_come_from_the_owner_and_github_s_envelope_is_read(capsys: pytest.CaptureFixture[str]) -> None:
    hub = Forge('github.com', 'team', 'hub')
    client = _Client(hub, {'/orgs/team/actions/secrets': {'total_count': 1, 'secrets': [{'name': 'ORG_KEY'}]}},
                     repo='/repos/team/hub')  # fmt: skip
    code, out, _ = _run(client, ['--org'], capsys)
    assert (code, out.splitlines()) == (0, ['ORG_KEY'])


def test_planted_a_field_beside_the_name_is_never_echoed(capsys: pytest.CaptureFixture[str]) -> None:
    planted = [{'name': 'ONLY_NAME', 'data': 'sk-ant-PLANTED', 'value': 'PLANTED-VALUE', 'created': '2026'}]
    code, out, err = _run(_Client(_TEA, {_TEA_SECRETS: planted}), [], capsys)
    assert (code, out.splitlines()) == (0, ['ONLY_NAME'])
    assert 'PLANTED' not in out + err


def test_an_unread_list_is_refused_never_read_as_empty(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, err = _run(_Client(_TEA, {}), [], capsys)
    assert code == 2
    assert out == ''
    assert 'refused: the secret names of forge.example/team/tea were not read' in err


def test_the_names_reader_takes_either_forge_s_answer() -> None:
    assert forgesecretnames.names([{'name': 'X'}, 'junk', {'no': 1}]) == ('X',)
    assert forgesecretnames.names({'secrets': [{'name': 'Y'}]}) == ('Y',)
    assert forgesecretnames.names(None) == ()


def test_list_needs_no_task_and_reads_the_named_checkout(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    seen: list[Path] = []

    def client(root: Path) -> _Client:
        seen.append(root)
        return _Client(_TEA, {_TEA_SECRETS: []})

    assert forgesecrets.main(['list', '--path', str(tmp_path)], client=client) == 0
    assert seen == [tmp_path]
    assert capsys.readouterr().out == ''


def test_one_read_is_the_one_get_of_the_repo_s_secret_names() -> None:
    client = _Client(_TEA, {_TEA_SECRETS: {'secrets': [{'name': 'B'}, {'name': 'A'}, {'name': ''}]}})
    assert forgesecretnames.read(client, org=False) == ('A', 'B')
    assert client.asked == [('GET', _TEA_SECRETS)]


def test_a_refused_read_raises_and_never_reads_as_holds_none() -> None:
    with pytest.raises(ForgeCallFailed):
        forgesecretnames.read(_Client(_TEA, {}), org=False)


def test_a_member_s_facts_read_their_secret_names_through_the_one_reader() -> None:
    held = ClientFacts(_Client(_TEA, {_TEA_SECRETS: [{'name': 'R'}]}))  # type: ignore[arg-type]
    assert held._secrets() == frozenset({'R'})
    assert held.unread == []
    refused = ClientFacts(_Client(_TEA, {}))  # type: ignore[arg-type]
    assert refused._secrets() == frozenset()
    assert refused.unread[0].startswith('secrets (')  # the planted control: refused is named, never "holds none"
