"""``drift`` -- what an account holds that its config source cannot render. Read only; run ON the account.

THE CONFIG SOURCE IS THE TRUTH; AN ACCOUNT IS A RENDER OF IT (user ruling 2026-11-16: backing an account up is
useless, everything worth keeping is in the config source). Two renders are compared with what the account holds:

* its machine file, rendered from ``--from <clone>`` for ``--host <cluster>-<user>``
  (:func:`dev_lab.dev.devrender.render`) with NO local table carried over -- a table only the live file holds is
  exactly what a lost account loses -- diffed table-by-key against the live file;
* ``crontab -l``, against the lines the deploy writes from that render
  (:func:`~dev_lab.dev.hpcaccount.spec.cron_lines`).

Each yields three lists: ONLY ON THE ACCOUNT (drift: fold it into the config source or discard it), ONLY IN THE
RENDER (what the next render adds) and DIFFERING values. A third report, ``old copies`` (:func:`strays`), lists
what the layout before the declared root left behind, with its file count: the dry-run list for the user's ruling
(migration is a reclone; nothing removes them by hand), never config the account would lose.
A value whose key names a token, key, password or secret,
or that looks encoded (long hex or base64), is printed only as ``<redacted, sha256:xxxx>``. Nothing is written: no
render, no fetch of the clone, no crontab. Exit 0 agrees, 1 drift, 2 refused.

``python -m dev_lab.dev.hpcaccount drift --from <clone> --host <name> [--config <machine file>]``; from a
workstation, ``drift-fleet (--cluster C | --account U)...`` (:mod:`~dev_lab.dev.hpcaccount.accountset`).
"""

from __future__ import annotations

import argparse
import hashlib
import re
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from lab_commons.config import config_path
from lab_commons.hpc.grants import declared_grants
from lab_commons.log import emit

from dev_lab.dev import devrender
from dev_lab.dev._machinefile import render_value
from dev_lab.dev.backedup import replace_backed_up
from dev_lab.dev.devdeclared import OWN_TABLE
from dev_lab.dev.diskusage import count_files
from dev_lab.dev.hpcaccount import deploy
from dev_lab.dev.hpcaccount.spec import MARK, VERIFICATION, cron_lines, parse
from dev_lab.dev.hpcaccount.steps import Step, Tools
from dev_lab.dev.venvpointer import RETIRED_POINTER

__all__ = [
    'DISCARD', 'OLD_IN_HOME', 'OLD_IN_ROOT', 'STRAYS', 'Drift', 'account_drift', 'compare', 'compare_lines',
    'main', 'report', 'shown', 'strays', 'unrenderable',
]  # fmt: skip

#: The switch with which ``ci-pause`` accepts the loss of what the config source cannot render.
DISCARD: Final = '--discard-drift'
_SECRET_KEY: Final = re.compile(r'token|key|password|secret', re.IGNORECASE)
_ENCODED: Final = re.compile(r'[0-9a-fA-F]{32,}|[A-Za-z0-9+/_-]{40,}={0,2}')
_ENCODED_WORD: Final = re.compile(r'[0-9a-fA-F]{32,}|[A-Za-z0-9+_-]{40,}={0,2}')  # a path's '/' is no secret
#: The report of old copies (:func:`strays`).
STRAYS: Final = 'old copies'
#: Where the layout before the declared root kept the forge, home-relative and root-relative.
OLD_IN_HOME: Final = ('.local/share/lab-forge', 'ci', 'src/dev-lab')
OLD_IN_ROOT: Final = ('dev-lab', 'src')
_SECRET_ASSIGN: Final = re.compile(r'(token|key|password|secret)\w*\s*=', re.IGNORECASE)


@dataclass(frozen=True)
class Drift:
    """One comparison: what only the account holds, what only the render holds, and what differs."""

    only_on_account: tuple[str, ...] = ()
    only_in_render: tuple[str, ...] = ()
    differing: tuple[str, ...] = ()

    def unrenderable(self) -> tuple[str, ...]:
        """What the account would lose to a render: its own items and its differing values."""
        return self.only_on_account + self.differing


def _redacted(text: str) -> str:
    return f'<redacted, sha256:{hashlib.sha256(text.encode()).hexdigest()[:12]}>'


def shown(key: str, value: object) -> str:
    """*value* as printed under *key*: redacted when the key names a secret or the value looks encoded."""
    text = render_value(value)
    secret = _SECRET_KEY.search(key.rsplit('.', 1)[-1]) or any(_ENCODED.fullmatch(s) for s in _strings(value))
    return _redacted(text) if secret else text


def _strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        return [s for item in value.values() for s in _strings(item)]
    if isinstance(value, list | tuple):
        return [s for item in value for s in _strings(item)]
    return []


def _shown_line(line: str) -> str:
    secret = _SECRET_ASSIGN.search(line) or any(_ENCODED_WORD.fullmatch(w) for w in re.split(r'[\s=:@\'"]+', line))
    return _redacted(line) if secret else line


def _leaves(table: Mapping[str, Any], prefix: str = '') -> dict[str, Any]:
    found: dict[str, Any] = {}
    for key, value in table.items():
        dotted = f'{prefix}{key}'
        found.update(_leaves(value, f'{dotted}.') if isinstance(value, Mapping) and value else {dotted: value})
    return found


def compare(live: Mapping[str, Any], rendered: Mapping[str, Any]) -> Drift:
    """*live* against *rendered*, key by dotted key; every value passed through :func:`shown`."""
    have, want = _leaves(live), _leaves(rendered)
    return Drift(
        tuple(f'{k} = {shown(k, have[k])}' for k in sorted(set(have) - set(want))),
        tuple(f'{k} = {shown(k, want[k])}' for k in sorted(set(want) - set(have))),
        tuple(
            f'{k}: account {shown(k, have[k])}, render {shown(k, want[k])}'
            for k in sorted(set(have) & set(want))
            if have[k] != want[k]
        ),
    )


def _mark(line: str) -> str:
    return line.rpartition(MARK)[2] if MARK in line else ''


def compare_lines(held: Sequence[str], wanted: Sequence[str]) -> Drift:
    """Crontab *held* against *wanted*: a marked line of the same repo with other text DIFFERS; blanks are no drift."""
    held = [line for line in held if line.strip() and not line.lstrip().startswith('#')]
    by_mark = {_mark(line): line for line in wanted if _mark(line)}
    differing = [line for line in held if line not in wanted and _mark(line) in by_mark]
    replaced = {by_mark[_mark(line)] for line in differing}
    return Drift(
        tuple(_shown_line(line) for line in held if line not in wanted and line not in differing),
        tuple(_shown_line(line) for line in wanted if line not in held and line not in replaced),
        tuple(f'{_shown_line(line)} (render: {_shown_line(by_mark[_mark(line)])})' for line in differing),
    )


def strays(home: Path, root: Path) -> tuple[str, ...]:
    """Each old copy on the account with its file count; read only.

    :data:`OLD_IN_HOME`, :data:`OLD_IN_ROOT`, and a retired ``repos/<repo>/.venv-current`` file.
    """
    old = [home / p for p in OLD_IN_HOME] + [root / p for p in OLD_IN_ROOT]
    old += [repo / RETIRED_POINTER for repo in sorted((root / 'repos').glob('*'))]
    return tuple(f'{p.as_posix()}: {count_files(p)} files' for p in old if p.exists() or p.is_symlink())


def unrenderable(found: Mapping[str, Drift]) -> list[str]:
    """What a render would lose, ``<report>: <item>``; an old copy is no config, so :data:`STRAYS` is not in it."""
    return [f'{what}: {item}' for what, drift in found.items() if what != STRAYS for item in drift.unrenderable()]


def account_drift(step: Step, home: Path, machine: Path, clone: Path, host: str) -> dict[str, Drift] | str:
    """``{'machine file': ..., 'crontab': ...}`` for this account; else why it cannot be compared (nothing read)."""
    if not (clone / devrender.host_file(host)).is_file() or not (clone / 'family.toml').is_file():
        return (
            f'{clone.as_posix()} holds no family.toml and {devrender.host_file(host)}: deploy-fleet fetches that clone'
        )
    try:
        rendered = tomllib.loads(devrender.render(clone, host, {}))
        live = tomllib.loads(machine.read_text(encoding='utf-8')) if machine.is_file() else {}
        spec = parse(rendered, clone / devrender.host_file(host))
        grants, _ = declared_grants(rendered.get('hpc', {}))
    except (OSError, ValueError) as failed:  # TOMLDecodeError is a ValueError
        return f'cannot render {host} from {clone.as_posix()}: {failed}'
    if spec is None or spec.role != VERIFICATION:  # SCHEDULER-ONLY-FOR-SERVING: no crontab to compare, none read
        return {'machine file': compare(live, rendered)}
    listed = step.read([*step.tools.crontab, '-l'])
    if listed.returncode and 'no crontab' not in listed.stderr:
        return f'crontab -l exited {listed.returncode}: {listed.stderr.strip()}'
    held = listed.stdout.splitlines() if listed.returncode == 0 else []
    slurm = deploy.slurm_dirs()
    if isinstance(slurm, str):
        return f'the deploy lines cannot be derived: {slurm}'
    user = step.read([*step.tools.id, '-un']).stdout.strip()
    setup = next((grant.setup for grant in grants if grant.user == user), ())
    wanted = cron_lines(spec, home, slurm=slurm, setup=setup)
    found = {'machine file': compare(live, rendered), 'crontab': compare_lines(held, wanted)}
    return {**found, STRAYS: Drift(only_on_account=strays(home, Path(spec.root)))}


def report(found: Mapping[str, Drift]) -> list[str]:
    """The printed lines of *found*: each list headed, an empty list omitted."""
    lines: list[str] = []
    for what, drift in found.items():
        if what == STRAYS:
            lines += [f'{what} (nothing removes them; the dry-run list for a ruling):'] if drift.only_on_account else []
            lines += [f'  {item}' for item in drift.only_on_account]
            continue
        for title, items in (
            ('only on the account (fold into the config source, or discard)', drift.only_on_account),
            ('only in the render (the next render adds it)', drift.only_in_render),
            ('differing values', drift.differing),
        ):
            lines += [f'{what}: {title}:'] + [f'  {item}' for item in items] if items else []
    return lines


def _discard(drift: Drift, *, home: Path, machine: Path, clone: Path, host: str, dry: bool) -> int:
    """Re-render *machine* from *clone* with no account-only layer; 1 under *dry*, else 0 once written.

    The one door for keys only the account holds (measured 2026-11-20: an empty ``capabilities.femm`` had none short
    of raw ssh). The render keeps the machine file's own ``[devhost]`` table; the previous file is backed up.
    """
    items = ''.join(f'\n  {item}' for item in drift.only_on_account)
    if dry:
        emit(f'[dry-run] would discard {len(drift.only_on_account)} item(s) only {machine} holds:{items}')
        return 1
    live = tomllib.loads(machine.read_text(encoding='utf-8')) if machine.is_file() else {}
    text = devrender.render(clone, host, {key: value for key, value in live.items() if key == OWN_TABLE})
    backup = replace_backed_up(machine, text, home / '.cache' / 'dev-lab' / f'{datetime.now(UTC):%y/%m/%d}' / 'devhost')
    emit(f'discarded {len(drift.only_on_account)} item(s); re-rendered {machine}; the previous file is {backup}{items}')
    return 0


def main(argv: Sequence[str], *, home: Path | None = None, tools: Tools | None = None) -> int:
    """The on-account ``drift`` verb; 0 agrees, 1 drift, 2 refused."""
    parser = argparse.ArgumentParser(prog='dev_lab.dev.hpcaccount drift', description=__doc__.splitlines()[0])
    parser.add_argument('--from', dest='clone', type=Path, required=True, help="the account's config-source clone")
    parser.add_argument('--host', required=True, help='the account file name, <cluster>-<user>')
    parser.add_argument('--config', type=Path, help='the live machine file (default: lab_commons.config)')
    parser.add_argument(DISCARD, action='store_true', help='re-render the machine file, dropping what only it holds')
    parser.add_argument('--dry-run', action='store_true', help=f'with {DISCARD}: list what would go, write nothing')
    args = parser.parse_args(list(argv))
    home, machine, clone = home or Path.home(), args.config or config_path(), args.clone.expanduser()
    found = account_drift(Step(tools or Tools(), dry=True), home, machine, clone, args.host)
    if isinstance(found, str):
        emit(f'drift refused: {found}', err=True)
        return 2
    lines = report(found)
    if args.discard_drift and found['machine file'].only_on_account:
        return _discard(
            found['machine file'], home=home, machine=machine, clone=clone, host=args.host, dry=args.dry_run
        )
    for line in lines or [f'agrees: {args.host} holds exactly the render of {args.clone.as_posix()}']:
        emit(line)
    return 1 if lines else 0
