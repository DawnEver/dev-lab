"""A published checkout environment as the one rule reads it: ``<root>/.venv`` linked to ``<root>/.venvs/<name>``."""

from __future__ import annotations

from pathlib import Path

from dev_lab.dev import venvcurrent
from dev_lab.dev.venvpointer import HOME


def linked_env(root: Path, name: str = 'x') -> Path:
    """Create ``<root>/.venvs/<name>`` and publish it (``.venv`` links to it); the environment directory."""
    env = Path(root) / HOME / name
    env.mkdir(parents=True, exist_ok=True)
    venvcurrent.publish(root, env, census=list)
    return env
