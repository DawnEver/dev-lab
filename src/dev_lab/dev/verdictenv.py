"""THE ENVIRONMENT A VERDICT CITES -- every installed distribution but the project under test.

A verdict is a fact about a content key (:class:`dev_lab.dev.verdictstore.ContentKey`): the code, named by its
tree, and the environment it ran in, named by :func:`lab_commons.envkey.env_key`. The project under test is
installed into its own environment too, and a VCS-derived version (``dev-lab==0.0.1.dev2253+gf0f28483d``) moves
with EVERY commit -- so a key over it names the sha, two commits of one tree never share a key, and the store
could never cite a verdict across them (measured 2026-11-05: a merge's smoke re-ran a 46 min Windows part on the
tree its PR head had just passed). The project's code is the tree's to name; its line leaves the manifest, read
by its normalized ``[project] name`` from *root*'s ``pyproject.toml``. Every other line stays: a git
dependency's commit rides in its version, and it does key the verdict.

A verdict is ALSO a fact about the POLICY it was judged by (:func:`verdict_policy`): the commit's test
declaration (``[tool.lab_commons.tests]``, ``[tool.lab_commons.hpc]``, ``[tool.dev_lab.parts]``) and its DECLARED
environment, the ``uv.lock``. Two runs of one part under two policies are two facts, never one overwriting the other
(:func:`dev_lab.dev.platformparts.parts_of`), and ``integrate promote`` requires the policy the promoted commit
declares.

One reading feeds the key and the record's ``resolved`` list (:func:`verdict_env_record`), so they cannot
disagree; every producer, the run cache and the verdict line key by it.
"""

from __future__ import annotations

import hashlib
import json
import re
import tomllib
from typing import TYPE_CHECKING, Any

import lab_commons.launch as _door
from lab_commons.envkey import env_key, env_manifest

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

__all__ = [
    'POLICY_CHARS',
    'verdict_env',
    'verdict_env_record',
    'verdict_manifest',
    'verdict_policy',
    'verdict_policy_at',
]

#: How many hex digits of a policy (and of an env key) a part's status description carries.
POLICY_CHARS = 8

#: The declaration tables a test policy is a digest of, as ``(tool, table)``.
_POLICY_TABLES = (('lab_commons', 'tests'), ('lab_commons', 'hpc'), ('dev_lab', 'parts'))

#: The declared environment a policy is a digest of.
_LOCK = 'uv.lock'


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
    """``{'env': <key>, 'resolved': [<line>, ...], 'policy': <version>}`` of *root*'s verdict environment.

    One reading for the key and the list; the policy is :func:`verdict_policy` of *root*'s working tree.
    """
    lines = list(verdict_manifest(root, manifest))
    return {'env': env_key(lines), 'resolved': lines, 'policy': _policy_here(root)}


def _policy_here(root: Path) -> str:
    def read(name: str) -> str:
        path = root / name
        return path.read_text(encoding='utf-8') if path.is_file() else ''

    return verdict_policy(read('pyproject.toml'), read(_LOCK))


def verdict_policy(pyproject: str, lock: str) -> str:
    """The policy version of a commit whose ``pyproject.toml`` is *pyproject* and whose ``uv.lock`` is *lock*.

    A digest of the test-declaration tables and the lock, and of nothing else: two commits declaring the same
    tests in the same declared environment share it; any change to either is another policy.
    """
    tool = tomllib.loads(pyproject).get('tool', {}) if pyproject else {}
    tables = {f'{kit}.{name}': tool.get(kit, {}).get(name, {}) for kit, name in _POLICY_TABLES}
    canonical = json.dumps(tables, sort_keys=True, separators=(',', ':')) + '\n' + lock
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()[:POLICY_CHARS]


def _shown(root: Path, sha: str, path: str) -> str:
    done = _door.run(
        ['git', '-C', str(root), 'show', f'{sha}:{path}'], capture_output=True, text=True, encoding='utf-8', check=False
    )
    return done.stdout if done.returncode == 0 else ''


def verdict_policy_at(root: Path, sha: str) -> str:
    """:func:`verdict_policy` of commit *sha* of *root*; ``''`` when *root* does not hold *sha*."""
    done = _door.run(
        ['git', '-C', str(root), 'cat-file', '-e', f'{sha}^{{commit}}'],
        capture_output=True, text=True, encoding='utf-8', check=False,
    )  # fmt: skip
    if done.returncode != 0:
        return ''
    return verdict_policy(_shown(root, sha, 'pyproject.toml'), _shown(root, sha, _LOCK))
