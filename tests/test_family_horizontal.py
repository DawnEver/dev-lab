"""The family compared horizontally: a feature one peer holds and another lacks is named, unless declared.

The fixture is the SHAPE measured 2026-11-09 across seven members of one forge (placeholder names): the review
secret on five, two legacy secrets on the same five, the integration branch's merge-ready context on five, an
extra trunk context on one, ``continue.yml`` on three, ``ephemeral`` on two, ``pr_merges_since`` on six, and the
kit without its ``AGENTS.md``/``CLAUDE.md``.
"""

from __future__ import annotations

from dev_lab.dev.family.horizontal import compare, features
from dev_lab.dev.family.members import Facts
from dev_lab.dev.family.origin import Snapshot

HOST = 'forge.example'
REVIEW = 'secret:AI_LAB_KEYS_PR_REVIEW'
LEGACY = frozenset({'secret:OLD_PROVIDER_KEY', 'secret:OLD_PROVIDER_KEY_2'})
REQUIRED = {'AI_LAB_KEYS_PR_REVIEW'}
MERGE = 'protect:integration:tests/merge-ready'
BASE = 'protect:trunk:tests/base'
FILES = frozenset({'file:AGENTS.md', 'file:CLAUDE.md'})
CORE = frozenset({'workflow:ci.yml', 'manifest:pr_merges_since', BASE}) | FILES


def _profiles() -> dict[str, tuple[str, frozenset[str]]]:
    full = CORE | LEGACY | {REVIEW, MERGE}
    return {
        'repo-a': (HOST, full | {'workflow:continue.yml', 'manifest:ephemeral=wip'}),  # its tests/windows is its own
        'kit': (HOST, (full | {'workflow:continue.yml'}) - FILES),
        'repo-c': (HOST, full),
        'repo-d': (HOST, full | {'workflow:continue.yml'}),
        'repo-e': (HOST, full),
        'repo-f': (HOST, CORE - {BASE} | {'manifest:ephemeral=wip'}),
        'repo-g': (HOST, CORE - {'manifest:pr_merges_since'}),
    }


def test_every_lacked_feature_is_named_with_who_holds_it() -> None:
    found = {(f.member, f.what.split(' (')[0]) for f in compare(_profiles(), {}, REQUIRED)}
    assert ('repo-f', f'lacks: {REVIEW}') in found
    assert ('repo-g', f'lacks: {MERGE}') in found
    assert ('repo-f', f'lacks: {BASE}') in found
    assert ('repo-c', 'lacks: workflow:continue.yml') in found
    assert ('repo-c', 'lacks: manifest:ephemeral=wip') in found
    assert ('repo-g', 'lacks: manifest:pr_merges_since') in found
    assert ('kit', 'lacks: file:AGENTS.md') in found


def test_an_unrequired_secret_is_baggage_on_its_holders_and_never_a_lack() -> None:
    found = compare(_profiles(), {}, REQUIRED)
    assert not [f for f in found if f.what.startswith('lacks: secret:OLD_PROVIDER')]
    holders = {f.member for f in found if f.what.startswith('baggage: secret:OLD_PROVIDER_KEY ')}
    assert holders == {'repo-a', 'kit', 'repo-c', 'repo-d', 'repo-e'}


def test_a_declared_exception_silences_exactly_its_feature() -> None:
    """PLANTED CONTROL: the same member's other lacks are still named."""
    found = {
        (f.member, f.what.split(' (')[0]) for f in compare(_profiles(), {'repo-c': ['workflow:continue.yml']}, REQUIRED)
    }
    assert ('repo-c', 'lacks: workflow:continue.yml') not in found
    assert ('repo-c', 'lacks: manifest:ephemeral=wip') in found


def test_members_of_another_forge_are_no_peers() -> None:
    profiles = {'hub': ('github.com', frozenset({MERGE})), 'tea': ('forge.example', frozenset({BASE}))}
    assert compare(profiles, {}, REQUIRED) == []


def test_a_profile_reads_the_origin_snapshot_and_the_forge() -> None:
    held = Snapshot('origin/integrate/main', frozenset({'.github/workflows/ci.yml', 'AGENTS.md', 'src/x.yml'}),
                    "[tool.dev_lab.branchset]\nephemeral = ['wip/*']\n")  # fmt: skip
    facts = Facts(pulls=True, missing_branches=(), protection_drift=(), secrets=frozenset({'AI_LAB_KEYS_PR_REVIEW'}),
                  oldest_open=None, contexts={'trunk': ('tests/base',)})  # fmt: skip
    assert features(held, facts) == {'workflow:ci.yml', 'file:AGENTS.md', "manifest:ephemeral=['wip/*']", REVIEW, BASE}


def test_a_context_the_member_s_own_resources_produce_is_no_family_feature() -> None:
    """A repo declaring ``resources = ["windows"]`` requires ``tests/windows`` BY DESIGN; no peer lacks it.

    PLANTED CONTROL: the same context on a repo that declares no such resource is compared like any other.
    """
    facts = Facts(pulls=True, missing_branches=(), protection_drift=(), secrets=frozenset(), oldest_open=None,
                  contexts={'trunk': ('tests/base', 'tests/windows')})  # fmt: skip
    windows = '[tool.lab_commons.tests]\nresources = ["windows"]\n'
    assert features(Snapshot('origin/x', frozenset(), windows), facts) == {BASE}
    assert features(Snapshot('origin/x', frozenset(), ''), facts) == {BASE, 'protect:trunk:tests/windows'}


def test_an_explicit_line_equal_to_the_built_in_default_is_no_feature() -> None:
    """``ephemeral = ['pr/*']`` restates ``branchset.FAMILY_EPHEMERAL``: holding it or not is the same fact.

    PLANTED CONTROL: a NON-default ephemeral value is a feature, compared like any other.
    """
    facts = Facts(pulls=True, missing_branches=(), protection_drift=(), secrets=frozenset(), oldest_open=None)
    table = "[tool.dev_lab.branchset]\ntrunk = 'main'\nsessions = ['integrate/main']\n"
    restated = Snapshot('origin/x', frozenset(), table + "ephemeral = ['pr/*']\n")
    assert features(restated, facts) == features(Snapshot('origin/x', frozenset(), table), facts) == frozenset()
    other = features(Snapshot('origin/x', frozenset(), table + "ephemeral = ['pr/*', 'wip/*']\n"), facts)
    assert other == {"manifest:ephemeral=['pr/*', 'wip/*']"}
