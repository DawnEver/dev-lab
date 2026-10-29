"""PARTS FROM WORKFLOW JOBS: the matrix a workflow fans out over, the absent parts, and the Actions token."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from _forge_fake import make_repo
from _forge_state import StateForge

from dev_lab.dev import jobparts, platformparts
from dev_lab.dev.forge import NoCredential
from dev_lab.dev.forgestatus import status_list
from dev_lab.dev.forgework import ACTIONS_BOT, client_for

SHA = 'b' * 40

PYPROJECT = """
[tool.lab_commons.tests]
resources = ["femm", "windows"]
"""


@pytest.mark.parametrize(
    ('part', 'runs_on'),
    [
        ('base', 'ubuntu-latest'),
        ('windows', 'windows-latest'),
        ('linux', 'ubuntu-latest'),
        ('macos', 'macos-latest'),
        ('femm+windows', ['self-hosted', 'femm', 'windows']),
        ('femm', ['self-hosted', 'femm']),
    ],
)
def test_a_part_runs_on_a_hosted_runner_only_when_it_needs_no_more_than_an_os(part: str, runs_on: object) -> None:
    assert jobparts.runner_for(part) == runs_on


def test_the_matrix_is_every_need_set_the_collection_derives_and_base_always(tmp_path: Path) -> None:
    (tmp_path / 'pyproject.toml').write_text(PYPROJECT, encoding='utf-8')
    carrying = {'': ['t::a', 't::w', 't::fw'], 'femm': ['t::fw'], 'windows': ['t::w', 't::fw']}
    found = jobparts.matrix(tmp_path, collect=lambda expression: carrying[expression])
    assert found == {
        'include': [
            {'part': 'base', 'runs-on': 'ubuntu-latest'},
            {'part': 'femm+windows', 'runs-on': ['self-hosted', 'femm', 'windows']},
            {'part': 'windows', 'runs-on': 'windows-latest'},
        ]
    }
    nothing = jobparts.matrix(tmp_path, collect=lambda _expression: [])
    assert nothing == {'include': [{'part': 'base', 'runs-on': 'ubuntu-latest'}]}, 'base is always wanted'


def test_the_matrix_command_prints_json_a_workflow_reads_with_fromjson(tmp_path: Path, monkeypatch, capsys) -> None:
    (tmp_path / 'pyproject.toml').write_text(PYPROJECT, encoding='utf-8')
    monkeypatch.setattr(jobparts, 'pytest_collector', lambda _root: lambda expression: [] if expression else ['t::a'])
    assert jobparts.main(['matrix', '--root', str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out) == {'include': [{'part': 'base', 'runs-on': 'ubuntu-latest'}]}


def test_every_expected_part_with_no_settled_status_is_posted_a_failure_and_a_settled_one_is_left() -> None:
    forge = StateForge()
    for context, state in (('tests/base', 'success'), ('tests/windows', 'pending')):
        forge.call(
            'POST',
            f'{forge.repo}/statuses/{SHA}',
            {'context': context, 'state': state, 'description': 'scope=full ran=1 hands=-'},
        )
    matrix = {'include': [{'part': name, 'runs-on': 'x'} for name in ('base', 'windows', 'femm+windows')]}
    said = jobparts.absent(forge, SHA, matrix)
    latest = {status.context: status.state for status in status_list(forge, SHA)}
    assert latest == {'tests/base': 'success', 'tests/windows': 'failure', 'tests/femm+windows': 'failure'}
    assert [line.split(':')[0] for line in said] == ['tests/femm+windows', 'tests/windows']
    parts, problems = platformparts.parts_of(status_list(forge, SHA))
    assert set(parts) == {'base'}, 'an absent part is never read as a settled part'
    assert len(problems) == 2


def test_inside_github_actions_the_job_token_is_the_credential_on_github_only(tmp_path: Path) -> None:
    """PLANTED CONTROL: the same variables outside Actions, or on a gitea remote, are never read."""
    empty = tmp_path / 'empty-gitconfig'
    empty.write_text('[credential]\n\thelper = "!f() { :; }; f"\n', encoding='utf-8')
    store = {'GIT_CONFIG_GLOBAL': str(empty), 'GIT_CONFIG_SYSTEM': str(tmp_path / 'absent')}
    actions = {**store, 'GITHUB_ACTIONS': 'true', 'GITHUB_TOKEN': 'job-token'}
    (tmp_path / 'hub').mkdir()
    (tmp_path / 'tea').mkdir()
    hub = make_repo(tmp_path / 'hub', 'https://github.com/o/r.git')
    client = client_for(hub, env=actions)
    assert (client.token, client.refresh) == ('job-token', None)
    assert client.whoami() == ACTIONS_BOT, 'an installation token cannot read /user; the bot is who it writes as'
    with pytest.raises(NoCredential):
        client_for(hub, env={**store, 'GITHUB_TOKEN': 'job-token'})
    with pytest.raises(NoCredential):
        client_for(make_repo(tmp_path / 'tea', 'https://forge.example.org/o/r.git'), env=actions)


def test_hosted_keeps_only_the_parts_a_hosted_runner_produces(tmp_path: Path) -> None:
    (tmp_path / 'pyproject.toml').write_text(PYPROJECT, encoding='utf-8')
    carrying = {'': ['t::a', 't::fw'], 'femm': ['t::fw'], 'windows': ['t::fw']}
    found = jobparts.matrix(tmp_path, collect=lambda expression: carrying[expression], hosted=True)
    assert found == {'include': [{'part': 'base', 'runs-on': 'ubuntu-latest'}]}
