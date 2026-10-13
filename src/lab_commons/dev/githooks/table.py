"""The git hooks a repo runs, declared ONCE in TOML: the family base plus the repo's own layer.

ONE SOURCE PER LAYER. The base is data shipped in this package (``base.toml`` beside this module);
a repo's layer is ``[[tool.lab_commons.hooks.<stage>]]`` in its own ``pyproject.toml``. Nothing is
rendered and nothing is parsed back: :func:`hook_table` merges the two layers in memory, and the
runner (:mod:`lab_commons.dev.githooks.runner`) and the installer (:mod:`lab_commons.dev.hook_install`)
both read that one answer.

THE MERGE IS BY ``id``. A repo row naming a base id is merged over it key by key -- the way a repo
narrows one check (``exclude``) without restating it; a repo row with a new id is appended, in the
order written. A key this module does not know RAISES, as does a stage it does not know, a row with
no ``run``, a key that means nothing at its stage, and a ``run`` that hands the interpreter to
somebody else (``uv``/``uvx``): every hook runs in the repo's own venv, so a launcher that may sync,
create or swap that venv is refused when the table is read rather than discovered at commit time.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, Final

__all__ = [
    'BASE_PATH',
    'STAGES',
    'Hook',
    'HookTableError',
    'base_rows',
    'hook_table',
    'hook_table_from',
    'merge',
    'repo_rows',
]

#: The git hook types the family runs, in the order a commit then a push meets them.
STAGES: Final[tuple[str, ...]] = ('pre-commit', 'commit-msg', 'pre-push')

#: The family base, as data.
BASE_PATH: Final = Path(__file__).resolve().parent / 'base.toml'

#: Launchers that choose (and may sync or create) an interpreter of their own.
_FOREIGN_LAUNCHERS: Final = frozenset({'uv', 'uv.exe', 'uvx', 'uvx.exe'})

#: Keys meaningful only where a stage selects paths, and only where a push names refs.
_PATH_KEYS: Final = frozenset({'files', 'exclude', 'pass_files'})
_PATH_STAGES: Final = frozenset({'pre-commit', 'pre-push'})


class HookTableError(ValueError):
    """A hook declaration this module cannot run as written -- raised, never guessed around."""


@dataclass(frozen=True)
class Hook:
    """One hook at one stage, after the layers are merged."""

    stage: str
    id: str
    run: tuple[str, ...]
    files: str | None = None
    exclude: str | None = None
    pass_files: bool = False
    always_run: bool = False
    refs: str | None = None
    env: dict[str, str] = field(default_factory=dict)

    def selects(self, path: str) -> bool:
        """Whether *path* (repo-relative, POSIX) is one this hook judges."""
        if self.files is not None and not re.search(self.files, path):
            return False
        return self.exclude is None or not re.search(self.exclude, path)


_KEYS: Final = frozenset(f.name for f in fields(Hook)) - {'stage'}


def _check_selectors(stage: str, row: dict[str, Any], origin: str) -> None:
    """`files`/`exclude`/`refs`: only where the stage hands a hook paths or refs, and valid regexes."""
    if stage not in _PATH_STAGES and _PATH_KEYS & set(row):
        msg = f'{origin}: {stage} hook {row["id"]!r} selects paths, and {stage} hands a hook none'
        raise HookTableError(msg)
    if stage != 'pre-push' and 'refs' in row:
        msg = f'{origin}: {stage} hook {row["id"]!r} declares `refs`; only a push names refs'
        raise HookTableError(msg)
    for key in ('files', 'exclude', 'refs'):
        if key in row:
            try:
                re.compile(row[key])
            except (re.error, TypeError) as exc:
                msg = f'{origin}: {stage} hook {row["id"]!r} has an invalid `{key}` regex: {exc}'
                raise HookTableError(msg) from exc


def _hook(stage: str, row: dict[str, Any], origin: str) -> Hook:
    unknown = set(row) - _KEYS
    if unknown:
        msg = f'{origin}: {stage} hook {row.get("id")!r} has unknown key(s) {sorted(unknown)}; known: {sorted(_KEYS)}'
        raise HookTableError(msg)
    if not isinstance(row.get('id'), str) or not row['id']:
        msg = f'{origin}: a {stage} hook has no `id`'
        raise HookTableError(msg)
    run = row.get('run')
    if not isinstance(run, list) or not run or not all(isinstance(word, str) and word for word in run):
        msg = f'{origin}: {stage} hook {row["id"]!r} needs `run`, a non-empty list of strings'
        raise HookTableError(msg)
    if run[0] in _FOREIGN_LAUNCHERS:
        msg = (
            f'{origin}: {stage} hook {row["id"]!r} runs {run[0]!r}, which picks (and may sync or create) an '
            f'interpreter of its own. Every hook already runs in this repo`s venv: write `run = ["python", ...]` '
            f'or the tool`s own name.'
        )
        raise HookTableError(msg)
    _check_selectors(stage, row, origin)
    env = row.get('env', {})
    if not isinstance(env, dict) or not all(isinstance(v, str) for v in env.values()):
        msg = f'{origin}: {stage} hook {row["id"]!r} has an `env` that is not a table of strings'
        raise HookTableError(msg)
    return Hook(stage=stage, **{**row, 'run': tuple(run)})


def _rows(table: dict[str, Any], origin: str) -> dict[str, tuple[dict[str, Any], ...]]:
    unknown = set(table) - set(STAGES)
    if unknown:
        msg = f'{origin}: unknown hook stage(s) {sorted(unknown)}; the family runs {list(STAGES)}'
        raise HookTableError(msg)
    out = {}
    for stage, rows in table.items():
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            msg = f'{origin}: `{stage}` must be an array of tables ([[...{stage}]])'
            raise HookTableError(msg)
        out[stage] = tuple(rows)
    return out


def base_rows() -> dict[str, tuple[dict[str, Any], ...]]:
    """The family base, raw, by stage."""
    return _rows(tomllib.loads(BASE_PATH.read_text(encoding='utf-8')), str(BASE_PATH))


def repo_rows(root: Path) -> dict[str, tuple[dict[str, Any], ...]] | None:
    """A repo's own layer, raw, by stage; ``None`` when it does not opt in (no ``[tool.lab_commons.hooks]``)."""
    pyproject = root / 'pyproject.toml'
    if not pyproject.is_file():
        return None
    data = tomllib.loads(pyproject.read_text(encoding='utf-8'))
    hooks = data.get('tool', {}).get('lab_commons', {}).get('hooks')
    return None if hooks is None else _rows(hooks, str(pyproject))


def merge(
    base: dict[str, tuple[dict[str, Any], ...]],
    layer: dict[str, tuple[dict[str, Any], ...]],
    *,
    origin: str = 'hooks',
) -> dict[str, tuple[Hook, ...]]:
    """Merge *layer* over *base*: same id merges key by key, a new id appends. PURE."""
    out: dict[str, tuple[Hook, ...]] = {}
    for stage in STAGES:
        merged: dict[str, dict[str, Any]] = {}
        for source, rows in (('base', base.get(stage, ())), (origin, layer.get(stage, ()))):
            seen: set[str] = set()
            for row in rows:
                hook_id = row.get('id')
                if hook_id in seen:
                    msg = f'{source}: {stage} declares hook {hook_id!r} twice'
                    raise HookTableError(msg)
                seen.add(hook_id)
                merged[hook_id] = {**merged.get(hook_id, {}), **row}
        hooks = tuple(_hook(stage, row, origin) for row in merged.values())
        if hooks:
            out[stage] = hooks
    return out


def hook_table(root: Path) -> dict[str, tuple[Hook, ...]]:
    """Every hook *root* runs, by stage: the family base with the repo's layer merged over it.

    A repo OPTS IN by declaring ``[tool.lab_commons.hooks]`` (an empty table takes the base as is); one
    that does not runs no hook and declares no stage, so a checkout that is not a family project is
    never reported unprotected.
    """
    layer = repo_rows(root)
    return {} if layer is None else merge(base_rows(), layer, origin=str(root / 'pyproject.toml'))


def hook_table_from(text: str, origin: str) -> dict[str, tuple[Hook, ...]]:
    """:func:`hook_table` for manifest *text* read anywhere (a commit or tree, not the working tree)."""
    hooks = tomllib.loads(text).get('tool', {}).get('lab_commons', {}).get('hooks')
    return {} if hooks is None else merge(base_rows(), _rows(hooks, origin), origin=origin)
