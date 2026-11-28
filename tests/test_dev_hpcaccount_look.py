"""``hpcaccount look``: a READ-ONLY look at a key-only account, a closed set of reads, no free-form command.

Measured 2026-11-23: a hung tick on a key-only account could not be seen at all.
"""

from __future__ import annotations

import re
from types import SimpleNamespace

import pytest

from dev_lab.dev.hpcaccount import look
from dev_lab.dev.hpcaccount.fleet import Target

ROOT = '/scratch/u1/lab'


@pytest.mark.parametrize(('what', 'repo', 'wanted'), [
    ('processes', '', 'ps -u "$(id -un)"'),
    ('ticks', '', f'cd {ROOT}/serve'),
    ('log', '', f'tail -n {look.LOG_LINES} {ROOT}/serve/tick.log'),
    ('crontab', '', 'crontab -l'),
    ('stuck', 'ci/experiments/x', 'p="$HOME"/ci/experiments/x'),
])  # fmt: skip
def test_each_read_is_a_fixed_line(what: str, repo: str, wanted: str) -> None:
    assert wanted in look.command_of(what, repo, ROOT)


@pytest.mark.parametrize(('what', 'repo'), [
    ('rm', ''), ('run', ''), ('kill', ''), ('crontab -r', ''), ('log', 'alpha'),
    ('log', 'a;rm -rf ~'), ('ticks', 'alpha'), ('stuck', ''), ('stuck', '../etc'),
    ('stuck', 'ci/../../x'), ('stuck', '/etc'), ('stuck', 'ci/$(rm -rf ~)'), ('stuck', 'a b'),
])  # fmt: skip
def test_a_write_shaped_request_is_refused_naming_the_reads(what: str, repo: str) -> None:
    with pytest.raises(ValueError, match=r'^look: '):
        look.command_of(what, repo, ROOT)


def _fleet(monkeypatch: pytest.MonkeyPatch, ran: list[str]) -> dict[str, object]:
    grant = SimpleNamespace(user='u1')
    monkeypatch.setattr(look, 'reached_machine', lambda _users: SimpleNamespace(grants=[grant]))
    monkeypatch.setattr(look, 'declared_target', lambda _g, _shell: Target('login1', ROOT))

    def runner(command: str, _stdin: str | None) -> str:
        ran.append(command)
        return '== alpha.lock\n{"pid": 4242}\n'

    return {'connect': lambda _g: runner, 'pin': lambda _g, _host: runner}


def test_a_read_returns_what_the_account_printed(monkeypatch: pytest.MonkeyPatch) -> None:
    ran: list[str] = []
    said: list[str] = []
    assert look.look('u1', 'ticks', say=said.append, **_fleet(monkeypatch, ran)) == 0
    assert ran == [look.command_of('ticks', '', ROOT)]
    assert said == ['u1@login1: ticks', '== alpha.lock', '{"pid": 4242}']


def test_planted_control_a_refused_read_reaches_no_account(monkeypatch: pytest.MonkeyPatch) -> None:
    ran: list[str] = []
    said: list[str] = []
    assert look.look('u1', 'rm', say=said.append, **_fleet(monkeypatch, ran)) == 2
    assert ran == []
    assert 'there is no free-form command' in said[0]


def test_stuck_reads_owner_mode_attrs_acls_and_every_ancestor() -> None:
    line = look.command_of('stuck', 'ci/experiments/x', ROOT)
    for read in ('id', 'stat -f', 'ls -ld "$d"', 'lsattr -d "$d"', '%u', '! -perm -u+w', 'getfacl'):
        assert read in line
    assert not re.search(r'(?<![\w-])(rm|chmod|chown|mv|setfacl|truncate)\b| > |>>', line)


_WRITES = re.compile(r'(?<![\w-])(rm|chmod|chown|mv|setfacl|truncate|crontab|module (purge|save|unload))\b| > |>>')


def test_modules_sends_exactly_the_module_query_and_lists_names(monkeypatch: pytest.MonkeyPatch) -> None:
    ran: list[str] = []
    said: list[str] = []
    fleet = _fleet(monkeypatch, ran)
    listing = '/opt/modulefiles/apps:\nansys/2023R2\nansys/2024R1\n\n'
    fleet['pin'] = lambda _g, _host: lambda command, _stdin: ran.append(command) or listing
    assert look.look('u1', 'modules', 'ansys', say=said.append, **fleet) == 0
    assert ran == [look.modules_command('ansys')]
    assert 'module -t avail ansys' in ran[0]
    assert 'module -t spider ansys' in ran[0]
    assert not _WRITES.search(ran[0])
    assert said == ['u1@login1: modules ansys', 'ansys/2023R2', 'ansys/2024R1']


def test_where_loads_in_its_own_shell_and_reads_the_path() -> None:
    line = look.command_of('where', 'ansys/2024R1 ansysedt', ROOT)
    for read in ('module load ansys/2024R1', 'module -t list', 'command -v ansysedt', 'readlink -f'):
        assert read in line
    assert not _WRITES.search(line)


def test_planted_control_the_write_pattern_catches_a_write() -> None:
    assert _WRITES.search('module purge; rm -rf x')


@pytest.mark.parametrize(('what', 'arg'), [
    ('modules', 'a;rm -rf ~'), ('modules', '../x'), ('modules', '$(id)'), ('where', 'ansys'),
    ('where', 'ansys a;b'), ('where', 'a`id` ansysedt'), ('where', ''),
])  # fmt: skip
def test_a_shell_shaped_module_request_is_refused(what: str, arg: str) -> None:
    with pytest.raises(ValueError, match=r'^look: '):
        look.command_of(what, arg, ROOT)


def test_a_stale_kit_schema_refusal_names_its_door(monkeypatch: pytest.MonkeyPatch) -> None:
    said: list[str] = []

    def stale(_users: object) -> object:
        msg = "[hpc] has unknown keys ['cluster_reach']; known: ['accounts']"
        raise ValueError(msg)

    monkeypatch.setattr(look, 'reached_machine', stale)
    assert look.look('u1', 'modules', say=said.append, connect=lambda _g: None) == 2
    assert 'dev_lab.dev.dep --sync' in said[0]
    assert 'cluster_reach' in said[0]


def test_planted_control_an_ordinary_refusal_names_no_kit_door(monkeypatch: pytest.MonkeyPatch) -> None:
    said: list[str] = []

    def other(_users: object) -> object:
        msg = 'no such account'
        raise LookupError(msg)

    monkeypatch.setattr(look, 'reached_machine', other)
    assert look.look('u1', 'modules', say=said.append, connect=lambda _g: None) == 2
    assert 'dep --sync' not in said[0]
