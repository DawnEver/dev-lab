"""THE ENVIRONMENT A VERDICT CITES -- every installed distribution but the project under test.

A verdict is a fact about a content key (:class:`dev_lab.dev.verdictstore.ContentKey`): the code, named by its
tree, and the environment it ran in, named by :func:`lab_commons.envkey.env_key`. The project under test is
installed into its own environment too, and a VCS-derived version (``dev-lab==0.0.1.dev2253+gf0f28483d``) moves
with EVERY commit -- so a key over it names the sha, two commits of one tree never share a key, and the store
could never cite a verdict across them (measured 2026-11-05: a merge's smoke re-ran a 46 min Windows part on the
tree its PR head had just passed). The project's code is the tree's to name; its line leaves the manifest, read
by its normalized ``[project] name`` from *root*'s ``pyproject.toml``. Every other line stays: a git
dependency's commit rides in its version, and it does key the verdict.

One reading feeds the key and the record's ``resolved`` list (:func:`verdict_env_record`), so they cannot
disagree; every producer, the run cache and the verdict line key by it.
"""

from __future__ import annotations

import re
import tomllib
from typing import TYPE_CHECKING, Any

from lab_commons.envkey import env_key, env_manifest

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

__all__ = ['verdict_env', 'verdict_env_record', 'verdict_manifest']


def _normalized(name: str) -> str:
    """A distribution name as PEP 503 compares it."""
    return re.sub(r'[-_.]+', '-', name).lower()


def _project(root: Path) -> str:
    """*root*'s normalized ``[project] name``; ``''`` when it declares none."""
    manifest = root / 'pyproject.toml'
    if not manifest.is_file():
        return ''
    name = tomllib.loads(manifest.read_text(encoding='utf-8')).get('project', {}).get('name', '')
    return _normalized(name) if isinstance(name, str) else ''


def verdict_manifest(root: Path, manifest: Iterable[str] | None = None) -> tuple[str, ...]:
    """*manifest* (default: this interpreter's) without the line of *root*'s own project."""
    own = _project(root)
    lines = env_manifest() if manifest is None else tuple(manifest)
    return tuple(line for line in lines if not own or _normalized(line.partition('==')[0]) != own)


def verdict_env(root: Path) -> str:
    """The env key of a verdict judged at *root* (module docstring)."""
    return env_key(verdict_manifest(root))


def verdict_env_record(root: Path, manifest: Iterable[str] | None = None) -> dict[str, Any]:
    """``{'env': <key>, 'resolved': [<line>, ...]}`` of *root*'s verdict environment -- one reading for both."""
    lines = list(verdict_manifest(root, manifest))
    return {'env': env_key(lines), 'resolved': lines}
