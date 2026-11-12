"""The Gitea admin a forge host runs: its declared accounts role, the CLI as the Gitea user, and the local API.

Split out of :mod:`dev_lab.ops.forgeaccounts` (2026-11-10, MODULE-SIZE-ALARM): that module decides WHICH account
or token a consented request makes; this one is HOW a host's Gitea is asked -- the CLI where it can, the local API
with a short-lived admin token where it cannot.
"""

from __future__ import annotations

import configparser
import json
import re
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from http import HTTPStatus
from pathlib import Path
from typing import Any, Final

from lab_commons import launch

__all__ = [
    'BREAKGLASS_SCOPES',
    'READ',
    'ROLE_GRANTS',
    'Forge',
    'ForgeRefused',
    'GiteaCli',
    'Http',
    'Runner',
    'TokenStore',
    'audit',
    'local_api',
    'run_argv',
]

#: The permission a reader is granted.
READ: Final = 'read'
#: Each declared machine-account role and the narrowest Gitea collaborator permission that serves it. A review
#: posts a pull review and a commit status; Gitea routes ``POST /repos/{o}/{r}/statuses/{sha}`` behind
#: ``reqRepoWriter(unit.TypeCode)``, so a reviewer is a WRITE collaborator and its token's scopes are its limit. A
#: break-glass merger merges past branch protection, which Gitea allows only a REPOSITORY admin -- never org or site.
ROLE_GRANTS: Final = {'read': READ, 'write': 'write', 'review': 'write', 'breakglass': 'admin'}
#: The only scopes a ``breakglass`` login's token may hold: merge (repository), post its reason comment (issue)
#: and name itself (``GET /user``).
BREAKGLASS_SCOPES: Final = frozenset({'read:repository', 'write:repository', 'read:issue', 'write:issue', 'read:user'})
#: Runs one argv; its exit code and output.
type Runner = Callable[[list[str]], tuple[int, str]]
#: One local API call ``(method, path, token, body) -> (status, json)``.
type Http = Callable[[str, str, str, Mapping[str, Any] | None], tuple[int, Any]]


@dataclass(frozen=True)
class Forge:
    """The forge's machine accounts, made only through ``forge account|token`` (:mod:`dev_lab.ops.forgeaccounts`).

    ``api`` is the local Gitea's base URL; ``admin`` the Gitea admin whose SHORT-LIVED token (minted by the CLI per
    use, deleted after it) grants a repository collaborator, which the Gitea CLI cannot. ``binary``, ``config`` and
    ``user`` run the Gitea CLI as the Gitea user. ``accounts`` declares each machine account,
    ``{login: {role, repos}}`` with a role of :data:`ROLE_GRANTS`; a ``read`` login may hold ``read:*`` scopes only, a
    ``breakglass`` login :data:`BREAKGLASS_SCOPES` only;
    ``email_domain`` the address a made account gets; ``log`` the audit (who, what -- never a token).
    """

    api: str
    admin: str
    binary: str = 'gitea'
    config: str = '/etc/gitea/app.ini'
    user: str = 'gitea'
    accounts: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    email_domain: str = 'noreply.invalid'
    log: str = '/var/log/dev-lab-ops/forge.jsonl'


class ForgeRefused(ValueError):
    """The request is refused; nothing was changed (or, mid-way, the audit says what was)."""


#: Why the token store is the database, not the API: Gitea's ``GET``/``DELETE /users/{u}/tokens`` sit behind
#: ``reqBasicOrRevProxyAuth`` -- only the owner's basic auth; an admin token, with or without ``Sudo``, is refused
#: (HTTP 401, measured 2026-11-10 on Gitea 28.3.0) -- and the CLI mints but cannot list or delete. A token VALUE is
#: never read: the table holds a hash, and it is never selected. Coverage (UNSUPPORTED-RAISES): ``sqlite3`` and
#: ``postgres``; any other ``DB_TYPE`` is refused by name.
#: A token name or login the store will put into a statement; anything else is refused before it runs.
_NAME: Final = re.compile(r'[\w.-]{1,255}')
#: The child's exit when its database client is missing.
_NO_TOOL: Final = 3

#: Run by the Gitea user's ``python3``: argv = (db, verb, login[, name]); prints the names as JSON, or nothing.
_SQLITE: Final = """
import json, sqlite3, sys
db, verb, login = sys.argv[1:4]
conn = sqlite3.connect(f'file:{db}?mode=rw', uri=True, timeout=10)
uid = 'SELECT id FROM "user" WHERE lower_name = ?'
if verb == 'delete':
    with conn:
        conn.execute(f'DELETE FROM access_token WHERE uid = ({uid}) AND name = ?', (login.lower(), sys.argv[4]))
rows = conn.execute(f'SELECT name FROM access_token WHERE uid = ({uid})', (login.lower(),)).fetchall()
print(json.dumps(sorted(row[0] for row in rows)))
"""


#: Run by the Gitea user's ``python3``: argv = (app.ini, verb, login[, name]). ASSUMPTION (measured on the Gitea host
#: 2026-11-10: psql 16, no psycopg): the host has ``psql``. The child reads ``[database]`` ITSELF, so the password
#: travels only in psql's ``PGPASSWORD`` and never through the caller's argv, log or output; values reach SQL only
#: as psql variables (``:'login'``), read from stdin where psql interpolates them. No psql: exit 3, naming it.
_POSTGRES: Final = r"""
import configparser, json, os, shutil, subprocess, sys
ini_path, verb, login = sys.argv[1:4]
psql = shutil.which('psql')
if psql is None:
    sys.stderr.write('psql not found')
    sys.exit(3)
ini = configparser.ConfigParser(interpolation=None)
ini.read_string('[root]\n' + open(ini_path, encoding='utf-8').read())
db = ini['database']
def value(key, default=''):
    raw = db.get(key, default).strip()
    return raw[1:-1] if len(raw) > 1 and raw[0] == raw[-1] and raw[0] in '"`' else raw
password = value('PASSWD')
where = value('HOST', '127.0.0.1:5432')
host, _, port = (where, '', '') if where.startswith('/') else where.partition(':')
env = dict(os.environ, PGPASSWORD=password, PGSSLMODE=value('SSL_MODE') or 'disable')
uid = "SELECT id FROM \"user\" WHERE lower_name = lower(:'login')"
sql = f'SELECT name FROM access_token WHERE uid = ({uid}) ORDER BY name;\n'
argv = [psql, '-X', '-q', '-A', '-t', '-v', 'ON_ERROR_STOP=1', '-h', host or '127.0.0.1',
        *(() if where.startswith('/') else ('-p', port or '5432')),
        '-U', value('USER', 'gitea'), '-d', value('NAME', 'gitea'), '-v', f'login={login}']
if verb == 'delete':
    argv += ['-v', f'name={sys.argv[4]}']
    sql = f"DELETE FROM access_token WHERE uid = ({uid}) AND name = :'name';\n" + sql
done = subprocess.run([*argv, '-f', '-'], input=sql, capture_output=True, text=True, env=env, check=False)
if done.returncode != 0:
    why = done.stderr.strip()[:300]
    print(json.dumps({'error': why.replace(password, '<redacted>') if password else why}))
    sys.exit(done.returncode)
print(json.dumps(sorted(line for line in done.stdout.splitlines() if line)))
"""


def _checked(kind: str, value: str) -> str:
    if not _NAME.fullmatch(value):
        msg = f'{value!r} is not a token name or login ({kind}); nothing was asked of the store'
        raise ForgeRefused(msg)
    return value


class TokenStore:
    """The token names of a host's Gitea (:class:`Forge`), read and deleted in its database as the Gitea user."""

    def __init__(self, role: Forge, *, run: Runner) -> None:
        """Bind *role*'s ``app.ini`` and Gitea user to *run*."""
        self.role, self.run = role, run

    def _program(self) -> tuple[str, str]:
        """The child program and its first argument for the declared ``DB_TYPE``; any other type is refused."""
        ini = configparser.ConfigParser(interpolation=None)
        ini.read_string('[root]\n' + Path(self.role.config).read_text(encoding='utf-8'))
        kind = ini.get('database', 'DB_TYPE', fallback='sqlite3').strip()
        if kind == 'sqlite3':
            return _SQLITE, ini.get('database', 'PATH', fallback='data/gitea.db').strip()
        if kind == 'postgres':
            return _POSTGRES, self.role.config
        msg = f'the token store reads sqlite3 and postgres; {self.role.config} names DB_TYPE {kind}'
        raise ForgeRefused(msg)

    def _ask(self, verb: str, login: str, *name: str) -> set[str]:
        argv = [verb, _checked('login', login), *(_checked('name', n) for n in name)]
        program, first = self._program()
        code, said = self.run(['runuser', '-u', self.role.user, '--', 'python3', '-I', '-c', program, first, *argv])
        if code == _NO_TOOL:
            msg = 'the token store needs psql on the forge host; it is not installed'
            raise ForgeRefused(msg)
        try:
            answer = json.loads(said)
        except json.JSONDecodeError:
            answer = None
        names = answer if code == 0 else None
        if not isinstance(names, list):
            what = 'reading' if verb == 'list' else f'deleting {name[0]} of'
            why = f': {answer["error"]}' if isinstance(answer, dict) and answer.get('error') else ''
            msg = f'{what} {login} token names failed (exit {code}){why}'
            raise ForgeRefused(msg)
        return {str(found) for found in names}

    def token_names(self, login: str) -> set[str]:
        """The names of *login*'s tokens."""
        return self._ask('list', login)

    def delete_token(self, login: str, name: str) -> None:
        """Delete *login*'s token *name*; refused unless the store then no longer holds it."""
        if name in self._ask('delete', login, name):
            msg = f'{login} token {name} is still held after the delete'
            raise ForgeRefused(msg)


class GiteaCli:
    """:class:`GiteaAdmin` on a host: the Gitea CLI as the Gitea user, and the local API for what it cannot do.

    The API calls carry an admin token the CLI mints for :attr:`Forge.admin` on first need (``write:repository``,
    ``write:user``, ``write:admin``) and :meth:`close` deletes; it never leaves this process. Token names are read
    and deleted in the forge's database (:class:`TokenStore`): Gitea's token API admits
    only the owner's basic auth.
    """

    def __init__(self, role: Forge, *, run: Runner, http: Http) -> None:
        """Bind *role*'s CLI and API to *run* and *http*."""
        self.role, self.run, self.http = role, run, http
        self.store = TokenStore(role, run=run)
        self._admin: tuple[str, str] | None = None  # (name, token)

    def _cli(self, *argv: str) -> str:
        role = self.role
        code, said = self.run(['runuser', '-u', role.user, '--', role.binary, '--config', role.config, *argv])
        if code != 0:
            msg = f'gitea {" ".join(argv[:3])} failed (exit {code})'  # its output may carry a secret: never repeated
            raise ForgeRefused(msg)
        return said

    def api(self, method: str, path: str, *, body: Mapping[str, Any] | None = None) -> tuple[int, Any]:
        """One local API call (*path* under ``/api/v1``) as the site admin; its status and parsed body."""
        if self._admin is None:
            name = f'dev-lab-ops-{uuid.uuid4().hex[:12]}'
            self._admin = (name, self.generate_token(self.role.admin, name, 'write:repository,write:user,write:admin'))
        return self.http(method, f'{self.role.api.rstrip("/")}/api/v1{path}', self._admin[1], body)

    def close(self) -> None:
        """Delete the admin token this use minted, if any."""
        if self._admin is not None:
            name, _token = self._admin
            self.store.delete_token(self.role.admin, name)
            self._admin = None

    def user_exists(self, login: str) -> bool:
        """Whether *login* is a Gitea user (``admin user list``'s second column)."""
        rows = self._cli('admin', 'user', 'list').splitlines()[1:]
        return any(len(cells) > 1 and cells[1] == login for cells in (row.split() for row in rows))

    def create_user(self, login: str, email: str) -> None:
        """A restricted user with a random password nobody holds."""
        self._cli('admin', 'user', 'create', '--username', login, '--email', email, '--random-password',
                  '--must-change-password=false', '--restricted')  # fmt: skip

    def permission(self, repo: str, login: str) -> str | None:
        """*login*'s permission on *repo* (``none`` when it holds none)."""
        status, found = self.api('GET', f'/repos/{repo}/collaborators/{login}/permission')
        if status == HTTPStatus.NOT_FOUND:
            msg = f'no repository {repo} (or no login {login})'
            raise ForgeRefused(msg)
        return str(found.get('permission', 'none')) if isinstance(found, dict) else None

    def grant(self, repo: str, login: str, permission: str) -> None:
        """Make *login* a collaborator of *repo* holding *permission*."""
        status, _ = self.api('PUT', f'/repos/{repo}/collaborators/{login}', body={'permission': permission})
        if status not in {HTTPStatus.OK, HTTPStatus.NO_CONTENT}:
            msg = f'granting {login} {permission} on {repo} failed (HTTP {status})'
            raise ForgeRefused(msg)

    def token_names(self, login: str) -> set[str]:
        """The names of *login*'s tokens, from the forge's database."""
        return self.store.token_names(login)

    def delete_token(self, login: str, name: str) -> None:
        """Delete *login*'s token *name* in the forge's database."""
        self.store.delete_token(login, name)

    def generate_token(self, login: str, name: str, scopes: str) -> str:
        """A new token of *login* named *name* with *scopes* (the CLI's ``--raw``: the bare token)."""
        return self._cli('admin', 'user', 'generate-access-token', '--username', login, '--token-name', name,
                         '--scopes', scopes, '--raw').strip()  # fmt: skip


def audit(log: str, by: str, line: Mapping[str, Any]) -> None:
    """Append one audit *line* to *log* (``[ops.forge] log``): when, who, what -- never a token."""
    path = Path(log)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8') as out:
        out.write(json.dumps({'at': datetime.now(UTC).isoformat(timespec='seconds'), 'by': by, **line}) + '\n')


def run_argv(argv: list[str]) -> tuple[int, str]:
    """One Gitea CLI argv through the launch door; its exit code and stdout."""
    done = launch.run(argv, capture_output=True, text=True, encoding='utf-8', check=False)
    return done.returncode, done.stdout


def local_api(method: str, url: str, token: str, body: Mapping[str, Any] | None) -> tuple[int, Any]:
    """One call to the host's own Gitea API (``[ops.forge] api``); its status and parsed body, ``None`` if none."""
    headers = {'Authorization': f'token {token}', 'Content-Type': 'application/json'}
    data = None if body is None else json.dumps(body).encode('utf-8')
    request = urllib.request.Request(url, data=data, headers=headers, method=method)  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=30) as answer:  # noqa: S310
            status, raw = answer.status, answer.read()
    except urllib.error.HTTPError as refused:
        status, raw = refused.code, b''
    try:
        return status, json.loads(raw) if raw else None
    except ValueError:
        return status, None
