"""``config apply`` reads the host's reviewed file from its declared forge-hosts repository.

The token travels in the environment of the one git process (``GIT_CONFIG_*``), never on argv and never in output.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import pytest

from dev_lab.ops.config import ConfigSource
from dev_lab.ops.configdoor import ConfigRefused, boundary, fetch

_PLANTED = 'planted-' + 'x' * 12  # a stand-in read credential, asserted never to leak


def _source(tmp_path: Path) -> ConfigSource:
    token = tmp_path / 'token'
    token.write_text(_PLANTED + '\n', encoding='utf-8')
    return ConfigSource(
        source='https://gitea.example/Team/forge-hosts.git',
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

    text = fetch(_source(tmp_path), run=clone)

    assert text == '[cycle]\ninterval_s = 60\n'
    argv, env = seen[0]
    assert _PLANTED not in ' '.join(argv)
    assert 'https://gitea.example/Team/forge-hosts.git' in argv
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
