"""AN ISSUE IS A NEED (user ruling 2026-11-14): the kind door and the one notice migration, on a stateful fake."""

from __future__ import annotations

import json

import pytest
from _forge_state import StateForge

from dev_lab.dev import forgecli, issuekind
from dev_lab.dev.forgerequesthost import DONE_LABEL
from dev_lab.dev.issuekind import KINDS, MOVED, SETTLED, create, retire_notices


@pytest.mark.parametrize('kind', KINDS)
def test_an_issue_is_created_labeled_with_its_kind(kind: str) -> None:
    forge = StateForge()
    made = create(forge, 'ask: x', 'body', kind)
    assert forge.labeled == [(made.number, f'kind:{kind}')]


def test_a_kind_outside_the_three_is_refused_before_any_write() -> None:
    """PLANTED CONTROL beside the parametrized pass: the same call with a notice kind writes nothing."""
    forge = StateForge()
    with pytest.raises(ValueError, match='forge issue create --kind'):
        create(forge, 'integration: x', 'body', 'notice')
    assert forge.issues_by_number == {}
    assert forge.labels == []


def test_the_cli_door_refuses_an_issue_without_a_kind_naming_the_three(capsys) -> None:
    parser = forgecli._parser()
    with pytest.raises(SystemExit):
        parser.parse_args(['issue', 'create', '--title', 'x'])
    assert '--kind' in capsys.readouterr().err
    with pytest.raises(SystemExit):
        parser.parse_args(['issue', 'create', '--title', 'x', '--kind', 'notice'])
    err = capsys.readouterr().err  # argparse quotes choices on 3.13, not on 3.12
    assert all(kind in err for kind in ('need', 'defect', 'decision'))
    assert parser.parse_args(['issue', 'create', '--title', 'x', '--kind', 'defect']).kind == 'defect'


def test_create_adds_each_label_creating_a_missing_one() -> None:
    forge = StateForge()
    forge.call('POST', f'{forge.repo}/labels', {'name': 'task:x'})
    made = create(forge, 'ask: x', 'body', 'need', ['task:x', 'rem', 'rem'])
    assert forge.labeled == [(made.number, 'kind:need'), (made.number, 'task:x'), (made.number, 'rem')]
    assert sorted(one['name'] for one in forge.labels) == ['kind:need', 'rem', 'task:x'], 'one each, none twice'


def test_issue_list_by_label_excludes_unlabeled_and_an_unknown_label_lists_nothing() -> None:
    """PLANTED CONTROLS: an unlabeled issue never passes; an unknown label lists nothing, not an error.

    The fake ignores ``labels=`` as Gitea does for a name it lacks, so only the client's own filter can exclude.
    """
    forge = StateForge()
    plain = forge.add_issue('plain')
    tagged = create(forge, 'tagged', '', 'need', ['task:x'])
    assert {one.number for one in forge.issue_list()} == {plain, tagged.number}, 'unfiltered: both'
    assert [one.number for one in forge.issue_list(labels=['task:x'])] == [tagged.number]
    assert [one.number for one in forge.issue_list(labels=['task:x', 'kind:need'])] == [tagged.number]
    assert forge.issue_list(labels=['task:nobody']) == ()
    assert any('labels=task%3Ax' in asked for asked in forge.asked), 'the forge is asked to filter too'


def test_the_cli_lists_by_label_as_json_and_closes_as_json(monkeypatch, capsys, tmp_path) -> None:
    forge = StateForge()
    forge.add_issue('plain')
    tagged = create(forge, 'tagged', '', 'need', ['task:x'])
    monkeypatch.setattr(forgecli, 'client_for', lambda *_a, **_k: forge)
    assert forgecli.issue_and_pr(['issue', 'list', '--label', 'task:x', '--json'], cwd=tmp_path, env={}) == 0
    listed = json.loads(capsys.readouterr().out)
    assert [{k: one[k] for k in ('number', 'url', 'state', 'title')} for one in listed] == [
        {'number': tagged.number, 'url': tagged.url, 'state': 'open', 'title': 'tagged'}
    ]
    assert forgecli.issue_and_pr(['issue', 'list', '--label', 'task:nobody', '--json'], cwd=tmp_path, env={}) == 0
    assert json.loads(capsys.readouterr().out) == []
    assert forgecli.issue_and_pr(['issue', 'close', str(tagged.number), '--json'], cwd=tmp_path, env={}) == 0
    assert json.loads(capsys.readouterr().out)['state'] == 'closed'


def test_the_cli_creates_with_repeated_labels(monkeypatch, tmp_path) -> None:
    forge = StateForge()
    monkeypatch.setattr(forgecli, 'client_for', lambda *_a, **_k: forge)
    monkeypatch.setattr(forgecli, '_refused', lambda *_a: None)  # the private-marker scan is tested elsewhere
    argv = ['issue', 'create', '--title', 't', '--kind', 'need', '--label', 'a', '--label', 'b']
    assert forgecli.issue_and_pr(argv, cwd=tmp_path, env={}) == 0
    assert [name for _n, name in forge.labeled] == ['kind:need', 'a', 'b']


def _seeded() -> tuple[StateForge, dict[str, int]]:
    forge = StateForge()
    numbers = {
        title: forge.add_issue(title, state=state)
        for title, state in (
            ('integration: integrate/main took break-glass #7', 'open'),
            ('starved: o/r tests', 'open'),
            ('integration: pr/old needs a sync', 'closed'),
            ('area: forge route red', 'open'),
            ('ask: decide the bar', 'open'),
        )
    }
    return forge, numbers


def test_the_migration_dry_run_names_the_notices_and_writes_nothing() -> None:
    forge, numbers = _seeded()
    found = retire_notices(forge, apply=False)
    assert sorted(one.number for one in found) == sorted(
        numbers[t] for t in ('integration: integrate/main took break-glass #7', 'starved: o/r tests')
    )
    assert not any(forge.comments.values())
    assert all(
        one['state'] == 'open'
        for n, one in forge.issues_by_number.items()
        if n != numbers['integration: pr/old needs a sync']
    )


def test_the_migration_closes_only_open_notices_each_with_one_pointer() -> None:
    """PLANTED CONTROLS: a defect (``area:``) and a need stay open; an already-closed notice gets no comment."""
    forge, numbers = _seeded()
    retire_notices(forge, apply=True)
    state = {title: forge.issues_by_number[n]['state'] for title, n in numbers.items()}
    assert state == {
        'integration: integrate/main took break-glass #7': 'closed',
        'starved: o/r tests': 'closed',
        'integration: pr/old needs a sync': 'closed',
        'area: forge route red': 'open',
        'ask: decide the bar': 'open',
    }
    commented = {n: [c['body'] for c in cs] for n, cs in forge.comments.items() if cs}
    assert commented == {
        numbers['integration: integrate/main took break-glass #7']: [MOVED],
        numbers['starved: o/r tests']: [MOVED],
    }
    assert 'forge queue' in MOVED


def test_the_migration_verb_defaults_to_a_dry_run(monkeypatch, capsys, tmp_path) -> None:
    forge, _numbers = _seeded()
    monkeypatch.setattr('dev_lab.dev.issuekind.client_for', lambda _root: forge)
    assert issuekind.main(['retire-notices', '--root', str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert out.count('would close #') == 2
    assert 'dry run: pass --apply' in out
    assert not any(forge.comments.values())


def _requests() -> tuple[StateForge, int, int]:
    forge = StateForge()
    done = forge.add_issue('request tests at 0123456789ab', labels=[{'name': 'forge:request'}, {'name': DONE_LABEL}])
    live = forge.add_issue('request tests at abcdef012345', labels=[{'name': 'forge:request'}])
    return forge, done, live


def test_the_migration_closes_a_settled_request_and_keeps_a_live_one() -> None:
    """PLANTED CONTROL: a request no host settled yet is a live need and stays open, uncommented."""
    forge, done, live = _requests()
    found = retire_notices(forge, apply=True)
    assert [one.number for one in found] == [done]
    assert forge.issues_by_number[done]['state'] == 'closed'
    assert [c['body'] for c in forge.comments[done]] == [SETTLED]
    assert forge.issues_by_number[live]['state'] == 'open'
    assert forge.comments[live] == []
    assert 'forge queue' in SETTLED
