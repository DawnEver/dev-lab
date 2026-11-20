"""A checkout environment as the one rule reads it: ``<root>/.venvs/<name>`` named by ``<root>/.venv-current``."""

from __future__ import annotations

from pathlib import Path

from dev_lab.dev.venvpointer import HOME, POINTER


def current_env(root: Path, name: str = 'x') -> Path:
    """Create ``<root>/.venvs/<name>`` and point ``.venv-current`` at it; the environment directory."""
    env = root / HOME / name
    env.mkdir(parents=True, exist_ok=True)
    (root / POINTER).write_text(f'{name}\n', encoding='utf-8')
    return env
