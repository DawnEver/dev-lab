"""FAMILY-REPO-IS-CHECKED-OUT: [repos] listed, compared with the family's repos, a duplicate clone refused."""

from __future__ import annotations

import io
import os
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
from lab_commons.config import config_path
from lab_commons.home import HOME_ENV

from dev_lab.dev import agenthooks, familyrepos
from dev_lab.dev.hook_adoption import HookAdoption, render
from dev_lab.dev.hooks import DENY_RULES, denies, rules_by_id

ROW = rules_by_id(DENY_RULES)[familyrepos.RULE_ID]


def _live(tmp_path: Path, *, extra: str = '') -> dict:
    present = tmp_path / 'checkouts' / 'alpha'
    present.mkdir(parents=True)
    return tomllib.loads(
        '[family_repos]\n'
        'alpha = { remote = "https://forge.example/o/alpha.git", branch = "integrate/main" }\n'
        'beta = { remote = "git@forge.example:o/beta.git", branch = "main" }\n'
        'gamma = { remote = "https://forge.example/o/gamma.git", branch = "main" }\n\n'
        '[repos]\n'
        f'alpha = "{present.as_posix()}"\n'
        f'beta = "{(tmp_path / "gone").as_posix()}"\n' + extra
    )


def test_the_listing_names_every_path_and_marks_a_missing_one(tmp_path: Path) -> None:
    lines = familyrepos.listing(_live(tmp_path))
    assert lines == [
        f'repo alpha -> {(tmp_path / "checkouts" / "alpha").as_posix()}',
        f'repo beta -> {(tmp_path / "gone").as_posix()} MISSING',
    ]


def test_the_census_names_a_family_repo_without_a_path_and_a_path_for_no_family_repo(tmp_path: Path) -> None:
    found = familyrepos.census(_live(tmp_path, extra='stray = "/x/stray"\n'))
    assert len(found) == 2, found
    assert found[0].startswith('family repo gamma has no [repos] path')
    assert 'devhost local set repos.<name>' in found[0]
    assert 'https://forge.example/o/gamma.git' in found[0]
    assert found[1].startswith('[repos] stray is not a family repo')
    assert 'devhost local unset repos.stray' in found[1]


def test_the_census_is_silent_when_every_family_repo_has_a_path_or_no_family_is_declared(tmp_path: Path) -> None:
    live = _live(tmp_path, extra='gamma = "/x/gamma"\n')
    assert familyrepos.census(live) == []
    assert familyrepos.census({'repos': {'only': '/x'}}) == []


@pytest.mark.parametrize(
    'command',
    [
        'git clone https://forge.example/o/alpha.git',
        'git clone https://forge.example/o/alpha ../alpha-2',
        'git clone HTTPS://Forge.Example/o/alpha.git/',
        'sh scripts/hooks/with-retry.sh clone ssh://git@forge.example/o/beta.git x',
        'git clone git@forge.example:o/beta.git',
    ],
)
def test_a_clone_of_a_checked_out_family_repo_is_refused_naming_the_path(tmp_path: Path, command: str) -> None:
    live = _live(tmp_path)
    refused = familyrepos.clone_refusal(command, live)
    assert refused is not None
    assert refused.startswith(f'{familyrepos.RULE_ID}:')
    name = 'alpha' if 'alpha' in command.lower() else 'beta'
    assert f'{name} is already checked out at {live["repos"][name]}' in refused


@pytest.mark.parametrize(
    'command',
    [
        'git clone https://forge.example/o/undeclared.git',  # PLANTED CONTROL: no family repo has this remote
        'git clone https://forge.example/o/gamma.git',  # a family repo with no path yet: cloning it is the remedy
        'git clone https://other.example/o/alpha.git',  # the same name on another forge is another repo
    ],
)
def test_a_clone_of_anything_else_passes(tmp_path: Path, command: str) -> None:
    assert familyrepos.clone_refusal(command, _live(tmp_path)) is None


def test_the_clone_check_cli_exits_one_with_the_refusal(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    machine = tmp_path / 'm.toml'
    live = _live(tmp_path)
    machine.write_text(
        '[family_repos]\nalpha = { remote = "https://forge.example/o/alpha.git", branch = "main" }\n\n'
        f'[repos]\nalpha = "{live["repos"]["alpha"]}"\n',
        encoding='utf-8',
    )
    argv = ['--machine', str(machine), 'clone-check']
    assert familyrepos.main(argv, stdin=io.StringIO('git clone https://forge.example/o/alpha.git')) == 1
    assert capsys.readouterr().out.startswith(f'{familyrepos.RULE_ID}:')
    assert familyrepos.main(argv, stdin=io.StringIO('git clone https://forge.example/o/new.git')) == 0


def test_the_row_binds_only_when_the_repo_is_declared() -> None:
    command = 'git clone https://forge.example/o/declared.git'
    assert denies([ROW], command) is None
    assert denies([ROW], command, declared=True) == familyrepos.RULE_ID
    assert denies([ROW], 'git log -1', declared=True) is None


def _junction(link: Path, target: Path) -> None:
    if os.name == 'nt':
        shell = os.environ.get('COMSPEC', 'cmd.exe')
        subprocess.run([shell, '/c', 'mklink', '/J', str(link), str(target)], check=True, capture_output=True)
    else:
        link.symlink_to(target, target_is_directory=True)


def _checkout(root: Path) -> Path:
    (root / '.git').mkdir(parents=True)
    return root


def test_the_real_engine_refuses_a_declared_clone_and_passes_an_undeclared_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PLANTED BOTH WAYS through the locked Node and this interpreter, the machine file a tmp one."""
    monkeypatch.setenv(HOME_ENV, str(tmp_path / 'home'))
    config_path().parent.mkdir(parents=True, exist_ok=True)
    alpha = _checkout(tmp_path / 'alpha')
    config_path().write_text(
        '[family_repos]\nalpha = { remote = "https://forge.example/o/alpha.git", branch = "main" }\n\n'
        f'[repos]\nalpha = "{alpha.as_posix()}"\n',
        encoding='utf-8',
    )
    session = _checkout(tmp_path / 'session')
    _junction(session / '.venv', Path(sys.prefix))  # the session's interpreter is this one, its kit included
    hooks = session / '.claude' / 'hooks'
    hooks.mkdir(parents=True)
    needing = frozenset(rule.id for rule in DENY_RULES if rule.needs is not None)
    rules = hooks / 'deny-rules.json'
    rules.write_text(render(HookAdoption(app_name='s', declared_absent=needing)), encoding='utf-8')
    refused = agenthooks.decide('git clone https://forge.example/o/alpha.git', rules, cwd=session)
    assert refused is not None
    assert refused.startswith(f'{familyrepos.RULE_ID}:'), refused
    other = agenthooks.decide('git clone https://forge.example/o/other.git', rules, cwd=session)
    assert other is None or not other.startswith(f'{familyrepos.RULE_ID}:')
