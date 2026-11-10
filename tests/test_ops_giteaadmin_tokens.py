"""The forge's token store: names read and deleted where Gitea keeps them, as the Gitea user, never a value."""

from __future__ import annotations

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
    ini = _ini(tmp_path, '[database]\nDB_TYPE = postgres\nHOST = 127.0.0.1:5432\n')
    store = TokenStore(Forge(api='x', admin='a', config=str(ini)), run=_local)
    with pytest.raises(ForgeRefused, match='DB_TYPE postgres'):
        store.token_names('server-reader')
