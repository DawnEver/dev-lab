"""``config apply``: the ONE door through which a host's supervise configuration changes (user ruling 2026-11-08).

After the lockdown no account edits ``/etc/dev-lab/supervise.toml`` by hand: the ``ops`` account may run this door
through its fixed sudo line, and the door decides what a change may touch. Routine knobs (repo lists, schedules,
thresholds, retention) change on the operator's word alone; every other key is the SECURITY BOUNDARY -- what runs as
root, as whom, who may log in and how -- and changes only with a ``ops.config`` consent credential the user granted
with their code, whose ``subject`` is the SHA-256 of exactly the candidate file (so it consents to that text, not to
"some change").

The list of routine keys is an ALLOWLIST (:data:`ROUTINE`): a key no pattern names is boundary, so a new table is
guarded until somebody argues it routine. Why so narrow: the configuration renders the sudoers line, the units' users
and interpreters and the probe commands, so a free hand on it is a free hand on root.

An accepted candidate is loaded by the CURRENT code before anything is written, the live file is backed up beside
itself, the candidate replaces it atomically, and the install self-check (:func:`dev_lab.ops.upgrade.checks`) runs;
a failed check restores the backup. The printed diff names keys, never values.

FIRST CONTACT (:func:`anchor`): a host whose live file has neither ``[ops.consent]`` nor ``[ops.consent_client]``
can verify no credential, so the table that would let it verify one could never pass the boundary. Exactly that one
table -- nothing else -- is then taken from the REVIEWED source (``[ops.config]``'s merged file, the trust root the
routine tick already uses), never from a local ``--from`` file. Once it exists, changing it is a boundary change.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import tempfile
import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from dev_lab.dev.netverb import run_network_verb
from dev_lab.dev.writeroots import TEMP_PREFIX

if TYPE_CHECKING:
    from dev_lab.ops.config import ConfigSource

__all__ = [
    'ACTION', 'ANCHOR', 'ROUTINE', 'Applied', 'ConfigRefused', 'anchor', 'apply', 'boundary', 'changes', 'digest',
    'fetch', 'git_with_env', 'tick',
]  # fmt: skip

#: The consent action a boundary change needs (:mod:`dev_lab.ops.consent.actions`).
ACTION: Final = 'ops.config'

#: The ``[ops.*]`` table a host that verifies nothing yet takes from the reviewed source with no credential.
ANCHOR: Final = 'consent_client'

#: Dotted key patterns (fnmatch) a change may touch WITHOUT consent. Everything else is the security boundary.
ROUTINE: Final[tuple[str, ...]] = (
    'cycle.*',
    'components.disk_usage.*',
    'components.host_pressure.*',
    'components.http_health.*',
    'components.process_monitor.*',
    'components.log_scanner.*',
    'components.heartbeat.*',
    'components.progress_tracker.*',
    'ops.repos',
    'ops.*.repos',
    'ops.*.schedule',
    'ops.*.tick',
    'ops.*.memory_max',
    'ops.breakglass.min_reason',
    'ops.breakglass.wave_hours_max',
    'ops.breakglass.max_merges_max',
    'ops.backup.keep*',
    'ops.backup.retention*',
)

#: Check name -> argv; each must exit 0 for the applied file to stand.
type Checks = Mapping[str, list[str]]
#: Runs one argv; its exit code and output.
type Runner = Callable[[list[str]], tuple[int, str]]
#: Redeems a credential for ACTION on one subject (:func:`dev_lab.ops.consent.client.redeem`); raises when it does not.
type Redeem = Callable[[Mapping[str, Any], str], object]
#: Runs one argv with extra environment; its exit code and output (the git clone of :func:`fetch`).
type EnvRunner = Callable[[list[str], Mapping[str, str]], tuple[int, str]]


class ConfigRefused(ValueError):
    """The candidate is refused; nothing was written."""


@dataclass(frozen=True)
class Applied:
    """What one apply did: the changed keys, which of them were boundary, and the backup it left."""

    changed: tuple[str, ...]
    boundary: tuple[str, ...]
    backup: Path | None


def digest(text: str) -> str:
    """The SHA-256 a consent credential's subject must equal to consent to exactly *text*."""
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _flat(table: Mapping[str, Any], prefix: str = '') -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in table.items():
        dotted = f'{prefix}{key}'
        if isinstance(value, Mapping):
            out |= _flat(value, f'{dotted}.')
        else:
            out[dotted] = value
    return out


def changes(old: Mapping[str, Any], new: Mapping[str, Any]) -> tuple[str, ...]:
    """Every dotted key added, removed or changed between two parsed configurations, sorted."""
    before, after = _flat(old), _flat(new)
    return tuple(sorted(key for key in before.keys() | after.keys() if before.get(key, ...) != after.get(key, ...)))


def boundary(changed: tuple[str, ...]) -> tuple[str, ...]:
    """The keys of *changed* no :data:`ROUTINE` pattern admits."""
    return tuple(key for key in changed if not any(fnmatch.fnmatchcase(key, pattern) for pattern in ROUTINE))


def git_with_env(argv: list[str], env: Mapping[str, str]) -> tuple[int, str]:
    """Run one network git through the retry door with *env* added; git's output may echo a header: never returned."""
    report = run_network_verb(argv, env=os.environ | dict(env), timeout=300)
    return report.returncode, ''


def fetch(source: ConfigSource, *, run: EnvRunner) -> str:
    """The text of ``source.path`` at the tip of ``source.ref``, cloned over HTTPS with the host's read token.

    The token goes into the git process's environment as an ``http.extraHeader`` (``GIT_CONFIG_*``), never on
    argv, and no refusal repeats git's output (it could echo the header).

    Raises:
        ConfigRefused: the clone failed or the declared file is not in it.

    """
    token = Path(source.token_file).read_text(encoding='utf-8').strip()
    env = {
        'GIT_CONFIG_COUNT': '1',
        'GIT_CONFIG_KEY_0': 'http.extraHeader',
        'GIT_CONFIG_VALUE_0': f'Authorization: token {token}',
        'GIT_TERMINAL_PROMPT': '0',
    }
    with tempfile.TemporaryDirectory(prefix=TEMP_PREFIX) as scratch:
        target = Path(scratch) / 'config-source'
        argv = ['git', 'clone', '--quiet', '--depth', '1', '--branch', source.ref, source.source, str(target)]
        status, _said = run(argv, env)
        if status != 0:
            msg = f'fetching {source.source}@{source.ref} failed (git exit {status})'
            raise ConfigRefused(msg)
        found = target / source.path
        if not found.is_file():
            msg = f'{source.source}@{source.ref} has no {source.path}'
            raise ConfigRefused(msg)
        return found.read_text(encoding='utf-8')


def _write(path: Path, text: str) -> None:
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=f'.{path.name}.')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as handle:
            handle.write(text)
        Path(temp).chmod(mode)
        Path(temp).replace(path)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise


def apply(
    live: Path, candidate: str, *, loads: Callable[[Path], object], checks: Checks, run: Runner,
    redeem: Redeem | None = None, credential: Mapping[str, Any] | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> Applied:  # fmt: skip
    """Replace *live* with *candidate* if the door admits it (see the module docstring).

    Raises:
        ConfigRefused: the candidate does not parse or load, touches the boundary without a credential that
            consents to exactly it, or failed the self-check (the backup was restored).

    """
    try:
        new = tomllib.loads(candidate)
    except tomllib.TOMLDecodeError as bad:
        msg = f'the candidate is not TOML: {bad}'
        raise ConfigRefused(msg) from bad
    old = tomllib.loads(live.read_text(encoding='utf-8'))
    changed = changes(old, new)
    guarded = boundary(changed)
    if not changed:
        return Applied((), (), None)
    if guarded:
        if credential is None or redeem is None:
            msg = f'boundary keys change and no {ACTION} consent credential was given: {list(guarded)}'
            raise ConfigRefused(msg)
        redeem(credential, digest(candidate))
    return Applied(changed, guarded, _land(live, candidate, loads=loads, checks=checks, run=run, now=now))


def _land(
    live: Path, candidate: str, *, loads: Callable[[Path], object], checks: Checks, run: Runner,
    now: Callable[[], datetime],
) -> Path:  # fmt: skip
    # loaded by the current code BEFORE the live file is touched
    with tempfile.TemporaryDirectory(prefix=TEMP_PREFIX) as scratch:
        probe = Path(scratch) / live.name
        probe.write_text(candidate, encoding='utf-8')
        try:
            loads(probe)
        except (ValueError, TypeError) as bad:
            msg = f'the current code refuses the candidate: {bad}'
            raise ConfigRefused(msg) from bad
    backup = live.with_name(f'{live.name}.bak-{now().strftime("%Y%m%dT%H%M%SZ")}')
    previous = live.read_text(encoding='utf-8')
    backup.write_text(previous, encoding='utf-8')
    _write(live, candidate)
    for name, argv in checks.items():
        status, said = run(argv)
        if status != 0:
            _write(live, previous)
            msg = f'self-check {name} failed ({status}) on the applied file; restored the previous one: {said[-400:]}'
            raise ConfigRefused(msg)
    return backup


def anchor(
    live: Path, reviewed: str, *, loads: Callable[[Path], object], checks: Checks, run: Runner,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> tuple[dict[str, str], Path] | None:  # fmt: skip
    """FIRST CONTACT: add *reviewed*'s ``[ops.consent_client]`` to *live*; the table and backup, else ``None``.

    ``None`` -- nothing written -- when *live* already declares ``[ops.consent]`` (an issuer) or the client table,
    or *reviewed* declares none. *reviewed* must be the fetched ``[ops.config]`` file, never a local candidate.

    Raises:
        ConfigRefused: the reviewed table holds a non-string value, does not load, or failed the self-check.

    """
    text = live.read_text(encoding='utf-8')
    held = tomllib.loads(text).get('ops', {})
    found = tomllib.loads(reviewed).get('ops', {}).get(ANCHOR)
    if 'consent' in held or ANCHOR in held or not isinstance(found, Mapping):
        return None
    if not all(isinstance(value, str) for value in found.values()):
        msg = f'[ops.{ANCHOR}] in the reviewed source holds a non-string value'
        raise ConfigRefused(msg)
    rows = ''.join(f'{key} = {json.dumps(value)}\n' for key, value in found.items())  # a JSON string is TOML
    candidate = f'{text.rstrip()}\n\n[ops.{ANCHOR}]\n{rows}'
    taken = dict(found)
    if tomllib.loads(candidate)['ops'][ANCHOR] != taken:
        msg = f'[ops.{ANCHOR}] did not round-trip'
        raise ConfigRefused(msg)
    return taken, _land(live, candidate, loads=loads, checks=checks, run=run, now=now)


def tick(
    live: Path, candidate: str, *, pending: Path, notify: Callable[[str], object], loads: Callable[[Path], object],
    checks: Checks, run: Runner, now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> str:  # fmt: skip
    """One scheduled pass of the door over the merged source: ``applied``, ``unchanged`` or ``needs-consent``.

    A merge is not consent. A ROUTINE change applies here with nobody present; a change touching the boundary is
    PARKED -- the live file stays, *pending* records the candidate's SHA-256 and *notify* tells the user once per
    candidate what to grant -- until ``config apply --credential`` lands it. A pass that finds nothing to do clears
    *pending*.

    Raises:
        ConfigRefused: the routine candidate does not load or failed the self-check (the backup was restored).

    """
    changed = changes(tomllib.loads(live.read_text(encoding='utf-8')), tomllib.loads(candidate))
    if not changed:
        pending.unlink(missing_ok=True)
        return 'unchanged'
    if guarded := boundary(changed):
        subject = digest(candidate)
        if not pending.is_file() or pending.read_text(encoding='utf-8').strip() != subject:
            notify(
                f'merged config touches boundary keys {list(guarded)}; it applies only with consent: grant '
                f'{ACTION} for subject {subject}, then config apply --credential <file>'
            )
            pending.write_text(f'{subject}\n', encoding='utf-8')
        return 'needs-consent'
    apply(live, candidate, loads=loads, checks=checks, run=run, now=now)
    pending.unlink(missing_ok=True)
    return 'applied'
