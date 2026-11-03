"""The ssh key fingerprint read from sshd's ExposeAuthInfo record matches ``ssh-keygen -l``'s SHA256 form."""

from __future__ import annotations

import base64
import hashlib
from pathlib import Path

from dev_lab.ops.sshkey import fingerprint

_BLOB = b'\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20' + bytes(range(32))


def test_the_publickey_line_gives_the_sha256_fingerprint(tmp_path: Path) -> None:
    record = tmp_path / 'auth'
    record.write_text(f'publickey ssh-ed25519 {base64.b64encode(_BLOB).decode()}\n', encoding='utf-8')
    expected = 'SHA256:' + base64.b64encode(hashlib.sha256(_BLOB).digest()).decode().rstrip('=')
    assert fingerprint(str(record)) == expected


def test_no_record_or_no_key_is_empty(tmp_path: Path) -> None:
    record = tmp_path / 'auth'
    record.write_text('keyboard-interactive\npublickey ssh-ed25519 !!notbase64!!\n', encoding='utf-8')
    assert fingerprint(str(record)) == ''
    assert fingerprint(str(tmp_path / 'absent')) == ''
    assert fingerprint('') == ''
