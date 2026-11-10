"""``ops config apply|tick``: the config door's two verbs, wired to a host's loader, checks and alerts.

Split out of :mod:`dev_lab.ops.__main__` (2026-11-10, MODULE-SIZE-ALARM): the door's rules live in
:mod:`dev_lab.ops.configdoor`; this module reads the candidate (``--from`` or ``[ops.config]``'s reviewed file)
and reports what the door did.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping
from pathlib import Path

from lab_commons.log import emit

from dev_lab.dev.netverb import run_network_verb
from dev_lab.ops import configdoor, upgrade
from dev_lab.ops.config import OpsConfig, load
from dev_lab.ops.consent.credential import ConsentRefused
from dev_lab.ops.forgeaccounts import Redeem

__all__ = ['apply', 'source_text', 'tick']

#: Raise one alert ``(title, detail)`` through the host's channels.
type Alert = Callable[[str, str], object]


def _git_with_env(argv: list[str], env: Mapping[str, str]) -> tuple[int, str]:
    report = run_network_verb(argv, env=os.environ | dict(env), timeout=300)  # the one retry door
    return report.returncode, ''  # git's output may echo the header: never returned


def source_text(config: OpsConfig, candidate: Path | None) -> str:
    """``--from <file>`` when given, else ``[ops.config]``'s reviewed file (:func:`configdoor.fetch`)."""
    if candidate is not None:
        return candidate.read_text(encoding='utf-8')
    if config.config_source is None:
        msg = f'{config.path} declares no [ops.config] source and no --from <file> was given'
        raise configdoor.ConfigRefused(msg)
    return configdoor.fetch(config.config_source, run=_git_with_env)


def apply(
    config: OpsConfig,
    candidate: Path | None,
    credential: str,
    *,
    alert: Alert,
    redeemer: Callable[[], Callable[[str], Redeem]],
) -> int:
    """``config apply [--from <file>] [--credential <file>]``: the one config door (:mod:`dev_lab.ops.configdoor`)."""
    try:
        redeem_ = redeemer()(configdoor.ACTION) if credential else None
        granted = json.loads(Path(credential).read_text(encoding='utf-8')) if credential else None
        done = configdoor.apply(
            config.path, source_text(config, candidate), loads=load, checks=upgrade.checks(config),
            run=upgrade.run_check, redeem=redeem_, credential=granted,
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
        said = configdoor.tick(
            config.path, source_text(config, None), pending=config.home / 'config-pending.sha256',
            notify=lambda detail: alert('config needs consent', detail), loads=load,
            checks=upgrade.checks(config), run=upgrade.run_check,
        )  # fmt: skip
    except configdoor.ConfigRefused as refused:
        emit(f'refused: {refused}', err=True)
        alert('config tick FAILED', str(refused))
        return 1
    emit(f'[ops config] tick: {said}')
    return 0
