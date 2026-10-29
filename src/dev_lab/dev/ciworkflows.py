"""GitHub Actions workflows, declared in TOML and RENDERED -- YAML only because GitHub forces it.

ONE SOURCE PER LAYER: the family base is ``ci_base.toml`` beside this module; a repo's layer is
``[tool.dev_lab.ci."<file>.yml"]`` in its ``pyproject.toml``. A repo opts in to a base workflow by
declaring its table (empty takes the base as is) and may declare workflows of its own. The layers are
deep-merged (tables key by key; anything else replaces) and each workflow is written to
``.github/workflows/<file>.yml`` as JSON -- JSON is YAML, so the stdlib renders it and no YAML library
is needed. Nothing ever parses a workflow back: the drift check compares RENDERED BYTES to the file,
and a workflow file the table does not declare is refused as hand-written.

SHARED STEPS ARE DECLARED ONCE. The top-level ``_steps`` table (the base's, the repo's ``[tool.dev_lab.ci._steps]``
merged over it) names step lists; a step ``{ use-steps = "<name>" }`` in any job is replaced by that list at render,
so the setup every job repeats has one source. ``_steps`` is never a workflow and never rendered.

``python -m dev_lab.dev.ciworkflows render`` writes; ``check`` exits 1 naming every drift.
"""

from __future__ import annotations

import argparse
import json
import tomllib
from pathlib import Path
from typing import Any, Final

from lab_commons.log import emit

from dev_lab.dev.family import declared_table

__all__ = [
    'BASE_PATH', 'RENDER_COMMAND', 'SHARED', 'STAMP', 'USE_STEPS', 'WORKFLOW_DIR', 'drift', 'expand', 'merge', 'render',
    'workflows', 'write',
]  # fmt: skip

BASE_PATH: Final = Path(__file__).resolve().parent / 'ci_base.toml'

#: The top-level table of named step lists; never a workflow.
SHARED: Final = '_steps'

#: The key of a step that stands for a named list of :data:`SHARED`.
USE_STEPS: Final = 'use-steps'
WORKFLOW_DIR: Final = Path('.github') / 'workflows'
RENDER_COMMAND: Final = 'python -m dev_lab.dev.ciworkflows render'

#: The first line of every rendered workflow -- a YAML comment, so the JSON body below stays valid YAML.
STAMP: Final = (
    f'# Rendered by dev_lab.dev.ciworkflows from TOML (dev_lab/dev/ci_base.toml + '
    f'[tool.dev_lab.ci] in pyproject.toml). Hand edits are refused; edit the TOML and run `{RENDER_COMMAND}`.'
)


def merge(base: dict[str, Any], layer: dict[str, Any]) -> dict[str, Any]:
    """*layer* deep-merged over *base*: tables merge key by key, any other value replaces. PURE."""
    out = dict(base)
    for key, value in layer.items():
        out[key] = merge(out[key], value) if isinstance(value, dict) and isinstance(out.get(key), dict) else value
    return out


def expand(workflow: dict[str, Any], shared: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """*workflow* with every ``{use-steps = <name>}`` step replaced by *shared*'s list of that name. PURE.

    Raises:
        KeyError: a step names a list no ``_steps`` table declares.

    """

    def steps(job: dict[str, Any]) -> list[dict[str, Any]]:
        return [one for step in job['steps'] for one in (shared[step[USE_STEPS]] if USE_STEPS in step else [step])]

    if 'jobs' not in workflow:
        return workflow
    jobs = {name: {**job, 'steps': steps(job)} if 'steps' in job else job for name, job in workflow['jobs'].items()}
    return {**workflow, 'jobs': jobs}


def workflows(root: Path) -> dict[str, dict[str, Any]]:
    """Every workflow *root* declares, by file name, with the base merged under the ones it names."""
    base = tomllib.loads(BASE_PATH.read_text(encoding='utf-8'))
    pyproject = root / 'pyproject.toml'
    data = tomllib.loads(pyproject.read_text(encoding='utf-8')) if pyproject.is_file() else {}
    declared = dict(declared_table(data, 'ci', {}))
    shared = merge(base.get(SHARED, {}), declared.pop(SHARED, {}))
    return {name: expand(merge(base.get(name, {}), layer), shared) for name, layer in sorted(declared.items())}


def render(workflow: dict[str, Any]) -> str:
    """The file's bytes: the stamp, then the workflow as indented JSON (which GitHub reads as YAML)."""
    return f'{STAMP}\n{json.dumps(workflow, indent=2, ensure_ascii=False)}\n'


def drift(root: Path) -> list[str]:
    """Every rendered workflow that differs from its file, and every workflow file nobody declared."""
    declared = workflows(root)
    directory = root / WORKFLOW_DIR
    out = []
    for name, workflow in declared.items():
        path = directory / name
        if not path.is_file():
            out.append(f'{path}: declared and not rendered')
        elif path.read_text(encoding='utf-8') != render(workflow):
            out.append(f'{path}: differs from its TOML (hand-edited, or the TOML moved without a render)')
    if directory.is_dir():
        out += [
            f'{path}: a workflow no [tool.dev_lab.ci] table declares -- hand-written; declare it in TOML'
            for path in sorted(directory.iterdir())
            if path.suffix in {'.yml', '.yaml'} and path.name not in declared
        ]
    return out


def write(root: Path) -> list[Path]:
    """Render every declared workflow of *root* to disk; returns the paths written."""
    directory = root / WORKFLOW_DIR
    written = []
    for name, workflow in workflows(root).items():
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / name
        path.write_text(render(workflow), encoding='utf-8', newline='\n')
        written.append(path)
    return written


def main(argv: list[str] | None = None) -> int:
    """``render`` writes the workflows; ``check`` exits 1 naming each drift and the render command."""
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.ciworkflows', description=__doc__.splitlines()[0])
    parser.add_argument('verb', choices=('render', 'check'))
    parser.add_argument('--root', type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    if args.verb == 'render':
        for path in write(args.root):
            emit(f'[ciworkflows] rendered {path}')
        return 0
    found = drift(args.root)
    for line in found:
        emit(f'[ciworkflows] {line}')
    if found:
        emit(f'[ciworkflows] REFUSED -- edit the TOML, then run `{RENDER_COMMAND}`.')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
