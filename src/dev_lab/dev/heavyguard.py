"""NO-LOCAL-HEAVY, the agent's half: a command launching a repo's DECLARED heavy entry is refused on a workstation.

User ruling 2026-11-26: a repo's core optimization programs never run on a workstation -- one froze the whole box and
the user had to kill it. They run on the forge, an HPC executor or a declared compute host. The RUNTIME refusal is
the entry's own (:func:`lab_commons.box.heavy.require`, called first in its ``main``); this row names the door
before the command is ever started, and a heavy test is never run where the capability is absent
(:func:`mark_heavy_tests`, the family pytest plugin).

THE ENTRIES ARE THE REPO'S DATA, never this kit's. A repo declares them in its ``pyproject.toml``::

    [tool.dev_lab.heavy]
    modules = ["pkg.campaign_driver"]           # python -m <module>
    scripts = ["examples/run_search.py", "examples/benchmarks/"]  # python <script>; a trailing / is every one under it
    bins = ["optimizer"]                         # cargo run --bin <bin>, or the built target/<profile>/<bin>

:func:`heavy_rules` renders them into ONE row of the repo's ``deny-rules.json`` (its adoption module's
``LOCAL_RULES``); a pytest selection of the heavy need marker (:data:`lab_commons.box.heavy.CAPABILITY`) is part of
every such row. The pattern is a PREFILTER: the host is judged by ``asks`` (:func:`main` ``--admit``), so the same row
admits the command on a compute host, and the user's approval words on the line
(:data:`lab_commons.hostenv.HEAVY_APPROVED_ENV`) admit it for that run.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO, Final

from lab_commons.box.heavy import CAPABILITY, DOOR, RULE, refusal
from lab_commons.hostenv import HEAVY_APPROVED_ENV

from dev_lab.dev.disclosure import details_for
from dev_lab.dev.hooks import DenyRule

if TYPE_CHECKING:
    import pytest

__all__ = ['KEYS', 'TABLE', 'Heavy', 'declared', 'heavy_rules', 'main', 'mark_heavy_tests', 'pattern']

#: Where a repo declares its heavy entries.
TABLE: Final = '[tool.dev_lab.heavy]'
#: Every key the table declares, each a list of strings.
KEYS: Final = ('modules', 'scripts', 'bins')

#: Leading environment assignments, quoted values included.
_ENVS: Final = r"""(?:[A-Za-z_]\w*=(?:"[^"]*"|'[^']*'|\S*)\s+)*"""
#: An interpreter, optionally through ``uv run`` and its options, then the interpreter's own options.
_PYTHON: Final = (
    r'(?:uv\s+run\s+(?:--?[\w-]+(?:[\s=](?!python)[^\s-]\S*)?\s+)*)?'
    r'\S*python[\w.]*(?:\.exe)?\s+(?:-\S+\s+)*'
)
_END: Final = r'(?=$|[\s;&|)])'
_APPROVED: Final = re.compile(rf'\b{HEAVY_APPROVED_ENV}=(?:"[^"\s][^"]*"|\'[^\'\s][^\']*\'|[^\s"\']+)')


@dataclass(frozen=True)
class Heavy:
    """A repo's declared heavy entries."""

    modules: tuple[str, ...] = ()
    scripts: tuple[str, ...] = ()
    bins: tuple[str, ...] = ()


def declared(manifest: Mapping[str, object]) -> Heavy | None:
    """The :data:`TABLE` of a parsed ``pyproject.toml``, or ``None`` when the repo declares none.

    Raises:
        ValueError: an unknown key, or a value that is not a list of non-empty strings -- each named.

    """
    tool = manifest.get('tool', {})
    dev = tool.get('dev_lab', {}) if isinstance(tool, Mapping) else {}
    table = dev.get('heavy') if isinstance(dev, Mapping) else None
    if table is None:
        return None
    if not isinstance(table, Mapping):
        msg = f'{TABLE} must be a table of {", ".join(KEYS)}'
        raise TypeError(msg)
    bad = [f'unknown key {key!r} (keys: {", ".join(KEYS)})' for key in table if key not in KEYS]
    bad += [
        f'{key} must be a list of non-empty strings'
        for key in KEYS
        if not (isinstance(table.get(key, []), list) and all(isinstance(v, str) and v for v in table.get(key, [])))
    ]
    if bad:
        msg = f'{TABLE}: {"; ".join(bad)}'
        raise ValueError(msg)
    return Heavy(*(tuple(table.get(key, [])) for key in KEYS))


def _script(script: str) -> str:
    """A declared script as a path pattern, either separator; a trailing ``/`` declares every script under it."""
    spelled = re.escape(script.rstrip('/')).replace('/', r'[\\/]')
    return rf'{spelled}[\\/]\S+\.py' if script.endswith('/') else spelled


def pattern(heavy: Heavy) -> str:
    """The prefilter: each declared entry's launch shape, and a pytest or verify selection of the heavy marker."""
    forms = [rf'{_PYTHON}-m\s+{re.escape(module)}(?:\.__main__)?{_END}' for module in heavy.modules]
    forms += [rf'{_PYTHON}(?:\S*[\\/])?{_script(script)}{_END}' for script in heavy.scripts]
    forms += [rf'cargo\s+run\b[^\n;&|]*\s--bin[\s=]+{re.escape(b)}{_END}' for b in heavy.bins]
    forms += [rf'\S*target[\\/](?:release|debug)[\\/]{re.escape(b)}(?:\.exe)?{_END}' for b in heavy.bins]
    marker = rf'["\']?{CAPABILITY}["\']?{_END}'
    forms += [
        rf'(?:{_PYTHON}-m\s+)?pytest\b[^\n;&|]*\s-m\s+{marker}',
        rf'{_PYTHON}-m\s+dev_lab\.dev\.verify\b[^\n;&|]*\s--part\s+(?:\S*\+)?{CAPABILITY}(?:\+\S*)?{_END}',
    ]
    return _ENVS + '(?:' + '|'.join(forms) + ')'


def _examples(heavy: Heavy) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """The commands the row refuses and permits, derived from the declaration: the row's own controls."""
    python = '.venv/Scripts/python.exe'
    refuses = [f'{python} -m {m} run set.toml' for m in heavy.modules]
    refuses += [f'{python} {s}{"bench.py" if s.endswith("/") else ""} --flag' for s in heavy.scripts]
    refuses += [f'cargo run --release --bin {b}' for b in heavy.bins]
    refuses += [f'{python} -m pytest -m {CAPABILITY} tests', f'{python} -m dev_lab.dev.verify --part {CAPABILITY}']
    permits = [f'{python} -m {m}_helpers' for m in heavy.modules]
    permits += [f'git add {s}' for s in heavy.scripts]
    permits += [f'cargo build --bin {b}' for b in heavy.bins]
    permits += ['cargo test -p core --lib', f'{python} -m pytest -m "not {CAPABILITY}" tests']
    return tuple(refuses), tuple(permits)


def heavy_rules(root: Path) -> tuple[DenyRule, ...]:
    """The NO-LOCAL-HEAVY row of the repo at *root*, or none when its ``pyproject.toml`` declares no :data:`TABLE`."""
    manifest = root / 'pyproject.toml'
    heavy = declared(tomllib.loads(manifest.read_text(encoding='utf-8'))) if manifest.is_file() else None
    if heavy is None:
        return ()
    refuses, permits = _examples(heavy)
    return (
        DenyRule(
            id=RULE,
            pattern=pattern(heavy),
            matches='command',
            asks='dev_lab.dev.heavyguard',
            hazard='a heavy compute entry saturates every core and the memory of the box it starts on; on a '
            'workstation one froze the whole system (user ruling 2026-11-26).',
            remedy=DOOR.replace('`python -m', '`{python} -m'),  # the engine names the interpreter
            refuses=refuses,
            permits=permits,
        ),
    )


def _admit_refusal(payload: Mapping[str, object]) -> str | None:
    """The refusal for a hook *payload* whose command the row's prefilter matched; ``None`` admits it.

    The host's two lines (:func:`lab_commons.box.heavy.refusal`) and the row's ``details:`` pointer: a refusal's shape.
    """
    tool_input = payload.get('tool_input')
    command = str(tool_input.get('command', '')) if isinstance(tool_input, Mapping) else ''
    if not command or _APPROVED.search(command):
        return None
    why = refusal(command.strip().splitlines()[0])
    return None if why is None else f'{why}\n{details_for(RULE)}'


def mark_heavy_tests(items: Sequence[pytest.Item], *, why: str | None) -> int:
    """Turn every collected test carrying the heavy marker into a never-run xfail naming *why*; how many it marked.

    *why* is :func:`lab_commons.box.heavy.refusal` for this host, read once by the caller; ``None`` (a host that may
    run heavy compute) marks nothing. ``run=False``: the body never starts, so no heavy work is begun to be failed.
    """
    if why is None:
        return 0
    import pytest  # noqa: PLC0415 -- the guard's --admit path never loads pytest

    heavy = [item for item in items if item.get_closest_marker(CAPABILITY) is not None]
    for item in heavy:
        item.add_marker(pytest.mark.xfail(run=False, reason=why, strict=False))
    return len(heavy)


def main(argv: Sequence[str] | None = None, *, stdin: BinaryIO | None = None, stdout: BinaryIO | None = None) -> int:
    """``--admit``: judge a shell hook payload on stdin; a refusal exits 1 with its reason on stdout."""
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.heavyguard', description=main.__doc__)
    parser.add_argument('--admit', action='store_true', required=True)
    parser.parse_args(argv)
    try:
        payload = json.loads((stdin or sys.stdin.buffer).read().decode('utf-8'))
        reason = _admit_refusal(payload) if isinstance(payload, dict) else None
    except (ValueError, OSError, RuntimeError):
        return 0
    if reason is None:
        return 0
    out = stdout or sys.stdout.buffer
    out.write(reason.encode('utf-8') + b'\n')
    out.flush()
    return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
