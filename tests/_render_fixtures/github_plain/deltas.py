"""Render-golden fixture DELTAS: a representative declaration, not any real repo's."""

from __future__ import annotations

from dev_lab.dev.famconfig import Delta

DELTAS = {
    '.gitignore': Delta(repo='plain', added=(), dropped={}, ceiling=0),
    '.gitattributes': Delta(repo='plain', added=(), dropped={}, ceiling=0),
    '.rgignore': Delta(repo='plain', added=(), dropped={}, ceiling=0),
}
