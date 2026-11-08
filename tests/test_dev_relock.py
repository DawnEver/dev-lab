"""The forge relocks integration through ONE ROLLING pull request, in-house moves at once, third-party on a cadence.

The staleness reading is ``lockcheck.stale`` -- the one staleness reading -- so these cases plant that reading
(and the door's rewrite of the lock) and run everything else for real: a bare ``origin``, a clone fetching
``origin/integrate/main``, a worktree, a commit, ``ls-remote`` and a leased force-push.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable, Sequence
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from dev_lab.dev import forgeservesteps, relock
from dev_lab.dev.forgealarm import Alarm
from dev_lab.dev.forgesync import relock_floating
from dev_lab.dev.forgework import Client, PullRequest
from dev_lab.dev.lanepolicy import Policy
from dev_lab.dev.lockcheck import UV_PIN
from dev_lab.dev.locklag import _commits_behind, floating_lag, floating_stale
from dev_lab.dev.relock import (
    BRANCH,
    DEFAULT_CADENCE,
    SCOPE,
    TITLE,
    RelockFailed,
    _tree_python,
    cadence,
    carry,
    chosen,
    dist_of,
    in_house,
    rerender,
)

_DECLARED = Policy(integration='integrate/main')  # every repo declares its integration branch (D83)

_GIT = shutil.which('git') or 'git'
_PINT = 'uv.lock is not the newest resolution: Update pint v0.26.1 -> v0.26.2'
_SIBLING = 'uv.lock is not the newest resolution: Update lab-commons v0.3.1 -> v0.3.2'
_DAY = 86400.0

#: A lock sourcing one sibling from git FOLLOWING its line, one git package held at a tag, and one index package.
_LOCK = """version = 1

[[package]]
name = "lab-commons"
source = { git = "https://github.com/DawnEver/lab-commons.git#ed24ab516a140b62b77a89a1b546d5fee8903d22" }

[[package]]
name = "held_dep"
source = { git = "https://example.invalid/held.git?tag=v1#0123456789abcdef0123456789abcdef01234567" }

[[package]]
name = "pint"
source = { registry = "https://pypi.org/simple" }
"""


class _Attempt:
    def __init__(self, output: str) -> None:
        self.output = output


class _Report:
    """The shape ``stale`` reads: ok, its last attempt's output, and a remedy."""

    ok = True
    remedy = ''

    def __init__(self, output: str = '') -> None:
        self.attempts = (_Attempt(output),) if output else ()


def _resolving(*changes: str) -> Callable[[Path], _Report]:
    output = ''.join(f'{change.partition("resolution: ")[2]}\n' for change in changes)
    return lambda _tree: _Report(output)


_fresh = _resolving()
_stale = _resolving(_PINT)


def _git(root: Path, *argv: str) -> str:
    done = subprocess.run(
        [_GIT, '-C', str(root), *argv], check=False, capture_output=True, text=True, encoding='utf-8', timeout=120
    )  # fmt: skip
    assert done.returncode == 0, f'{argv}: {done.stderr}'
    return done.stdout.strip()


def _commit(world: tuple[Path, Path, str], message: str, files: dict[str, str]) -> str:
    """Commit *files* on the seed's integration, push it, fetch it into the clone; the new tip."""
    clone, origin, _ = world
    seed = origin.parent / 'seed'
    for name, text in files.items():
        (seed / name).parent.mkdir(parents=True, exist_ok=True)
        (seed / name).write_text(text, encoding='utf-8')
    _git(seed, 'add', '-A')
    _git(seed, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '--allow-empty', '-m', message)
    _git(seed, 'push', '-q', str(origin), 'integrate/main')
    _git(clone, 'fetch', '-q', 'origin')
    return _git(clone, 'rev-parse', 'origin/integrate/main')


@pytest.fixture
def world(tmp_path: Path) -> tuple[Path, Path, str]:
    """``(clone, origin, integration sha)``: a clone whose ``origin/integrate/main`` commits a lock."""
    origin, seed, clone = tmp_path / 'origin.git', tmp_path / 'seed', tmp_path / 'clone'
    _git(tmp_path, 'init', '-q', '--bare', str(origin))
    _git(tmp_path, 'init', '-q', '-b', 'integrate/main', str(seed))
    (seed / 'pyproject.toml').write_text('[project]\nname = "x"\nversion = "0"\n', encoding='utf-8')
    (seed / 'uv.lock').write_text(_LOCK, encoding='utf-8')
    _git(seed, 'add', '-A')
    _git(seed, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '-m', 'seed')
    _git(seed, 'push', '-q', str(origin), 'integrate/main')
    _git(tmp_path, 'clone', '-q', '-b', 'integrate/main', str(origin), str(clone))
    _git(clone, 'config', 'user.name', 't')
    _git(clone, 'config', 'user.email', 't@t')
    return clone, origin, _git(clone, 'rev-parse', 'origin/integrate/main')


class _Door:
    """The dependency door: appends a line to the lock and records which packages it was told to move."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, tree: Path, packages: Sequence[str]) -> int:
        self.calls.append(tuple(packages))
        with (tree / 'uv.lock').open('a', encoding='utf-8') as lock:
            lock.write(f'# relocked {len(self.calls)}\n')
        return 0


def _never(_tree: Path, _packages: Sequence[str]) -> int:
    msg = 'the door must not run'
    raise AssertionError(msg)


class _Forge:
    """The forge calls a relock makes: list the open pull requests, open one, rewrite one's body, close one."""

    def __init__(self) -> None:
        self.open: list[PullRequest] = []
        self.created: list[tuple[str, str, str, str]] = []
        self.edited: list[tuple[int, str]] = []
        self.closed: list[int] = []

    def pulls(self) -> list[PullRequest]:
        return self.open

    def create(self, title: str, body: str, *, head: str, base: str, draft: bool) -> PullRequest:
        assert draft is False, 'a relock is done work'
        self.created.append((title, body, head, base))
        pull = PullRequest(99, title, 'open', body, 'https://forge/pulls/99', 'serve', head, base)
        self.open.append(pull)
        return pull

    def edit(self, number: int, body: str) -> None:
        self.edited.append((number, body))

    def close(self, number: int) -> None:
        self.closed.append(number)
        self.open = [pull for pull in self.open if pull.number != number]


def _carry(clone: Path, forge: _Forge, *, now: float = 0.0, **seams: object) -> str:
    seams.setdefault('upgrade', _Door())
    return carry(
        clone, _DECLARED, pulls=forge.pulls, create=forge.create, edit=forge.edit, close=forge.close, now=now,
        **cast('dict[str, Any]', seams),
    )  # fmt: skip


def _scope(origin: Path) -> str:
    return _git(origin, 'log', '-1', f'--format=%(trailers:key={SCOPE},valueonly)', BRANCH)


# --- reading ------------------------------------------------------------------------------------------------


def test_the_dist_is_the_word_the_change_names() -> None:
    assert dist_of(_PINT) == 'pint'
    assert dist_of('uv.lock is not the newest resolution: Add ruff v0.17.1') == 'ruff'
    assert dist_of('uv.lock is not the newest resolution: something else entirely') == 'lock'
    assert dist_of(f'{UV_PIN} is not the newest uv: 0.13.7 -> 0.13.8') == 'uv'


def test_in_house_is_a_git_source_following_a_line_read_off_the_lock() -> None:
    """PLANTED control: a git source held at a tag and an index package are third-party."""
    assert in_house(_LOCK) == {'lab-commons'}
    assert in_house('not toml [') == frozenset(), 'an unreadable lock follows nothing'


_SIBLING_SHA = 'ed24ab516a140b62b77a89a1b546d5fee8903d22'
_BRANCHED = _LOCK.replace('lab-commons.git#', 'lab-commons.git?branch=release%2Fx#')


def test_the_floating_reading_compares_each_siblings_locked_commit_with_its_lines_head() -> None:
    """User ruling 2026-11-07: an ls-remote per sibling, never a resolution. PLANTED CONTROL: at its head, fresh."""
    asked: list[tuple[str, str]] = []

    def moved(url: str, branch: str) -> str:
        asked.append((url, branch))
        return 'f' * 40

    (why,) = floating_stale(_LOCK, head=moved)
    assert 'lab-commons' in why
    assert _SIBLING_SHA[:12] in why
    assert asked == [('https://github.com/DawnEver/lab-commons.git', 'integrate/main')], 'held and index: not read'
    assert floating_stale(_LOCK, head=lambda _url, _branch: _SIBLING_SHA) == ()


def test_the_floating_reading_follows_the_sources_branch() -> None:
    asked: list[str] = []
    floating_stale(_BRANCHED, head=lambda _url, branch: asked.append(branch) or _SIBLING_SHA)
    assert asked == ['release/x']


def test_the_floating_reading_refuses_a_line_that_cannot_be_read() -> None:
    def offline(_url: str, _branch: str) -> str:
        msg = 'no network'
        raise RelockFailed(msg)

    (why,) = floating_stale(_LOCK, head=offline)
    assert 'no network' in why
    assert floating_stale('not toml [', head=offline) == (), 'PLANTED CONTROL: nothing floats, nothing is read'


def test_relock_floating_moves_only_the_siblings_and_raises_on_a_failed_door(tmp_path: Path) -> None:
    """PLANTED CONTROL: a tree with no lock moves nothing and never calls the door."""
    asked: list[Sequence[str]] = []
    assert relock_floating(tmp_path, upgrade=lambda _t, names: asked.append(names) or 0) == ()
    assert asked == []
    (tmp_path / 'uv.lock').write_text(_LOCK, encoding='utf-8')
    assert relock_floating(tmp_path, upgrade=lambda _t, names: asked.append(names) or 0) == ('lab-commons',)
    assert asked == [('lab-commons',)]
    with pytest.raises(RelockFailed, match='exited 3'):
        relock_floating(tmp_path, upgrade=lambda _t, _names: 3)


def test_before_the_cadence_only_sibling_moves_are_chosen() -> None:
    """PLANTED control: due, every move is chosen; the toolchain and the uv pin are never siblings."""
    rust = 'rust-toolchain.toml is not the newest stable: 1.99.0 -> 1.99.1'
    found = (_PINT, _SIBLING, rust)
    assert chosen(found, frozenset({'lab-commons'}), due=False) == (_SIBLING,)
    assert chosen(found, frozenset({'lab-commons'}), due=True) == found


def test_the_cadence_is_declared_once_in_the_repo_default_daily() -> None:
    assert cadence('[project]\nname = "x"\n') == DEFAULT_CADENCE == timedelta(days=1)
    assert cadence('[tool.dev_lab.relock]\nthird_party_every = "12 h"\n') == timedelta(hours=12)
    with pytest.raises(ValueError, match='unknown key'):
        cadence('[tool.dev_lab.relock]\nevery = "1 d"\n')
    with pytest.raises(ValueError, match='needs a unit'):
        cadence('[tool.dev_lab.relock]\nthird_party_every = "24"\n')


# --- the rolling pull request --------------------------------------------------------------------------------


def test_a_stale_integration_lock_is_carried_as_the_one_rolling_pull_request(world: tuple[Path, Path, str]) -> None:
    """PLANTED control: the same integration with a fresh lock pushes and opens nothing."""
    clone, origin, sha = world
    forge = _Forge()
    said = _carry(clone, forge, resolve=_fresh, upgrade=_never)
    assert said == f'the lock of integrate/main at {sha[:12]} needs no relock'
    assert (forge.created, _git(origin, 'branch', '--list', BRANCH)) == ([], '')

    door = _Door()
    said = _carry(clone, forge, resolve=_stale, upgrade=door)
    assert said == f'relocked integrate/main at {sha[:12]} onto {BRANCH} (full, 1 move(s)): https://forge/pulls/99'
    ((title, body, head, base),) = forge.created
    assert (head, base, title) == (BRANCH, 'integrate/main', TITLE)
    assert _PINT in body
    assert door.calls == [()], 'never relocked before: third-party is due, the door upgrades everything'
    assert _git(origin, 'rev-parse', f'{BRANCH}^') == sha, 'the relock is one commit on integration'
    assert _git(origin, 'diff', '--name-only', sha, BRANCH) == 'uv.lock', 'it moves the lock and nothing else'
    assert _git(origin, 'log', '-1', '--format=%s', BRANCH) == TITLE
    assert _scope(origin) == 'full'
    assert _git(clone, 'worktree', 'list', '--porcelain').count('worktree ') == 1, 'its worktree is removed'
    assert _git(clone, 'status', '--porcelain') == '', 'the serving checkout is never written'


def test_an_open_relock_carrying_these_moves_on_this_tip_is_left_alone(world: tuple[Path, Path, str]) -> None:
    clone, origin, _ = world
    forge = _Forge()
    _carry(clone, forge, resolve=_stale)
    head = _git(origin, 'rev-parse', BRANCH)
    said = _carry(clone, forge, resolve=_stale, upgrade=_never)
    assert said == '#99 already carries the 1 move(s) integrate/main needs'
    assert (_git(origin, 'rev-parse', BRANCH), len(forge.created), forge.edited) == (head, 1, [])


def test_a_newer_resolution_updates_the_same_pull_request_in_place(world: tuple[Path, Path, str]) -> None:
    """At most ONE relock PR: a tick finding new staleness rewrites the one branch and body, opens nothing."""
    clone, origin, sha = world
    forge = _Forge()
    _carry(clone, forge, resolve=_stale)
    newer = 'uv.lock is not the newest resolution: Update pint v0.26.1 -> v0.26.3'
    said = _carry(clone, forge, resolve=_resolving(newer))
    assert said == f'rebuilt #99 on {sha[:12]} (full, 1 move(s)): https://forge/pulls/99'
    assert len(forge.created) == 1
    ((number, body),) = forge.edited
    assert number == 99
    assert newer in body
    assert _PINT not in body
    assert _git(origin, 'rev-parse', f'{BRANCH}^') == sha, 'still ONE commit on integration'
    assert newer in _git(origin, 'log', '-1', '--format=%B', BRANCH)


def test_an_integration_that_moved_while_the_pull_request_was_open_is_rebuilt_on(
    world: tuple[Path, Path, str],
) -> None:
    clone, origin, _ = world
    forge = _Forge()
    _carry(clone, forge, resolve=_stale)
    tip = _commit(world, 'feat: integration moves', {'a.txt': 'a\n'})
    said = _carry(clone, forge, resolve=_stale)
    assert said.startswith(f'rebuilt #99 on {tip[:12]}')
    assert _git(origin, 'rev-parse', f'{BRANCH}^') == tip, 'rebuilt on the new tip, never merged into'
    assert _git(origin, 'diff', '--name-only', tip, BRANCH) == 'uv.lock'


def test_an_open_relock_integration_no_longer_needs_is_closed(world: tuple[Path, Path, str]) -> None:
    clone, _, sha = world
    forge = _Forge()
    _carry(clone, forge, resolve=_stale)
    said = _carry(clone, forge, resolve=_fresh, upgrade=_never)
    assert said == f'closed #99: integrate/main at {sha[:12]} needs no relock'
    assert forge.closed == [99]


def test_a_push_that_lost_its_lease_to_a_racing_writer_is_a_named_refusal(world: tuple[Path, Path, str]) -> None:
    """PLANTED control: the same push with origin's real head as its lease lands (every case above)."""
    clone, origin, _ = world
    forge = _Forge()
    _carry(clone, forge, resolve=_stale)
    raced = _git(origin, 'rev-parse', BRANCH)
    with pytest.raises(RelockFailed, match='lease'):
        _carry(clone, forge, resolve=_resolving(_SIBLING), remote_head=lambda _root: '0' * 39 + '1')
    assert _git(origin, 'rev-parse', BRANCH) == raced, "the racing writer's head stands"


# --- the cadence --------------------------------------------------------------------------------------------


def _relocked_fully(world: tuple[Path, Path, str]) -> float:
    """Give integration's history a full relock commit; its commit time."""
    _commit(world, f'{TITLE}\n\n{SCOPE}: full', {'uv.lock': _LOCK + '# relocked\n'})
    return float(_git(world[0], 'log', '-1', '--format=%ct', 'origin/integrate/main'))


def test_an_in_house_move_before_the_cadence_moves_only_the_sibling(world: tuple[Path, Path, str]) -> None:
    """PLANTED control: the same staleness a cadence later moves everything, through one full upgrade."""
    clone, origin, _ = world
    at = _relocked_fully(world)
    forge, door = _Forge(), _Door()
    said = _carry(clone, forge, now=at + 3600, resolve=_resolving(_PINT, _SIBLING), upgrade=door)
    assert '(in-house, 1 move(s))' in said
    assert door.calls == [('lab-commons',)], 'only the sibling is named to the door'
    ((_, body, _, _),) = forge.created
    carried, _, held = body.partition('held for the cadence')
    assert _SIBLING in carried
    assert _PINT in held
    assert _PINT not in carried
    assert _scope(origin) == 'in-house'

    said = _carry(clone, forge, now=at + _DAY, resolve=_resolving(_PINT, _SIBLING), upgrade=door)
    assert '(full, 2 move(s))' in said
    assert door.calls[-1] == ()
    assert _scope(origin) == 'full'


def test_third_party_only_staleness_waits_for_the_cadence(world: tuple[Path, Path, str]) -> None:
    """PLANTED control: a cadence after the last full relock, the same staleness is carried."""
    clone, origin, _ = world
    at = _relocked_fully(world)
    forge = _Forge()
    said = _carry(clone, forge, now=at + 3600, resolve=_stale, upgrade=_never)
    assert said.endswith('needs no relock; 1 third-party move(s) held for the cadence')
    assert (forge.created, _git(origin, 'branch', '--list', BRANCH)) == ([], '')
    assert '(full, 1 move(s))' in _carry(clone, forge, now=at + _DAY, resolve=_stale)


def test_a_declared_cadence_is_read_at_the_tip(world: tuple[Path, Path, str]) -> None:
    """PLANTED control: the default cadence holds this move an hour after a full relock (the case above)."""
    at = _relocked_fully(world)
    manifest = '[project]\nname = "x"\nversion = "0"\n[tool.dev_lab.relock]\nthird_party_every = "1 h"\n'
    _commit(world, 'build: hourly third-party relock', {'pyproject.toml': manifest})
    assert '(full, 1 move(s))' in _carry(world[0], _Forge(), now=at + 3600, resolve=_stale)


# --- refusals and seams kept from the single-shot relock -----------------------------------------------------


def test_a_door_that_moves_nothing_is_a_named_refusal(world: tuple[Path, Path, str]) -> None:
    """The resolution says stale and the door leaves the lock as it was: refused, never an empty PR."""
    clone, origin, _ = world
    forge = _Forge()
    with pytest.raises(RelockFailed, match=r'left uv\.lock unchanged'):
        _carry(clone, forge, resolve=_stale, upgrade=lambda _t, _p: 0)
    with pytest.raises(RelockFailed, match='the dependency door exited 1'):
        _carry(clone, forge, resolve=_stale, upgrade=lambda _t, _p: 1)
    assert (forge.created, _git(origin, 'branch', '--list', BRANCH)) == ([], '')
    assert _git(clone, 'worktree', 'list', '--porcelain').count('worktree ') == 1


def test_no_integration_branch_is_a_named_refusal(tmp_path: Path) -> None:
    _git(tmp_path, 'init', '-q')
    with pytest.raises(RelockFailed, match='no origin/integrate/main'):
        _carry(tmp_path, _Forge(), resolve=_stale, upgrade=_never)


def test_the_serve_step_relocks_only_where_the_forge_merges_and_alarms_a_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only a repo declaring ``pr_merges_since`` lands a relock PR by itself; a failed relock is an alarm."""
    said: list[str] = []
    raised: list[Alarm] = []

    def failing(*_a: object, **_k: object) -> str:
        msg = 'there is no origin/integrate/main here to relock'
        raise RelockFailed(msg)

    monkeypatch.setattr(forgeservesteps, 'carry', failing)
    monkeypatch.setattr(forgeservesteps, 'pr_list', lambda _client: ())
    (tmp_path / 'pyproject.toml').write_text('[tool.dev_lab.integrator]\nintegration = "integrate/main"\n', 'utf-8')
    forgeservesteps.relock(tmp_path, 'r', _CLIENT, say=said.append, alarm=raised.append)
    assert (said, raised) == ([], []), 'CONTROL: no pr_merges_since, no relock'
    manifest = '[project]\nname = "x"\nversion = "0"\n'
    manifest += '[tool.dev_lab.integrator]\nintegration = "integrate/main"\npr_merges_since = "abc"\n'
    (tmp_path / 'pyproject.toml').write_text(manifest, encoding='utf-8')
    forgeservesteps.relock(tmp_path, 'r', _CLIENT, say=said.append, alarm=raised.append)
    (alarm,) = raised
    assert alarm.subject == 'the integrate/main lock could not be relocked'
    assert 'no origin/integrate/main' in alarm.body


_CLIENT = cast(
    'Client',
    SimpleNamespace(pr_create=lambda *_a, **_k: None, issue_edit=lambda *_a: None, issue_close=lambda _n: None),
)


def test_a_relock_commit_is_the_forges_and_carries_no_session(monkeypatch, tmp_path: Path) -> None:
    """ONE-SESSION-ONE-PR: a forge started inside a session must not stamp that session on its own commits."""
    seen: dict = {}

    def fake(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        seen.update(kwargs)
        return subprocess.CompletedProcess(argv, 0, '', '')

    monkeypatch.setenv('LAB_SESSION', 'session-from-the-host-shell')
    monkeypatch.setattr(relock._door, 'run', fake)
    relock._git(tmp_path, 'status')
    assert 'LAB_SESSION' not in seen['env']
    assert 'PATH' in {key.upper() for key in seen['env']}


def test_a_toolchain_behind_the_newest_stable_is_carried_like_a_stale_lock(world: tuple[Path, Path, str]) -> None:
    """User ruling 2026-10-25: the forge refreshes ``rust-toolchain.toml`` by the same pull request as the lock."""
    clone, origin, _ = world
    sha = _commit(world, 'pin', {'rust-toolchain.toml': '[toolchain]\nchannel = "1.99.0"\n'})

    def bumped(tree: Path, _packages: Sequence[str]) -> int:
        (tree / 'rust-toolchain.toml').write_text('[toolchain]\nchannel = "1.99.1"\n', encoding='utf-8')
        return 0

    said = _carry(clone, _Forge(), resolve=_fresh, stable=lambda: '1.99.1', upgrade=bumped)
    assert said.startswith(f'relocked integrate/main at {sha[:12]} onto {BRANCH} (full, 1 move(s))')
    assert _git(origin, 'diff', '--name-only', sha, BRANCH) == 'rust-toolchain.toml'


def test_a_relock_rerenders_the_generated_workflows_in_the_same_commit(world: tuple[Path, Path, str]) -> None:
    """A relock that moves dev-lab carries what the new pin renders, in the same commit.

    2026-11-03: lab-commons pinned a dev-lab 224 commits old, so its rendered review job could not import
    the review method and passed silently.
    PLANTED control: a render that writes nothing leaves the relock the lock alone (the first carry case).
    """
    clone, origin, sha = world
    rendered: list[Path] = []

    def render(tree: Path) -> tuple[str, ...]:
        rendered.append(tree)
        workflow = tree / '.github' / 'workflows' / 'ci.yml'
        workflow.parent.mkdir(parents=True)
        workflow.write_text('{"jobs": {"review": {"steps": ["install the review method"]}}}\n', encoding='utf-8')
        (tree / '.gitignore').write_text('rendered\n', encoding='utf-8')
        return ('ciworkflows', 'famfiles')

    _carry(clone, _Forge(), resolve=_stale, rerender=render)
    assert len(rendered) == 1, 'the render runs once, after the door moved the lock'
    assert _git(origin, 'diff', '--name-only', sha, BRANCH).splitlines() == [
        '.github/workflows/ci.yml', '.gitignore', 'uv.lock',
    ], 'every renderer`s output rides, not the workflows alone'  # fmt: skip
    assert _git(origin, 'rev-parse', f'{BRANCH}^') == sha, 'still ONE commit on integration'


def test_a_render_that_fails_is_a_named_refusal_and_pushes_nothing(world: tuple[Path, Path, str]) -> None:
    clone, origin, _ = world
    forge = _Forge()

    def failing(_tree: Path) -> tuple[str, ...]:
        msg = 'the renderer famfiles exited 3'
        raise RelockFailed(msg)

    with pytest.raises(RelockFailed, match='the renderer famfiles exited 3'):
        _carry(clone, forge, resolve=_stale, rerender=failing)
    assert (forge.created, _git(origin, 'branch', '--list', BRANCH)) == ([], '')


def test_a_tree_without_its_venv_is_refused_not_rendered_with_this_interpreter(tmp_path: Path) -> None:
    """The running interpreter holds the OLD pin: rendering with it would carry the stale workflow (#71 review)."""
    (tmp_path / '.gitignore').write_text('x\n', encoding='utf-8')
    with pytest.raises(RelockFailed, match=r'no \.venv'):
        rerender(tmp_path)


def test_rerender_runs_every_due_renderer_with_the_trees_interpreter_and_names_a_failure(tmp_path: Path) -> None:
    """PLANTED CONTROL: a tree with no generated file runs nothing, so it needs no interpreter at all."""
    assert rerender(tmp_path, run=lambda _argv, _tree: 1) == ()
    (tmp_path / '.claude' / 'hooks').mkdir(parents=True)
    (tmp_path / '.claude' / 'hooks' / 'deny-commands.js').write_text('x\n', encoding='utf-8')
    python = tmp_path / '.venv' / 'bin' / 'python'
    python.parent.mkdir(parents=True)
    python.write_text('', encoding='utf-8')
    ran: list[list[str]] = []
    assert rerender(tmp_path, run=lambda argv, _tree: ran.append(argv) or 0) == ('agent_guard',)
    assert ran == [[str(python), '-m', 'dev_lab.dev.agent_guard', '--install', '--repo', str(tmp_path)]]
    with pytest.raises(RelockFailed, match='the renderer agent_guard exited 4'):
        rerender(tmp_path, run=lambda _argv, _tree: 4)


def test_planted_control_a_tree_with_its_venv_renders_with_that_interpreter(tmp_path: Path) -> None:
    for python in (tmp_path / '.venv' / 'Scripts' / 'python.exe', tmp_path / '.venv' / 'bin' / 'python'):
        python.parent.mkdir(parents=True, exist_ok=True)
        python.write_text('', encoding='utf-8')
    assert Path(_tree_python(tmp_path)).parent.parent == tmp_path / '.venv'


def _uv_bumped(tree: Path, _packages: Sequence[str]) -> int:
    (tree / UV_PIN).write_text('version = "0.13.8"\n', encoding='utf-8')
    return 0


def test_a_uv_pin_behind_the_newest_release_is_carried_like_a_stale_lock(world: tuple[Path, Path, str]) -> None:
    """User directive 2026-11-05: the forge raises dev-lab's uv pin by the same relock pull request."""
    clone, origin, _ = world
    sha = _commit(world, 'pin uv', {UV_PIN: 'version = "0.13.7"\n'})
    said = _carry(
        clone, _Forge(), resolve=_fresh, uv=lambda: '0.13.8', follow_uv=lambda _version: '', upgrade=_uv_bumped
    )
    assert said.startswith(f'relocked integrate/main at {sha[:12]} onto {BRANCH}')
    assert _git(origin, 'diff', '--name-only', sha, BRANCH) == UV_PIN


def _not_followed(version: str) -> str:
    return f'uv 0.13.7 did not follow to {version}'


def test_planted_control_a_host_without_the_new_uv_refuses_the_relock_naming_the_update(
    world: tuple[Path, Path, str],
) -> None:
    """A lock is never written by the old uv: the relock RAISES naming ``uv self update`` and pushes nothing."""
    clone, origin, _ = world
    _commit(world, 'pin uv', {UV_PIN: 'version = "0.13.7"\n'})
    with pytest.raises(RelockFailed, match=r'uv self update 0\.13\.8'):
        _carry(
            clone,
            _Forge(),
            resolve=_fresh,
            uv=lambda: '0.13.8',
            follow_uv=lambda version: f'uv 0.13.7 did not follow to {version}',
            upgrade=_never,
        )
    assert _git(origin, 'branch', '--list', BRANCH) == ''


def test_the_lag_reading_counts_each_floated_sibling_against_the_limit() -> None:
    """``lock/lag``: past the limit is a sentence. PLANTED CONTROLS: AT the limit is none; uncounted refuses."""
    asked: list[tuple[str, str, str]] = []

    def behind(n: int) -> Callable[[str, str, str], int]:
        return lambda url, branch, sha: asked.append((url, branch, sha)) or n

    (why,) = floating_lag(_LOCK, 20, behind=behind(21))
    assert 'lab-commons' in why
    assert '21 commits behind' in why
    assert asked == [('https://github.com/DawnEver/lab-commons.git', 'integrate/main', _SIBLING_SHA)]
    assert floating_lag(_LOCK, 20, behind=behind(20)) == ()

    def offline(_url: str, _branch: str, _sha: str) -> int:
        msg = 'no network'
        raise RelockFailed(msg)

    (why,) = floating_lag(_LOCK, 20, behind=offline)
    assert 'no network' in why


def test_the_lag_count_is_the_lines_commits_past_the_pin(tmp_path: Path) -> None:
    """A treeless fetch of the sibling's line counts ``<pin>..<tip>``. PLANTED CONTROL: a pin off the line raises."""
    sibling = tmp_path / 'sibling'
    sibling.mkdir()

    def git(*argv: str) -> str:
        return subprocess.run(
            [shutil.which('git') or 'git', '-C', str(sibling), *argv],
            capture_output=True,
            text=True,
            encoding='utf-8',
            check=True,
        ).stdout.strip()

    git('init', '-q', '-b', 'integrate/main')
    git('-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '--no-verify', '--allow-empty', '-m', 'feat: pin')
    pin = git('rev-parse', 'HEAD')
    for n in range(3):
        git(
            '-c',
            'user.name=t',
            '-c',
            'user.email=t@t',
            'commit',
            '-q',
            '--no-verify',
            '--allow-empty',
            '-m',
            f'feat: {n}',
        )
    url = sibling.as_uri()
    assert _commits_behind(url, 'integrate/main', pin) == 3
    assert _commits_behind(url, 'integrate/main', git('rev-parse', 'HEAD')) == 0
    with pytest.raises(RelockFailed, match='is not on'):
        _commits_behind(url, 'integrate/main', 'e' * 40)
