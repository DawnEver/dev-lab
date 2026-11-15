"""Render-golden fixture DELTAS: a representative declaration, not any real repo's."""

from __future__ import annotations

from dev_lab.dev.famconfig import Delta

DELTAS = {
    '.gitignore': Delta(repo='gitea', added=('/output/',), dropped={}, ceiling=1),
    '.rgignore': Delta(repo='gitea', added=(), dropped={}, ceiling=0),
}
