"""The forge's token store: names read and deleted where Gitea keeps them, as the Gitea user, never a value."""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from dev_lab.ops.giteaadmin import Forge, ForgeRefused, TokenStore


def _db(tmp_path: Path) -> Path:
    path = tmp_path / 'gitea.db'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE "user" (id INTEGER PRIMARY KEY, lower_name TEXT)')
        db.execute('CREATE TABLE access_token (id INTEGER PRIMARY KEY, uid INTEGER, name TEXT, token_hash TEXT)')
        db.executemany('INSERT INTO "user" VALUES (?, ?)', [(1, 'server-reader'), (2, 'site-admin')])
        db.executemany('INSERT INTO access_token (uid, name, token_hash) VALUES (?, ?, ?)',
                       [(1, 'host-a', 'deadbeef'), (1, 'host-b', 'cafe1234'), (2, 'host-a', 'feedface')])  # fmt: skip
    return path


def _ini(tmp_path: Path, body: str) -> Path:
    ini = tmp_path / 'app.ini'
    ini.write_text(body, encoding='utf-8')
    return ini


def _local(argv: list[str]) -> tuple[int, str]:
    """Run the store's argv here: drop ``runuser -u <user> --`` and use this interpreter for ``python3``."""
    assert argv[:2] == ['runuser', '-u']
    rest = argv[4:]
    rest[0] = sys.executable if rest[0] == 'python3' else rest[0]
    done = subprocess.run(rest, capture_output=True, text=True, encoding='utf-8', check=False)
    return done.returncode, done.stdout


def _store(tmp_path: Path) -> tuple[TokenStore, Path]:
    db = _db(tmp_path)
    ini = _ini(tmp_path, f'APP_NAME = forge\n[database]\nDB_TYPE = sqlite3\nPATH = {db.as_posix()}\n')
    return TokenStore(Forge(api='http://127.0.0.1:3000', admin='site-admin', config=str(ini)), run=_local), db


def test_names_are_read_per_login_and_no_hash_reaches_them(tmp_path: Path) -> None:
    store, _db_path = _store(tmp_path)
    names = store.token_names('server-reader')
    assert names == {'host-a', 'host-b'}
    assert not any(leak in repr(names) for leak in ('deadbeef', 'cafe1234'))


def test_a_delete_removes_only_that_logins_named_token(tmp_path: Path) -> None:
    store, db = _store(tmp_path)
    store.delete_token('server-reader', 'host-a')
    with sqlite3.connect(db) as conn:
        rows = sorted(conn.execute('SELECT uid, name FROM access_token').fetchall())
    assert rows == [(1, 'host-b'), (2, 'host-a')]


def test_a_name_shaped_like_sql_is_refused_and_deletes_nothing(tmp_path: Path) -> None:
    """Planted control: an injection-shaped name never reaches the store, and every row survives."""
    store, db = _store(tmp_path)
    with pytest.raises(ForgeRefused, match='not a token name'):
        store.delete_token('server-reader', "x' OR '1'='1")
    with sqlite3.connect(db) as conn:
        assert conn.execute('SELECT count(*) FROM access_token').fetchone() == (3,)


def test_the_store_runs_as_the_gitea_user(tmp_path: Path) -> None:
    seen: list[list[str]] = []
    db = _db(tmp_path)
    ini = _ini(tmp_path, f'[database]\nDB_TYPE = sqlite3\nPATH = {db.as_posix()}\n')

    def run(argv: list[str]) -> tuple[int, str]:
        seen.append(argv)
        return _local(argv)

    TokenStore(Forge(api='x', admin='a', config=str(ini), user='git'), run=run).token_names('server-reader')
    assert seen[0][:4] == ['runuser', '-u', 'git', '--']


def test_an_unread_store_is_refused_never_empty(tmp_path: Path) -> None:
    ini = _ini(tmp_path, f'[database]\nDB_TYPE = sqlite3\nPATH = {(tmp_path / "absent.db").as_posix()}\n')
    store = TokenStore(Forge(api='x', admin='a', config=str(ini)), run=lambda _argv: (1, ''))
    with pytest.raises(ForgeRefused, match='reading server-reader token names failed'):
        store.token_names('server-reader')


def test_a_database_type_the_store_cannot_reach_raises_naming_it(tmp_path: Path) -> None:
    ini = _ini(tmp_path, '[database]\nDB_TYPE = mysql\nHOST = 127.0.0.1:3306\n')
    store = TokenStore(Forge(api='x', admin='a', config=str(ini)), run=_local)
    with pytest.raises(ForgeRefused, match='DB_TYPE mysql'):
        store.token_names('server-reader')


#: A fake ``psql``: records its argv and whether a password came by env, reads the ``-v`` variables psql would
#: interpolate for ``:'var'``, and answers from a JSON table -- no server needed. A value spelled into the
#: statement itself (not a variable) exits 9: the store must never build SQL from a value.
_FAKE_PSQL = r"""
import json, os, sys
args = sys.argv[1:]
values = dict(args[i + 1].split('=', 1) for i, flag in enumerate(args) if flag == '-v')
sql = sys.stdin.read()
with open(os.environ['FAKE_PG_LOG'], 'a', encoding='utf-8') as log:
    log.write(json.dumps({'argv': args, 'password_by_env': bool(os.environ.get('PGPASSWORD')), 'sql': sql}) + '\n')
if any(f"'{value}'" in sql for key, value in values.items() if key in ('login', 'name')):
    sys.exit(9)
table = json.load(open(os.environ['FAKE_PG_DB'], encoding='utf-8'))
login = values['login'].lower()
if 'DELETE' in sql:
    table[login] = [n for n in table.get(login, []) if n != values['name']]
    json.dump(table, open(os.environ['FAKE_PG_DB'], 'w', encoding='utf-8'))
print('\n'.join(sorted(table.get(login, []))))
"""


def _pg_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, psql: bool = True) -> tuple[TokenStore, Path]:
    bindir = tmp_path / 'bin'
    bindir.mkdir()
    if psql:
        fake = tmp_path / 'fake_psql.py'
        fake.write_text(_FAKE_PSQL, encoding='utf-8')
        if sys.platform == 'win32':
            (bindir / 'psql.bat').write_text(f'@"{sys.executable}" "{fake}" %*\n', encoding='utf-8')
        else:
            launcher = bindir / 'psql'
            launcher.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{fake}" "$@"\n', encoding='utf-8')
            launcher.chmod(0o755)
    table = tmp_path / 'pg.json'
    table.write_text('{"server-reader": ["host-a", "host-b"], "site-admin": ["host-a"]}', encoding='utf-8')
    monkeypatch.setenv('PATH', str(bindir))
    monkeypatch.setenv('FAKE_PG_DB', str(table))
    monkeypatch.setenv('FAKE_PG_LOG', str(tmp_path / 'pg.log'))
    ini = _ini(tmp_path, '[database]\nDB_TYPE = postgres\nHOST = 127.0.0.1:5432\nNAME = gitea\nUSER = gitea\n'
                         'PASSWD = s3cret-PLANTED\nSSL_MODE = disable\n')  # fmt: skip
    return TokenStore(Forge(api='x', admin='a', config=str(ini)), run=_local), tmp_path / 'pg.log'


def test_postgres_names_are_read_per_login(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store, _log = _pg_store(tmp_path, monkeypatch)
    assert store.token_names('Server-Reader') == {'host-a', 'host-b'}


def test_postgres_delete_removes_only_that_logins_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store, _log = _pg_store(tmp_path, monkeypatch)
    store.delete_token('server-reader', 'host-a')
    assert store.token_names('server-reader') == {'host-b'}
    assert store.token_names('site-admin') == {'host-a'}


def test_the_postgres_password_rides_env_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Planted control: the password is in app.ini; it reaches psql by env only -- never an argv, never output."""
    store, log = _pg_store(tmp_path, monkeypatch)
    seen: list[str] = []
    inner = store.run

    def run(argv: list[str]) -> tuple[int, str]:
        code, said = inner(argv)
        seen.extend([*argv, said])
        return code, said

    store.run = run
    store.delete_token('server-reader', 'host-a')
    calls = [json.loads(line) for line in log.read_text(encoding='utf-8').splitlines()]
    assert calls
    assert all(call['password_by_env'] for call in calls)
    assert not any('PLANTED' in arg for call in calls for arg in call['argv'])
    assert not any('PLANTED' in part for part in seen)
    assert all(":'login'" in call['sql'] for call in calls)


def test_a_missing_psql_is_refused_naming_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store, _log = _pg_store(tmp_path, monkeypatch, psql=False)
    with pytest.raises(ForgeRefused, match='needs psql'):
        store.token_names('server-reader')


def test_a_postgres_sql_shaped_name_never_reaches_psql(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store, log = _pg_store(tmp_path, monkeypatch)
    with pytest.raises(ForgeRefused, match='not a token name'):
        store.delete_token('server-reader', "x' OR '1'='1")
    assert not log.exists()
