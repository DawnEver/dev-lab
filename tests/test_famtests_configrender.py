"""``lab_commons.dev.famtests.configrender`` -- driven over REAL artefacts on disk.

WHY REAL FILES. Every assertion this body makes is about what is ON DISK against what the live base
and a declared delta RENDER, and a fixture that hands the comparison two in-memory strings has
deleted the only half that can drift. So each case writes a real artefact into ``tmp_path`` through
the kit's own renderer, then bends exactly one thing about it.

EVERY REFUSAL IS PLANTED IN BOTH DIRECTIONS. A guard that only ever reds is as useless as one that
only ever passes, and both readings look identical from a green suite, so each arm below drives the
passing state through the SAME function first.

THE RESOLVER IS THE TEST'S, AND SO IT MUST BE. ``pre_commit`` is not installed in this package and
must not become a dependency of it -- ``lab_commons.dev``'s own inventory records that the layer is
"stdlib plus tier 1" and that ``pip install lab-commons`` pulls nothing new. The stage engine is
therefore a REQUIRED ARGUMENT with no default, and the arms here supply a real callable that reads a
real file, which is also what proves the refusal fires when a caller supplies nothing usable.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

from lab_commons.dev.famconfig import (
    BASES,
    RENDERED,
    REQUIRED,
    Base,
    Delta,
    artefact_base,
    render,
)
from lab_commons.dev.famtests.configrender import (
    UnresolvedHooks,
    assert_artefact_is_rendered,
    assert_declared_ids_survive,
    assert_delta_is_not_a_fork,
    assert_every_base_is_accounted_for,
    assert_modes_are_as_agreed,
    assert_no_base_line_left_undeclared,
    assert_no_rule_is_reopened,
    assert_pre_push_premise,
    assert_render_round_trips,
    assert_stage_declaration,
    declared_hook_ids,
    reopenings,
    resolved_stages,
    stage_partition,
)

_REPO = 'planted-repo'


@dataclass(frozen=True)
class _Hook:
    """What a stage engine hands back: an id and the stages it resolved to. Duck-typed on purpose."""

    id: str
    stages: tuple[str, ...]


def _gitignore_delta(**over: object) -> Delta:
    fields: dict[str, object] = {'repo': _REPO, 'added': ('scratch/',), 'dropped': {}, 'ceiling': 4}
    return Delta(**(fields | over))


def _write(root: Path, artefact: str, delta: Delta) -> Path:
    """Render the artefact into *root* exactly as a consumer's re-render would."""
    path = root / artefact
    path.write_text(render(artefact_base(artefact), delta), encoding='utf-8')
    return path


def _deltas(root: Path) -> dict[str, Delta]:
    """A complete declaration over the kit's bases, rendered into *root*."""
    out = {name: Delta(repo=_REPO, added=(), dropped={}, ceiling=4) for name in BASES}
    out['.gitignore'] = _gitignore_delta()
    for artefact, delta in out.items():
        _write(root, artefact, delta)
    return out


# ---------------------------------------------------------------- completeness over the kit's bases


def test_a_declaration_covering_every_base_passes_and_a_gap_is_named(tmp_path: Path) -> None:
    """BOTH SIDES. A base nobody adopted or refused is an artefact drifting with nobody saying so."""
    complete = _deltas(tmp_path)
    assert_every_base_is_accounted_for(deltas=complete, repo=_REPO)

    partial = dict(complete)
    dropped = min(partial)
    del partial[dropped]
    with pytest.raises(AssertionError, match=re.escape(dropped)):
        assert_every_base_is_accounted_for(deltas=partial, repo=_REPO)


def test_a_declaration_naming_an_artefact_the_kit_does_not_publish_is_named(tmp_path: Path) -> None:
    """The other side: a declaration outliving its subject reads as a live adoption."""
    deltas = dict(_deltas(tmp_path))
    deltas['pyproject.toml'] = Delta(repo=_REPO, added=(), dropped={}, ceiling=1)
    with pytest.raises(AssertionError, match=re.escape('pyproject.toml')):
        assert_every_base_is_accounted_for(deltas=deltas, repo=_REPO)


def test_an_empty_declaration_is_refused_rather_than_reported_clean() -> None:
    """THE FLOOR. ``set() == set()`` would be green over a repo that adopted nothing at all."""
    with pytest.raises(AssertionError, match='declares no artefact'):
        assert_every_base_is_accounted_for(deltas={}, repo=_REPO)


# ---------------------------------------------------------------- the property, and a hand edit


def test_a_freshly_rendered_tree_installs_and_one_hand_edit_reds(tmp_path: Path) -> None:
    """THE PROPERTY, BOTH WAYS, through the function a consumer calls rather than through a copy."""
    deltas = _deltas(tmp_path)
    for artefact in sorted(deltas):
        assert_artefact_is_rendered(
            root=tmp_path, artefact=artefact, deltas=deltas, repo=_REPO, rerender_hint='make render'
        )

    path = tmp_path / '.gitignore'
    path.write_text(path.read_text(encoding='utf-8').replace('uv.lock', 'uv.lock.bak'), encoding='utf-8')
    with pytest.raises(AssertionError, match=re.escape('uv.lock')):
        assert_artefact_is_rendered(
            root=tmp_path, artefact='.gitignore', deltas=deltas, repo=_REPO, rerender_hint='make render'
        )


def test_the_remedy_is_the_one_the_caller_declared_and_the_mode_decides_which(tmp_path: Path) -> None:
    """A rendered artefact's remedy is a RE-RENDER; a required one's is adding the missing line.

    The hint has no default because the command that re-renders a repo's artefacts is that repo's --
    one lab runs a Makefile target and the other an inline interpreter line, measured today.
    """
    deltas = _deltas(tmp_path)
    (tmp_path / '.gitignore').write_text('nothing like the base\n', encoding='utf-8')
    with pytest.raises(AssertionError, match='the-declared-remedy'):
        assert_artefact_is_rendered(
            root=tmp_path, artefact='.gitignore', deltas=deltas, repo=_REPO, rerender_hint='the-declared-remedy'
        )

    makefile = next(name for name, base in BASES.items() if base.mode == REQUIRED)
    (tmp_path / makefile).write_text('nothing:\n\t@true\n', encoding='utf-8')
    with pytest.raises(AssertionError, match=re.escape('declare each as a Delta.dropped')):
        assert_artefact_is_rendered(
            root=tmp_path, artefact=makefile, deltas=deltas, repo=_REPO, rerender_hint='the-declared-remedy'
        )


def test_a_missing_artefact_is_refused_rather_than_read_as_clean(tmp_path: Path) -> None:
    """An unwritten artefact guarantees nothing, which is not the same as passing."""
    deltas = _deltas(tmp_path)
    (tmp_path / '.gitignore').unlink()
    with pytest.raises(AssertionError, match=re.escape('.gitignore')):
        assert_artefact_is_rendered(
            root=tmp_path, artefact='.gitignore', deltas=deltas, repo=_REPO, rerender_hint='make render'
        )


def test_a_delta_is_checked_as_a_declaration_separately_from_the_file(tmp_path: Path) -> None:
    """The anti-fork arm reds on the DECLARATION rather than only on the file.

    "The file drifted" and "the declaration is broken" are two answers rather than one opaque failure.
    """
    deltas = _deltas(tmp_path)
    assert_delta_is_not_a_fork(artefact='.gitignore', deltas=deltas, repo=_REPO)

    forked = dict(deltas)
    restated = artefact_base('.gitignore').content_lines[0]
    forked['.gitignore'] = _gitignore_delta(added=(restated,))
    with pytest.raises(AssertionError, match='not a delta of the base'):
        assert_delta_is_not_a_fork(artefact='.gitignore', deltas=forked, repo=_REPO)


# ---------------------------------------------------------------- last-match-wins on .gitignore


def test_a_bare_spelling_of_a_slashed_base_rule_is_named() -> None:
    """A trailing slash matches a DIRECTORY ONLY, so the two spellings are different RULES.

    The delta renders AFTER the base and gitignore is last-match-wins per path, so a bare
    re-statement silently reverts the slashed base rule while every byte comparison stays green --
    the one regression the rendered-bytes property cannot see.
    """
    base = artefact_base('.gitignore')
    slashed = next(line for line in base.content_lines if line.endswith('/'))
    bare = slashed.rstrip('/')

    clean = _gitignore_delta()
    assert_no_rule_is_reopened(base=base, delta=clean, repo=_REPO, directory_floor=1)
    assert reopenings(base, clean).bare == ()

    with pytest.raises(AssertionError, match=bare.replace('*', r'\*').replace('.', r'\.')):
        assert_no_rule_is_reopened(base=base, delta=_gitignore_delta(added=(bare,)), repo=_REPO, directory_floor=1)


def test_a_negation_reopening_a_base_directory_is_named_unless_the_delta_closes_it() -> None:
    """THE ORDERING HAZARD, and its declared remedy, both driven.

    One lab has a single negation naming one file and the other has twenty, closed again by a final
    ``__pycache__/``. The PROPERTY is the same in both and the count is not, so the count is not
    what is asserted.
    """
    base = artefact_base('.gitignore')
    slashed = next(line for line in base.content_lines if line.endswith('/'))
    reopened = f'!{slashed}'

    with pytest.raises(AssertionError, match='re-include'):
        assert_no_rule_is_reopened(base=base, delta=_gitignore_delta(added=(reopened,)), repo=_REPO, directory_floor=1)

    closed = _gitignore_delta(added=(reopened, slashed.lstrip('*/')))
    assert reopenings(base, closed).reopened == (), reopenings(base, closed)
    assert_no_rule_is_reopened(base=base, delta=closed, repo=_REPO, directory_floor=1)


def test_the_reopening_scan_refuses_a_base_it_could_not_read() -> None:
    """THE FLOOR. Finding no reopened rule over a base holding no directory rule is vacuous."""
    empty = Base(artefact='.gitignore', lines=('*.log',), mode=RENDERED)
    assert reopenings(empty, _gitignore_delta()).base_directories == ()
    with pytest.raises(AssertionError, match='directory rule'):
        assert_no_rule_is_reopened(base=empty, delta=_gitignore_delta(), repo=_REPO, directory_floor=1)


# ---------------------------------------------------------------- the hook ids, read off the file


def test_the_declared_ids_are_read_off_the_real_artefact(tmp_path: Path) -> None:
    """A named set that only ever agrees with itself stays green through losing every hook it names."""
    path = tmp_path / '.pre-commit-config.yaml'
    path.write_text(
        'repos:\n  - repo: somewhere\n    hooks:\n      - id: alpha\n      - id: beta\n        exclude: x\n',
        encoding='utf-8',
    )
    assert declared_hook_ids(path) == frozenset({'alpha', 'beta'})
    assert_declared_ids_survive(config=path, extra_hook_ids=('alpha',), hook_floor=2)

    with pytest.raises(AssertionError, match='gamma'):
        assert_declared_ids_survive(config=path, extra_hook_ids=('alpha', 'gamma'), hook_floor=2)


def test_an_unreadable_config_answers_None_and_the_assert_refuses(tmp_path: Path) -> None:
    """``None`` is not the empty set: a file that is not there names no ids and denies none either."""
    assert declared_hook_ids(tmp_path / 'absent.yaml') is None
    with pytest.raises(AssertionError, match='could not be read'):
        assert_declared_ids_survive(config=tmp_path / 'absent.yaml', extra_hook_ids=('alpha',), hook_floor=1)


def test_a_config_below_the_floor_is_refused_rather_than_reported_clean(tmp_path: Path) -> None:
    """A subset check against a file that parsed to nothing agrees with every claim made about it."""
    path = tmp_path / '.pre-commit-config.yaml'
    path.write_text('repos: []\n', encoding='utf-8')
    assert declared_hook_ids(path) == frozenset()
    with pytest.raises(AssertionError, match='below the'):
        assert_declared_ids_survive(config=path, extra_hook_ids=(), hook_floor=5)


# ---------------------------------------------------------------- the stages, through a real engine


def _engine(table: Path) -> Callable[[Path], tuple[_Hook, ...]]:
    """A REAL resolver: it reads a REAL file and returns what that file says. No default exists."""

    def resolve(config: Path) -> tuple[_Hook, ...]:
        rows = json.loads((table.parent / f'{config.name}.resolved').read_text(encoding='utf-8'))
        return tuple(_Hook(id=row['id'], stages=tuple(row['stages'])) for row in rows)

    return resolve


def _resolved(tmp_path: Path, rows: list[dict[str, object]]) -> Path:
    config = tmp_path / '.pre-commit-config.yaml'
    config.write_text('repos: []\n', encoding='utf-8')
    (tmp_path / f'{config.name}.resolved').write_text(json.dumps(rows), encoding='utf-8')
    return config


def test_the_stage_partition_is_two_sided_on_both_sets(tmp_path: Path) -> None:
    """A declaration that only listed what MOVED could not see a hook silently joining the move."""
    rows = [
        {'id': 'narrowed-one', 'stages': ['pre-commit']},
        {'id': 'narrowed-two', 'stages': ['pre-commit']},
        {'id': 'keeps-push', 'stages': ['pre-commit', 'pre-push', 'manual']},
        {'id': 'commit-msg-hook', 'stages': ['commit-msg']},
    ]
    config = _resolved(tmp_path, rows)
    resolve = _engine(config)

    partition = stage_partition(resolved_stages(config, resolve=resolve))
    assert partition.narrowed == frozenset({'narrowed-one', 'narrowed-two'}), partition
    assert partition.pre_push == frozenset({'keeps-push'}), partition

    assert_stage_declaration(
        config=config,
        resolve=resolve,
        hook_floor=4,
        narrowed=frozenset({'narrowed-one', 'narrowed-two'}),
        keeps_pre_push=frozenset({'keeps-push'}),
    )

    with pytest.raises(AssertionError, match='narrowed-two'):
        assert_stage_declaration(
            config=config,
            resolve=resolve,
            hook_floor=4,
            narrowed=frozenset({'narrowed-one'}),
            keeps_pre_push=frozenset({'keeps-push'}),
        )
    with pytest.raises(AssertionError, match='keeps-push'):
        assert_stage_declaration(
            config=config,
            resolve=resolve,
            hook_floor=4,
            narrowed=frozenset({'narrowed-one', 'narrowed-two'}),
            keeps_pre_push=frozenset(),
        )


def test_a_declared_empty_narrowing_is_a_measurement_and_not_a_hole(tmp_path: Path) -> None:
    """``frozenset()`` must be SPELLED: "we measured and none narrowed" is not "we never asked"."""
    config = _resolved(tmp_path, [{'id': 'keeps-push', 'stages': ['pre-commit', 'pre-push']}])
    assert_stage_declaration(
        config=config,
        resolve=_engine(config),
        hook_floor=1,
        narrowed=frozenset(),
        keeps_pre_push=frozenset({'keeps-push'}),
    )


def test_an_engine_that_resolved_nothing_refuses_rather_than_agreeing(tmp_path: Path) -> None:
    """THE FLOOR.

    A stage table read off a config the engine resolved to nothing agrees with every claim made about
    it, including a declaration that narrowed everything.
    """
    config = _resolved(tmp_path, [])
    with pytest.raises(UnresolvedHooks, match='below the'):
        assert_stage_declaration(
            config=config,
            resolve=_engine(config),
            hook_floor=5,
            narrowed=frozenset(),
            keeps_pre_push=frozenset(),
        )


def test_an_engine_that_raises_is_reported_as_unresolved_and_never_as_empty(tmp_path: Path) -> None:
    """An engine that could not answer is not an engine that answered nothing."""

    def broken(config: Path) -> tuple[_Hook, ...]:
        msg = f'the engine could not load {config}'
        raise RuntimeError(msg)

    config = _resolved(tmp_path, [{'id': 'a', 'stages': ['pre-commit']}])
    with pytest.raises(UnresolvedHooks, match='could not load'):
        resolved_stages(config, resolve=broken)


# ---------------------------------------------------------------- the premise the narrowing rests on


def test_the_pre_push_premise_is_pinned_in_whichever_direction_the_repo_declared(tmp_path: Path) -> None:
    """The premise is the repo's, so it arrives declared, and BOTH sides red.

    One lab's narrowing is free because it has NO pre-push hook; the other's is a real loss because
    it has one.
    """
    hooks = tmp_path / 'hooks'
    hooks.mkdir()
    assert_pre_push_premise(hooks_dir=hooks, pre_push_installed=False)
    with pytest.raises(AssertionError, match='declares a pre-push hook'):
        assert_pre_push_premise(hooks_dir=hooks, pre_push_installed=True)

    (hooks / 'pre-push').write_text('#!/bin/sh\n', encoding='utf-8')
    assert_pre_push_premise(hooks_dir=hooks, pre_push_installed=True)
    with pytest.raises(AssertionError, match='a pre-push hook is installed'):
        assert_pre_push_premise(hooks_dir=hooks, pre_push_installed=False)


def test_a_hooks_directory_that_is_not_there_is_refused(tmp_path: Path) -> None:
    """A guard that looked nowhere reports the same green as one that looked and found nothing."""
    with pytest.raises(AssertionError, match='looked nowhere'):
        assert_pre_push_premise(hooks_dir=tmp_path / 'absent', pre_push_installed=False)


# ---------------------------------------------------------------- the modes, and the survey


def test_the_mode_each_artefact_is_judged_under_is_the_one_the_repo_agreed_to() -> None:
    """The weaker mode is NAMED so applying it stays a decision somebody typed.

    A ``Makefile`` arriving as RENDERED would turn every repo-local recipe into a diff against a
    family file that cannot hold it, and nothing else in a consumer's suite would say so.
    """
    agreed = {name: base.mode for name, base in BASES.items()}
    assert_modes_are_as_agreed(modes=agreed)

    flipped = dict(agreed)
    required = next(name for name, mode in agreed.items() if mode == REQUIRED)
    flipped[required] = RENDERED
    with pytest.raises(AssertionError, match=re.escape(required)):
        assert_modes_are_as_agreed(modes=flipped)


def test_an_empty_mode_declaration_is_refused() -> None:
    """A mapping nobody filled in compares equal to nothing and passes."""
    with pytest.raises(AssertionError, match='declares no mode'):
        assert_modes_are_as_agreed(modes={})


def test_the_survey_finds_no_undeclared_drop_and_a_deleted_line_is_named(tmp_path: Path) -> None:
    """A second route to the same ratchet, and it does NOT go through the rendered bytes."""
    deltas = _deltas(tmp_path)
    assert_no_base_line_left_undeclared(root=tmp_path, artefact='.gitignore', repo=_REPO)

    path = tmp_path / '.gitignore'
    gone = artefact_base('.gitignore').content_lines[0]
    kept = [line for line in path.read_text(encoding='utf-8').splitlines() if line != gone]
    path.write_text('\n'.join(kept) + '\n', encoding='utf-8')
    with pytest.raises(AssertionError, match='left this file'):
        assert_no_base_line_left_undeclared(root=tmp_path, artefact='.gitignore', repo=_REPO)
    assert deltas['.gitignore'].repo == _REPO


def test_the_round_trip_control_passes_then_reds_on_one_edited_line(tmp_path: Path) -> None:
    """PLANTED CONTROL. A guard green on the real tree could be asserting a constant."""
    deltas = _deltas(tmp_path)
    scratch = tmp_path / 'scratch'
    scratch.mkdir()
    assert_render_round_trips(artefact='.gitignore', deltas=deltas, repo=_REPO, scratch=scratch, edit=('uv.lock', 'x'))

    with pytest.raises(AssertionError, match='no such line'):
        assert_render_round_trips(
            artefact='.gitignore', deltas=deltas, repo=_REPO, scratch=scratch, edit=('not-in-the-base', 'x')
        )


# ------------------------------------------- last-match-wins is about POSITION, not about presence

#: A re-inclusion of a whole SUBTREE. Everything under it comes back, including the cache
#: directories a base directory rule excluded at any depth -- which is what makes a later
#: re-statement of that rule load-bearing rather than redundant.
_DEEP_NEGATION = '!**/.claude/memory/**'

#: The delta's re-statement of a base directory rule. It closes the re-inclusion above it and
#: closes NOTHING below it, because gitignore is last-match-wins per path.
_CLOSURE = '__pycache__/'


def test_a_closure_only_closes_the_reinclusions_ABOVE_it() -> None:
    """A membership test cannot see order, and order is the entire rule.

    The two deltas below hold the SAME TWO LINES and differ only in which comes first. One is
    correct and one re-includes every cache directory under the re-included subtree -- the incident
    a sibling repo's `.gitignore` records, where a `.pyc` under `.claude/memory/` ended up TRACKED.
    A reading that reduced `added` to a set would pass both, which is why both are driven here.
    """
    base = artefact_base('.gitignore')
    assert any(line.rstrip('/').lstrip('*/') == _CLOSURE.rstrip('/') for line in base.content_lines), (
        'the premise: the base must actually exclude this directory, or the case proves nothing'
    )

    sealed = _gitignore_delta(added=(_DEEP_NEGATION, _CLOSURE))
    assert reopenings(base, sealed).unsealed == ()
    assert_no_rule_is_reopened(base=base, delta=sealed, repo=_REPO, directory_floor=1)

    unsealed = _gitignore_delta(added=(_CLOSURE, _DEEP_NEGATION))
    assert reopenings(base, unsealed).unsealed == (_CLOSURE,)
    with pytest.raises(AssertionError, match='re-included by a LATER'):
        assert_no_rule_is_reopened(base=base, delta=unsealed, repo=_REPO, directory_floor=1)


def test_a_negation_naming_one_file_does_not_reopen_a_directory_rule() -> None:
    """THE OTHER SIDE, and it is what keeps the reading from being a ban on negations.

    One sibling repo's whole `.gitignore` negation is a single FILE name. It re-includes that path
    and nothing under it, so no directory rule is reopened and no closure is owed -- a reading that
    reported it would have to be waived somewhere, and a waiver is how this guard would be lost.
    """
    base = artefact_base('.gitignore')
    shallow = _gitignore_delta(added=(_CLOSURE, '!example.log'))
    assert reopenings(base, shallow).unsealed == ()
    assert_no_rule_is_reopened(base=base, delta=shallow, repo=_REPO, directory_floor=1)


def test_a_closure_that_comes_first_does_not_close_the_negation_it_precedes() -> None:
    """The same correction applied to `reopened`: `closed` was a set and answered ANYWHERE.

    The negation and its closure name the same base rule here, so the older membership reading
    reported the rule closed whichever order they were written in.
    """
    base = artefact_base('.gitignore')
    slashed = next(line for line in base.content_lines if line.endswith('/'))
    negation = f'!{slashed}'
    closure = slashed.lstrip('*/')

    assert reopenings(base, _gitignore_delta(added=(negation, closure))).reopened == ()
    assert reopenings(base, _gitignore_delta(added=(closure, negation))).reopened == (negation,)
