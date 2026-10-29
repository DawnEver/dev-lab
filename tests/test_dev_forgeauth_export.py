"""``forge auth export`` / ``auth login --from-file``: every forge credential moves to a new box in one pipe.

The credential stores are git's own ``store`` helper on files under ``tmp_path`` (``_isolated_store``), so
``approve``/``fill`` run for real; the tokens are fakes.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from _forge_fake import make_repo, run_git
from test_dev_forgeauth import _isolated_store
from test_dev_forgework import _answer, _Loopback, server

from dev_lab.dev.forge import credential_for, store_credential
from dev_lab.dev.forgeauth import KeyLine, family_hosts, format_key_file, main, parse_key_file

__all__ = ['server']

_GITEA_PAT = 'pat-gitea-0123456789'
_GITHUB_PAT = 'ghp_fake0123456789'


class _Tty(io.StringIO):
    def isatty(self) -> bool:
        return True


def _box(tmp_path: Path, name: str) -> tuple[Path, dict[str, str]]:
    home = tmp_path / name
    home.mkdir()
    return home, _isolated_store(home)[0]


def test_parse_reads_user_at_host_and_skips_comments_and_blanks() -> None:
    text = '# forge credentials\n\nalice@gitea.example tok1\nOAUTH_USER@github.com  tok2 \n'
    assert parse_key_file(text) == (
        KeyLine('gitea.example', 'alice', 'tok1'),
        KeyLine('github.com', 'OAUTH_USER', 'tok2'),
    )


def test_parse_keeps_a_username_holding_an_at_and_a_host_with_a_port() -> None:
    assert parse_key_file('a@b.invalid@git.example:3000 t\n') == (KeyLine('git.example:3000', 'a@b.invalid', 't'),)


@pytest.mark.parametrize(
    'bad', ['alice@gitea.example\n', 'gitea.example tok\n', '@gitea.example tok\n', 'alice@ tok\n', 'a@h t extra\n']
)
def test_parse_refuses_a_malformed_line_naming_its_number_never_its_token(bad: str) -> None:
    with pytest.raises(ValueError, match='line 2') as refused:
        parse_key_file('# header\n' + bad)
    assert 'tok' not in str(refused.value).replace('token', '')


@pytest.mark.parametrize(
    'host',
    ['internal-admin:8080/x', 'h?q=1', 'h#frag', r'h\evil', 'h:port', 'h:', '-h', 'h..example', 'h\x01'],
)
def test_parse_refuses_a_host_that_is_not_a_bare_name_with_an_optional_port(host: str) -> None:
    """The host becomes an HTTPS target the token is sent to: a path, query, fragment or junk is refused."""
    with pytest.raises(ValueError, match='line 1: host'):
        parse_key_file(f'alice@{host} tok\n')


def test_parse_refuses_a_host_named_twice_for_one_username() -> None:
    with pytest.raises(ValueError, match='twice'):
        parse_key_file('a@h t1\na@h t2\n')


def test_format_round_trips_through_parse() -> None:
    keys = (KeyLine('gitea.example', 'alice', 'tok1'), KeyLine('github.com', 'bob', 'tok2'))
    assert parse_key_file(format_key_file(keys)) == keys


def test_export_refuses_a_terminal_stdout(tmp_path, capsys) -> None:
    home, env = _box(tmp_path, 'old')
    store_credential('gitea.example', 'alice', _GITEA_PAT, cwd=home, env=env)
    out = _Tty()
    assert main(['export', '--host', 'gitea.example'], cwd=home, env=env, stdout=out) == 2
    assert out.getvalue() == ''
    assert 'pipe or redirect it' in capsys.readouterr().err


def test_export_then_login_from_file_moves_every_credential(server, tmp_path, capsys) -> None:
    old, old_env = _box(tmp_path, 'old')
    store_credential('gitea.example', 'alice', _GITEA_PAT, cwd=old, env=old_env)
    store_credential('github.com', 'OAUTH_USER', _GITHUB_PAT, cwd=old, env=old_env)
    hosts = ['--host', 'gitea.example', '--host', 'github.com', '--host', 'empty.example']
    exported = io.StringIO()
    assert main(['export', *hosts], cwd=old, env=old_env, stdout=exported) == 0
    err = capsys.readouterr().err
    assert '2 credential' in err
    assert 'empty.example' in err
    assert _GITEA_PAT not in err
    assert _GITHUB_PAT not in err

    new, new_env = _box(tmp_path, 'new')
    _answer('GET', '/api/v1/user', (200, {'login': 'alice'}))
    _answer('GET', '/user', (200, {'login': 'bob'}))
    code = main(
        ['login', '--from-file', '-'],
        cwd=new,
        env=new_env,
        transport=_Loopback(server),
        stdin=io.StringIO(exported.getvalue()),
    )
    assert code == 0
    assert credential_for('gitea.example', cwd=new, env=new_env) == ('alice', _GITEA_PAT)
    assert credential_for('github.com', cwd=new, env=new_env) == ('OAUTH_USER', _GITHUB_PAT)
    out = capsys.readouterr()
    assert _GITEA_PAT not in out.out + out.err


def test_login_from_file_stores_nothing_when_one_token_is_refused(server, tmp_path, capsys) -> None:
    new, env = _box(tmp_path, 'new')
    key_file = new / 'keys'
    key_file.write_text(f'alice@gitea.example {_GITEA_PAT}\nbob@github.com {_GITHUB_PAT}\n', encoding='utf-8')
    _answer('GET', '/api/v1/user', (200, {'login': 'alice'}))
    _answer('GET', '/user', (401, {'message': 'Bad credentials'}))
    assert main(['login', '--from-file', str(key_file)], cwd=new, env=env, transport=_Loopback(server)) == 1
    assert 'NOT stored' in capsys.readouterr().err
    store = new / 'credentials'
    assert not store.exists() or not store.read_text(encoding='utf-8').strip()


def test_family_hosts_reads_every_remote_of_every_sibling_checkout(tmp_path) -> None:
    family = tmp_path / 'family'
    family.mkdir()
    one = make_repo(family, 'https://gitea.example/team/one.git')
    other = family / 'other'
    other.mkdir()
    run_git(other, 'init', '-q')
    run_git(other, 'remote', 'add', 'origin', 'https://github.com/someone/other')
    run_git(other, 'remote', 'add', 'template', 'git@gitea.example:team/template.git')
    (family / 'not-a-repo').mkdir()
    assert family_hosts(one) == ('gitea.example', 'github.com')
