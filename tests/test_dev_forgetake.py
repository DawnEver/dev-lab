"""WHAT A HOST CLAIMS: its ``[serve]`` rule skips parts; a withheld resource is never its forge work at all."""

from __future__ import annotations

from lab_commons.compute.model import REQUEST
from lab_commons.compute.serves import NEEDS_A_RESOURCE, SKIPPED_HERE, Serves

from dev_lab.dev.forgetake import skips

PART = 'part'


def test_a_withheld_resource_is_never_claimed_even_by_a_request() -> None:
    """A light workstation withholds jmag: a JMAG request is heavy compute too (user ruling 2026-10-28)."""
    light = Serves(withholds=frozenset({'jmag'}))
    assert skips(light, REQUEST, {'jmag', 'windows'}).startswith(SKIPPED_HERE)
    assert skips(light, PART, {'jmag'}).startswith(SKIPPED_HERE)
    assert skips(light, REQUEST, {'windows'}) == '', 'PLANTED CONTROL: a request needing no withheld resource'


def test_a_request_is_no_part_so_the_parts_rule_never_skips_it() -> None:
    resource_only = Serves(NEEDS_A_RESOURCE)
    assert skips(resource_only, PART, set()).startswith(SKIPPED_HERE)
    assert skips(resource_only, REQUEST, set()) == ''
