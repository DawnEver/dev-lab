"""WHICH SSH KEY CONNECTED: the fingerprint of the key that authenticated this session, from sshd's own record.

sshd's ``ExposeAuthInfo yes`` (rendered by :mod:`dev_lab.ops.install`) writes the methods that authenticated the
session to a file it names in ``$SSH_USER_AUTH`` -- one ``publickey <type> <base64 blob>`` line for a key. The
sudoers line keeps that one variable, so the root-run role reads it and records the key's ``SHA256:`` fingerprint
(the form ``ssh-keygen -l`` and sshd's log print) in the wave and its summary (the audit report).
"""

from __future__ import annotations

import base64
import binascii
import hashlib
from pathlib import Path
from typing import Final

__all__ = ['ENV', 'fingerprint']

#: The variable sshd names its authentication record in.
ENV: Final = 'SSH_USER_AUTH'
#: A key's line: method, key type, base64 blob.
_FIELDS: Final = 3


def fingerprint(auth_file: str) -> str:
    """The ``SHA256:<base64>`` fingerprint of the first public key in *auth_file*; ``''`` when there is none."""
    try:
        lines = Path(auth_file).read_text(encoding='utf-8').splitlines() if auth_file else []
    except OSError:
        return ''
    for line in lines:
        parts = line.split()
        if len(parts) >= _FIELDS and parts[0] == 'publickey':
            try:
                blob = base64.b64decode(parts[2], validate=True)
            except (ValueError, binascii.Error):
                continue
            return 'SHA256:' + base64.b64encode(hashlib.sha256(blob).digest()).decode().rstrip('=')
    return ''
