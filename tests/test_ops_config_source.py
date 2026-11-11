"""``config apply`` reads the host's reviewed file from its declared config repository.

The token travels in the environment of the one git process (``GIT_CONFIG_*``), never on argv and never in output.
"""

from __future__ import annotations

import dataclasses
import sys
from collections.abc import Mapping
from pathlib import Path

import pytest

from dev_lab.ops.config import ConfigSource
from dev_lab.ops.configdoor import FAMILY_KEY, ConfigRefused, Family, apply, boundary, digest, fetch, tick

_PLANTED = 'planted-' + 'x' * 12  # a stand-in read credential, asserted never to leak


def _source(tmp_path: Path) -> ConfigSource:
    token = tmp_path / 'token'
    token.write_text(_PLANTED + '\n', encoding='utf-8')
    return ConfigSource(
        source='https://forge.example/team/host-config.git',
        path='hosts/forge-a1.toml',
        token_file=str(token),
        ref='main',
    )


def test_fetch_reads_the_declared_file_with_the_token_only_in_the_environment(tmp_path: Path) -> None:
    seen: list[tuple[list[str], Mapping[str, str]]] = []

    def clone(argv: list[str], env: Mapping[str, str]) -> tuple[int, str]:
        seen.append((argv, env))
        target = Path(argv[-1])
        (target / 'hosts').mkdir(parents=True)
        (target / 'hosts' / 'forge-a1.toml').write_text('[cycle]\ninterval_s = 60\n', encoding='utf-8')
        return 0, ''

    text = fetch(_source(tmp_path), run=clone).host

    assert text == '[cycle]\ninterval_s = 60\n'
    argv, env = seen[0]
    assert _PLANTED not in ' '.join(argv)
    assert 'https://forge.example/team/host-config.git' in argv
    assert '--branch' in argv
    assert 'main' in argv
    assert env['GIT_CONFIG_KEY_0'] == 'http.extraHeader'
    assert env['GIT_CONFIG_VALUE_0'] == f'Authorization: token {_PLANTED}'


def test_a_failed_fetch_is_refused_without_echoing_the_token(tmp_path: Path) -> None:
    def broken(_argv: list[str], env: Mapping[str, str]) -> tuple[int, str]:
        return 128, f'fatal: auth failed ({env["GIT_CONFIG_VALUE_0"]})'

    with pytest.raises(ConfigRefused) as refused:
        fetch(_source(tmp_path), run=broken)
    assert _PLANTED not in str(refused.value)


def test_a_missing_host_file_is_refused(tmp_path: Path) -> None:
    def empty(argv: list[str], _env: Mapping[str, str]) -> tuple[int, str]:
        Path(argv[-1]).mkdir(parents=True)
        return 0, ''

    with pytest.raises(ConfigRefused, match=r'hosts/forge-a1.toml'):
        fetch(_source(tmp_path), run=empty)


def test_the_config_source_itself_is_the_security_boundary() -> None:
    assert boundary(('ops.config.source', 'ops.config.token_file', 'ops.config.ref')) == (
        'ops.config.source',
        'ops.config.token_file',
        'ops.config.ref',
    )


_HOST = '[cycle]\ninterval_s = 60\n'
_FAMILY = '[judge]\nmonthly_usd = 40\n'


def _family_source(tmp_path: Path) -> ConfigSource:
    to = '/etc/dev-lab/family.toml'
    return dataclasses.replace(_source(tmp_path), family={'file': 'family.toml', 'to': to})


def _clone_both(argv: list[str], _env: Mapping[str, str]) -> tuple[int, str]:
    target = Path(argv[-1])
    (target / 'hosts').mkdir(parents=True)
    (target / 'hosts' / 'forge-a1.toml').write_text(_HOST, encoding='utf-8')
    (target / 'family.toml').write_text(_FAMILY, encoding='utf-8')
    return 0, ''


def test_the_family_file_is_fetched_with_the_host_file_in_one_clone(tmp_path: Path) -> None:
    """PLANTED CONTROL: a source declaring no family fetches the host file alone."""
    clones: list[list[str]] = []

    def counted(argv: list[str], env: Mapping[str, str]) -> tuple[int, str]:
        clones.append(argv)
        return _clone_both(argv, env)

    fetched = fetch(_family_source(tmp_path), run=counted)
    assert (fetched.host, fetched.family.text, fetched.family.to.as_posix()) == (
        _HOST, _FAMILY, '/etc/dev-lab/family.toml',
    )  # fmt: skip
    assert len(clones) == 1
    assert fetch(_source(tmp_path), run=_clone_both).family is None


def test_a_declared_family_file_missing_from_the_source_is_refused(tmp_path: Path) -> None:
    def host_only(argv: list[str], _env: Mapping[str, str]) -> tuple[int, str]:
        (Path(argv[-1]) / 'hosts').mkdir(parents=True)
        (Path(argv[-1]) / 'hosts' / 'forge-a1.toml').write_text(_HOST, encoding='utf-8')
        return 0, ''

    with pytest.raises(ConfigRefused, match=r'has no family\.toml'):
        fetch(_family_source(tmp_path), run=host_only)


@pytest.mark.parametrize('family', [{'file': 'family.toml'}, {'file': 'f', 'to': 'relative/family.toml'}])
def test_a_family_declaration_is_exactly_file_and_an_absolute_to(tmp_path: Path, family: dict[str, str]) -> None:
    assert _family_source(tmp_path).family  # the control
    with pytest.raises(ValueError, match='family is'):
        dataclasses.replace(_source(tmp_path), family=family)


def _door(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    live = tmp_path / 'supervise.toml'
    live.write_text(_HOST, encoding='utf-8')
    return live, {'loads': lambda _path: None, 'checks': {}, 'run': lambda _argv: (0, '')}


def test_a_changed_family_file_is_boundary_and_places_only_with_consent_to_both_texts(tmp_path: Path) -> None:
    live, door = _door(tmp_path)
    family = Family(tmp_path / 'etc' / 'family.toml', _FAMILY)
    with pytest.raises(ConfigRefused, match=FAMILY_KEY.replace('.', r'\.')):
        apply(live, _HOST, family=family, **door)
    assert not family.to.exists()
    redeemed: list[str] = []
    expected = digest(_HOST, family)  # before the placement: what `config apply --subject` printed
    done = apply(live, _HOST, family=family, redeem=lambda _c, subject: redeemed.append(subject), credential={}, **door)
    assert redeemed == [expected]
    assert redeemed[0] != digest(_HOST), 'the subject binds the family text, not the host file alone'
    assert (done.changed, done.boundary) == ((FAMILY_KEY,), (FAMILY_KEY,))
    assert family.to.read_text(encoding='utf-8') == _FAMILY
    assert live.read_text(encoding='utf-8') == _HOST
    if sys.platform != 'win32':
        assert family.to.stat().st_mode & 0o777 == 0o644


def test_an_unchanged_family_file_is_not_written_and_a_changed_one_is_backed_up(tmp_path: Path) -> None:
    live, door = _door(tmp_path)
    family = Family(tmp_path / 'family.toml', _FAMILY)
    family.to.write_text(_FAMILY, encoding='utf-8')
    before = family.to.stat().st_mtime_ns
    assert apply(live, _HOST, family=family, **door).changed == ()  # unchanged: no consent asked, no write
    assert family.to.stat().st_mtime_ns == before
    assert digest(_HOST, family) == digest(_HOST)
    moved = Family(family.to, '[judge]\nmonthly_usd = 80\n')
    done = apply(live, _HOST, family=moved, redeem=lambda _c, _s: None, credential={}, **door)
    assert done.backup is not None
    assert done.backup.read_text(encoding='utf-8') == _FAMILY
    assert family.to.read_text(encoding='utf-8') == moved.text


def test_a_tick_parks_a_family_change_as_needs_consent(tmp_path: Path) -> None:
    """PLANTED CONTROL: the same tick with the family file already placed is ``unchanged``."""
    live, door = _door(tmp_path)
    family = Family(tmp_path / 'family.toml', _FAMILY)
    told: list[str] = []
    pending = tmp_path / 'pending'
    said = tick(live, _HOST, pending=pending, notify=told.append, family=family, **door)
    assert said == 'needs-consent'
    assert not family.to.exists()
    assert digest(_HOST, family) in told[0]
    family.to.write_text(_FAMILY, encoding='utf-8')
    assert tick(live, _HOST, pending=pending, notify=told.append, family=family, **door) == 'unchanged'
