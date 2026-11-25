"""The family's engineering principles: one tuple, its JSON payload, its rendered rules page."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dev_lab.dev import principles
from dev_lab.dev.docwidth import WIDTH_CEILING
from dev_lab.dev.principles import PRINCIPLES, bullet_lines, payload
from dev_lab.dev.rules import RULES

ROOT = Path(__file__).resolve().parents[1]


def test_the_set_is_the_named_set_and_keeps_valuable_options() -> None:
    """A NAMED SET, not a count: a dropped or renamed id names itself."""
    assert [one.id for one in PRINCIPLES] == [
        'first-principles', 'no-historical-baggage', 'occams-razor', 'single-source-of-truth',
        'layered-decoupling', 'names-match-behavior', 'no-backward-compatibility', 'progressive-disclosure',
        'keep-valuable-options', 'every-wall-teaches', 'no-barrier-fan-out', 'images-by-absolute-path',
        'worktree-names-its-task', 'native-first',
    ]  # fmt: skip
    kept = {one.id: one for one in PRINCIPLES}['keep-valuable-options']
    assert kept.name == 'Keep every valuable parameter and option'
    assert kept.statement.startswith('Generality is a requirement: keep every parameter and option')


def test_a_reference_match_adds_an_option_and_the_razors_never_remove_capability() -> None:
    """User ruling 2026-11-12: a vendor match is ADDED as a choice, never substituted for the native one."""
    by_id = {one.id: one.statement for one in PRINCIPLES}
    kept = by_id['keep-valuable-options']
    for clause in (
        'ADDS a selectable option',
        'never replaces or deletes the alternative',
        'numerical method choices are options even with no current caller',
    ):
        assert clause in kept
    assert by_id['occams-razor'].endswith('never a capability.')
    assert by_id['no-historical-baggage'].endswith('never a capability.')


def test_every_wall_teaches_names_the_gap_and_the_loop() -> None:
    """User ruling 2026-11-13: a wall with no named cause and door is a mechanism gap, closed before the task."""
    wall = {one.id: one for one in PRINCIPLES}['every-wall-teaches']
    for clause in (
        'names its cause and its door',
        'is a mechanism gap',
        'comes before the task',
        'Never route around a wall or hand the user a command.',
        'docs-src/dev/feedback.md',
    ):
        assert clause in wall.statement


def test_no_barrier_fan_out_lands_each_item_without_waiting() -> None:
    """User ruling 2026-11-13: parallel items land as each finishes; no join on the slowest unless truly needed."""
    fan = {one.id: one for one in PRINCIPLES}['no-barrier-fan-out']
    for clause in (
        'each landed the moment it is done',
        'nothing waits for the slowest sibling',
        'unless a step truly needs every result',
        'docs-src/dev/fanout.md',
    ):
        assert clause in fan.statement


def test_an_image_is_delivered_by_absolute_path_and_a_worktree_is_named_for_its_task() -> None:
    """User ruling 2026-11-22: both statements, each citing the rule whose mechanism refuses a violation."""
    by_id = {one.id: one.statement for one in PRINCIPLES}
    for clause in ('ABSOLUTE path', 'never a relative one', 'IMAGES-BY-ABSOLUTE-PATH'):
        assert clause in by_id['images-by-absolute-path']
    for clause in ('physical meaning tied to its task', '`agent-<hex>`', 'is forbidden', 'WORKTREE-NAMES-ITS-TASK'):
        assert clause in by_id['worktree-names-its-task']
    assert {'IMAGES-BY-ABSOLUTE-PATH', 'WORKTREE-NAMES-ITS-TASK'} <= {rule.id for rule in RULES}


def test_native_first_is_the_ruling_verbatim_and_has_its_mechanism() -> None:
    """User ruling 2026-11-25 (D51 L2): the statement is the user's words; NATIVE-FIRST is its opt-in mechanism."""
    native = {one.id: one for one in PRINCIPLES}['native-first']
    assert native.name == 'Native first'
    assert native.statement == (
        'Python declares and orchestrates, Rust computes. A stage Rust owns is written in Rust from its first line; '
        'a Python version of it is only a scratch prototype, never a second implementation; acceptance is against '
        'references (analytic, the vendor ladder, the previous implementation during a migration), never against a '
        'Python twin.'
    )
    assert 'NATIVE-FIRST' in {rule.id for rule in RULES}


def test_the_json_flag_prints_the_payload(capsys: pytest.CaptureFixture[str]) -> None:
    """``--json`` prints exactly ``{"principles": [{id, name, statement}...]}``."""
    assert principles.main(['--json']) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed == payload()
    assert printed['principles'][0] == {
        'id': 'first-principles',
        'name': 'First principles',
        'statement': PRINCIPLES[0].statement,
    }


def test_the_page_fits_the_width_and_names_every_principle() -> None:
    """Every line within the injected-doc ceiling; every id and verbatim statement present."""
    lines = bullet_lines()
    assert all(len(line) <= WIDTH_CEILING for line in lines)
    flat = ' '.join(line.strip() for line in lines)
    for one in PRINCIPLES:
        assert f'- **{one.name}** (`{one.id}`): {one.statement}' in flat
