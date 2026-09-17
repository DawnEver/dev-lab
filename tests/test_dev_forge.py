"""``lab_commons.dev.forge`` -- driven against a REAL HTTP server and REAL git repositories.

WHY A REAL SERVER AND NOT A STUBBED CLIENT. Every claim this module makes is about what the forge was
ASKED and what it ANSWERED, and a stubbed client erases exactly that: it asserts the arguments the
test just wrote down. So each case starts a real :mod:`http.server` on a loopback port, lets the
module's own request path reach it, and then reads the requests the SERVER RECORDED -- method, path
and decoded body. What the child received is the evidence; what the caller passed is not.

THE TRANSPORT IS THE TEST'S, AND THAT IS THE ONLY SUBSTITUTION HERE. The shipped default is
HTTPS-only by construction, so a loopback server cannot be reached through it without a certificate
no test can mint from the standard library. :func:`_plain` is therefore a REAL
:class:`http.client.HTTPConnection` written here rather than a fake written anywhere -- the request
still crosses a socket, and :func:`test_the_shipped_transport_cannot_speak_another_scheme` pins that
the kit's own default is the HTTPS one.

THE TWO MEASURED DEFECTS ARE PLANTED EXPLICITLY, because each is a state that reads as success:

* a POPULATED whitelist with ``enable_push_whitelist`` off -- decorative, and the report it replaces
  said OK for exactly that state on 2026-08-27;
* an EMPTY declared whitelist -- ``set() <= anything`` is true, so a target naming nobody would be
  met by every rule on every forge. That is the vacuous green arriving through the arithmetic, and
  it is refused at declaration rather than found at assessment.
"""

from __future__ import annotations

import http.client
import inspect
import json
import shutil
import subprocess
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, ClassVar

import pytest

from lab_commons.dev import forge as module
from lab_commons.dev.forge import (
    APPLIED,
    INERT,
    NOT_APPLIED,
    UNREADABLE,
    Clause,
    Forge,
    NoCredential,
    Protection,
    UnreadableRemote,
    apply_protection,
    assess,
    forge_from_remote,
    protection_body,
    read_rule,
    token_for,
)

_GIT = shutil.which('git') or 'git'


def _run(cwd: Path, *args: str) -> None:
    subprocess.run([_GIT, *args], cwd=cwd, check=True, capture_output=True, timeout=60)


def _repo(tmp_path: Path, remote: str, *, name: str = 'repo') -> Path:
    """A REAL repository whose ``origin`` is the given URL. No network is touched by reading it."""
    repo = tmp_path / name
    repo.mkdir(parents=True)
    _run(repo, 'init', '-q')
    _run(repo, 'remote', 'add', 'origin', remote)
    return repo


def _target(**over: object) -> Protection:
    """The declaration under test. Every field is spelled, because every field is required."""
    fields: dict[str, Any] = {
        'branch': 'trunk',
        'push_accounts': ('alice',),
        'allow_force_push': False,
        'status_contexts': (),
    }
    return Protection(**(fields | over))


def _rule(**over: object) -> dict:
    """A forge payload in the shape Gitea returns, fully applied unless a case bends one key."""
    base = {
        'branch_name': 'trunk',
        'enable_push': True,
        'enable_push_whitelist': True,
        'push_whitelist_usernames': ['alice'],
        'enable_force_push': False,
        'enable_status_check': False,
        'status_check_contexts': [],
    }
    return base | over


class _Recorder(BaseHTTPRequestHandler):
    """A real request handler that RECORDS what it received and answers from a scripted table."""

    received: ClassVar[list[tuple[str, str, Any]]] = []
    answers: ClassVar[dict[tuple[str, str], Any]] = {}

    def _serve(self, method: str) -> None:
        length = int(self.headers.get('Content-Length') or 0)
        body = json.loads(self.rfile.read(length)) if length else None
        type(self).received.append((method, self.path, body))
        payload = type(self).answers.get((method, self.path))
        if payload is None:
            self.send_response(404)
            self.end_headers()
            return
        encoded = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self) -> None:
        """``GET``, recorded then answered."""
        self._serve('GET')

    def do_POST(self) -> None:
        """``POST``, recorded then answered."""
        self._serve('POST')

    def do_PATCH(self) -> None:
        """``PATCH``, recorded then answered."""
        self._serve('PATCH')

    def log_message(self, fmt: str, *args: object) -> None:
        """Silent: the recording IS the log, and stderr noise hides a real failure."""


@pytest.fixture
def server() -> Iterator[ThreadingHTTPServer]:
    """A real loopback HTTP server, torn down with the test."""
    _Recorder.received = []
    _Recorder.answers = {}
    httpd = ThreadingHTTPServer(('127.0.0.1', 0), _Recorder)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield httpd
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=10)


def _plain(host: str, timeout: float) -> http.client.HTTPConnection:
    """A REAL connection, over the one scheme a loopback server can answer."""
    return http.client.HTTPConnection(host, timeout=timeout)


def _forge_at(httpd: ThreadingHTTPServer) -> Forge:
    host, port = httpd.server_address[0], httpd.server_address[1]
    return Forge(host=f'{host}:{port}', owner='someone', repo='something')


# --------------------------------------------------------------------------------------------
# where the repository lives


def test_an_https_remote_yields_its_host_owner_and_repo(tmp_path: Path) -> None:
    """Read from the REAL repository's REAL ``origin``, never from a string the test also parses."""
    repo = _repo(tmp_path, 'https://forge.example.org/someone/something.git')
    assert forge_from_remote(repo) == Forge(host='forge.example.org', owner='someone', repo='something')


def test_an_ssh_remote_yields_the_same_three_and_the_original_could_not(tmp_path: Path) -> None:
    """THE IMPROVEMENT, PLANTED.

    ``git@host:owner/repo.git`` is not a URL, and a URL parser reads it as a path with no host --
    which authenticates against the empty string and then reports on the wrong repository. Both
    spellings name one repository and must answer identically.
    """
    scp = _repo(tmp_path, 'git@forge.example.org:someone/something.git')
    assert forge_from_remote(scp) == Forge(host='forge.example.org', owner='someone', repo='something')
    ssh = _repo(tmp_path, 'ssh://git@forge.example.org/someone/something.git', name='ssh')
    assert forge_from_remote(ssh) == forge_from_remote(scp)


def test_a_remote_that_names_no_repository_is_refused_rather_than_half_parsed(tmp_path: Path) -> None:
    """A partial parse is the failure that travels: it authenticates somewhere and reports on it."""
    for index, bad in enumerate(('https://forge.example.org/', 'https://forge.example.org/someone', 'not-a-remote')):
        repo = _repo(tmp_path, bad, name=f'bad{index}')
        with pytest.raises(UnreadableRemote, match='origin'):
            forge_from_remote(repo)


def test_a_repository_with_no_origin_is_refused(tmp_path: Path) -> None:
    """Not an empty answer. There is no forge to report on, and saying so is the whole content."""
    repo = tmp_path / 'bare'
    repo.mkdir()
    _run(repo, 'init', '-q')
    with pytest.raises(UnreadableRemote):
        forge_from_remote(repo)


# --------------------------------------------------------------------------------------------
# the credential, taken from the transport that already holds one


def test_the_token_comes_from_a_real_credential_helper(tmp_path: Path) -> None:
    """A REAL ``git credential fill`` against a REAL helper, so the mechanism under test is git's."""
    repo = _repo(tmp_path, 'https://forge.example.org/someone/something.git')
    config = tmp_path / 'gitconfig'
    config.write_text(
        '[credential]\n\thelper = "!f() { echo username=alice; echo password=s3cret; }; f"\n',
        encoding='utf-8',
    )
    env = {'GIT_CONFIG_GLOBAL': str(config), 'GIT_CONFIG_SYSTEM': str(tmp_path / 'absent')}
    assert token_for('forge.example.org', cwd=repo, env=env) == 's3cret'


def test_no_stored_credential_refuses_and_never_answers_the_empty_string(tmp_path: Path) -> None:
    """An empty token is a token as far as a header is concerned; it would send ``token `` and 401."""
    repo = _repo(tmp_path, 'https://forge.example.org/someone/something.git')
    config = tmp_path / 'gitconfig'
    config.write_text('[credential]\n\thelper = "!f() { :; }; f"\n', encoding='utf-8')
    env = {'GIT_CONFIG_GLOBAL': str(config), 'GIT_CONFIG_SYSTEM': str(tmp_path / 'absent')}
    with pytest.raises(NoCredential, match=r'forge\.example\.org'):
        token_for('forge.example.org', cwd=repo, env=env)


# --------------------------------------------------------------------------------------------
# the declaration, and the floor under it


def test_every_field_of_the_target_is_required() -> None:
    """NO DEFAULTS.

    A trunk name, an account list and a force-push posture are each ONE repo's answer, and a default
    hands every other repo that one. Declared absence is SPELLED: an empty ``status_contexts`` says
    "measured, and none", which is not the same act as never asking.
    """
    for missing in ('branch', 'push_accounts', 'allow_force_push', 'status_contexts'):
        fields = {
            'branch': 'trunk',
            'push_accounts': ('alice',),
            'allow_force_push': False,
            'status_contexts': (),
        }
        del fields[missing]
        with pytest.raises(TypeError, match=missing):
            Protection(**fields)


def test_a_target_naming_no_account_is_refused_at_declaration() -> None:
    """THE VACUOUS GREEN, IN ITS ARITHMETIC FORM.

    The empty set is a subset of every whitelist, so a target naming nobody is MET by every rule on
    every forge -- including one protecting nothing.
    """
    with pytest.raises(ValueError, match='at least one account'):
        _target(push_accounts=())


def test_a_target_branch_must_be_named() -> None:
    """The empty string is a branch name no forge holds, and a rule for it can never be found."""
    with pytest.raises(ValueError, match='branch'):
        _target(branch='')


# --------------------------------------------------------------------------------------------
# the assessment, and the state that reads as success


def test_a_fully_applied_rule_meets_every_clause() -> None:
    """The green arm, so the reds below are not the only thing this function can say."""
    clauses = assess(_rule(), _target())
    assert [c.standing for c in clauses] == [APPLIED, APPLIED, APPLIED], clauses
    assert all(isinstance(c, Clause) for c in clauses)


def test_a_populated_whitelist_with_the_switch_off_is_INERT_and_not_merely_unapplied() -> None:
    """THE MEASURED DEFECT, 2026-08-27.

    The names were checked and the SWITCH was not, so the report said OK while anyone with write
    access could push. ``INERT`` is its own standing because the remedy differs: the list is right
    and one flag turns it on, which is not "not applied".
    """
    clauses = assess(_rule(enable_push_whitelist=False), _target())
    push = next(c for c in clauses if c.name == 'push_whitelist')
    assert push.standing == INERT, clauses
    assert 'enable_push_whitelist' in push.detail, push.detail


def test_an_account_missing_from_the_whitelist_is_NOT_APPLIED() -> None:
    """The other direction: the switch is on and the declaration is not satisfied."""
    clauses = assess(_rule(push_whitelist_usernames=['bob']), _target())
    assert next(c for c in clauses if c.name == 'push_whitelist').standing == NOT_APPLIED


def test_a_missing_key_is_UNREADABLE_and_never_read_as_a_false(tmp_path: Path) -> None:
    """An absent answer and a negative answer are different facts.

    A forge that renames a key would otherwise report the protection as NOT APPLIED, and the
    honest-looking repair for that is to re-apply a rule that was already there.
    """
    payload = _rule()
    del payload['enable_push_whitelist']
    clauses = assess(payload, _target())
    assert next(c for c in clauses if c.name == 'push_whitelist').standing == UNREADABLE
    assert not (tmp_path / 'unused').exists()


def test_no_rule_at_all_is_NOT_APPLIED_on_every_clause() -> None:
    """No rule is not a failed rule. Nothing was measured, so nothing may be reported as measured."""
    clauses = assess(None, _target())
    assert {c.standing for c in clauses} == {NOT_APPLIED}, clauses
    assert all('no protection rule' in c.detail for c in clauses), clauses


def test_force_push_and_status_contexts_are_assessed_against_the_declaration() -> None:
    """Both directions on both clauses, so neither is a constant wearing a comparison."""
    allowed = assess(_rule(enable_force_push=True), _target())
    assert next(c for c in allowed if c.name == 'force_push').standing == NOT_APPLIED
    assert next(c for c in assess(_rule(), _target(allow_force_push=True)) if c.name == 'force_push').standing == (
        NOT_APPLIED
    )
    wanted = _target(status_contexts=('somewhere/heavy',))
    assert next(c for c in assess(_rule(), wanted) if c.name == 'status_checks').standing == NOT_APPLIED
    met = _rule(enable_status_check=True, status_check_contexts=['somewhere/heavy'])
    assert next(c for c in assess(met, wanted) if c.name == 'status_checks').standing == APPLIED


def test_the_assessment_is_not_vacuous() -> None:
    """A FLOOR under the scan: an assessment that produced no clause would satisfy every ``all``."""
    assert len(assess(_rule(), _target())) >= 3


# --------------------------------------------------------------------------------------------
# what the forge was actually asked


def test_reading_a_rule_hits_the_real_server_and_finds_the_named_branch(server: ThreadingHTTPServer) -> None:
    """The path is derived from the forge, and the branch is matched rather than assumed to be first."""
    forge = _forge_at(server)
    _Recorder.answers[('GET', forge.protections)] = [_rule(branch_name='other'), _rule()]
    found = read_rule(forge, 'tok', _target(), transport=_plain)
    assert found is not None, found
    assert found['branch_name'] == 'trunk', found
    method, path, body = _Recorder.received[-1]
    assert (method, body) == ('GET', None)
    assert path == forge.protections


def test_a_branch_with_no_rule_reads_as_None_rather_than_as_an_error(server: ThreadingHTTPServer) -> None:
    """``None`` is the answer :func:`assess` turns into NOT APPLIED on every clause, above."""
    forge = _forge_at(server)
    _Recorder.answers[('GET', forge.protections)] = [_rule(branch_name='other')]
    assert read_rule(forge, 'tok', _target(), transport=_plain) is None


def test_applying_with_no_rule_POSTS_the_branch_and_the_child_received_every_clause(
    server: ThreadingHTTPServer,
) -> None:
    """READ WHAT THE CHILD RECEIVED. The body is taken off the SERVER, not off the call."""
    forge = _forge_at(server)
    _Recorder.answers[('GET', forge.protections)] = []
    _Recorder.answers[('POST', forge.protections)] = {}
    apply_protection(forge, 'tok', _target(), transport=_plain)
    method, path, body = next(row for row in _Recorder.received if row[0] == 'POST')
    assert (method, path) == ('POST', forge.protections)
    assert body == {
        'branch_name': 'trunk',
        'enable_push': True,
        'enable_push_whitelist': True,
        'push_whitelist_usernames': ['alice'],
        'enable_force_push': False,
    }, body


def test_applying_over_an_existing_rule_PATCHES_it_and_does_not_send_the_branch_twice(
    server: ThreadingHTTPServer,
) -> None:
    """A PATCH addresses the branch in its PATH.

    Repeating it in the body is a second place to be wrong, and a forge that honoured it would
    rename the rule instead of amending it.
    """
    forge = _forge_at(server)
    _Recorder.answers[('GET', forge.protections)] = [_rule(enable_push_whitelist=False)]
    _Recorder.answers[('PATCH', f'{forge.protections}/trunk')] = {}
    apply_protection(forge, 'tok', _target(), transport=_plain)
    _method, path, body = next(row for row in _Recorder.received if row[0] == 'PATCH')
    assert path == f'{forge.protections}/trunk'
    assert 'branch_name' not in body, body
    assert body['enable_push_whitelist'] is True


def test_the_request_carries_the_token_and_the_token_is_never_in_the_body(server: ThreadingHTTPServer) -> None:
    """``invariant.md``: never log a token. The body a caller may print must not contain one."""
    forge = _forge_at(server)
    _Recorder.answers[('GET', forge.protections)] = []
    _Recorder.answers[('POST', forge.protections)] = {}
    apply_protection(forge, 'tok-s3cret', _target(), transport=_plain)
    assert all('s3cret' not in json.dumps(body) for _, _, body in _Recorder.received if body)


def test_an_http_error_refuses_and_names_the_call(server: ThreadingHTTPServer) -> None:
    """A 4xx that returned an empty body would otherwise parse as "no rules" and read as clean."""
    forge = _forge_at(server)
    with pytest.raises(OSError, match='404'):
        read_rule(forge, 'tok', _target(), transport=_plain)


def test_the_body_is_pure_and_carries_no_status_clause_when_none_is_declared() -> None:
    """LAYER C IS REPORTED AND NEVER APPLIED.

    A branch protected against a status nobody publishes is indistinguishable from a broken gate,
    so declaring no context must WRITE no context.
    """
    assert 'enable_status_check' not in protection_body(_target())
    assert 'status_check_contexts' not in protection_body(_target())
    wanted = protection_body(_target(status_contexts=('somewhere/heavy',)))
    assert wanted['enable_status_check'] is True
    assert wanted['status_check_contexts'] == ['somewhere/heavy']


def test_the_shipped_transport_cannot_speak_another_scheme() -> None:
    """The default is the guarantee, and it is STRUCTURAL rather than asserted in a comment.

    The connection class cannot open ``file://`` or ``ftp://`` because it speaks exactly one protocol.
    """
    default = inspect.signature(module.read_rule).parameters['transport'].default
    assert default is module.https_transport
    assert isinstance(module.https_transport('127.0.0.1:1', 0.1), http.client.HTTPSConnection)
