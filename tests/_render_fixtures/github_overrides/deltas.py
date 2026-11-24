"""Render-golden fixture DELTAS: a representative declaration, not any real repo's."""

from __future__ import annotations

from dev_lab.dev.famconfig import Delta

DELTAS = {
    '.gitignore': Delta(repo='overrides', added=('/data/', '*.h5'), dropped={}, ceiling=2),
    '.gitattributes': Delta(repo='overrides', added=('*.h5 binary',), dropped={}, ceiling=1),
}
