"""A config KEY never spells its unit; its VALUE carries it (`CONFIG-VALUES-CARRY-UNITS`, user ruling 2026-11-25).

THE DEFECT. ``memory_gb = 32`` puts the unit in the KEY NAME and leaves the number bare, so nothing checks it: a
reader who writes ``32768`` meaning megabytes is never told. The family writes ``memory = "32 GiB"`` instead and
every reader turns the value into a number through :func:`lab_commons.quantity.parse`, the one boundary where a
unit is read; an old key is refused by name with its new line (:func:`lab_commons.quantity.refuse_renamed`).

WHY A SECOND TOKEN TABLE BESIDE :mod:`dev_lab.dev._unit_tokens`. That table governs NAMES in code and deliberately
leaves out the size and duration tokens (``_s`` is a plural, ``_d`` a derivative, ``_mb`` a megabyte or nothing),
because over a Python tree they collide too often to refuse. A config key is a smaller, human-typed vocabulary in
which those very tokens are the defect -- ``tick_minutes``, ``max_idle_hours``, ``wall_s`` -- so this rule carries
its own set (:data:`UNIT_SUFFIXES`) and scans only CONFIG surfaces:

* every key at every depth of a TOML document, arrays of tables included (:func:`toml_sites`);
* every ``toml`` fenced block of a Markdown page, because a documented key is the one a reader copies
  (:func:`markdown_sites`);
* every DECLARED SCHEMA in Python -- a module- or class-level constant named ``*KEYS`` or ``*SCHEMA``, or annotated
  ``Final`` and holding a dict whose values are all types (``{'memory_gb': (int, float)}``): its string keys or
  members are a table's keys; and a ``@dataclass`` whose docstring's first line names a ````[table]````, built from
  that table, whose fields ARE its keys (:func:`schema_sites`).

WHAT IS NOT SCANNED, named so an empty result is not read as a clean one: a key a reader takes by ``.get('...')``
without declaring it in a schema constant (its retired spelling is then caught by that reader's own planted test),
a JSON record field (the JSON half of `UNITS-GO-THROUGH-PINT`), and a forge's own vocabulary that a renderer emits
(GitHub/Gitea ``timeout-minutes``): a caller exempts a site by name, with its reason, and a stale exemption reds.

A ``_min`` suffix is refused although it may mean "minimum": in a config key it reads as minutes, so a minimum is
named another way (``shortest_shard``, ``floor``).
"""

from __future__ import annotations

import ast
import re
import tomllib
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Final

__all__ = [
    'RULE',
    'UNIT_ANYWHERE',
    'UNIT_SUFFIXES',
    'UNIT_WORDS',
    'Site',
    'markdown_sites',
    'refusal',
    'schema_sites',
    'sites_in',
    'toml_sites',
    'unit_token',
]

#: The rule this module enforces (`dev_lab.dev.rules`).
RULE: Final = 'CONFIG-VALUES-CARRY-UNITS'

#: A key's LAST ``_``/``-`` segment that spells a size, a duration or a percentage.
UNIT_SUFFIXES: Final = frozenset({
    'b', 'kb', 'kib', 'mb', 'mib', 'gb', 'gib', 'tb', 'tib', 'bytes',
    'ns', 'us', 'ms', 's', 'sec', 'secs', 'seconds', 'min', 'mins', 'minutes',
    'h', 'hr', 'hrs', 'hour', 'hours', 'd', 'day', 'days', 'week', 'weeks',
    'pct', 'percent',
})  # fmt: skip
#: A whole key that IS a unit word (``seconds = 60``): the unit with no name of its own left.
UNIT_WORDS: Final = frozenset({'bytes', 'seconds', 'minutes', 'hours', 'days', 'weeks', 'percent'})
#: A token refused in ANY segment (``wave_hours_max``, ``disk_percent_ceiling``): unambiguous in a key's middle,
#: where a lone ``min`` (minimum: ``min_age``), ``s``, ``h`` or ``d`` is not.
UNIT_ANYWHERE: Final = frozenset({
    'kb', 'kib', 'mb', 'mib', 'gb', 'gib', 'tb', 'tib', 'bytes',
    'ms', 'secs', 'seconds', 'mins', 'minutes', 'hrs', 'hours', 'days', 'weeks', 'pct', 'percent',
})  # fmt: skip

_SEGMENTS: Final = re.compile(r'[_-]')
_FENCE: Final = re.compile(r'^```toml\s*$(.*?)^```\s*$', re.MULTILINE | re.DOTALL)
_SCHEMA_NAME: Final = re.compile(r'(KEYS|SCHEMA)$')
_TABLE_CITED: Final = re.compile(r'``\[[A-Za-z_][\w.\-"<>]*\]')


@dataclass(frozen=True)
class Site:
    """One key that spells its unit: where (``path:line``), the dotted key, and the token that spells it."""

    where: str
    key: str
    token: str

    def __str__(self) -> str:
        """``path:line: key`` -- the form a refusal and a report print."""
        return f'{self.where}: {self.key}'


def unit_token(key: str) -> str | None:
    """The unit token *key* spells, else ``None``.

    The token is its last segment (:data:`UNIT_SUFFIXES`), an unambiguous one anywhere (:data:`UNIT_ANYWHERE`), or
    the whole key when it is a unit word (:data:`UNIT_WORDS`).
    """
    parts = [part.lower() for part in _SEGMENTS.split(key) if part]
    if len(parts) > 1 and parts[-1] in UNIT_SUFFIXES:
        return parts[-1]
    if len(parts) == 1:
        return parts[0] if parts[0] in UNIT_WORDS else None
    return next((part for part in parts if part in UNIT_ANYWHERE), None)


def refusal(site: Site) -> str:
    """The refusal for *site*: the rule, the key, and the door -- the key without its unit, the unit in the value."""
    stem = [part for part in _SEGMENTS.split(site.key.rsplit('.', 1)[-1]) if part.lower() != site.token]
    new = '_'.join(stem) if stem else '<what it measures>'
    return (
        f'{RULE}: {site} spells its unit ({site.token!r}) in the key -- write {new} = "<n> <unit>", a quantity '
        f'string read once by lab_commons.quantity.parse (user ruling 2026-11-25)'
    )


def _walk(node: object, prefix: str) -> Iterator[str]:
    if isinstance(node, dict):
        for key, value in node.items():
            dotted = f'{prefix}.{key}' if prefix else str(key)
            yield dotted
            yield from _walk(value, dotted)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item, f'{prefix}[]')


def _line_of(lines: list[str], key: str) -> int:
    pattern = re.compile(rf'(^|[\s{{,."\']){re.escape(key)}["\']?\s*=')
    return next((number for number, line in enumerate(lines, 1) if pattern.search(line)), 0)


def toml_sites(text: str, where: str, *, offset: int = 0) -> list[Site]:
    """Every key of the TOML *text* (named *where*) that spells its unit; an unparsable text is a ``ValueError``."""
    try:
        document = tomllib.loads(text)
    except tomllib.TOMLDecodeError as bad:
        msg = f'{where}: not TOML ({bad})'
        raise ValueError(msg) from bad
    lines = text.splitlines()
    found: dict[str, Site] = {}
    for dotted in _walk(document, ''):
        leaf = dotted.rsplit('.', 1)[-1].removesuffix('[]')
        if (token := unit_token(leaf)) is not None and dotted not in found:
            found[dotted] = Site(f'{where}:{_line_of(lines, leaf) + offset}', dotted, token)
    return list(found.values())


def markdown_sites(text: str, where: str) -> list[Site]:
    """Every unit-spelling key in the ``toml`` fenced blocks of the Markdown *text*.

    A block that is not whole TOML (an excerpt with ``...``) is read line by line, each ``key = value`` on its own.
    """
    found: list[Site] = []
    for block in _FENCE.finditer(text):
        offset = text.count('\n', 0, block.start(1))
        body = block.group(1)
        try:
            found += toml_sites(body, where, offset=offset)
        except ValueError:
            for number, line in enumerate(body.splitlines(), offset + 1):
                key = line.split('=', 1)[0].strip().strip('"\'') if '=' in line else ''
                if key and not key.startswith(('#', '[')) and (token := unit_token(key)) is not None:
                    found.append(Site(f'{where}:{number}', key, token))
    return found


def _is_type(node: ast.expr) -> bool:
    if isinstance(node, ast.Tuple):
        return bool(node.elts) and all(_is_type(e) for e in node.elts)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return _is_type(node.left) and _is_type(node.right)
    return isinstance(node, ast.Name | ast.Attribute)


def _declared_keys(name: str, value: ast.expr, *, final: bool) -> Iterable[ast.expr]:
    """The key nodes *value* declares when it is a schema constant (module docstring), else nothing."""
    if isinstance(value, ast.Call) and value.args and isinstance(value.func, ast.Name):
        value = value.args[0] if value.func.id in {'frozenset', 'set', 'tuple'} else value
    if isinstance(value, ast.Dict):
        typed = final and value.values and all(_is_type(v) for v in value.values)
        return [k for k in value.keys if k is not None] if _SCHEMA_NAME.search(name) or typed else []
    if isinstance(value, ast.Set | ast.Tuple | ast.List) and _SCHEMA_NAME.search(name):
        return value.elts
    return []


def _is_table_dataclass(node: ast.ClassDef) -> bool:
    """A ``@dataclass`` whose docstring's first line names a TOML table (````[table]````): that table's schema."""
    decorated = any('dataclass' in ast.unparse(d) for d in node.decorator_list)
    first = (ast.get_docstring(node) or '').strip().splitlines()[:1]
    return decorated and bool(first) and _TABLE_CITED.search(first[0]) is not None


def _fields(tree: ast.Module) -> Iterator[tuple[str, int, str]]:
    """``(Class.field, line, field)`` for every field of a table dataclass."""
    for cls in (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and _is_table_dataclass(n)):
        for node in cls.body:
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                yield f'{cls.name}.{node.target.id}', node.lineno, node.target.id


def _constants(tree: ast.Module) -> Iterator[tuple[str, int, str]]:
    """``(NAME['key'], line, key)`` for every string key of a schema constant at module or class level."""
    for scope in [tree, *(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef))]:
        for node in scope.body:
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
                name, value, final = node.target.id, node.value, 'Final' in ast.unparse(node.annotation)
            elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                name, value, final = node.targets[0].id, node.value, False
            else:
                continue
            for key in _declared_keys(name, value, final=final):
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    yield f'{name}[{key.value!r}]', key.lineno, key.value


def schema_sites(source: str, where: str) -> list[Site]:
    """Every unit-spelling key of the declared schemas (module docstring) in the Python *source*."""
    tree = ast.parse(source)
    return [
        Site(f'{where}:{line}', named, token)
        for named, line, key in (*_fields(tree), *_constants(tree))
        if (token := unit_token(key)) is not None
    ]


def sites_in(path: Path, where: str) -> list[Site]:
    """The sites of one file by its kind: TOML, Markdown or Python; any other kind has none."""
    text = path.read_text(encoding='utf-8')
    if path.suffix == '.toml':
        return toml_sites(text, where)
    if path.suffix == '.md':
        return markdown_sites(text, where)
    if path.suffix == '.py':
        return schema_sites(text, where)
    return []
