"""A SYNC NEVER ROLLS A LANE BACK: every git pin of a synced lock contains both sides' pins.

THE INCIDENT (2026-11-06). The forge's auto-sync merged integration into acme-consumer ``pr/opt-refactor-all``; the
lock conflicted, :mod:`dev_lab.dev.forgeautosync` took INTEGRATION's lock and relocked it, and the lane's newer
family pins went back -- ai-lab, acme-lib and lab-commons each to integration's older commit, so the lane's code
no longer imported. A relock resolves each sibling to the line it follows, which need not contain a lane's pin.

THE RULE, read per package sourced from git on BOTH sides (an index package follows the normal resolution):

* the pins agree, or one contains the other: the merged lock must pin a commit containing the NEWER one; if it
  does not, that package's whole ``[[package]]`` entry is taken from the side holding the newer pin (its metadata
  is that commit's) -- :func:`carry`;
* neither contains the other (DIVERGED): the machine does not guess. :func:`carry` raises :class:`Diverged`
  naming the package and both pins, and the sync is refused for its owner.

Ancestry is read from the dependency's own repository: a commits-only fetch (``--filter=tree:0``) of every branch
into ``<git-common-dir>/syncpins/<dist>.git``, over https only (:func:`dev_lab.dev.drift.require_fetchable`) --
the same fetch the drift watch already makes from every serving host (:func:`ancestor`).
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Final

import lab_commons.launch as _door

from dev_lab.dev.drift import SCHEMES, cache_dir, require_fetchable, sources
from dev_lab.dev.forge import _GIT, _GIT_TIMEOUT_S
from dev_lab.dev.lockcheck import unlocated_env
from dev_lab.dev.netverb import run_network_verb

__all__ = ['DIVERGED', 'Ancestry', 'Diverged', 'ancestor', 'carry']

#: The refusal, said once, here.
DIVERGED: Final = (
    '{dist} pins diverged: the lane holds {head}, integration {tip}, and neither contains the other -- '
    'the machine does not guess; pin a commit containing both by hand'
)

#: ``(dist, url, older, newer) -> whether older is an ancestor of (or is) newer``.
Ancestry = Callable[[str, str, str, str], bool]

_BLOCK: Final = re.compile(r'(?m)^(?=\[\[package\]\]$)')
_NAME: Final = re.compile(r'(?m)^name = "([^"]+)"$')


class Diverged(OSError):
    """A family pin whose two sides diverged; its message is :data:`DIVERGED`."""


def _git(repo: Path, *argv: str) -> tuple[int, str]:
    done = _door.run(
        [_GIT, '-C', str(repo), *argv], capture_output=True, text=True, encoding='utf-8', errors='replace',
        check=False, timeout=_GIT_TIMEOUT_S, env=unlocated_env(),
    )  # fmt: skip
    return done.returncode, (done.stdout + done.stderr).strip()


def ancestor(cache: Path) -> Ancestry:
    """The ancestry reading over a commits-only cache of each dependency under *cache*; a failed fetch raises."""

    def read(dist: str, url: str, older: str, newer: str) -> bool:
        require_fetchable(url, older, SCHEMES)
        require_fetchable(url, newer, SCHEMES)
        repo = cache_dir(cache, dist)
        if not repo.is_dir():
            repo.mkdir(parents=True)
            _git(repo, 'init', '-q', '--bare')
        allow = [arg for scheme in SCHEMES for arg in ('-c', f'protocol.{scheme}.allow=always')]
        argv = [
            _GIT, '-C', str(repo), '-c', 'protocol.allow=never', *allow,
            'fetch', '-q', '--filter=tree:0', '--no-tags', '--', url, '+refs/heads/*:refs/syncpins/*',
        ]  # fmt: skip
        report = run_network_verb(argv, cwd=repo, timeout=300, env=unlocated_env())
        if not report.ok:
            msg = f'the fetch of {url} failed: {report.remedy}'
            raise OSError(msg)
        for sha in (older, newer):
            if _git(repo, 'cat-file', '-e', f'{sha}^{{commit}}')[0] != 0:
                msg = f'{dist} pin {sha} is on no branch of {url}'
                raise OSError(msg)
        return _git(repo, 'merge-base', '--is-ancestor', older, newer)[0] == 0

    return read


def _blocks(lock: str) -> dict[str, str]:
    return {found[1]: block for block in _BLOCK.split(lock) if (found := _NAME.search(block))}


def _transplant(lock: str, dist: str, block: str) -> str:
    parts = _BLOCK.split(lock)
    for index, part in enumerate(parts):
        if (found := _NAME.search(part)) and found[1].lower().replace('_', '-') == dist:
            parts[index] = block.rstrip('\n') + part[len(part.rstrip('\n')) :]  # the entry's own spacing kept
    return ''.join(parts)


def _pins(lock: str) -> dict[str, tuple[str, str]]:
    """*lock*'s git pins; a lock that is not TOML pins nothing (as :func:`dev_lab.dev.relock.in_house` reads it)."""
    try:
        return sources(lock)
    except tomllib.TOMLDecodeError:
        return {}


def carry(head_lock: str, tip_lock: str, merged_lock: str, ancestry: Ancestry) -> str:
    """*merged_lock* with every git pin holding both sides' pins; :class:`Diverged` when the two sides diverged."""
    head_pins, tip_pins, merged_pins = _pins(head_lock), _pins(tip_lock), _pins(merged_lock)
    head_blocks, tip_blocks = _blocks(head_lock), _blocks(tip_lock)
    out = merged_lock
    for dist in sorted(head_pins.keys() & tip_pins.keys() & merged_pins.keys()):
        (url, ours), (_, theirs), (_, now) = head_pins[dist], tip_pins[dist], merged_pins[dist]
        if ours == theirs or ancestry(dist, url, ours, theirs):
            newer, blocks = theirs, tip_blocks
        elif ancestry(dist, url, theirs, ours):
            newer, blocks = ours, head_blocks
        else:
            raise Diverged(DIVERGED.format(dist=dist, head=ours, tip=theirs))
        if now == newer or ancestry(dist, url, newer, now):
            continue
        block = next(text for name, text in blocks.items() if name.lower().replace('_', '-') == dist)
        out = _transplant(out, dist, block)
    return out
