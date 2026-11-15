"""AN ISSUE IS A NEED (user ruling 2026-11-14): the kind door and the one notice migration, on a stateful fake."""

from __future__ import annotations

import pytest
from _forge_state import StateForge

from dev_lab.dev import forgecli, issuekind
from dev_lab.dev.issuekind import KINDS, MOVED, create, retire_notices


@pytest.mark.parametrize('kind', KINDS)
def test_an_issue_is_created_labelled_with_its_kind(kind: str) -> None:
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
    assert "'need', 'defect', 'decision'" in capsys.readouterr().err
    assert parser.parse_args(['issue', 'create', '--title', 'x', '--kind', 'defect']).kind == 'defect'


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
    monkeypatch.setattr('dev_lab.dev.forgework.client_for', lambda _root: forge)
    assert issuekind.main(['retire-notices', '--root', str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert out.count('would close #') == 2
    assert 'dry run: pass --apply' in out
    assert not any(forge.comments.values())
