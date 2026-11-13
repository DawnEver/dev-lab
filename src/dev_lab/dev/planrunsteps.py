"""PLANRUN STEPS: the steps file a plan runs -- one step per grant, on its host or here -- and how a step is invoked.

Split out of :mod:`dev_lab.dev.planrun` (preflight, the run and the CLI); the file's shape is that module's docstring.
"""

from __future__ import annotations

import hashlib
import json
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
]

#: Runs a local client verb (``forge`` argv words); ``(merged output, exit status)``.
type Local = Callable[[Sequence[str]], tuple[str, int]]


#: A host's remote, by its dest.
type Remotes = Callable[[str], Remote]


#: The action whose step changes the host's config -- and so may install the sudo doors of the steps after it.
CONFIG_ACTION: Final = 'ops.config'


#: Where a carried credential lives on the host, relative to the session account's home (umask 077).
REMOTE_DIR: Final = '.dev-lab/consent'


#: A grant redeemed HERE rather than on a host: action -> (its ``forge`` client verb, the machine-file table naming
#: that client's endpoint). The step adds ``--credential <id>``.
LOCAL_VERBS: Final[Mapping[str, tuple[tuple[str, ...], str]]] = {
    'breakglass.wave': (('breakglass', 'open'), 'breakglass'),
}


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


def _step(index: int, step: object, action: str, data: dict[str, Any], dest: str) -> Step:
    name = f'step {index + 1}'
    if isinstance(step, dict) and step.get('local') is True and set(step) == {'local'}:
        if action not in LOCAL_VERBS:
            msg = f'{name} is local, but {action} is redeemed on a host; local steps: {sorted(LOCAL_VERBS)}'
            raise ConsentRefused(msg)
        return Step(LOCAL_VERBS[action][0], local=True)
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
    if 'stdout_local' in step and not _relative(step['stdout_local']):
        msg = f'{name} stdout_local is {step["stdout_local"]!r}: a relative name under the private state, no ..'
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


def _relative(name: str) -> bool:
    """*name* is a non-empty relative path on every platform, with no ``..`` part."""
    pure = PureWindowsPath(name)
    return bool(name) and not (pure.drive or pure.root or PurePosixPath(name).is_absolute()) and '..' not in pure.parts


def stdout_path(name: str, home: Path | None = None) -> Path:
    """Where a ``stdout_local`` *name* is kept: ``outputs/<name>`` under :func:`.consentguard.state_dir`."""
    return state_dir(home) / 'outputs' / name


def shown_output(step: Step, said: str, status: int, home: Path | None) -> str:
    """What the run prints of *step*'s output: its last line, or -- for ``stdout_local`` -- where it was kept."""
    if step.stdout_local is None:
        return last_line(said)
    if status:
        return 'output withheld (stdout_local)'
    path, data = stdout_path(step.stdout_local, home), said.encode('utf-8')
    write_private(path, said)
    return f'wrote {path} (sha256 {hashlib.sha256(data).hexdigest()[:12]}, {len(data)} bytes)'


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
    """Run ``python -m dev_lab.dev.forge`` *words* here; ``(merged output, exit status)``."""
    argv = [sys.executable, '-m', 'dev_lab.dev.forge', *words]
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
