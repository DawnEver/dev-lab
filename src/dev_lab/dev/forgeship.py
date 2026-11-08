"""DECLARED OUTPUTS ON THE SERVE PATH -- what a cluster run stores, and the cleanup its host owns.

:func:`store_outputs` packs a run's declared outputs from its work tree and puts the archive in the
store its size selects (:func:`dev_lab.dev.artefacts.store_for`); :func:`tidy` cleans, in every store
this repo writes, the runs of THIS host's cluster account only -- several accounts write one shared
library, and each cleans its own (:mod:`dev_lab.dev.forgerun`, :mod:`dev_lab.dev.forgeserve`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from dev_lab.dev.artefactindex import StoredOutputs
from dev_lab.dev.artefactpack import collect, pack
from dev_lab.dev.artefacts import (
    ARCHIVE,
    ArtefactStore,
    ForgeStore,
    OutputBudgetRefused,
    clean,
    large_store,
    load_config,
    pinned,
    store_for,
)
from dev_lab.dev.artefactstores import OutputIntegrityRefused, ref_of
from dev_lab.dev.forge import forge_from_remote
from dev_lab.dev.forgeclaim import forge_now

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path

    from dev_lab.dev.forgework import Client

__all__ = ['store_outputs', 'tidy']


def store_outputs(
    root: Path, client: Client, tree: Path, outputs: Sequence[str], *, ident: str, workdir: Path
) -> StoredOutputs:
    """Pack *outputs* from *tree* as run *ident* under the repo's budgets, put it, and return it with its index.

    The three ``member_index_*`` limits are mandatory for declared outputs (:class:`OutputBudgetRefused`
    without them); the ``expanded_output_*`` budget is checked before anything is packed. The stored Ref
    must be the sealed archive's bytes and sha256, else :class:`OutputIntegrityRefused`. Only this call's
    packed archive is removed, even when storing fails; the inputs are never retired here, so an
    interrupted store retries by repacking.
    """
    config = load_config(root)
    members, index_bytes, path_bytes = (
        config.member_index_max_members,
        config.member_index_max_bytes,
        config.member_index_max_path_bytes,
    )
    if members is None or index_bytes is None or path_bytes is None:
        msg = 'output index budget refused: all three member_index limits must be explicitly declared'
        raise OutputBudgetRefused(msg)
    files = collect(
        tree, outputs, max_entries=config.expanded_output_max_entries, max_bytes=config.expanded_output_max_bytes
    )
    packed = pack(
        tree,
        files,
        workdir / f'{ident}{ARCHIVE}',
        max_members=members,
        max_index_bytes=index_bytes,
        max_path_bytes=path_bytes,
    )
    sealed = (packed.archive_sha256, packed.compressed_bytes)
    try:
        now = ref_of('', '', packed.path)
        if (now.sha256, now.bytes) != sealed:
            msg = 'packed archive identity changed before storing'
            raise OutputIntegrityRefused(msg)
        store = store_for(config, client, forge_from_remote(root).repo, size=now.bytes)
        ref = store.put(ident, packed.path)
        if (ref.sha256, ref.bytes) != sealed:
            msg = 'stored archive identity differs from indexed payload'
            raise OutputIntegrityRefused(msg)
        return StoredOutputs(ref, packed.members)
    finally:
        packed.path.unlink()


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
