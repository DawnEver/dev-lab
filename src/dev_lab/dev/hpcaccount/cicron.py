"""The consent a CI cron change redeems: ``--credential <id>`` on ``ci-pause[-fleet]`` / ``ci-resume[-fleet]``.

CI-CRON-NEEDS-CONSENT (:mod:`dev_lab.dev._deny_cicron_row`) leaves an agent two doors: the user runs the verb, or the
user grants a consent plan whose step carries a :data:`ACTION` credential. Its subject (:func:`subject`) is ONE cluster,
its sorted account list, and pause or resume; the verb derives the subject from what it is about to change and
:func:`spend` redeems the credential against it BEFORE any crontab is touched -- a credential for another cluster,
another account set or the other direction is refused without its use being registered.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any, Final

from dev_lab.dev.consentguard import state_dir
from dev_lab.ops.consent.client import public_key, redeem, remote_register
from dev_lab.ops.consent.credential import ConsentRefused

__all__ = ['ACTION', 'Redeem', 'spend', 'subject']

#: The consent registry row (:data:`dev_lab.ops.consent.actions.ACTIONS`).
ACTION: Final = 'hpcaccount.ci-cron'
#: ``ci-pause`` -> ``pause``: the direction a subject names.
_KIND: Final = {'ci-pause': 'pause', 'ci-resume': 'resume'}
_IDENT: Final = re.compile(r'[0-9A-Za-z-]{8,64}')

#: ``(credential, subject) -> None``: redeem *credential* for this change; raises :class:`ConsentRefused`.
type Redeem = Callable[[Mapping[str, Any], str], object]


def subject(verb: str, cluster: str, accounts: Iterable[str]) -> str:
    """``<pause|resume> <cluster> <account,account...>`` -- the accounts sorted, so the order never matters."""
    return f'{_KIND[verb]} {cluster} {",".join(sorted(set(accounts)))}'


def _live(credential: Mapping[str, Any], wanted: str) -> object:
    """Redeem through the machine file's ``[consent]`` issuer: verified offline, then registered."""
    return redeem(credential, action=ACTION, subject=wanted, key=public_key(), register=remote_register(),
                  now=time.time())  # fmt: skip


def spend(ident: str, wanted: str, *, redeem_with: Redeem | None = None, home: Path | None = None) -> str | None:
    """Redeem the held credential *ident* for subject *wanted*; ``None`` when it is spent, else why it is refused."""
    if not _IDENT.fullmatch(ident):
        return f'--credential {ident!r} is not a credential id'
    held = state_dir(home) / f'{ident}.json'
    try:
        (redeem_with or _live)(json.loads(held.read_text(encoding='utf-8')), wanted)
    except (ConsentRefused, OSError, ValueError) as refused:
        return f'the {ACTION} credential {ident} is refused for {wanted!r} -- {refused}'
    return None
