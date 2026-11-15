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

The FAMILY FILE (``[ops.config] family = {file, to}``) rides the same door: every fetch of the host file also takes
``file`` from the same reviewed source and ref (:func:`fetch`), and the door writes it at ``to`` (backup beside it,
mode 0644: it holds no secrets by rule -- the config source's check refuses a secret value in it -- and the judge
reads it as its own account) only when its text changed. A family change is BOUNDARY, never routine: it carries the
family's spend caps and HPC grants, so it needs an ``ops.config`` credential exactly as a boundary host key does, and
the credential's subject binds both texts (:func:`digest`) WHENEVER a family is declared -- changed or not -- so the
subject is a function of the reviewed source alone and an operator derives it with no session on the host
(:func:`local_subject`); ``config tick`` parks a boundary change as ``needs-consent``.
"""

from __future__ import annotations

import fnmatch
import hashlib
import os
import tempfile
import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from lab_commons.temp import TEMP_PREFIX

from dev_lab.dev.netverb import run_network_verb

if TYPE_CHECKING:
    from dev_lab.ops.config import ConfigSource

__all__ = [
    'ACTION', 'FAMILY_KEY', 'ROUTINE', 'Applied', 'ConfigRefused', 'Family', 'Fetched', 'apply', 'boundary', 'changes',
    'digest', 'fetch', 'git_with_env', 'loadable', 'local_subject', 'tick',
]  # fmt: skip

#: The consent action a boundary change needs (:mod:`dev_lab.ops.consent.actions`).
ACTION: Final = 'ops.config'

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

#: The name a family-file change is reported under among the changed (and boundary) keys.
FAMILY_KEY: Final = 'ops.config.family:file'

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


@dataclass(frozen=True)
class Family:
    """The family file as fetched: its *text*, and the path *to* on this host it is placed at."""

    to: Path
    text: str

    def changed(self) -> bool:
        """Whether the placed file is absent or differs from *text*."""
        return not self.to.is_file() or self.to.read_text(encoding='utf-8') != self.text


@dataclass(frozen=True)
class Fetched:
    """One fetch of the reviewed source: the host file's text, and the family file when ``[ops.config]`` declares it."""

    host: str
    family: Family | None = None


def digest(text: str, family: Family | None = None) -> str:
    """The SHA-256 a consent credential's subject must equal: exactly *text*, and the *family* text when declared.

    Never the host's state (whether the placed family file already matches): the subject depends on the reviewed
    source alone, so :func:`local_subject` derives it off the host.
    """
    if family is None:
        return hashlib.sha256(text.encode('utf-8')).hexdigest()
    bound = f'{text}\0family {family.to.as_posix()}\0{family.text}'
    return hashlib.sha256(bound.encode('utf-8')).hexdigest()


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


def fetch(source: ConfigSource, *, run: EnvRunner) -> Fetched:
    """``source.path`` (and ``source.family``'s file) at the tip of ``source.ref``, cloned over HTTPS, read token.

    One clone serves both files. The token goes into the git process's environment as an ``http.extraHeader``
    (``GIT_CONFIG_*``), never on argv, and no refusal repeats git's output (it could echo the header).

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
        texts = [_read(target, source, name) for name in (source.path, source.family.get('file'))]
    family = Family(Path(source.family['to']), texts[1]) if source.family else None
    return Fetched(texts[0], family)


#: ``(source url, path, ref)`` -> that file's text at the ref of the source, read off the host (a forge read).
type SourceReader = Callable[[str, str, str], str]


def local_subject(source: str, path: str, read: SourceReader, ref: str = 'main') -> str:
    """``config apply --subject`` of the host whose reviewed file is *path* in *source*, derived HERE.

    The host fetches what its LIVE ``[ops.config]`` declares; the candidate is assumed to declare the same table (the
    reviewed file names its own source, path, ref and family), so the table read at *ref* is followed once to the
    declared ``ref``/``path``; a declaration that still moves, or names another source, is refused: a plan that
    changes ``[ops.config]`` itself is derived by the host. Then :func:`digest` of exactly what :func:`fetch` reads.

    Raises:
        ConfigRefused: the file declares no ``[ops.config]``, names another source, or does not settle.

    """
    for _ in range(2):
        text = read(source, path, ref)
        try:
            table = tomllib.loads(text).get('ops', {}).get('config')
        except tomllib.TOMLDecodeError as bad:
            msg = f'{path}@{ref} is not TOML: {bad}'
            raise ConfigRefused(msg) from bad
        if not isinstance(table, Mapping) or not table.get('source') or not table.get('path'):
            msg = f"{path}@{ref} declares no [ops.config] source and path: its subject is the host's to derive"
            raise ConfigRefused(msg)
        if table['source'] != source:
            msg = f'{path}@{ref} names config source {table["source"]}, not {source}: derive it there'
            raise ConfigRefused(msg)
        declared = (str(table['path']), str(table.get('ref', 'main')))
        if declared == (path, ref):
            family = table.get('family') or {}
            placed = Family(Path(family['to']), read(source, family['file'], ref)) if family else None
            return digest(text, placed)
        path, ref = declared
    msg = f'{source}: [ops.config] does not settle on one path and ref (last {path}@{ref})'
    raise ConfigRefused(msg)


def _read(target: Path, source: ConfigSource, name: str | None) -> str:
    if name is None:
        return ''
    if not (found := target / name).is_file():
        msg = f'{source.source}@{source.ref} has no {name}'
        raise ConfigRefused(msg)
    return found.read_text(encoding='utf-8')


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
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


def loadable(candidate: str, name: str, loads: Callable[[Path], object]) -> None:
    """Load *candidate* with the CURRENT code, as the live file *name* would be; nothing is written.

    ``config apply`` runs it before it redeems a credential, and ``config apply --subject`` before it prints the
    subject a preflight compares -- so a host whose code predates a key the candidate declares answers BLOCKED at
    preflight instead of spending the user's code at run (#555).

    Raises:
        ConfigRefused: the current code refuses the candidate; the remedy is to upgrade the host first.

    """
    with tempfile.TemporaryDirectory(prefix=TEMP_PREFIX) as scratch:
        probe = Path(scratch) / name
        probe.write_text(candidate, encoding='utf-8')
        try:
            loads(probe)
        except (ValueError, TypeError) as bad:
            msg = (f'the current code refuses the candidate: {bad} -- upgrade first (an ops.upgrade step before this '
                   f'one, or the bare `ops upgrade` door), then apply')  # fmt: skip
            raise ConfigRefused(msg) from bad


def apply(
    live: Path, candidate: str, *, loads: Callable[[Path], object], checks: Checks, run: Runner,
    redeem: Redeem | None = None, credential: Mapping[str, Any] | None = None, family: Family | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> Applied:  # fmt: skip
    """Replace *live* with *candidate*, and place a changed *family*, if the door admits it (module docstring).

    Raises:
        ConfigRefused: the candidate does not parse or load, touches the boundary without a credential that
            consents to exactly it, or failed the self-check (the backup was restored).

    """
    try:
        new = tomllib.loads(candidate)
    except tomllib.TOMLDecodeError as bad:
        msg = f'the candidate is not TOML: {bad}'
        raise ConfigRefused(msg) from bad
    changed, guarded = _changed(live, new, family)
    if not changed:
        return Applied((), (), None)
    if guarded and (credential is None or redeem is None):
        msg = f'boundary keys change and no {ACTION} consent credential was given: {list(guarded)}'
        raise ConfigRefused(msg)
    loadable(candidate, live.name, loads)  # BEFORE the credential is spent: a refusal never costs a code (#555)
    if guarded and credential is not None and redeem is not None:  # both present: refused above otherwise
        redeem(credential, digest(candidate, family))
    if changed == (FAMILY_KEY,) and family is not None:  # only the family file moved: the host file stays
        return Applied(changed, guarded, _place(family, now))
    backup = live.with_name(f'{live.name}.bak-{_stamp(now)}')
    previous = live.read_text(encoding='utf-8')
    backup.write_text(previous, encoding='utf-8')
    _write(live, candidate)
    for name, argv in checks.items():
        status, said = run(argv)
        if status != 0:
            _write(live, previous)
            msg = f'self-check {name} failed ({status}) on the applied file; restored the previous one: {said[-400:]}'
            raise ConfigRefused(msg)
    if family is not None and FAMILY_KEY in changed:
        _place(family, now)
    return Applied(changed, guarded, backup)


def _changed(live: Path, new: Mapping[str, Any], family: Family | None) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """``(changed, boundary)`` keys of the host file, plus :data:`FAMILY_KEY` (boundary) when the family file moved."""
    changed = changes(tomllib.loads(live.read_text(encoding='utf-8')), new)
    moved = (FAMILY_KEY,) if family is not None and family.changed() else ()
    return changed + moved, boundary(changed) + moved


def _stamp(now: Callable[[], datetime]) -> str:
    return now().strftime('%Y%m%dT%H%M%SZ')


def _place(family: Family, now: Callable[[], datetime]) -> Path | None:
    """Write the changed family file at its ``to``, mode 0644, backing up the one it replaces; that backup, if any."""
    backup = None
    if family.to.is_file():
        backup = family.to.with_name(f'{family.to.name}.bak-{_stamp(now)}')
        backup.write_text(family.to.read_text(encoding='utf-8'), encoding='utf-8')
    _write(family.to, family.text)
    family.to.chmod(0o644)
    return backup


def tick(
    live: Path, candidate: str, *, pending: Path, notify: Callable[[str], object], loads: Callable[[Path], object],
    checks: Checks, run: Runner, family: Family | None = None, now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> str:  # fmt: skip
    """One scheduled pass of the door over the merged source: ``applied``, ``unchanged`` or ``needs-consent``.

    A merge is not consent. A ROUTINE change applies here with nobody present; a change touching the boundary is
    PARKED -- the live file stays, *pending* records the candidate's SHA-256 and *notify* tells the user once per
    candidate what to grant -- until ``config apply --credential`` lands it. A pass that finds nothing to do clears
    *pending*.

    Raises:
        ConfigRefused: the routine candidate does not load or failed the self-check (the backup was restored).

    """
    changed, guarded = _changed(live, tomllib.loads(candidate), family)
    if not changed:
        pending.unlink(missing_ok=True)
        return 'unchanged'
    if guarded:
        subject = digest(candidate, family)
        if not pending.is_file() or pending.read_text(encoding='utf-8').strip() != subject:
            notify(
                f'merged config touches boundary keys {list(guarded)}; it applies only with consent: grant '
                f'{ACTION} for subject {subject}, then config apply --credential <file>'
            )
            pending.write_text(f'{subject}\n', encoding='utf-8')
        return 'needs-consent'
    apply(live, candidate, loads=loads, checks=checks, run=run, family=family, now=now)
    pending.unlink(missing_ok=True)
    return 'applied'
