"""PARTS FROM WORKFLOW JOBS: the matrix a workflow fans out over, the absent parts, and the Actions token."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from _forge_fake import make_repo
from _forge_state import StateForge

from dev_lab.dev import jobparts, localpart, partrows, platformparts
from dev_lab.dev.forge import NoCredential
from dev_lab.dev.forgestatus import status_list
from dev_lab.dev.forgework import ACTIONS_BOT, client_for
from dev_lab.dev.producer import full_suite_refusal

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
    found = jobparts.matrix(tmp_path, collect=lambda expression: carrying[expression], event='pull_request')
    assert found == {
        'include': [
            {'part': 'base', 'runs-on': 'ubuntu-latest'},
            {'part': 'base@windows', 'runs-on': 'windows-latest'},
            {'part': 'femm+windows', 'runs-on': ['self-hosted', 'femm', 'windows']},
            {'part': 'windows', 'runs-on': 'windows-latest'},
        ]
    }
    nothing = jobparts.matrix(tmp_path, collect=lambda _expression: [], event='pull_request')
    assert [row['part'] for row in nothing['include']] == ['base', 'base@windows'], 'base is always wanted'


@pytest.mark.parametrize(
    ('event', 'rows'),
    [
        ('pull_request', ['base', 'base@windows', 'macos', 'windows']),
        ('push', ['base', 'base@macos', 'base@windows', 'macos', 'windows']),
        ('workflow_dispatch', ['base', 'base@macos', 'base@windows', 'macos', 'windows']),
    ],
)
def test_an_os_free_part_runs_on_every_os_of_the_event_and_an_os_part_keeps_its_one_os(
    tmp_path: Path, event: str, rows: list[str]
) -> None:
    """D84: a pull request runs linux + windows; a push to integration (or a dispatch) adds macos."""
    declared = '[tool.lab_commons.tests]\nresources = ["macos", "windows"]\n'
    (tmp_path / 'pyproject.toml').write_text(declared, encoding='utf-8')
    carrying = {'': ['t::a', 't::m', 't::w'], 'macos': ['t::m'], 'windows': ['t::w']}
    found = jobparts.matrix(tmp_path, collect=lambda expression: carrying[expression], event=event, hosted=True)
    assert [row['part'] for row in found['include']] == rows
    runner = {row['part']: row['runs-on'] for row in found['include']}
    assert (runner['macos'], runner['windows']) == ('macos-latest', 'windows-latest'), 'an OS part keeps its OS'
    expected = {jobparts.HOSTED_RUNNERS[system] for system in jobparts.systems_for(event)}
    assert {runner[row] for row in rows if row.startswith('base')} == expected


def test_a_row_of_another_os_is_refused_here(tmp_path: Path) -> None:
    (tmp_path / 'pyproject.toml').write_text(PYPROJECT, encoding='utf-8')
    here = partrows.this_platform()
    elsewhere = next(system for system in ('linux', 'windows') if system != here)
    assert localpart.part_selection(tmp_path, f'base@{here}') == localpart.part_selection(tmp_path, 'base')
    with pytest.raises(ValueError, match=f'base@{elsewhere} is the {elsewhere} row of base'):
        localpart.part_selection(tmp_path, f'base@{elsewhere}')


def test_the_matrix_command_prints_json_a_workflow_reads_with_fromjson(tmp_path: Path, monkeypatch, capsys) -> None:
    (tmp_path / 'pyproject.toml').write_text(PYPROJECT, encoding='utf-8')
    monkeypatch.setattr(jobparts, 'pytest_collector', lambda _root: lambda expression: [] if expression else ['t::a'])
    assert jobparts.main(['matrix', '--root', str(tmp_path), '--event', 'pull_request']) == 0
    assert json.loads(capsys.readouterr().out) == {
        'include': [{'part': 'base', 'runs-on': 'ubuntu-latest'}, {'part': 'base@windows', 'runs-on': 'windows-latest'}]
    }


def test_every_expected_part_with_no_settled_status_is_posted_a_failure_and_a_settled_one_is_left() -> None:
    forge = StateForge()
    for context, state in (('tests/base', 'success'), ('tests/windows', 'pending')):
        forge.call(
            'POST',
            f'{forge.repo}/statuses/{SHA}',
            {'context': context, 'state': state, 'description': 'scope=full ran=1 hands=-'},
        )
    forge.call(
        'POST',
        f'{forge.repo}/statuses/{SHA}',
        {'context': 'tests/base@macos', 'state': 'success', 'description': 'scope=full ran=1 hands=-'},
    )
    rows = ('base', 'base@macos', 'base@windows', 'windows', 'femm+windows')
    said = jobparts.absent(forge, SHA, {'include': [{'part': name, 'runs-on': 'x'} for name in rows]})
    latest = {status.context: status.state for status in status_list(forge, SHA)}
    assert latest == {
        'tests/base': 'success',
        'tests/base@macos': 'success',
        'tests/base@windows': 'failure',
        'tests/windows': 'failure',
        'tests/femm+windows': 'failure',
    }
    assert [line.split(':')[0] for line in said] == ['tests/base@windows', 'tests/femm+windows', 'tests/windows']
    parts, problems = platformparts.parts_of(status_list(forge, SHA))
    assert set(parts) == {'base', 'base@macos'}, 'an absent row is never read as a settled part; a settled one is'
    assert len(problems) == 3
    judged = platformparts.standing(status_list(forge, SHA), head=SHA)
    assert judged.result.name == 'INCONCLUSIVE', 'promote reads every row absent judged'


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
    found = jobparts.matrix(tmp_path, collect=lambda expression: carrying[expression], event='push', hosted=True)
    assert [row['part'] for row in found['include']] == ['base', 'base@macos', 'base@windows']


@pytest.mark.parametrize(('row', 'other'), [('base', 'femm'), ('base@windows', 'base'), ('base@macos', 'base@windows')])
def test_produce_hands_the_row_the_producing_marker_of_its_own_context_at_sha(
    tmp_path: Path, monkeypatch, row: str, other: str
) -> None:
    """An OS-qualified row (``base@windows``) is admitted under the context verify checks; another row is not."""
    sha = 'a' * 40
    seen: dict[str, object] = {}

    def run(argv: list[str], **kwargs: object) -> SimpleNamespace:
        if argv[:2] == ['git', 'rev-parse']:
            return SimpleNamespace(stdout=f'{sha}\n', returncode=0)
        seen.update(kwargs)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(jobparts._door, 'run', run)
    monkeypatch.setattr(jobparts, 'producer_argv', lambda _root, part, *, sha: ['-m', 'x', part, sha])
    assert jobparts.produce(tmp_path, row) == 0
    env = seen['env']
    assert full_suite_refusal('verify', env, platformparts.part_context(row)) is None
    assert full_suite_refusal('verify', env, platformparts.part_context(other)) is not None, 'planted control'
