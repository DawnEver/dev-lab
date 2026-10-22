"""DECLARED OUTPUTS ON THE SERVE PATH -- what a cluster run stores, and the cleanup its host owns.

:func:`store_outputs` packs a run's declared outputs from its work tree and puts the archive in the
store its size selects (:func:`dev_lab.dev.artefacts.store_for`); :func:`tidy` cleans, in every store
this repo writes, the runs of THIS host's cluster account only -- several accounts write one shared
library, and each cleans its own (:mod:`dev_lab.dev.forgerun`, :mod:`dev_lab.dev.forgeserve`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from dev_lab.dev.artefacts import (
    ARCHIVE,
    ArtefactStore,
    ForgeStore,
    Ref,
    clean,
    collect,
    large_store,
    load_config,
    pack,
    pinned,
    store_for,
)
from dev_lab.dev.forge import forge_from_remote
from dev_lab.dev.forgeclaim import forge_now

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path

    from dev_lab.dev.forgework import Client

__all__ = ['store_outputs', 'tidy']


def store_outputs(root: Path, client: Client, tree: Path, outputs: Sequence[str], *, ident: str, workdir: Path) -> Ref:
    """Pack *outputs* from *tree* as run *ident*, put the archive, and return its :class:`Ref`."""
    archive = pack(tree, collect(tree, outputs), workdir / f'{ident}{ARCHIVE}')
    store = store_for(load_config(root), client, forge_from_remote(root).repo, size=archive.stat().st_size)
    ref = store.put(ident, archive)
    archive.unlink()
    return ref


def tidy(root: Path, client: Client, *, account: str, say: Callable[[str], None]) -> tuple[str, ...]:
    """Clean *account*'s runs in every store this repo writes: past ``retain_days``, then down to ``cap_gb``."""
    config = load_config(root)
    stores: list[ArtefactStore] = [ForgeStore(client)]
    large = large_store(config, forge_from_remote(root).repo)
    stores += [large] if large is not None else []
    keep, now = pinned(client, say=say), forge_now(client)
    gone = []
    for store in stores:
        cap = config.cap_bytes if store is large else 0
        for ref in clean(store, account=account, now=now, retain_days=config.retain_days, cap_bytes=cap, pinned=keep):
            gone.append(f'{ref.backend}:{ref.key}')
            say(f'[artefacts] deleted {ref.backend}:{ref.key}')
    return tuple(gone)
