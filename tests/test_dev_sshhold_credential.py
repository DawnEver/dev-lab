"""``sshhold credential``: a forge token stored on the held account WITHOUT reaching the audit, argv or disk here.

The ``run`` audit records every command verbatim, so a secret never travels as a command. ``credential`` reads
the token from stdin and sends it as heredoc DATA to the remote ``git credential approve``; the audit keeps the
url's host, the login and a sha256 prefix. PLANTED CONTROLS: the token was live this run and appears in none of
the audit, the holder's state file or the fake ssh's argv, while the fake remote receives exactly its lines.
"""

from __future__ import annotations

import hashlib
import io
import json
import sys
from pathlib import Path

import pytest

from dev_lab.dev import sshhold, sshholdrun, sshholdstate
from dev_lab.dev.sshholdwire import HoldRefused

FAKE = (sys.executable, str(Path(__file__).with_name('_sshhold_fake.py')))
PLANTED = 'gt-planted-5e7d1a'
URL = 'https://forge.example/team/repo.git'


def test_the_script_feeds_git_exactly_the_credential_lines() -> None:
    script = sshholdrun.credential_script(URL, 'ro-login', PLANTED, 'n1')
    assert 'git credential approve' in script
    lines = 'protocol=https\nhost=forge.example\nusername=ro-login\npassword=' + PLANTED + '\n'
    assert lines in script
    assert 'credential.helper' in script


@pytest.mark.parametrize(
    ('url', 'login', 'token'),
    [
        ('http://forge.example/x', 'ro-login', PLANTED),
        (URL, 'ro login', PLANTED),
        (URL, 'ro-login', 'two\nlines'),
        (URL, 'ro-login', ''),
    ],
)
def test_a_value_that_could_inject_a_line_is_refused(url: str, login: str, token: str) -> None:
    with pytest.raises(HoldRefused):
        sshholdrun.credential_script(url, login, token, 'n1')


@pytest.fixture
def held(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    out = {'cred': tmp_path / 'cred.txt', 'argv': tmp_path / 'argv.json', 'helper': tmp_path / 'helper.txt'}
    out['helper'].write_text('store', encoding='utf-8')
    monkeypatch.setenv('FAKESSH_HELPER_FILE', str(out['helper']))
    monkeypatch.setenv('FAKESSH_CODE', '')
    monkeypatch.setenv('FAKESSH_CRED_OUT', str(out['cred']))
    monkeypatch.setenv('FAKESSH_ARGV_OUT', str(out['argv']))
    sshhold.open_session('ops@fake', 1.0, '', ssh=FAKE)
    yield out
    sshhold.close_session('ops@fake')


def test_a_credential_reaches_the_remote_and_nowhere_else(held: dict[str, Path]) -> None:
    state = sshholdstate.state_path('ops@fake').read_text(encoding='utf-8')
    sshholdrun.store_credential('ops@fake', URL, 'ro-login', PLANTED)
    said = held['cred'].read_text(encoding='utf-8')
    assert said == f'protocol=https\nhost=forge.example\nusername=ro-login\npassword={PLANTED}\n'
    line = json.loads(sshholdstate.audit_path().read_text(encoding='utf-8').splitlines()[-1])
    assert line['verb'] == 'credential'
    assert (line['host'], line['login'], line['status']) == ('forge.example', 'ro-login', 0)
    assert line['sha256'] == hashlib.sha256(PLANTED.encode()).hexdigest()[:12]
    assert PLANTED not in sshholdstate.audit_path().read_text(encoding='utf-8')
    assert PLANTED not in state
    assert PLANTED not in held['argv'].read_text(encoding='utf-8')


def test_no_credential_helper_on_the_remote_is_refused_by_name(held: dict[str, Path]) -> None:
    held['helper'].write_text('', encoding='utf-8')
    with pytest.raises(HoldRefused, match='credential helper'):
        sshholdrun.store_credential('ops@fake', URL, 'ro-login', PLANTED)
    assert not held['cred'].exists()


def test_the_cli_reads_the_token_from_stdin(held: dict[str, Path], monkeypatch, capsys) -> None:
    monkeypatch.setattr('sys.stdin', io.StringIO(PLANTED + '\n'))
    assert sshhold.main(['credential', 'ops@fake', '--url', URL, '--login', 'ro-login']) == 0
    said = capsys.readouterr()
    assert PLANTED not in said.out + said.err
    assert held['cred'].read_text(encoding='utf-8').endswith(f'password={PLANTED}\n')
