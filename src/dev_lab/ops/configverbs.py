"""``ops config apply|tick``: the config door's two verbs, wired to a host's loader, checks and alerts.

Split out of :mod:`dev_lab.ops.__main__` (2026-11-10, MODULE-SIZE-ALARM): the door's rules live in
:mod:`dev_lab.ops.configdoor`; this module reads the candidate (``--from`` or ``[ops.config]``'s reviewed file)
and reports what the door did. A bare ``config apply`` (no ``--from``, no credential) on a host that verifies nothing
yet first takes the consent anchor from the reviewed file (:func:`configdoor.anchor`).

AN APPLIED FILE IS RENDERED IN THE SAME STEP (2026-11-23): whatever ``install`` derives from the configuration -- the
consent and break-glass ``authorized_keys`` the client keys feed, sudoers, units -- is written by the apply (or tick)
that changed it, through the *render* the caller passes (``ops install`` on the applied file). ``install`` stays its
own verb for a host's first bring-up and a code upgrade, but no apply ever leaves an install owed: measured 2026-11-22,
a consented client key sat in ``[ops.clients]`` while the issuer refused it, because nothing rendered its key file.
"""

from __future__ import annotations

import hashlib
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
#: Render what the applied file declares (``ops install`` on it); its exit code.
type Render = Callable[[], int]


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
    render: Render,
    subject: bool = False,
) -> int:
    """``config apply [--from <file>] [--credential <file>] [--subject]``: the one config door (:mod:`.configdoor`).

    ``--subject`` prints the digest an ``ops.config`` credential must name for this candidate, and applies nothing:
    what a preflight compares with the plan's grant before any code is spent.
    """
    try:
        if subject:
            fetched = source_text(config, candidate)
            configdoor.loadable(  # a host that cannot load it has no subject; loading needs no alert environment
                fetched.host, config.path.name, lambda path: load(path, alerts=False)
            )
            emit(configdoor.digest(fetched.host, fetched.family))
            return 0
        fetched = source_text(config, candidate)
        if candidate is None and not credential:  # first contact reads only the reviewed source
            _anchor(config, fetched.host, alert=alert)
        redeem_ = redeemer()(configdoor.ACTION) if credential else None
        granted = json.loads(Path(credential).read_text(encoding='utf-8')) if credential else None
        done = configdoor.apply(
            config.path, fetched.host, loads=load, checks=upgrade.checks(config),
            run=upgrade.run_check, redeem=redeem_, credential=granted, family=fetched.family,
        )  # fmt: skip
    except (configdoor.ConfigRefused, ConsentRefused) as refused:
        emit(f'refused: {refused}', err=True)
        return 2
    return _said(done, alert=alert, render=render)


def _anchor(config: OpsConfig, reviewed: str, *, alert: Alert) -> None:
    taken = configdoor.anchor(
        config.path, reviewed, loads=load, checks=upgrade.checks(config), run=upgrade.run_check,
    )  # fmt: skip
    if taken is None:
        return
    table, backup = taken
    key = table.get('public_key', '')
    held = f'sha256:{hashlib.sha256(key.encode()).hexdigest()[:16]}' if key else 'the packaged issuer.pub'
    said = f'took [ops.{configdoor.ANCHOR}] from the reviewed source: endpoint {table.get("endpoint", "")}, key {held}'
    emit(f'[ops config] first contact: {said}; backup {backup}')
    alert('config consent anchor taken', said)


def _said(done: configdoor.Applied, *, alert: Alert, render: Render) -> int:
    if not done.changed:
        emit('[ops config] unchanged')
        return 0
    emit(f'[ops config] applied; changed {list(done.changed)}; boundary {list(done.boundary)}; backup {done.backup}')
    alert('config applied', f'changed {list(done.changed)}; boundary {list(done.boundary)}')
    return _rendered(render, alert=alert)


def _rendered(render: Render, *, alert: Alert) -> int:
    """Render the applied file now; a refused render is alerted, never left as a silent ``install`` owed."""
    emit('[ops config] rendering the applied file (ops install)')
    if (status := render()) != 0:
        alert('config applied, render FAILED', f'ops install exited {status}; the applied file is not rendered yet')
    return status


def tick(config: OpsConfig, *, alert: Alert, render: Render) -> int:
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
    return _rendered(render, alert=alert) if said == 'applied' else 0
