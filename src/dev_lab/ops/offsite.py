"""THE OFF-SITE COPY: each backup file into an S3-compatible bucket, as the store measured on 2026-11-03 allows.

What Oracle Object Storage measured, encoded as the rule for EVERY store:

* the bucket's retention rule forbids overwrite -- so no key is ever written twice: every key is
  ``<label>/<stamp>/<name>-<sha256[:16]>.<ext>`` (:func:`key_for`), unique by content and time;
* the credential cannot create multipart uploads -- so every file goes up as ONE ``PutObject``, and a file above the
  single-PUT limit (``max_put_bytes``, 5 GB on S3) is refused before anything is sent;
* path-style addressing -- the AWS CLI config file must say ``s3 = addressing_style = path``;
* the remote size is read back after each PUT and must equal the local size.

THE AWS CLI, NOT boto3: no new dependency (the runtime set is pinned by name), and ``aws s3api put-object`` IS one
``PutObject`` call -- never multipart, whichever transfer client is installed (the classic-vs-CRT question applies
only to the high-level ``aws s3 cp``, which this never uses).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

import lab_commons.launch as _door

from dev_lab.ops.backup import BackupRefused
from dev_lab.ops.backuprole import Offsite

__all__ = ['AwsCli', 'Store', 'key_for', 'upload']


class Store(Protocol):
    """An object store that writes one object per call and reads its size back."""

    def put(self, key: str, path: Path) -> None:
        """Write *path* as object *key* in one request."""
        ...

    def size(self, key: str) -> int | None:
        """The stored size of *key*, ``None`` when it is absent."""
        ...


def _digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open('rb') as data:
        for block in iter(lambda: data.read(1 << 20), b''):
            sha.update(block)
    return sha.hexdigest()


def key_for(label: str, stamp: str, path: Path) -> str:
    """``<label>/<stamp>/<stem>-<sha256[:16]><suffix>``: never the same key for different content or time."""
    return f'{label}/{stamp}/{path.stem}-{_digest(path)[:16]}{path.suffix}'


def upload(site: Offsite, store: Store, stamp: str, files: Sequence[Path]) -> list[str]:
    """Put every file (each checked against the single-PUT limit first), verifying each remote size; the keys.

    Raises:
        BackupRefused: a file above ``max_put_bytes`` (before any PUT), or a remote size that differs.

    """
    if big := [f'{path.name} ({path.stat().st_size} B)' for path in files if path.stat().st_size > site.max_put_bytes]:
        msg = f'above the single-PUT limit of {site.max_put_bytes} B: {big}'
        raise BackupRefused(msg)
    keys = []
    for path in files:
        key = key_for(site.label, stamp, path)
        store.put(key, path)
        stored, local = store.size(key), path.stat().st_size
        if stored != local:
            msg = f'{key}: remote size {stored} differs from local {local}'
            raise BackupRefused(msg)
        keys.append(key)
    return keys


class AwsCli:
    """:class:`Store` over ``aws s3api`` with the site's endpoint, region, profile and files."""

    def __init__(self, site: Offsite) -> None:
        """Refuse a config that does not address the store path-style."""
        config = Path(site.config_file) if site.config_file else None
        text = config.read_text(encoding='utf-8') if config and config.is_file() else ''
        if 'addressing_style' not in text or 'path' not in text:
            msg = f'{site.config_file or "the AWS CLI config"} must set s3 = addressing_style = path'
            raise ValueError(msg)
        self._site = site
        self._aws = shutil.which(site.aws) or site.aws

    def _run(self, *args: str) -> str:
        site = self._site
        argv = [self._aws, 's3api', *args, '--bucket', site.bucket, '--endpoint-url', site.endpoint, '--output', 'json']
        argv += ['--region', site.region] if site.region else []
        argv += ['--profile', site.profile] if site.profile else []
        env = {**os.environ, 'AWS_CONFIG_FILE': site.config_file}
        env |= {'AWS_SHARED_CREDENTIALS_FILE': site.credentials_file} if site.credentials_file else {}
        done = _door.run(argv, capture_output=True, text=True, encoding='utf-8', check=False, timeout=3600, env=env)
        if done.returncode != 0:
            msg = f'aws s3api {args[0]} failed (exit {done.returncode}): {done.stderr.strip()[:400]}'
            raise OSError(msg)
        return done.stdout

    def put(self, key: str, path: Path) -> None:
        """One ``PutObject``."""
        self._run('put-object', '--key', key, '--body', str(path))

    def size(self, key: str) -> int | None:
        """``HeadObject``'s ``ContentLength``."""
        try:
            return int(json.loads(self._run('head-object', '--key', key))['ContentLength'])
        except OSError:
            return None
