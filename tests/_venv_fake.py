"""A published checkout environment as the one rule reads it: ``<root>/.venv`` linked to ``<root>/.venvs/<name>``."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import cast

from dev_lab.dev import venvcurrent
from dev_lab.dev.venvpointer import HOME


def linked_env(root: Path, name: str = 'x') -> Path:
    """Create ``<root>/.venvs/<name>`` and publish it (``.venv`` links to it); the environment directory."""
    env = Path(root) / HOME / name
    env.mkdir(parents=True, exist_ok=True)
    venvcurrent.publish(root, env, census=list)
    return env


def uv_child(argv: Sequence[str], kwargs: Mapping[str, object]) -> SimpleNamespace:
    """A uv child that succeeds as uv does: a ``sync`` creates the environment it is pointed at.

    The door publishes ``.venv`` onto that environment, and :func:`dev_lab.dev.venvcurrent.publish` refuses one that
    does not exist -- so a fake sync that leaves none is no sync (2026-11-27: on Windows it was a bare junction
    error, on POSIX a dangling link).
    """
    if 'sync' in argv:
        Path(cast('Mapping[str, str]', kwargs['env'])['UV_PROJECT_ENVIRONMENT']).mkdir(parents=True, exist_ok=True)
    return SimpleNamespace(returncode=0, stdout='', stderr='')
