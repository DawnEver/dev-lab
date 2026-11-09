"""``family check`` / ``family join``: the machine file's ``[repos]`` is the member list; every fact is checked.

A half-onboarded member -- not beside its siblings, its forge without protection or the review secret, a founding
PR open for weeks, absent from what this machine serves -- is NAMED by ``check``; ``join`` runs the steps in
order and prints what is left for the user. The forge is a fake here.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from dev_lab.dev.family import members, watch
from dev_lab.dev.family.members import Facts, Finding

REVIEW = 'AI_LAB_KEYS_PR_REVIEW'
NOW = datetime(2026, 11, 9, tzinfo=UTC)
ONBOARDED = """\
[tool.dev_lab.branchset]
trunk = 'main'
sessions = ['integrate/main']
ephemeral = ['pr/*']

[tool.dev_lab.integrator]
integration = 'integrate/main'
trunk = 'main'
pr_merges_since = 'abc'

[tool.dev_lab.hooks]

[tool.lab_commons.tests]
produce = ['-m', 'dev_lab.dev.verify', '--part', '{part}']
"""


@dataclass
class FakeForge:
    """One member's forge facts."""

    pulls: bool = True
    branches: set[str] = field(default_factory=lambda: {'main', 'integrate/main'})
    drift: tuple[str, ...] = ()
    secrets: set[str] = field(default_factory=lambda: {'AI_LAB_KEYS_PR_REVIEW'})
    oldest: tuple[int, datetime] | None = None

    def facts(self, _root: Path, trunk: str, integration: str) -> Facts:
        return Facts(
            pulls=self.pulls,
            missing_branches=tuple(b for b in (trunk, integration) if b not in self.branches),
            protection_drift=self.drift,
            secrets=frozenset(self.secrets),
            oldest_open=self.oldest,
        )


def _repo(parent: Path, name: str, text: str = ONBOARDED) -> Path:
    root = parent / name
    root.mkdir(parents=True)
    (root / 'pyproject.toml').write_text(text, encoding='utf-8')
    (root / 'AGENTS.md').write_text('x', encoding='utf-8')
    (root / 'uv.lock').write_text('x', encoding='utf-8')
    return root


def _check(tmp_path: Path, forge: FakeForge, served: tuple[str, ...] | None = ('a', 'b')) -> list[Finding]:
    family = {'a': tmp_path / 'work' / 'a', 'b': tmp_path / 'work' / 'b'}
    return members.check(family, forge=lambda _name, _root: forge, served=served, now=NOW,
                         bundle_name='AI_LAB_KEYS_PR_REVIEW')  # fmt: skip


def test_a_fully_onboarded_family_has_no_finding(tmp_path: Path) -> None:
    _repo(tmp_path / 'work', 'a')
    _repo(tmp_path / 'work', 'b')
    assert _check(tmp_path, FakeForge()) == []


def test_a_half_onboarded_member_is_named_for_every_missing_fact(tmp_path: Path) -> None:
    _repo(tmp_path / 'work', 'a')
    _repo(tmp_path / 'work', 'b', ONBOARDED.replace("pr_merges_since = 'abc'\n", ''))
    half = FakeForge(branches={'integrate/main'}, drift=('integrate/main: requires tests/merge-ready',),
                     secrets=set(), oldest=(1, NOW - timedelta(days=30)))  # fmt: skip
    found = {(f.member, f.what.split(':')[0]) for f in _check(tmp_path, half, served=('a',))}
    assert {
        ('b', 'onboarding'),
        ('b', 'trunk branch'),
        ('b', 'protection'),
        ('b', 'secret'),
        ('b', 'open PR'),
        ('b', 'not served'),
    } <= found
    # PLANTED CONTROL: the onboarded sibling with the same fake forge is named only for the forge's facts
    assert ('a', 'onboarding') not in found
    assert ('a', 'not served') not in found


def test_a_member_not_beside_its_siblings_or_absent_is_named(tmp_path: Path) -> None:
    _repo(tmp_path / 'work', 'a')
    _repo(tmp_path / 'elsewhere', 'b')
    family = {'a': tmp_path / 'work' / 'a', 'b': tmp_path / 'elsewhere' / 'b', 'c': tmp_path / 'work' / 'c'}
    found = members.check(family, forge=lambda _n, _r: FakeForge(), served=None, now=NOW, bundle_name=REVIEW)
    whats = {(f.member, f.what.split(':')[0]) for f in found}
    assert ('c', 'not cloned') in whats
    assert ('a', 'not beside') not in whats
    assert len([f for f in found if f.member == 'b' and f.what.startswith('not beside')]) == 1


def test_a_served_repo_no_member_names_is_drift(tmp_path: Path) -> None:
    _repo(tmp_path / 'work', 'a')
    _repo(tmp_path / 'work', 'b')
    found = _check(tmp_path, FakeForge(), served=('a', 'b', 'stray'))
    assert [(f.member, f.what) for f in found] == [('stray', 'served but no [repos] member')]


def test_join_records_the_member_and_prints_what_is_left(tmp_path: Path) -> None:
    machine = tmp_path / 'config.toml'
    machine.write_text('[repos]\na = "' + (tmp_path / 'work' / 'a').as_posix() + '"\n', encoding='utf-8')
    _repo(tmp_path / 'work', 'a')
    cloned: list[tuple[str, Path]] = []

    def clone(url: str, where: Path) -> None:
        cloned.append((url, where))
        _repo(where.parent, where.name, ONBOARDED.replace("pr_merges_since = 'abc'\n", ''))

    steps = members.join('b', 'https://forge.example/o/b.git', machine=machine, clone=clone,
                         protect=lambda _root: (), secrets=None)  # fmt: skip
    assert cloned == [('https://forge.example/o/b.git', tmp_path / 'work' / 'b')]
    assert 'b = ' in machine.read_text(encoding='utf-8')
    assert any(line.startswith('left: onboarding') for line in steps)
    assert any(line.startswith('left: secrets') for line in steps)
    # PLANTED CONTROL: a second join clones nothing and records nothing twice
    again = members.join('b', 'https://forge.example/o/b.git', machine=machine, clone=clone,
                         protect=lambda _root: (), secrets=None)  # fmt: skip
    assert len(cloned) == 1
    assert machine.read_text(encoding='utf-8').count('b = ') == 1
    assert 'cloned' not in ' '.join(again)


def test_join_refuses_a_machine_with_no_member_to_stand_beside(tmp_path: Path) -> None:
    machine = tmp_path / 'config.toml'
    machine.write_text('', encoding='utf-8')
    with pytest.raises(members.FamilyRefused, match=r'\[repos\]'):
        members.join('b', 'https://forge.example/o/b.git', machine=machine, clone=lambda _u, _w: None,
                     protect=lambda _root: (), secrets=None)  # fmt: skip


def test_the_watch_alarms_each_finding_on_the_kits_tick_only(tmp_path: Path) -> None:
    raised: list[object] = []
    findings = [Finding('b', 'secret: absent'), Finding('b', 'open PR: #1 open 30 days')]
    watch.step(tmp_path / 'dev-lab', 'https://forge.example/o/dev-lab.git', say=lambda _s: None,
               alarm=raised.append, read=lambda: findings)  # fmt: skip
    assert [(a.kind, a.about) for a in raised] == [('family', 'b:secret'), ('family', 'b:open PR')]
    # PLANTED CONTROL: another repo's tick reads nothing and raises nothing
    watch.step(tmp_path / 'other', 'https://forge.example/o/other.git', say=lambda _s: None,
               alarm=raised.append, read=lambda: pytest.fail('read on a non-kit tick'))  # fmt: skip
    assert len(raised) == 2


def test_a_gitea_member_is_never_owed_the_bundle_and_is_named_when_it_holds_one(tmp_path: Path) -> None:
    """Ruling 2026-11-03. PLANTED CONTROLS: a GitHub member without it is named; a Gitea member holding it is a leak."""
    _repo(tmp_path / 'work', 'a')
    _repo(tmp_path / 'work', 'b')
    family = {'a': tmp_path / 'work' / 'a', 'b': tmp_path / 'work' / 'b'}

    def run(host: str, secrets: set[str]) -> set[str]:
        @dataclass
        class Hosted(FakeForge):
            def facts(self, root: Path, trunk: str, integration: str) -> Facts:
                return replace(super().facts(root, trunk, integration), host=host)

        found = members.check(family, forge=lambda _n, _r: Hosted(secrets=secrets), served=None, now=NOW,
                              bundle_name=REVIEW)  # fmt: skip
        return {f.what.split(' --')[0] for f in found if f.member == 'a'}

    assert not {w for w in run('forge.example', set()) if w.startswith('secret')}
    assert any('where any PR can read it' in w for w in run('forge.example', {REVIEW}))
    assert any(w.startswith(f'secret: {REVIEW} is absent') for w in run('github.com', set()))
