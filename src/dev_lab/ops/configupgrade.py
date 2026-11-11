"""Every retired ``[ops]`` shape upgraded on read (FORMATS-UPGRADE-ON-READ): the ONE place an old shape is read.

:func:`dev_lab.ops.config.load` hands the raw ``[ops]`` table here before it builds the typed config, so a host whose
file predates a change still loads, and the next ``config apply`` writes the new shape.
"""

from __future__ import annotations

from typing import Any, Final

from lab_commons.log import emit

__all__ = ['BREAKGLASS_MOVED', 'upgraded']


#: The keys #311 moved out of ``[ops.breakglass]`` (FORMATS-UPGRADE-ON-READ): the TOTP seed and the code lockout went
#: to the consent issuer; a wave's window and cap became the params of its ``breakglass.wave`` credential.
BREAKGLASS_MOVED: Final = ('totp', 'wave_hours', 'max_merges', 'lockout_after', 'lockout_minutes')
#: Where a derived issuer keeps its key and ledger when a pre-#311 host declared none.
_CONSENT_DEFAULTS: Final = {
    'account': 'consent',
    'key': '/etc/dev-lab/consent/issuer.key',
    'state': '/var/lib/dev-lab-ops/consent',
}


def _forge_accounts(ops: dict[str, Any]) -> dict[str, Any]:
    """A pre-#402 ``[ops.forge] read_only`` upgraded on read to ``accounts`` with role ``read``; both is refused.

    The old list named no repositories (``account ensure --read`` took them as arguments), so each upgraded reader
    reads the host's own served repositories on its forge (``[ops] repos`` not on github.com).
    """
    forge = ops.get('forge')
    if not isinstance(forge, dict) or 'read_only' not in forge:
        return ops
    if 'accounts' in forge:
        msg = '[ops.forge] holds both read_only (retired by #402) and accounts; keep accounts only'
        raise ValueError(msg)
    urls = [url for url in ops.get('repos', ()) if 'github.com' not in url]
    served = sorted('/'.join(url.removesuffix('.git').split('/')[-2:]) for url in urls)
    accounts = {login: {'role': 'read', 'repos': served} for login in forge['read_only']}
    emit(f'[ops] upgraded [ops.forge] read_only on read: {sorted(accounts)} -> accounts role read', err=True)
    return dict(ops, forge={**{k: v for k, v in forge.items() if k != 'read_only'}, 'accounts': accounts})


def upgraded(ops: dict[str, Any]) -> dict[str, Any]:
    """*ops* with every retired shape upgraded on read: the ONE place an old shape is read.

    ``[ops.upgrade] overrides`` (a hand-written uv override file, 2026-11-08) is dropped: the family's revisions come
    from dev-lab's own lock at the installed commit. A pre-#311 ``[ops.breakglass]``: the moved keys leave the
    break-glass table. Its ``totp`` and lockout seed the consent issuer when the file declares none (keys =
    break-glass's); a declared ``[ops.consent]`` wins. ``wave_hours``/``max_merges`` are dropped: a wave's window and
    cap are its credential's params now, and the ceilings stay where they were. A pre-#402 ``[ops.forge] read_only``
    becomes ``accounts`` (:func:`_forge_accounts`).
    """
    ops = _forge_accounts(ops)
    lifted = ops.get('upgrade')
    if isinstance(lifted, dict) and 'overrides' in lifted:
        ops = dict(ops, upgrade={key: value for key, value in lifted.items() if key != 'overrides'})
        emit('[ops] upgraded [ops.upgrade] on read: dropped overrides (the lock pins the family)', err=True)
    glass = ops.get('breakglass')
    if not isinstance(glass, dict) or not (moved := {key: glass[key] for key in BREAKGLASS_MOVED if key in glass}):
        return ops
    upgraded = dict(ops, breakglass={key: value for key, value in glass.items() if key not in moved})
    if 'consent' not in ops and 'totp' in moved:
        lockout = {key: moved[key] for key in ('lockout_after', 'lockout_minutes') if key in moved}
        keys = list(glass.get('keys', ()))
        upgraded['consent'] = {**_CONSENT_DEFAULTS, 'totp': moved['totp'], 'keys': keys, **lockout}
    emit(f'[ops] upgraded a pre-consent [ops.breakglass] on read: moved {sorted(moved)}', err=True)
    return upgraded
