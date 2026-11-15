"""``upgrade --follow``: a host upgrades ITSELF to the tip of the branch ``[ops.upgrade] follow`` declares.

User ruling 2026-11-13: a forge host should not need a consent code per dev-lab upgrade. The DECLARATION is the
authorization: ``follow`` is a boundary key (:mod:`dev_lab.ops.configdoor`), so it is set only by a consented
``config apply``, and from then on the ``schedule`` timer (rendered by :mod:`dev_lab.ops.install`) runs this verb.
No ``follow`` -- today's behaviour: upgrades are the consented plan step or the operator's bare verb only.

One tick reads the branch into a persistent bare cache (``<home>/upgrade-follow/source.git``, so a tick fetches
only what moved) and judges the step from the installed sha to the branch tip:

* the tip IS the installed sha, or is behind it (the host runs a newer line): nothing to do, nothing recorded;
* the installed sha is not an ancestor of the tip (a rewritten or foreign branch): REFUSED -- not a fast-forward;
* the installed sha is an ancestor but not on the tip's FIRST-PARENT line (it reached the branch only through a
  merged side branch): REFUSED -- the host never stood on this branch's line;
* otherwise the tip is installed by THE SAME PATH every upgrade takes (:func:`dev_lab.ops.upgrade.run`): the lock's
  family pins, the self-check, and on a failed check the rollback to the installed sha.

Every attempt that is not a no-op is ONE audit line (``from``, ``to``, ``result``, ``detail``, ``at``) in
``<home>/upgrade-follow/audit.jsonl``, and a refusal or a failure is alerted -- once while it stands: a tick that
would repeat the last line exactly records and alerts nothing.
"""

from __future__ import annotations

import json
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import lab_commons.launch as _door
from lab_commons.temp import TEMP_PREFIX

from dev_lab.dev.gitenv import unlocated
from dev_lab.dev.netverb import run_network_verb
from dev_lab.ops import upgrade
from dev_lab.ops.config import OpsConfig
from dev_lab.ops.statelock import exclusive

__all__ = ['AUDIT', 'Line', 'LineReader', 'follow', 'read_line']

#: The audit file, under ``[ops] home``.
AUDIT: Final = 'upgrade-follow/audit.jsonl'
_CACHE: Final = 'upgrade-follow/source.git'


@dataclass(frozen=True)
class Line:
    """The followed branch as seen from the installed sha: its tip, dev-lab's lock there, and how the two relate."""

    tip: str
    lock: str
    behind: bool
    fast_forward: bool
    on_line: bool


#: ``(source, branch, installed sha) -> Line``.
type LineReader = Callable[[str, str, str], Line]


def _git(repo: Path, *args: str) -> tuple[int, str]:
    done = _door.run(['git', '-C', str(repo), *args], check=False, capture_output=True, text=True, encoding='utf-8',
                     env=unlocated())  # fmt: skip
    return done.returncode, done.stdout


def read_line(source: str, branch: str, installed: str, *, cache: Path | None = None) -> Line:
    """Fetch *branch* of *source* into *cache* (a scratch repo when ``None``) and relate its tip to *installed*."""
    if cache is None:
        with tempfile.TemporaryDirectory(prefix=f'{TEMP_PREFIX}follow-') as scratch:
            return read_line(source, branch, installed, cache=Path(scratch) / 'source.git')
    if not (cache / 'HEAD').is_file():
        cache.mkdir(parents=True, exist_ok=True)
        _git(cache, 'init', '-q', '--bare')
    ref = f'refs/follow/{branch}'
    report = run_network_verb(['git', '-C', str(cache), 'fetch', '-q', '--no-tags', source, f'+{branch}:{ref}'],
                              env=unlocated())  # fmt: skip
    if not report.ok:
        raise ValueError(report.remedy)
    tip = _git(cache, 'rev-parse', ref)[1].strip()
    code, lock = _git(cache, 'show', f'{tip}:uv.lock')
    if code != 0:
        msg = f'{branch} at {tip} holds no uv.lock'
        raise ValueError(msg)
    known = _git(cache, 'cat-file', '-e', f'{installed}^{{commit}}')[0] == 0
    ancestor = known and _git(cache, 'merge-base', '--is-ancestor', installed, tip)[0] == 0
    behind = known and _git(cache, 'merge-base', '--is-ancestor', tip, installed)[0] == 0
    on_line = ancestor and installed in _git(cache, 'rev-list', '--first-parent', tip)[1].split()
    return Line(tip=tip, lock=lock, behind=behind, fast_forward=ancestor, on_line=on_line)


def _last(path: Path) -> dict[str, str]:
    try:
        rows = path.read_text(encoding='utf-8').splitlines()
    except FileNotFoundError:
        return {}
    return json.loads(rows[-1]) if rows else {}


def _record(config: OpsConfig, alert: Callable[[str, str], bool], row: dict[str, str]) -> None:
    """Append *row* and alert a non-install -- unless the last line already says exactly this."""
    path = config.home / AUDIT
    if {key: value for key, value in _last(path).items() if key != 'at'} == row:
        return
    with path.open('a', encoding='utf-8') as audit:
        audit.write(json.dumps({**row, 'at': datetime.now(UTC).isoformat(timespec='seconds')}) + '\n')
    if row['result'] != 'installed':
        alert(f'upgrade --follow {row["result"].upper()}: {row["to"][:12]}', row['detail'])


def follow(
    config: OpsConfig,
    *,
    alert: Callable[[str, str], bool],
    line: LineReader | None = None,
    install: upgrade.Runner | None = None,
    probe: upgrade.Runner = upgrade.run_check,
    fetch: upgrade.Fetcher = upgrade.fetch_lock,
    candidate: Callable[[OpsConfig], str | None] | None = None,
) -> tuple[int, str]:
    """One tick (see the module docstring); the exit code (0 done or nothing to do, 1 rolled back, 2 refused)."""
    role = config.upgrade
    if role is None or not role.follow:
        return 2, f'refused: {config.path} declares no follow in [ops.upgrade]; upgrades stay consented'
    old = upgrade.commit(config, probe)
    if not old:
        return 2, 'refused: no installed dev-lab commit is recordable (direct_url.json), so no rollback is possible'
    state = config.home / AUDIT
    with exclusive(state.parent):
        seen = (line or (lambda s, b, i: read_line(s, b, i, cache=config.home / _CACHE)))(role.source, role.follow, old)
        if seen.tip == old or seen.behind:
            return 0, f'nothing to do: dev-lab {old} is at or ahead of {role.follow} ({seen.tip})'
        row = {'from': old, 'to': seen.tip}
        if not seen.fast_forward:
            why = f'refused: {seen.tip} ({role.follow}) is not a fast-forward from the installed {old}'
            _record(config, alert, {**row, 'result': 'refused', 'detail': why})
            return 2, why
        if not seen.on_line:
            why = f'refused: the installed {old} is not on the first-parent line of {role.follow} at {seen.tip}'
            _record(config, alert, {**row, 'result': 'refused', 'detail': why})
            return 2, why

        def pinned(source: str, ref: str) -> tuple[str, str]:  # the tip judged IS the tip installed
            return (seen.tip, seen.lock) if ref == role.ref else fetch(source, ref)

        installer = {'install': install} if install is not None else {}
        code, said = upgrade.run(config, **installer, probe=probe, fetch=pinned, candidate=candidate)
        result = 'installed' if code == 0 else 'rolled-back' if 'restored' in said else 'failed'
        _record(config, alert, {**row, 'result': result, 'detail': said})
    return (0 if code == 0 else 1), said
