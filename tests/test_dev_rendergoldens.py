"""A generator change shows exactly which repos' renders it moves: every fixture's render, pinned byte for byte.

A red here names each moved render. If the move is intended, re-render the goldens and commit them in the same
change -- that diff is the reviewed edit:
``python -m dev_lab.dev.rendergoldens update --fixtures tests/_render_fixtures --goldens tests/_render_goldens``.
"""

from __future__ import annotations

import dataclasses
import shutil
import subprocess
from pathlib import Path

import pytest

from dev_lab.dev import ciworkflows, famfiles, rendergoldens
from dev_lab.dev.famconfig import BASES, RENDERED
from dev_lab.dev.rules import ALWAYS_ON, RULES, enforced_ids

_TESTS = Path(__file__).resolve().parent
FIXTURES = _TESTS / '_render_fixtures'
GOLDENS = _TESTS / '_render_goldens'
#: Each fixture BY NAME, and the forge it stands for: a fixture lost from the directory cannot read as clean.
_FIXTURES = {'github_plain': 'github', 'github_overrides': 'github', 'gitea_review': 'gitea'}


def test_every_fixture_render_matches_its_golden() -> None:
    moved = rendergoldens.compare(rendergoldens.render_fixtures(FIXTURES), rendergoldens.read_goldens(GOLDENS))
    assert moved == [], f'renders moved; if intended, re-render the goldens (module docstring): {moved}'


def test_every_golden_is_tracked_and_no_ignore_rule_reaches_one() -> None:
    """A golden git ignores is never committed: every other checkout reads it as missing (the Linux red, 11-12)."""
    files = sorted(path.relative_to(_TESTS.parent).as_posix() for path in GOLDENS.rglob(f'*{rendergoldens.SUFFIX}'))
    done = subprocess.run(
        [shutil.which('git') or 'git', 'check-ignore', '--no-index', '--stdin'],
        input='\n'.join(files),
        cwd=_TESTS.parent,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert files
    assert done.stdout.split() == [], f'goldens under an ignore rule: {done.stdout.split()}'


def test_the_fixtures_are_the_named_set_and_cover_every_generator() -> None:
    rendered = rendergoldens.render_fixtures(FIXTURES)
    assert {key.split('/', 1)[0] for key in rendered} == set(_FIXTURES)
    paths = {key.split('/', 1)[1] for key in rendered}
    assert {base for base, row in BASES.items() if row.mode == RENDERED} <= paths
    assert {rel for rel, _ in famfiles.whole_files()} <= paths
    for forge in set(_FIXTURES.values()):
        assert {(ciworkflows.WORKFLOW_DIRS[forge] / name).as_posix() for name in ciworkflows.base_names(forge)} <= paths


def test_a_planted_generator_change_is_named_in_every_fixture_it_moves(monkeypatch: pytest.MonkeyPatch) -> None:
    """PLANTED CONTROL: a moved base names each fixture rendering it, and leaves the others' renders unnamed."""
    base = BASES['.rgignore']
    monkeypatch.setitem(BASES, '.rgignore', dataclasses.replace(base, lines=(*base.lines, 'planted/')))
    moved = rendergoldens.compare(rendergoldens.render_fixtures(FIXTURES), rendergoldens.read_goldens(GOLDENS))
    assert moved == ['gitea_review/.rgignore: changed', 'github_plain/.rgignore: changed']


def test_compare_names_a_changed_a_new_and_a_gone_render() -> None:
    assert rendergoldens.compare({'a': '1', 'b': '2'}, {'a': '0', 'c': '3'}) == [
        'a: changed',
        'b: new, no golden',
        'c: gone, its golden is stale',
    ]


def test_update_writes_exactly_the_render_and_removes_a_stale_golden(tmp_path: Path) -> None:
    stale = tmp_path / f'x/a{rendergoldens.SEP}old{rendergoldens.SUFFIX}'
    stale.parent.mkdir()
    stale.write_text('old', encoding='utf-8')
    assert rendergoldens.write({'x/.claude/rem.json': 'a\n'}, tmp_path) == [
        'x/.claude/rem.json: new, no golden',
        'x/a/old: gone, its golden is stale',
    ]
    assert rendergoldens.read_goldens(tmp_path) == {'x/.claude/rem.json': 'a\n'}
    assert (tmp_path / f'x/.claude{rendergoldens.SEP}rem.json{rendergoldens.SUFFIX}').is_file()
    assert not stale.exists()


def test_declared_forge_reads_the_one_forge_and_refuses_none() -> None:
    assert ciworkflows.declared_forge('[tool.dev_lab.ci."review.yml"]\n', 'x') == 'gitea'
    with pytest.raises(ValueError, match='no'):
        ciworkflows.declared_forge('', 'x')


def test_enforced_ids_is_the_registry_less_the_absent_and_the_always_on() -> None:
    some = RULES[0].id if RULES[0].id not in ALWAYS_ON else RULES[1].id
    assert enforced_ids({some}) == {rule.id for rule in RULES} - ALWAYS_ON - {some}
    with pytest.raises(ValueError, match='NOT-A-RULE'):
        enforced_ids({'NOT-A-RULE'})
