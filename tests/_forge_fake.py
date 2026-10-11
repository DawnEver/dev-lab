"""The loopback forge every forge-door test drives: a REAL HTTP server that records, and a transport to it.

Shared by ``test_dev_forgework.py``, ``test_dev_forgestatus.py`` and ``test_dev_forgeissue.py`` so the
three suites assert against one recorder. The evidence is what the SERVER recorded (method, path,
headers, decoded body), never the arguments a test passed.
"""

from __future__ import annotations

import http.client
import json
import shutil
import subprocess
import threading
from collections.abc import Callable, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, ClassVar

from lab_commons.dev.forge import Forge
from lab_commons.dev.forgework import Client

_GIT = shutil.which('git') or 'git'


def run_git(cwd: Path, *args: str) -> None:
    subprocess.run([_GIT, *args], cwd=cwd, check=True, capture_output=True, timeout=60)


def git_out(cwd: Path, *args: str) -> str:
    """One git read in *cwd*, stripped."""
    done = subprocess.run(
        [_GIT, *args], cwd=cwd, check=True, capture_output=True, text=True, encoding='utf-8', timeout=60
    )
    return done.stdout.strip()


#: What the fake credential helper answers unless told otherwise.
_HELPER_ANSWER = 'T'


def credential_env(tmp_path: Path, token: str = _HELPER_ANSWER) -> dict[str, str]:
    """An env whose ONLY credential is a git helper answering *token*: the one route a forge verb reads."""
    config = tmp_path / 'gitconfig-credential'
    helper = f'!f() {{ echo username=u; echo password={token}; }}; f'
    config.write_text(f'[credential]\n\thelper = "{helper}"\n', encoding='utf-8')
    return {'GIT_CONFIG_GLOBAL': str(config), 'GIT_CONFIG_SYSTEM': str(tmp_path / 'absent')}


def make_repo(tmp_path: Path, remote: str, *, branch: str = 'feature') -> Path:
    repo = tmp_path / 'repo'
    repo.mkdir()
    run_git(repo, 'init', '-q', '-b', branch)
    run_git(repo, 'remote', 'add', 'origin', remote)
    return repo


class Recorder(BaseHTTPRequestHandler):
    """Records every request and answers from a table of ``(method, path) -> (status, payload)``."""

    received: ClassVar[list[dict[str, Any]]] = []
    answers: ClassVar[dict[tuple[str, str], list[tuple[int | None, Any]]]] = {}
    #: When set, a request whose Authorization header it rejects is answered 401 -- the forge's credential check.
    accept: ClassVar[Callable[[str], bool] | None] = None

    def _serve(self, method: str) -> None:
        length = int(self.headers.get('Content-Length') or 0)
        raw = self.rfile.read(length) if length else b''
        is_json = (self.headers.get('Content-Type') or '').startswith('application/json')
        body = json.loads(raw) if raw and is_json else None
        type(self).received.append(
            {'method': method, 'path': self.path, 'body': body, 'raw': raw, 'headers': dict(self.headers)}
        )
        answers = type(self).answers
        accept = type(self).accept
        if accept is not None and not accept(self.headers.get('Authorization') or ''):
            answers = {(method, self.path): [(401, {'message': 'invalid username, password or token'})]}
        found = answers.get((method, self.path)) or answers.get((method, self.path.split('?')[0]))
        queue = found or [(404, {'message': 'not found'})]
        status, payload = queue.pop(0) if len(queue) > 1 else queue[0]
        if status is None:  # APPLIED, then the response is lost: the connection drops unanswered
            self.close_connection = True
            return
        encoded = b'' if payload is None else json.dumps(payload).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self) -> None:
        """Recorded then answered."""
        self._serve('GET')

    def do_POST(self) -> None:
        """Recorded then answered."""
        self._serve('POST')

    def do_PATCH(self) -> None:
        """Recorded then answered."""
        self._serve('PATCH')

    def do_DELETE(self) -> None:
        """Recorded then answered."""
        self._serve('DELETE')

    def log_message(self, fmt: str, *args: object) -> None:
        """Silent: the recording IS the log."""


def serve() -> Iterator[ThreadingHTTPServer]:
    """A fresh recorder and a running server, shut down after the test."""
    Recorder.received = []
    Recorder.answers = {}
    Recorder.accept = None
    httpd = ThreadingHTTPServer(('127.0.0.1', 0), Recorder)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield httpd
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=10)


class Loopback:
    """A REAL connection to the test server, recording which API host the backend asked for."""

    def __init__(self, httpd: ThreadingHTTPServer) -> None:
        self.address = f'{httpd.server_address[0]}:{httpd.server_address[1]}'
        self.asked: list[str] = []

    def __call__(self, host: str, timeout: float) -> http.client.HTTPConnection:
        self.asked.append(host)
        return http.client.HTTPConnection(self.address, timeout=timeout)


def client(forge: Forge, transport: Loopback, *, stamp: str | None = None) -> Client:
    return Client(forge, 'T', transport=transport, stamp=stamp, sleep=lambda _s: None)


def answer(method: str, path: str, *replies: tuple[int | None, Any]) -> None:
    Recorder.answers[(method, path)] = list(replies)
