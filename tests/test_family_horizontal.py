"""The family compared horizontally: a feature one peer holds and another lacks is named, unless declared.

The fixture is the SHAPE measured 2026-11-09 across seven members of one forge (placeholder names): the review
secret on five, two legacy secrets on the same five, the integration branch's merge-ready context on five, an
extra trunk context on one, ``continue.yml`` on three, ``ephemeral`` on two, ``pr_merges_since`` on six, and the
kit without its ``AGENTS.md``/``CLAUDE.md``.
"""

from __future__ import annotations

from pathlib import Path

from dev_lab.dev.family.horizontal import compare, features
from dev_lab.dev.family.members import Facts

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
        'repo-a': (HOST, full | {'workflow:continue.yml', 'manifest:ephemeral'}),  # its tests/windows is its own
        'kit': (HOST, (full | {'workflow:continue.yml'}) - FILES),
        'repo-c': (HOST, full),
        'repo-d': (HOST, full | {'workflow:continue.yml'}),
        'repo-e': (HOST, full),
        'repo-f': (HOST, CORE - {BASE} | {'manifest:ephemeral'}),
        'repo-g': (HOST, CORE - {'manifest:pr_merges_since'}),
    }


def test_every_lacked_feature_is_named_with_who_holds_it() -> None:
    found = {(f.member, f.what.split(' (')[0]) for f in compare(_profiles(), {}, REQUIRED)}
    assert ('repo-f', f'lacks: {REVIEW}') in found
    assert ('repo-g', f'lacks: {MERGE}') in found
    assert ('repo-f', f'lacks: {BASE}') in found
    assert ('repo-c', 'lacks: workflow:continue.yml') in found
    assert ('repo-c', 'lacks: manifest:ephemeral') in found
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
    assert ('repo-c', 'lacks: manifest:ephemeral') in found


def test_members_of_another_forge_are_no_peers() -> None:
    profiles = {'hub': ('github.com', frozenset({MERGE})), 'tea': ('forge.example', frozenset({BASE}))}
    assert compare(profiles, {}, REQUIRED) == []


def test_a_profile_reads_the_tree_and_the_forge(tmp_path: Path) -> None:
    (tmp_path / '.github' / 'workflows').mkdir(parents=True)
    (tmp_path / '.github' / 'workflows' / 'ci.yml').write_text('x', encoding='utf-8')
    (tmp_path / 'AGENTS.md').write_text('x', encoding='utf-8')
    (tmp_path / 'pyproject.toml').write_text("[tool.dev_lab.branchset]\nephemeral = ['pr/*']\n", encoding='utf-8')
    facts = Facts(pulls=True, missing_branches=(), protection_drift=(), secrets=frozenset({'AI_LAB_KEYS_PR_REVIEW'}),
                  oldest_open=None, contexts={'trunk': ('tests/base',)})  # fmt: skip
    assert features(tmp_path, facts) == {'workflow:ci.yml', 'file:AGENTS.md', 'manifest:ephemeral', REVIEW, BASE}


def test_a_context_the_member_s_own_resources_produce_is_no_family_feature(tmp_path: Path) -> None:
    """A repo declaring ``resources = ["windows"]`` requires ``tests/windows`` BY DESIGN; no peer lacks it.

    PLANTED CONTROL: the same context on a repo that declares no such resource is compared like any other.
    """
    (tmp_path / 'pyproject.toml').write_text('[tool.lab_commons.tests]\nresources = ["windows"]\n', encoding='utf-8')
    facts = Facts(pulls=True, missing_branches=(), protection_drift=(), secrets=frozenset(), oldest_open=None,
                  contexts={'trunk': ('tests/base', 'tests/windows')})  # fmt: skip
    assert features(tmp_path, facts) == {BASE}
    (tmp_path / 'pyproject.toml').write_text('', encoding='utf-8')
    assert features(tmp_path, facts) == {BASE, 'protect:trunk:tests/windows'}
