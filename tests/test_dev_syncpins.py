"""A SYNC NEVER ROLLS A LANE BACK: every git pin of the merged lock contains both sides' pins.

The 2026-11-06 incident: the auto-sync took integration's lock over a lane's newer ai-lab, optimi-lab and
lab-commons pins. Ancestry is a planted history (``older -> newer`` edges); the evidence is the lock written.
"""

from __future__ import annotations

import pytest

from dev_lab.dev.drift import sources
from dev_lab.dev.syncpins import Diverged, carry

_URL = 'https://example.test/fam/ai-lab'
#: a1 <- a2 <- a3 on one line; b2 branched from a1 beside it.
_HISTORY = {('a1', 'a2'), ('a1', 'a3'), ('a2', 'a3'), ('a1', 'b2')}


def _ancestry(_dist: str, _url: str, older: str, newer: str) -> bool:
    return older == newer or (older, newer) in _HISTORY


def _lock(pin: str, numpy: str = '2.0.0', *, marker: str = '') -> str:
    return (
        'version = 1\n\n'
        f'[[package]]\nname = "ai-lab"\nversion = "0.1.0"\nsource = {{ git = "{_URL}#{pin}" }}{marker}\n\n'
        f'[[package]]\nname = "numpy"\nversion = "{numpy}"\nsource = {{ registry = "https://pypi.org/simple" }}\n'
    )


def _pin(lock: str) -> str:
    return sources(lock)['ai-lab'][1]


def test_a_lane_pin_newer_than_integrations_is_kept_over_a_relock_that_rolled_it_back() -> None:
    """The incident: the merged lock holds integration's a2, the lane held a3; a3 comes back, its entry whole."""
    merged = carry(_lock('a3', marker='\n# lane'), _lock('a2'), _lock('a2', numpy='2.1.0'), _ancestry)
    assert _pin(merged) == 'a3'
    assert '# lane' in merged  # the lane's whole entry, not a rewritten sha
    assert 'version = "2.1.0"' in merged  # the rest of the merged lock untouched


def test_planted_control_an_integration_pin_newer_than_the_lanes_is_kept() -> None:
    """Same shape, sides swapped: integration's a3 stands, nothing is rewritten."""
    merged_lock = _lock('a3')
    assert carry(_lock('a2'), _lock('a3'), merged_lock, _ancestry) == merged_lock


def test_a_relock_past_both_pins_stands() -> None:
    """A merged pin that contains the newer side is not moved back to it."""
    merged_lock = _lock('a3')
    assert carry(_lock('a2'), _lock('a1'), merged_lock, _ancestry) == merged_lock


def test_diverged_pins_refuse_naming_the_package_and_both_pins() -> None:
    with pytest.raises(Diverged) as refused:
        carry(_lock('a2'), _lock('b2'), _lock('b2'), _ancestry)
    assert {'ai-lab', 'a2', 'b2'} <= set(str(refused.value).replace(',', ' ').split())


def test_a_package_from_the_index_follows_the_normal_resolution() -> None:
    """The index package numpy moved differently on each side; the merged resolution is never touched for it."""
    merged_lock = _lock('a3', numpy='2.2.0')
    assert carry(_lock('a3', numpy='2.0.0'), _lock('a3', numpy='2.1.0'), merged_lock, _ancestry) == merged_lock


def test_a_lock_that_is_not_toml_pins_nothing_and_is_never_refused() -> None:
    """The lock-only conflict test's ``ours``/``theirs`` locks: no git pin to carry, so the merged lock stands."""
    assert carry('ours', 'theirs', 'relocked', _ancestry) == 'relocked'
