"""The ``[ops.backup]`` role and its ``offsite`` table, as :func:`dev_lab.ops.config.load` builds them."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field

from dev_lab.ops.mirrors import mirror_host, mirror_name
from dev_lab.ops.placement import Placement

__all__ = ['Backup', 'Offsite']


@dataclass(frozen=True)
class Offsite:
    """The off-site copy of each backup: an S3-compatible bucket, written by single PUTs only.

    ``label`` is the first segment of every object key; ``profile`` / ``config_file`` / ``credentials_file`` name the
    AWS CLI profile and files holding the store's key; ``max_put_bytes`` is the single-PUT limit (5 GB on S3).
    """

    endpoint: str
    bucket: str
    label: str
    region: str = ''
    profile: str = ''
    config_file: str = ''
    credentials_file: str = ''
    max_put_bytes: int = 5_000_000_000
    aws: str = 'aws'


@dataclass(frozen=True)
class Backup(Placement):
    """The backup role, either side or both: EXPORT on the forge host, PULL (and off-site copy) on the backup host.

    Export (``dumpers`` non-empty): the ``account`` whose forced command is ``ops backup export``, the ``keys`` of the
    pullers, the dumpers' own settings. Pull (``source`` non-empty): ``<account>@<host>`` with a dedicated
    ``identity`` key, the ``dest`` directory, the ``user`` and ``schedule`` of the timer, ``retention_days``, and an
    optional ``offsite`` table (:class:`Offsite`).

    The ``git_mirror`` dumper reads ``mirrors`` (clone URLs on any forge), keeps a ``git clone --mirror`` of each
    under ``mirror_cache`` (persistent, so each export only fetches what is new) and bundles each into the export.
    ``mirror_metadata`` adds each repo's pulls (with reviews and head statuses) and issues as JSON, read through the
    forge's API with the read token in ``mirror_tokens[<host>]`` (a file), anonymously for a host naming none. A
    ``git_mirror`` with no mirror or no cache, one repository twice, or a token no mirror uses is refused at load.
    """

    dumpers: tuple[str, ...] = ()
    account: str = ''
    keys: tuple[str, ...] = ()
    tmp: str = ''
    gitea_binary: str = 'gitea'
    gitea_config: str = ''
    gitea_workdir: str = ''
    gitea_user: str = 'gitea'
    pg_database: str = ''
    pg_user: str = 'postgres'
    source: str = ''
    identity: str = ''
    dest: str = ''
    user: str = 'backup'
    schedule: str = ''
    retention_days: int = 14
    offsite: Offsite | None = None
    mirrors: tuple[str, ...] = ()
    mirror_cache: str = ''
    mirror_metadata: bool = False
    mirror_tokens: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Refuse a ``git_mirror`` declaration that lies (see the class docstring)."""
        if 'git_mirror' not in self.dumpers:
            declared = zip(
                _MIRROR_KEYS, (self.mirrors, self.mirror_cache, self.mirror_metadata, self.mirror_tokens), strict=True
            )
            if declared := [key for key, value in declared if value]:
                msg = (
                    f'[ops.backup] {", ".join(declared)} set but dumpers names no git_mirror: nothing would be mirrored'
                )
                raise ValueError(msg)
            return
        if not self.mirrors:
            msg = '[ops.backup] git_mirror names no mirror: declare mirrors = ["<clone url>", ...]'
            raise ValueError(msg)
        if not self.mirror_cache:
            msg = '[ops.backup] git_mirror needs mirror_cache (the persistent directory the mirrors live in)'
            raise ValueError(msg)
        names = [mirror_name(url) for url in self.mirrors]
        if len(set(names)) != len(names):
            msg = f'[ops.backup] mirrors name one repository twice: {names}'
            raise ValueError(msg)
        if secret := [mirror_name(url) for url in self.mirrors if _PASSWORD.match(url)]:
            msg = (
                f'[ops.backup] mirrors {secret} carry a password in the URL; it would persist in the mirror cache '
                'and reach messages: use an ssh key or the git credential store'
            )
            raise ValueError(msg)
        hosts = {mirror_host(url) for url in self.mirrors}
        if unused := sorted(set(self.mirror_tokens) - hosts):
            msg = f'[ops.backup.mirror_tokens] {", ".join(unused)} serves no mirror'
            raise ValueError(msg)


#: The ``mirror_*`` keys only the ``git_mirror`` dumper reads.
_MIRROR_KEYS = ('mirrors', 'mirror_cache', 'mirror_metadata', 'mirror_tokens')
#: A URL whose userinfo carries a password (``scheme://<user>:<password>@host/...``).
_PASSWORD = re.compile(r'^[a-z][a-z0-9+.-]*://[^/@]*:[^/@]*@', re.IGNORECASE)
