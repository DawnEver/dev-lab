"""Validated native harness identity, independent of worktree provenance and authorization."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ['harness_keys', 'primary_of', 'session_of', 'valid']


def _catalog() -> dict:
    try:
        catalog = json.loads(Path(__file__).with_suffix('.json').read_text(encoding='utf-8'))
        readable = type(catalog['max_length']) is int and catalog['max_length'] > 0
        readable = readable and isinstance(catalog['punctuation'], str)
        readable = (
            readable
            and isinstance(catalog['harnesses'], list)
            and bool(catalog['harnesses'])
            and all(
                isinstance(row['primary'], str)
                and isinstance(row['auxiliary'], list)
                and all(isinstance(field, str) for field in row['auxiliary'])
                for row in catalog['harnesses']
            )
        )
    except (OSError, ValueError, KeyError, TypeError) as failed:
        msg = 'native session catalog is missing or invalid.\nDoor: restore the declared dev-lab installation.'
        raise ValueError(msg) from failed
    if not readable:
        msg = 'native session catalog is invalid.\nDoor: restore the declared dev-lab installation.'
        raise ValueError(msg)
    return catalog


def valid(session: object) -> bool:
    """Whether a raw identity is safe and valid, without normalizing its signed subject."""
    catalog = _catalog()
    return (
        isinstance(session, str)
        and 0 < len(session) <= catalog['max_length']
        and all(char.isalnum() or char in catalog['punctuation'] for char in session)
    )


def harness_keys() -> frozenset[str]:
    """Every environment key a native harness names its session in -- what a machine's own commit must not carry."""
    return frozenset(key for row in _catalog()['harnesses'] for key in (row['primary'], *row['auxiliary']))


def primary_of(env: Mapping[str, object] | None = None) -> str:
    """The primary key of the ONE native harness *env* declares (``''`` for none) -- which harness this session runs.

    Raises:
        ValueError: *env* declares more than one harness.

    """
    env = os.environ if env is None else env
    declared = [
        row for row in _catalog()['harnesses'] if any(field in env for field in [row['primary'], *row['auxiliary']])
    ]
    if len(declared) > 1:
        msg = 'ambiguous native session harnesses.\nDoor: run from exactly one native agent harness.'
        raise ValueError(msg)
    return declared[0]['primary'] if declared else ''


def session_of(env: Mapping[str, object] | None = None) -> str:
    """Read one canonical native identity; configured invalid/ambiguous harnesses refuse, never bypass."""
    env = os.environ if env is None else env
    primary = primary_of(env)
    if not primary:
        return ''
    session = env.get(primary)
    if not valid(session):
        msg = f'native session {primary} is not a session id or is missing.\nDoor: restore the native harness identity.'
        raise ValueError(msg)
    return session
