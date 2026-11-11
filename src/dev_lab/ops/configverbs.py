"""``ops config apply|tick``: the config door's two verbs, wired to a host's loader, checks and alerts.

Split out of :mod:`dev_lab.ops.__main__` (2026-11-10, MODULE-SIZE-ALARM): the door's rules live in
:mod:`dev_lab.ops.configdoor`; this module reads the candidate (``--from`` or ``[ops.config]``'s reviewed file)
and reports what the door did.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from lab_commons.log import emit

from dev_lab.ops import configdoor, upgrade
from dev_lab.ops.config import OpsConfig, load
from dev_lab.ops.consent.credential import ConsentRefused
from dev_lab.ops.forgeaccounts import Redeem

__all__ = ['apply', 'source_text', 'tick']

#: Raise one alert ``(title, detail)`` through the host's channels.
type Alert = Callable[[str, str], object]


def source_text(config: OpsConfig, candidate: Path | None) -> configdoor.Fetched:
    """``--from <file>`` when given (no family file), else ``[ops.config]``'s reviewed files (:func:`.fetch`)."""
    if candidate is not None:
        return configdoor.Fetched(candidate.read_text(encoding='utf-8'))
    if config.config_source is None:
        msg = f'{config.path} declares no [ops.config] source and no --from <file> was given'
        raise configdoor.ConfigRefused(msg)
    return configdoor.fetch(config.config_source, run=configdoor.git_with_env)


def apply(
    config: OpsConfig,
    candidate: Path | None,
    credential: str,
    *,
    alert: Alert,
    redeemer: Callable[[], Callable[[str], Redeem]],
    subject: bool = False,
) -> int:
    """``config apply [--from <file>] [--credential <file>] [--subject]``: the one config door (:mod:`.configdoor`).

    ``--subject`` prints the digest an ``ops.config`` credential must name for this candidate, and applies nothing:
    what a preflight compares with the plan's grant before any code is spent.
    """
    try:
        if subject:
            fetched = source_text(config, candidate)
            emit(configdoor.digest(fetched.host, fetched.family))
            return 0
        redeem_ = redeemer()(configdoor.ACTION) if credential else None
        granted = json.loads(Path(credential).read_text(encoding='utf-8')) if credential else None
        fetched = source_text(config, candidate)
        done = configdoor.apply(
            config.path, fetched.host, loads=load, checks=upgrade.checks(config),
            run=upgrade.run_check, redeem=redeem_, credential=granted, family=fetched.family,
        )  # fmt: skip
    except (configdoor.ConfigRefused, ConsentRefused) as refused:
        emit(f'refused: {refused}', err=True)
        return 2
    if not done.changed:
        emit('[ops config] unchanged')
        return 0
    emit(f'[ops config] applied; changed {list(done.changed)}; boundary {list(done.boundary)}; backup {done.backup}')
    alert('config applied', f'changed {list(done.changed)}; boundary {list(done.boundary)}')
    return 0


def tick(config: OpsConfig, *, alert: Alert) -> int:
    """``config tick``: apply the merged source's routine change; park a boundary one and alert the user once."""
    try:
        fetched = source_text(config, None)
        said = configdoor.tick(
            config.path, fetched.host, pending=config.home / 'config-pending.sha256',
            notify=lambda detail: alert('config needs consent', detail), loads=load,
            checks=upgrade.checks(config), run=upgrade.run_check, family=fetched.family,
        )  # fmt: skip
    except configdoor.ConfigRefused as refused:
        emit(f'refused: {refused}', err=True)
        alert('config tick FAILED', str(refused))
        return 1
    emit(f'[ops config] tick: {said}')
    return 0
