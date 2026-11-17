"""PLANRUN STEPS: the steps file a plan runs -- one step per grant, on its host or here -- and how a step is invoked.

Split out of :mod:`dev_lab.dev.planrun` (preflight, the run and the CLI); the file's shape is that module's docstring.
"""

from __future__ import annotations

import hashlib
import json
import re
import shlex
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Final

import lab_commons.launch as _door

from dev_lab.dev import forgesecrets
from dev_lab.dev.consentguard import state_dir
from dev_lab.dev.planremote import Remote
from dev_lab.ops import forgeprotection
from dev_lab.ops.consent.credential import ConsentRefused
from dev_lab.ops.consent.plan import Plan
from dev_lab.ops.totp import write_private

__all__ = [
    'CONFIG_ACTION',
    'LOCAL_VERBS',
    'REMOTE_DIR',
    'Local',
    'LocalVerb',
    'Remotes',
    'Step',
    'Steps',
    'last_line',
    'load_steps',
    'ops_command',
    'run_local',
    'shown_output',
    'stdout_path',
    'step_stdin',
    'token_step',
]

#: Runs a local client verb (``[module, *words]``); ``(merged output, exit status)``.
type Local = Callable[[Sequence[str]], tuple[str, int]]


#: A host's remote, by its dest.
type Remotes = Callable[[str], Remote]


#: The action whose step changes the host's config -- and so may install the sudo doors of the steps after it.
CONFIG_ACTION: Final = 'ops.config'


#: Where a carried credential lives on the host, relative to the session account's home (umask 077).
REMOTE_DIR: Final = '.dev-lab/consent'


@dataclass(frozen=True)
class LocalVerb:
    """How a grant redeemed HERE runs: ``python -m <module> <words>``, the endpoint's machine-file table.

    *verbs* empty: *words* is the whole verb and a step is ``{"local": true}``. Else the step names its own argv
    (``{"local": true, "argv": [verb, ...]}``) whose first word is one of *verbs* -- the request the credential's
    subject names, which the verb derives and redeems against.
    """

    module: str
    words: tuple[str, ...]
    table: str
    verbs: frozenset[str] = frozenset()


#: A grant redeemed HERE rather than on a host, by action. The step adds ``--credential <id>``.
LOCAL_VERBS: Final[Mapping[str, LocalVerb]] = {
    'breakglass.wave': LocalVerb('dev_lab.dev.forge', ('breakglass', 'open'), 'breakglass'),
    'hpcaccount.ci-cron': LocalVerb(
        'dev_lab.dev.hpcaccount', (), 'consent',
        frozenset({'ci-pause', 'ci-pause-fleet', 'ci-resume', 'ci-resume-fleet'}),
    ),
}  # fmt: skip


_LOCAL_S: Final = 600.0


@dataclass(frozen=True)
class Step:
    """One grant's step: ops *argv* on *dest* (with that host's *config* and *python*), or a *local* client verb."""

    argv: tuple[str, ...]
    dest: str = ''
    config: str = ''
    python: str = ''
    stdin_local: str | None = None
    stdin_task: str | None = None
    stdout_local: str | None = None
    local: bool = False
    forge: str = ''
    config_host: str = ''


@dataclass(frozen=True)
class Steps:
    """A steps file, every default resolved: one :class:`Step` per grant, in the plan's order."""

    steps: tuple[Step, ...]


_HOST_KEYS: Final = {'argv', 'stdin_local', 'stdin_task', 'stdout_local', 'config', 'python', 'forge', 'config_host'}


def _local_step(name: str, action: str, argv: object) -> Step:
    if action not in LOCAL_VERBS:
        msg = f'{name} is local, but {action} is redeemed on a host; local steps: {sorted(LOCAL_VERBS)}'
        raise ConsentRefused(msg)
    verb = LOCAL_VERBS[action]
    if not verb.verbs:
        if argv is not None:
            msg = f'{name} grants {action}, whose local step is {{"local": true}}: it names no argv'
            raise ConsentRefused(msg)
        return Step((verb.module, *verb.words), local=True)
    if not (isinstance(argv, list) and argv and all(isinstance(word, str) for word in argv)) or (
        argv[0] not in verb.verbs or '--credential' in argv
    ):
        msg = (f'{name} grants {action}: {{"local": true, "argv": [one of {sorted(verb.verbs)}, ...]}}, '
               'never --credential (the runner adds it)')  # fmt: skip
        raise ConsentRefused(msg)
    return Step((verb.module, *verb.words, *argv), local=True)


def _step(index: int, step: object, action: str, data: dict[str, Any], dest: str) -> Step:
    name = f'step {index + 1}'
    if isinstance(step, dict) and step.get('local') is True and set(step) <= {'local', 'argv'}:
        return _local_step(name, action, step.get('argv'))
    argv = step.get('argv') if isinstance(step, dict) else None
    if not (isinstance(argv, list) and argv and all(isinstance(word, str) for word in argv)) or (
        set(step) - _HOST_KEYS or not all(isinstance(step.get(key, ''), str) for key in _HOST_KEYS - {'argv'})
    ):
        msg = (f'{name} is {{"argv": [ops verb words...], "stdin_local"? | "stdin_task"?, "config"?, '
               '"stdout_local"?, "python"?: "<str>"} or {"local": true}')  # fmt: skip
        raise ConsentRefused(msg)
    if {'stdin_local', 'stdin_task'} <= set(step):
        msg = f'{name} names both stdin_local and stdin_task: exactly one source feeds its stdin'
        raise ConsentRefused(msg)
    if 'stdout_local' in step and (fault := _stdout_fault(step['stdout_local'], argv)):
        msg = f'{name} {fault}'
        raise ConsentRefused(msg)
    if action in LOCAL_VERBS:
        msg = f'{name} grants {action}, which is redeemed here: {{"local": true}}'
        raise ConsentRefused(msg)
    if 'forge' in step and action != forgeprotection.ACTION:
        msg = f'{name} names forge, which only an {forgeprotection.ACTION} step derives its subject from'
        raise ConsentRefused(msg)
    if 'config_host' in step and (action != CONFIG_ACTION or '--from' in argv):
        msg = (f'{name} names config_host, which only an {CONFIG_ACTION} step reading its reviewed source (no --from) '
               'derives its subject from')  # fmt: skip
        raise ConsentRefused(msg)
    if '--credential' in argv or '--subject' in argv:
        msg = f'{name} names --credential or --subject itself: the runner adds them'
        raise ConsentRefused(msg)
    return Step(
        tuple(argv), dest, step.get('config', str(data['config'])),
        step.get('python', str(data['python'])), step.get('stdin_local'), step.get('stdin_task'),
        step.get('stdout_local'), forge=step.get('forge', ''), config_host=step.get('config_host', ''),
    )  # fmt: skip


def _stdout_fault(name: str, argv: Sequence[str]) -> str:
    """Why ``stdout_local`` *name* is refused on a step running *argv*; ``''`` when it is fine."""
    if token_step(argv):
        return 'mints tokens: each lands in its own outputs/<login>-<name>.token by itself; drop stdout_local'
    return '' if _relative(name) else f'stdout_local is {name!r}: a relative name under the private state, no ..'


def _relative(name: str) -> bool:
    """*name* is a non-empty relative path on every platform, with no ``..`` part."""
    pure = PureWindowsPath(name)
    return bool(name) and not (pure.drive or pure.root or PurePosixPath(name).is_absolute()) and '..' not in pure.parts


def stdout_path(name: str, home: Path | None = None) -> Path:
    """Where a ``stdout_local`` *name* is kept: ``outputs/<name>`` under :func:`.consentguard.state_dir`."""
    return state_dir(home) / 'outputs' / name


#: The ops verbs whose OUTPUT is secret: every token they print lands in its own file, never on the terminal.
_TOKEN_VERBS: Final = (('forge', 'token', 'mint'), ('forge', 'token', 'mint-batch'))


#: A login or token name safe as a file-name part.
_NAME: Final = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]*')


def token_step(argv: Sequence[str]) -> bool:
    """*argv* mints forge tokens (``forge token mint`` / ``mint-batch``): its output carries secrets."""
    return tuple(argv[:3]) in _TOKEN_VERBS


def _flag(argv: Sequence[str], flag: str) -> str:
    return argv[argv.index(flag) + 1] if flag in argv[:-1] else ''


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()[:12]


def _tokens(argv: Sequence[str], said: str) -> list[tuple[str, str]] | None:
    """``(name, token)`` per token *said* prints; ``None`` when any non-blank line is not one (never truncated).

    ``mint-batch`` prints one ``{"name": N, "token": T}`` line per item; ``mint`` prints its bare token once.
    """
    lines = [line.strip() for line in said.splitlines() if line.strip()]
    if argv[2] == 'mint':
        name = _flag(argv, '--name')
        ok = len(lines) == 1 and not lines[0].startswith(('{', 'refused')) and ' ' not in lines[0]
        return [(name, lines[0])] if ok and _NAME.fullmatch(name) else None
    found = []
    for line in lines:
        try:
            item = json.loads(line)
        except ValueError:
            return None
        if not (isinstance(item, dict) and set(item) == {'name', 'token'} and isinstance(item['token'], str)
                and isinstance(item['name'], str) and _NAME.fullmatch(item['name']) and item['token']):  # fmt: skip
            return None
        found.append((item['name'], item['token']))
    return found or None


def _token_output(step: Step, said: str, status: int, home: Path | None) -> tuple[str, bool]:
    """Each token *said* carries to ``outputs/<login>-<name>.token``; else the raw output kept, named, refused.

    A failed batch may still have printed the tokens it minted before failing: they are kept the same way. The ops
    verb's own ``refused: ...`` lines carry no secret and are shown.
    """
    refusal = [line.strip() for line in said.splitlines() if line.strip().startswith('refused: ')]
    whole, said = said, '\n'.join(line for line in said.splitlines() if not line.strip().startswith('refused: '))
    login, why = _flag(step.argv, '--login'), ' '.join(refusal) or 'no output'
    tokens = _tokens(step.argv, said) if _NAME.fullmatch(login) else None
    if tokens is None:
        if not said.strip():
            return why, not status
        raw = stdout_path(f'{login if _NAME.fullmatch(login) else "unnamed"}-{_sha(whole)}.raw', home)
        write_private(raw, whole)
        return (f'output carries a secret but did not parse as tokens; kept unread, owner-only, at {raw} '
                f'(sha256 {_sha(whole)}) -- place each token from it, then delete it'), False  # fmt: skip
    wrote = []
    for name, token in tokens:
        path = stdout_path(f'{login}-{name}.token', home)
        write_private(path, token + '\n')
        wrote.append(f'{path} (sha256 {_sha(token)})')
    return f'wrote {len(wrote)} token file(s): {", ".join(wrote)}' + (f'; {why}' if refusal else ''), True


def shown_output(step: Step, said: str, status: int, home: Path | None) -> tuple[str, bool]:
    """``(what the run prints of *step*'s output, it was handled)``; ``False`` only for an unparsed secret.

    A token step's tokens each land in their own file (:func:`_token_output`); a ``stdout_local`` step's output is
    kept whole; any other step shows its last line.
    """
    if token_step(step.argv):
        return _token_output(step, said, status, home)
    if step.stdout_local is None:
        return last_line(said), True
    if status:
        return 'output withheld (stdout_local)', True
    path, data = stdout_path(step.stdout_local, home), said.encode('utf-8')
    write_private(path, said)
    return f'wrote {path} (sha256 {hashlib.sha256(data).hexdigest()[:12]}, {len(data)} bytes)', True


def load_steps(path: Path, plan: Plan) -> Steps:
    """The steps file at *path* for *plan*, each step on its grant's host; :class:`ConsentRefused` names the fault."""
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict) or set(data) != {'config', 'python', 'steps'}:
        msg = 'a steps file is a JSON object with exactly config, python and steps'
        raise ConsentRefused(msg)
    steps = data['steps']
    if not isinstance(steps, list) or len(steps) != len(plan.grants):
        listed = len(steps) if isinstance(steps, list) else 'no'
        msg = f'the steps file lists {listed} steps; the plan grants {len(plan.grants)}: one step per grant, in order'
        raise ConsentRefused(msg)
    grants = plan.grants
    return Steps(tuple(_step(i, step, grants[i]['action'], data, grants[i]['host']) for i, step in enumerate(steps)))


def ops_command(step: Step, words: Sequence[str], *, sudo: str = 'sudo -n') -> str:
    """The shell line running ``dev_lab.ops`` *words* on *step*'s host under *sudo* (``sudo -n -l`` asks the door)."""
    argv = [step.python, '-m', 'dev_lab.ops', '--config', step.config, *words]
    return f'{sudo} {shlex.join(argv)}'


def run_local(words: Sequence[str]) -> tuple[str, int]:
    """Run ``python -m`` *words* (``[module, *verb words]``) here; ``(merged output, exit status)``."""
    argv = [sys.executable, '-m', *words]
    done = _door.run(argv, capture_output=True, text=True, encoding='utf-8', check=False, timeout=_LOCAL_S)
    return done.stdout + done.stderr, done.returncode


def step_stdin(step: Step) -> bytes | None:
    """The bytes of *step*'s ``stdin_local`` file or ``stdin_task`` bundle, read here; ``None`` when it has neither."""
    if step.stdin_task is not None:
        return forgesecrets.stored_bundle(step.stdin_task).encode('utf-8')
    return None if step.stdin_local is None else Path(step.stdin_local).read_bytes()


def last_line(output: str) -> str:
    """The last non-blank line of *output*, stripped; ``''`` when it has none."""
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    return lines[-1] if lines else ''
