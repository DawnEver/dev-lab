"""Every ``forge sync`` refusal and stop leads with its rule id, its cause on one line and its door on the next.

MEASURED 2026-11-17: a sync on a dirty tree printed ONE line, ``[sync] refused: the tree has uncommitted changes:
commit them first, a merge must start from a commit``, and the walls ledger recorded it as rule ``unknown`` with
``remedy_present: false`` -- it named no rule id (:func:`walls.rule_of` reads ``<RULE-ID>:`` at a line start) and its
door shared the cause's line (:func:`walls.has_remedy` wants a cause line and a door line). The conflict stop had its
door on a line of its own and still no rule id. Each text below is produced by its REAL cause on a planted git repo,
printed by ``forge sync`` itself, and recorded through the walls choke point. PLANTED CONTROL: the old one-line form,
and each text folded back onto one line, name no door.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from _branch_repos import advance, clone_pair, commit
from _forge_fake import git_out, run_git

from dev_lab.dev import disclosure, forgesync, walls
from dev_lab.dev.lanepolicy import Policy

ROOT = Path(__file__).resolve().parents[1]
POLICY = Policy(integration='integrate/main')
OLD_DIRTY = '[sync] refused: the tree has uncommitted changes: commit them first, a merge must start from a commit'


def _child(tmp_path: Path) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    _, work = clone_pair(tmp_path)
    advance(work, 'integrate/main', 'i.txt', 'i\n')
    advance(work, 'feat/other', 'o.txt', 'o\n')
    run_git(work, 'checkout', '-q', '-B', 'feat/mine', 'origin/main')
    commit(work, 'm.txt', 'm\n')
    return work


def _refusing_hook(work: Path) -> None:
    """A pre-commit hook that refuses every commit, so the sync's merge commit fails."""
    hooks = work.parent / 'hooks'
    hooks.mkdir(exist_ok=True)
    hook = '#!/bin/sh\necho the hook refused >&2; exit 1\n'
    (hooks / 'pre-commit').write_text(hook, encoding='utf-8', newline='\n')
    (hooks / 'pre-commit').chmod(0o755)
    run_git(work, 'config', 'core.hooksPath', hooks.as_posix())


def _said(work: Path, capsys: pytest.CaptureFixture[str], *argv: str, fetch=lambda _root: None) -> str:
    """What ``forge sync`` printed to stderr refusing in *work*; it must exit 2."""
    assert forgesync.main(list(argv), cwd=work, fetch=fetch, door=lambda _root: ()) == 2
    return capsys.readouterr().err.strip()


def _failed_fetch(_: Path) -> None:
    msg = 'git fetch origin failed after 3 attempts: could not resolve host'
    raise OSError(msg)


def _every_refusal(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> dict[str, tuple[str, str]]:
    """``{case: (the rule id it must lead with, the text forge sync printed)}``, each from its real cause."""
    found: dict[str, tuple[str, str]] = {}
    dirty = _child(tmp_path / 'dirty')
    (dirty / 'm.txt').write_text('edited\n', encoding='utf-8')
    found['dirty tree'] = (forgesync.STARTS_FROM_A_COMMIT, _said(dirty, capsys))
    merging = _child(tmp_path / 'merging')
    run_git(merging, 'merge', '--no-ff', '--no-commit', 'origin/integrate/main')
    found['half-done merge'] = (forgesync.STARTS_FROM_A_COMMIT, _said(merging, capsys))
    (tmp_path / 'clash').mkdir()
    _, clash = clone_pair(tmp_path / 'clash')
    advance(clash, 'integrate/main', 'x.txt', 'ours\n')
    run_git(clash, 'checkout', '-q', '-B', 'feat/mine', 'origin/main')
    commit(clash, 'x.txt', 'theirs\n')
    found['conflict'] = (forgesync.STOPS_ON_A_CONFLICT, _said(clash, capsys))
    hooked = _child(tmp_path / 'hooked')
    _refusing_hook(hooked)
    found['merge commit refused'] = (forgesync.STEP_FAILED, _said(hooked, capsys))
    found['fetch failed'] = (forgesync.STEP_FAILED, _said(_child(tmp_path / 'offline'), capsys, fetch=_failed_fetch))
    detached = _child(tmp_path / 'detached')
    run_git(detached, 'checkout', '-q', '--detach')
    found['detached HEAD'] = (forgesync.UPSTREAM_SET, _said(detached, capsys))
    trunk = _child(tmp_path / 'trunk')
    run_git(trunk, 'checkout', '-q', 'main')
    found['not a child branch'] = (forgesync.UPSTREAM_SET, _said(trunk, capsys))
    found['watch names no commit'] = (
        forgesync.UPSTREAM_SET,
        _said(_child(tmp_path / 'watch'), capsys, '--watch', 'origin/no-such-branch'),
    )
    return found


def test_every_sync_refusal_leads_with_its_rule_and_puts_its_door_on_a_line_of_its_own(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    said = _every_refusal(tmp_path, capsys)
    assert {case: walls.rule_of(text) for case, (_, text) in said.items()} == {
        case: rule for case, (rule, _) in said.items()
    }
    assert {case for case, (_, text) in said.items() if not walls.has_remedy(text)} == set()
    assert {case for case, (_, text) in said.items() if not text.splitlines()[1].startswith('Door: ')} == set()
    pointed = {case: text for case, (_, text) in said.items()}
    assert disclosure.unresolved_pointers(pointed, ROOT) == [], 'each closes with a details pointer that resolves'


def test_planted_control_the_one_line_form_names_no_rule_and_no_door(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert not walls.has_remedy(OLD_DIRTY)
    assert walls.rule_of(OLD_DIRTY).startswith(walls.UNNAMED)
    said = _every_refusal(tmp_path, capsys)
    folded = {case: ' '.join(text.splitlines()[:-1]) for case, (_, text) in said.items()}
    assert {case for case, text in folded.items() if walls.has_remedy(text)} == set()


def test_a_refused_sync_is_one_wall_on_record_naming_its_rule_and_a_door(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The ledger line the measured wall should have been: its rule, ``remedy_present: true``, in this checkout."""
    work = _child(tmp_path)
    (work / 'm.txt').write_text('edited\n', encoding='utf-8')
    _said(work, capsys)
    lines = walls.ledger(work).read_text(encoding='utf-8').splitlines()
    assert [(row['rule'], row['remedy_present']) for row in map(json.loads, lines)] == [
        (forgesync.STARTS_FROM_A_COMMIT, True)
    ]


def test_the_upstream_set_and_held_index_refusals_carry_a_rule_and_a_door(tmp_path: Path) -> None:
    """The two refusals a plain ``forge sync`` cannot reach: a ref outside the set, an index a relock would sweep."""
    work = _child(tmp_path)
    with pytest.raises(ValueError, match=forgesync.UPSTREAM_SET) as foreign:
        forgesync.sync(work, POLICY, ['origin/feat/other'])
    (work / 'm.txt').write_text('staged\n', encoding='utf-8')
    run_git(work, 'add', 'm.txt')
    with pytest.raises(OSError, match=forgesync.STARTS_FROM_A_COMMIT) as held:
        forgesync.relock(work, door=lambda _root: ('dev-lab',), render=lambda _root: ())
    for text in (str(foreign.value), str(held.value)):
        assert walls.has_remedy(text), text
        assert walls.rule_of(text) in {forgesync.UPSTREAM_SET, forgesync.STARTS_FROM_A_COMMIT}
    assert git_out(work, 'diff', '--cached', '--name-only') == 'm.txt', 'the held index is the owner`s, untouched'
