"""THE FORGE READS OF A PLANRUN PREFLIGHT: a declaration, a file and a directory listing at a ref, read without a code.

Split out of :mod:`dev_lab.dev.planrunpreflight` by concept (2026-11-27, at the module-size band): that module
checks a plan's doors; this one owns what its :class:`~dev_lab.dev.planrunpreflight.Readers` read from a forge by
default. Every read goes through the forge client, never a working tree.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from dev_lab.dev.forgeclient import client_for
from dev_lab.dev.forgefailure import ForgeCallFailed
from dev_lab.dev.reviewgate import DeclarationUnread, file_at, manifest_at

__all__ = ['declared_at', 'listed_at', 'text_at']


def declared_at(forge: str, repo: str, ref: str) -> str:
    """*repo*'s ``pyproject.toml`` at *ref* on *forge*, read here through the forge client (never a working tree)."""
    return manifest_at(client_for(Path.cwd(), url=f'https://{forge}/{repo}.git'), ref)


def listed_at(source: str, where: str, ref: str) -> list[str]:
    """The file names directly in directory *where* at *ref* of the forge repo at *source*, read here."""
    client = client_for(Path.cwd(), url=source)
    try:
        answer: Any = client.call('GET', f'{client.repo}/contents/{where}?ref={ref}')
    except ForgeCallFailed as failed:
        msg = f'{where}/ at {ref} cannot be listed: {failed}'
        raise DeclarationUnread(msg) from failed
    if not isinstance(answer, list):
        msg = f'{where} at {ref} is not a directory'
        raise DeclarationUnread(msg)
    return [str(entry['name']) for entry in answer if isinstance(entry, dict) and entry.get('type') == 'file']


def text_at(source: str, path: str, ref: str) -> str:
    """*path* at *ref* of the forge repo at *source* (an https clone URL), read here through the forge client."""
    return file_at(client_for(Path.cwd(), url=source), path, ref)
