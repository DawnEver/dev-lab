"""A confirmed vendor location becomes a row on a config-source branch; an unconfirmed or malformed one never does."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from _ops_fixtures import git

from dev_lab.dev import devhost, vendorrow
from dev_lab.dev.vendorrow import Proposal, Unconfirmed

HOST = """\
# a synthetic workstation
[dev]
os = "windows"

[dev.vendors.jmag]  # seats: a ruling
seats = 2
"""


def _source(tmp_path: Path) -> Path:
    clone = tmp_path / 'hosts-config'
    (clone / 'hosts').mkdir(parents=True)
    (clone / 'hosts' / 'ws-x.toml').write_text(HOST, encoding='utf-8')
    git(clone, 'init', '-q', '-b', 'main')
    git(clone, 'config', 'user.email', 't@t')
    git(clone, 'config', 'user.name', 't')
    git(clone, 'add', '.')
    git(clone, 'commit', '-q', '-m', 'init')
    return clone


GOOD = Proposal('ws-x', 'jmag', '25.2', 'C:/Program Files/Vendor-25.2')


def test_a_confirmed_row_is_committed_on_its_branch_and_reads_back(tmp_path: Path) -> None:
    clone = _source(tmp_path)
    tree, sha = vendorrow.write(clone, GOOD, confirmed=True, base='main')
    assert git(tree, 'rev-parse', '--abbrev-ref', 'HEAD') == 'pr/vendor/ws-x-jmag'
    committed = tomllib.loads(git(clone, 'show', f'{sha}:hosts/ws-x.toml'))
    assert committed['dev']['vendors']['jmag'] == {'seats': 2, 'version': '25.2', 'home': GOOD.home}
    assert git(clone, 'show', 'main:hosts/ws-x.toml') == HOST.strip()  # the trunk and the checkout are untouched
    assert (clone / 'hosts' / 'ws-x.toml').read_text(encoding='utf-8') == HOST
    assert '# seats: a ruling' in (tree / 'hosts' / 'ws-x.toml').read_text(encoding='utf-8')


def test_an_unconfirmed_proposal_is_refused_and_writes_nothing(tmp_path: Path) -> None:
    clone = _source(tmp_path)
    with pytest.raises(Unconfirmed, match='--confirmed'):
        vendorrow.write(clone, GOOD, confirmed=False, base='main')
    assert not (clone / '.claude').exists()
    assert 'pr/vendor/ws-x-jmag' not in git(clone, 'branch', '--list')


@pytest.mark.parametrize(
    ('proposal', 'named'),
    [
        (Proposal('ws-x', 'jm ag', '25.2', 'C:/V'), 'program'),
        (Proposal('ws x', 'jmag', '25.2', 'C:/V'), 'host'),
        (Proposal('ws-x', 'jmag', '', 'C:/V'), 'version'),
        (Proposal('ws-x', 'jmag', '25.2', 'Program Files/V'), 'home'),
        (Proposal('ws-x', 'jmag', '25.2', 'C:\\Program Files\\V'), 'forward slashes'),
    ],
)
def test_a_malformed_row_is_refused_by_its_field(tmp_path: Path, proposal: Proposal, named: str) -> None:
    clone = _source(tmp_path)
    with pytest.raises(ValueError, match=named):
        vendorrow.write(clone, proposal, confirmed=True, base='main')
    assert not (clone / '.claude').exists()


def test_the_well_formed_control_has_no_defects() -> None:
    assert GOOD.defects() == []
    assert Proposal('ws-x', 'femm', '5.0', '/opt/femm').defects() == []


def test_a_machine_without_a_host_file_is_refused(tmp_path: Path) -> None:
    clone = _source(tmp_path)
    with pytest.raises(RuntimeError, match=r'hosts/ws-y\.toml'):
        vendorrow.write(clone, Proposal('ws-y', 'jmag', '25.2', 'C:/V'), confirmed=True, base='main')


def test_the_devhost_verb_refuses_unconfirmed_and_writes_confirmed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    clone = _source(tmp_path)
    argv = ['--machine', str(tmp_path / 'absent.toml'), 'vendor-row', '--from', str(clone), '--host', 'ws-x',
            '--program', 'jmag', '--version', '25.2', '--home', GOOD.home, '--base', 'main']  # fmt: skip
    assert devhost.main(argv) == 2
    assert 'refused:' in capsys.readouterr().err
    assert devhost.main([*argv, '--confirmed']) == 0
    assert 'pr/vendor/ws-x-jmag' in capsys.readouterr().out
