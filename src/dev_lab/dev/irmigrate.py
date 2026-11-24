"""THE ONE MIGRATE DOOR: ``python -m dev_lab.dev.irschema migrate <path>...``.

It rewrites stored IR records at the current version, once (``FORMATS-MIGRATE-ONCE``; ``docs-src/dev/ir-schema.md``,
"Reading and migration").

The door is generic; the steps are the repo's. ``[tool.dev_lab.ir_schema] migrations`` names a module whose
``MIGRATIONS: dict[int, Callable[[str, dict], dict]]`` maps MAJOR ``k`` to the function turning a MAJOR-``k`` value
into MAJOR ``k + 1``. The door chains them, rebuilds the record through its generated class (so the migrated value is
validated like any other) and writes the envelope back at the current version.
"""

from __future__ import annotations

import importlib
import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from dev_lab.dev.irmodel import IR

__all__ = ['migrate']


def _refusal(path: Path, what: str, door: str) -> str:
    return f'IR-NO-MIGRATION: {path}: {what} -- {door}'


def migrate(ir: IR, path: Path) -> str | None:
    """Rewrite *path* at the current version; ``None`` on success, else the refusal line naming its door."""
    stored = json.loads(path.read_bytes())
    name, version, value = stored['record'], stored['schema_version'], stored['value']
    module, record = name.split('.')
    if module not in ir.modules or record not in ir.modules[module].records:
        return _refusal(path, f'holds {name}, which this repo does not declare', 'migrate it in the repo that owns it')
    have, want = int(version.split('.')[0]), ir.declaration.version[0]
    if have > want:
        return _refusal(path, f'schema_version {version} is newer than {ir.declaration.version_text}', 'regenerate')
    steps = {}
    if have < want:
        if not ir.declaration.migrations:
            door = 'declare [tool.dev_lab.ir_schema] migrations = "<module>" holding MIGRATIONS'
            return _refusal(path, 'no migrations module is declared', door)
        steps = importlib.import_module(ir.declaration.migrations).MIGRATIONS
    for major in range(have, want):
        if major not in steps:
            door = f'add MIGRATIONS[{major}] to {ir.declaration.migrations}'
            return _refusal(path, f'no step from MAJOR {major} to {major + 1}', door)
        value = steps[major](name, value)
    package = ir.declaration.package
    importlib.import_module(f'{package}._ir_{module}')  # registers its classes
    cls = importlib.import_module(f'{package}._ir_runtime').REGISTRY[name]
    cls.from_json(json.dumps(value).encode()).dump(path)
    return None
