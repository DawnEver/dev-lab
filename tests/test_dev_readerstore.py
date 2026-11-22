"""A named reader's line lives in its own file, read get-only: REAL git, so the mechanism under test is git's.

Measured 2026-11-22 on two verification accounts: the writer and the config reader shared ``~/.git-credentials``.
After each authenticated fetch as the reader git ran ``credential approve``, and the ``store`` helper rewrote the
file with the approved line FIRST -- so the host's unnamed request, the one a serve posts with, answered as the
read-only login after every deploy, whatever order a placement had written.
"""

from __future__ import annotations

import base64
import functools
import os
import shutil
import subprocess
import threading
from collections.abc import Iterator
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from dev_lab.dev.credstore import (
    READER_STORE,
    STORE,
    drop_held_command,
    held_command,
    move_reader_command,
    named_fill_command,
    reader_git,
    rewrite_command,
    stage_command,
)

_BASH = shutil.which('bash')
_HOST = 'forge.example'
_STAMP = '20261122T120000Z'
_TOKENS = {'forge-ci': 'writer-TOKEN', 'server-reader': 'reader-TOKEN'}


def _line(login: str, host: str = _HOST, scheme: str = 'https') -> str:
    """One store line, assembled from parts so no fixture reads as an email address."""
    return f'{scheme}://{login}:{_TOKENS[login]}' + '@' + host


def _run(home: Path, command: str, stdin: str = '') -> subprocess.CompletedProcess[bytes]:
    assert _BASH, 'every login host runs these commands in bash'
    env = {**os.environ, 'HOME': home.as_posix(), 'GIT_TERMINAL_PROMPT': '0', 'GIT_CONFIG_NOSYSTEM': '1'}
    env['GIT_CONFIG_GLOBAL'] = (home / '.gitconfig').as_posix()  # never the machine's global config
    return subprocess.run([_BASH, '-c', command], input=stdin.encode(), env=env, check=False, capture_output=True)


def _bash(home: Path, command: str, stdin: str = '') -> str:
    done = _run(home, command, stdin)
    assert done.returncode == 0, done.stderr.decode()
    return done.stdout.decode()  # bytes both ways: a text pipe on Windows writes CRLF


def _unnamed(home: Path, host: str = _HOST, scheme: str = 'https') -> str:
    asked = f"printf 'protocol={scheme}\\nhost={host}\\n\\n' | git credential fill | sed -n 's/^password=//p'"
    return _bash(home, asked).strip()


def _approve(home: Path, login: str, git: str = 'git') -> None:
    """What git does after a fetch authenticated as *login*: ``credential approve`` on every helper."""
    said = f'protocol=https\\nhost={_HOST}\\nusername={login}\\npassword={_TOKENS[login]}\\n\\n'
    _bash(home, f"printf '{said}' | {git} credential approve")


def _helpers(home: Path) -> None:
    """The account's own helpers: the store, generically and for the host (what a workstation's door writes)."""
    _bash(
        home,
        f'git config --global credential.helper store && git config --global credential.https://{_HOST}.helper store',
    )


def _lines(home: Path, name: str) -> list[str]:
    path = home / name
    return path.read_text(encoding='utf-8').splitlines() if path.exists() else []


def test_git_moves_an_approved_line_first_so_a_reader_in_the_shared_store_takes_the_unnamed_request(
    tmp_path: Path,
) -> None:
    """THE MEASURED DEFECT, reproduced: order in the shared store does not survive the reader's own fetch."""
    _helpers(tmp_path)
    (tmp_path / STORE).write_text(f'{_line("forge-ci")}\n{_line("server-reader")}\n', encoding='utf-8', newline='\n')
    assert _unnamed(tmp_path) == _TOKENS['forge-ci']  # as placed: the writer first
    _approve(tmp_path, 'server-reader')
    assert _lines(tmp_path, STORE) == [_line('server-reader'), _line('forge-ci')]
    assert _unnamed(tmp_path) == _TOKENS['server-reader']


def test_a_reader_in_its_own_file_cannot_reorder_or_write_any_store(tmp_path: Path) -> None:
    """The same approve -- and a reject -- through the reader's git options leaves both files byte-identical."""
    _helpers(tmp_path)
    (tmp_path / STORE).write_text(_line('forge-ci') + '\n', encoding='utf-8', newline='\n')
    _bash(tmp_path, stage_command(_STAMP), _line('server-reader') + '\n')
    _bash(tmp_path, rewrite_command(_HOST, _STAMP, login='server-reader', staged=True, store=READER_STORE))
    before = {name: (tmp_path / name).read_bytes() for name in (STORE, READER_STORE)}
    git = f'git {reader_git(_HOST)}'
    assert _bash(tmp_path, named_fill_command(_HOST, 'server-reader')).strip() == _TOKENS['server-reader']
    _approve(tmp_path, 'server-reader', git)
    said = f'protocol=https\\nhost={_HOST}\\nusername=server-reader\\npassword=x\\n\\n'
    _bash(tmp_path, f"printf '{said}' | {git} credential reject")
    assert {name: (tmp_path / name).read_bytes() for name in before} == before
    assert _unnamed(tmp_path) == _TOKENS['forge-ci']
    writer = _bash(tmp_path, named_fill_command(_HOST, 'forge-ci')).strip()
    assert writer == '', 'PLANTED CONTROL: the reader file never answers as the writer'


def test_the_move_takes_the_readers_line_out_of_the_shared_store_once(tmp_path: Path) -> None:
    """Store [reader, writer, other] -> store [writer, other], reader file [reader]; a second run changes nothing."""
    _helpers(tmp_path)
    other = 'https://u:x' + '@github.com'
    before = f'{_line("server-reader")}\n{_line("forge-ci")}\n{other}\n'
    (tmp_path / STORE).write_text(before, encoding='utf-8', newline='\n')
    move = move_reader_command(_HOST, 'server-reader')
    assert _bash(tmp_path, held_command(_HOST, 'server-reader')).strip() == 'held'  # the old shape is detected
    assert _unnamed(tmp_path) == _TOKENS['server-reader']  # ... and is the defect
    said = _bash(tmp_path, move)
    assert _TOKENS['server-reader'] not in said
    assert 'moved the server-reader line' in said
    assert _lines(tmp_path, STORE) == [_line('forge-ci'), other]
    assert _lines(tmp_path, READER_STORE) == [_line('server-reader')]
    backups = [p for p in tmp_path.iterdir() if p.name.startswith(f'{STORE}.bak-')]
    assert [p.read_text(encoding='utf-8') for p in backups] == [before]
    assert _bash(tmp_path, held_command(_HOST, 'server-reader')).strip() == ''
    assert _unnamed(tmp_path) == _TOKENS['forge-ci']
    assert _bash(tmp_path, named_fill_command(_HOST, 'server-reader')).strip() == _TOKENS['server-reader']
    names = sorted(p.name for p in tmp_path.iterdir())
    assert _bash(tmp_path, move) == ''  # idempotent: nothing held, nothing run, no second backup
    assert sorted(p.name for p in tmp_path.iterdir()) == names
    assert _lines(tmp_path, STORE) == [_line('forge-ci'), other]


def test_a_placement_cut_after_the_reader_file_was_written_is_finished_by_the_next_move(tmp_path: Path) -> None:
    """The line in BOTH files (a cut between the two writes): the move leaves one, in the reader file."""
    (tmp_path / STORE).write_text(f'{_line("forge-ci")}\n{_line("server-reader")}\n', encoding='utf-8', newline='\n')
    (tmp_path / READER_STORE).write_text(_line('server-reader') + '\n', encoding='utf-8', newline='\n')
    _bash(tmp_path, move_reader_command(_HOST, 'server-reader'))
    assert _lines(tmp_path, STORE) == [_line('forge-ci')]
    assert _lines(tmp_path, READER_STORE) == [_line('server-reader')]


def test_dropping_a_held_line_runs_only_when_the_file_holds_it(tmp_path: Path) -> None:
    """PLANTED CONTROL: a file without the line is not rewritten and gets no backup."""
    (tmp_path / STORE).write_text(_line('forge-ci') + '\n', encoding='utf-8', newline='\n')
    assert _bash(tmp_path, drop_held_command(_HOST, _STAMP, login='server-reader')) == ''
    assert [p.name for p in tmp_path.iterdir()] == [STORE]
    (tmp_path / READER_STORE).write_text(_line('server-reader') + '\n', encoding='utf-8', newline='\n')
    said = _bash(tmp_path, drop_held_command(_HOST, _STAMP, login='server-reader', store=READER_STORE))
    assert f'{READER_STORE}.bak-{_STAMP}' in said
    assert _lines(tmp_path, READER_STORE) == []
    assert _lines(tmp_path, STORE) == [_line('forge-ci')]


class _Authenticated(SimpleHTTPRequestHandler):
    """A dumb-http git remote that serves only a request carrying the reader's basic credential."""

    def do_GET(self) -> None:
        wanted = base64.b64encode(f'server-reader:{_TOKENS["server-reader"]}'.encode()).decode()
        if self.headers.get('Authorization') == f'Basic {wanted}':
            super().do_GET()
            return
        self.send_response(401)
        self.send_header('WWW-Authenticate', 'Basic realm="forge"')
        self.send_header('Content-Length', '0')
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 -- the base class's name
        """Say nothing: the request line would carry no token, but a test prints nothing."""


@pytest.fixture
def remote(tmp_path: Path) -> Iterator[tuple[Path, str]]:
    """A home, and the ``127.0.0.1:<port>`` of a served bare repository ``config-source.git`` with one commit."""
    home, served = tmp_path / 'home', tmp_path / 'served'
    home.mkdir()
    served.mkdir()
    ident = '-c user.name=t -c user.email=t -c init.defaultBranch=main'
    work, bare = (tmp_path / 'work').as_posix(), (served / 'config-source.git').as_posix()
    made = f'git {ident} init -q {work} && git -C {work} {ident} commit -q --allow-empty -m one'
    _bash(home, f'{made} && git clone -q --bare {work} {bare} && git -C {bare} update-server-info')
    server = ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(_Authenticated, directory=str(served)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield home, f'127.0.0.1:{server.server_address[1]}'
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)


def test_an_authenticated_fetch_as_the_reader_never_touches_the_shared_store(remote: tuple[Path, str]) -> None:
    """A REAL clone and pull over authenticated http, as the render runs them.

    PLANTED CONTROL: the old shape -- the reader's line beside the writer's, the fetch through the inherited
    ``store`` helper -- is rewritten by that same fetch with the reader first, and the unnamed request answers as
    the reader.
    """
    home, served = remote
    url = f'http://server-reader@{served}/config-source.git'
    writer, reader = _line('forge-ci', served, 'http'), _line('server-reader', served, 'http')
    _bash(home, 'git config --global credential.helper store')
    (home / STORE).write_text(writer + '\n', encoding='utf-8', newline='\n')
    (home / READER_STORE).write_text(reader + '\n', encoding='utf-8', newline='\n')
    git, clone = f'git {reader_git("127.0.0.1")}', (home / 'clone').as_posix()
    _bash(home, f'{git} clone -q {url} {clone} && {git} -C {clone} pull -q --ff-only')
    assert (home / 'clone' / '.git').is_dir()
    assert _lines(home, STORE) == [writer]
    assert _lines(home, READER_STORE) == [reader]
    assert _unnamed(home, served, 'http') == _TOKENS['forge-ci']
    refused = _run(home, f'git -c credential.helper= clone -q {url} {(home / "anonymous").as_posix()}')
    assert refused.returncode != 0, 'PLANTED CONTROL: the remote serves nothing without the credential'

    (home / STORE).write_text(f'{writer}\n{reader}\n', encoding='utf-8', newline='\n')  # the old shape
    assert _unnamed(home, served, 'http') == _TOKENS['forge-ci']
    _bash(home, f'git -C {clone} pull -q --ff-only')
    assert _unnamed(home, served, 'http') == _TOKENS['server-reader']
