"""The ``[ops.probe]`` role: the forge probe's repos, read-only tokens, schedule and account.

A plain declaration read by :func:`dev_lab.ops.config.load`, split from it as :mod:`dev_lab.ops.judgerole` is.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from dev_lab.dev.forge import forge_of_url
from dev_lab.ops.placement import Placement
from dev_lab.ops.served import served

__all__ = ['Probe']


@dataclass(frozen=True)
class Probe(Placement):
    """The forge probe (:mod:`dev_lab.ops.probe`): the repos it reads, a READ-ONLY token per forge, when, as whom.

    ``repos`` are clone URLs on any forge -- its own set, as break-glass's is; ``tokens`` maps each forge host to the
    file holding that forge's probe token (refused as :class:`Breakglass` refuses its own); ``state`` the directory
    of what was already alerted; ``schedule`` the timer's ``OnCalendar``; ``user`` the account it runs as, which must
    read the token files.
    """

    user: str
    schedule: str
    state: str
    repos: tuple[str, ...] = ()
    tokens: Mapping[str, str] = field(default_factory=dict[str, str])

    def __post_init__(self) -> None:
        """Refuse a declaration that lies (see :func:`~dev_lab.ops.served.served`)."""
        served(self.repos, self.tokens, '[ops.probe]')

    def token_file(self, url: str) -> str:
        """The file holding the probe token of *url*'s forge."""
        return self.tokens[forge_of_url(url).host]
