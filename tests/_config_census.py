"""The CONFIG-layer placement census: the three sides, the composer, and the live re-measurement.

MACHINERY ONLY. The table is ``_config_census_rows.py`` and the seam is the one
``test_arch_registry_data_is_separate.py`` already names one level up: a table edited through the
module that checks it drifts away from what it describes, because the same edit that adds a row can
relax the check that would have refused it, and the diff looks like one change.

WHAT A ROW IS, and it is the shape ``tests/architecture/layering/_placement_*.py`` in
motronics-studio already runs: a key (``<repo>::<artefact>``), a SIDE, and a REASON -- and the
reason is the deliverable, not the label. A side with a one-line reason is a label wearing a
table's clothes, so :class:`Placement` refuses one AT CONSTRUCTION.

THE THREE SIDES, stated so a row cannot be assigned by feel:

* ``STAYS`` -- genuinely repo-shaped. The reason must name the fact about THIS repo that makes it
  so, and say what breaks if it moved.
* ``MOVES`` -- identical or near-identical across consumers, so it belongs in the shared kit. The
  reason must say what a consumer would lose if it were not shared.
* ``SPLITS`` -- a shared base plus a repo-shaped delta. The reason must name WHERE the seam is.

THIS COMMIT IS THE DECLARATION, NOT THE MIGRATION. Nothing here moves a file. What it buys is that
the next lane to move one cannot do it without saying which side it was on and what the measurement
was, and that a row describing a file's former shape reds instead of reading as current.

THE LIVE HALF IS WHY THIS IS A CENSUS RATHER THAN A NOTE. Every quantity the rows cite is
re-derivable from the four checkouts, and the readers below are how: a recorded number that nothing
re-measures is exactly the declaration-that-lies defect the family names as dominant. lab-commons
is ALWAYS reachable (it is the tree this test runs in), so the floor is never zero; the other three
are read when they are checked out beside it and NAMED when they are not.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Final

__all__ = [
    'MOVES',
    'SIDES',
    'SPLITS',
    'STAYS',
    'CensusError',
    'Placement',
    'UnreadableTree',
    'compose',
    'dev_pages',
    'gitignore_patterns',
    'head_sha',
    'hook_ids',
    'installed_hook_names',
    'make_targets',
    'names_at_head',
    'reachable_repos',
    'read_at_head',
    'repo_root',
    'ruff_config',
    'ruff_excludes',
    'ruff_ignore',
    'ruff_per_file_waivers',
    'ruff_scalars',
    'ruff_select',
    'selector_covers',
]

STAYS: Final = 'stays'
MOVES: Final = 'moves'
SPLITS: Final = 'splits'

#: The only three sides. A fourth would be a row nobody has to decide, which is the shape this
#: census exists to refuse.
SIDES: Final = (STAYS, MOVES, SPLITS)

#: The shortest a REASON may be. Not a style rule: every side above demands a named fact and a
#: stated consequence, and neither fits in a caption. MEASURED against the motronics roster this is
#: modelled on -- its shortest live reason is well over this -- so the bar is a floor under prose,
#: not a pin on it.
REASON_FLOOR: Final = 240

#: This file is ``<lab-commons>/tests/_config_census.py``.
ROOT: Final = Path(__file__).resolve().parents[1]


#: How long a `git` read of another checkout may take. Bounded because an unbounded wait here parks
#: this repo's whole verdict on somebody else's index lock -- the shape
#: `lab_commons.dev.famtests.untimedwaits` refuses before anything runs.
_GIT_TIMEOUT_S: Final = 60

#: Resolved once rather than looked up on PATH at every call.
_GIT: Final = shutil.which('git') or 'git'


class CensusError(ValueError):
    """A row the census refuses to hold: a bad side, a caption for a reason, a key in two hands."""


class UnreadableTree(RuntimeError):
    """A declared checkout is there and its committed state cannot be read, so it is not INCONCLUSIVE quietly."""


def head_sha(root: Path) -> str | None:
    """The commit this census read *root* at, or ``None`` when it cannot be resolved.

    THE POINT IN TIME IS PART OF THE READING and must travel with it. A cross-repo census that names
    no sha produces a verdict the next reader cannot reproduce, and this repo paid for that on
    2026-09-18: an uncommitted edit in another repo's lane worktree turned a lab-commons test RED,
    and that red was attributable to NO COMMIT -- it appeared and vanished with somebody else's
    in-flight work. The lane that met it correctly refused to "fix" the row it accused.
    """
    found = subprocess.run(
        [_GIT, '-C', str(root), 'rev-parse', 'HEAD'],
        capture_output=True,
        text=True,
        check=False,
        timeout=_GIT_TIMEOUT_S,
    )
    return found.stdout.strip() or None if found.returncode == 0 else None


def read_at_head(root: Path, relpath: str) -> str | None:
    """*relpath*'s content as COMMITTED in *root*, or ``None`` when that path is not committed there.

    **A DECLARATION IS A COMMITTED FACT, AND THIS IS NOT THIS MODULE'S INVENTION.** It is the rule
    :func:`lab_commons.dev.rules.tracked_files` already states and
    :mod:`lab_commons.dev.cjk` already turns down its corpus for: *a file that exists only in one
    working copy is not a file the fleet has, so a guarantee resting on it is one nobody else can
    reproduce.* A cross-repo census asks what the four repos DECLARE, and a working tree is what one
    box happens to hold this minute -- including another agent's half-finished edit.

    WHAT THIS DELIBERATELY GIVES UP, so nobody reads it as free. A lane's uncommitted work is INVISIBLE
    here, so the census describes the last published state rather than the one its author is looking
    at. That is the correct trade for a guard whose whole subject is what the family has AGREED, and
    it is the wrong trade for a guard about what this BOX has -- see :func:`installed_hook_names`,
    which stays on the filesystem for exactly that reason and says so.
    """
    found = subprocess.run(
        [_GIT, '-C', str(root), 'show', f'HEAD:{relpath}'],
        capture_output=True,
        text=True,
        check=False,
        timeout=_GIT_TIMEOUT_S,
    )
    return found.stdout if found.returncode == 0 else None


def names_at_head(root: Path, directory: str, suffix: str) -> frozenset[str]:
    """Committed filenames directly under *directory* ending in *suffix*, never a working-tree glob."""
    found = subprocess.run(
        [_GIT, '-C', str(root), 'ls-tree', '--name-only', f'HEAD:{directory}'],
        capture_output=True,
        text=True,
        check=False,
        timeout=_GIT_TIMEOUT_S,
    )
    if found.returncode != 0:
        return frozenset()
    return frozenset(name for name in found.stdout.split() if name.endswith(suffix))


@dataclass(frozen=True)
class Placement:
    """One artefact in one repo: which side it is on, and why -- checked at construction."""

    side: str
    why: str

    def __post_init__(self) -> None:
        if self.side not in SIDES:
            msg = f'{self.side!r} is not one of the three sides {SIDES}'
            raise CensusError(msg)
        if len(self.why) < REASON_FLOOR:
            msg = (
                f'a reason of {len(self.why)} characters, under the {REASON_FLOOR} floor. The REASON is '
                f'the deliverable and the side is only its label; a caption cannot name the measured '
                f'fact, the seam, or what breaks if the artefact moved.'
            )
            raise CensusError(msg)


def compose(partitions: tuple[tuple[str, dict[str, Placement]], ...]) -> dict[str, Placement]:
    """Union the per-REPO partitions, refusing a duplicate key and a key in the wrong partition.

    The axis is the REPO because that is what a lane owns: a change to one repo's config touches one
    partition and merges with every lane that does not. A plain ``{**a, **b}`` swallows both refusals
    below -- last wins, silently -- which is why the composer exists at all.
    """
    out: dict[str, Placement] = {}
    for repo, rows in partitions:
        for key, row in rows.items():
            if key in out:
                msg = f'{key!r} is declared in two partitions'
                raise CensusError(msg)
            if not key.startswith(f'{repo}::'):
                msg = f'partition {repo!r} owns exactly one repo, and {key!r} is not in it'
                raise CensusError(msg)
            out[key] = row
    return out


# --------------------------------------------------------------------------- the live readers


def repo_root(repo: str, paths: dict[str, str]) -> Path | None:
    """The checkout for *repo*, or ``None`` when it is not beside this one.

    *paths* are relative to lab-commons' PARENT, so the census reads siblings rather than climbing
    into a checkout it was told to leave alone -- the motronics entry names a worktree on purpose.
    """
    if repo == 'lab-commons':
        return ROOT
    candidate = ROOT.parent / paths[repo]
    return candidate if (candidate / '.git').exists() else None


def reachable_repos(paths: dict[str, str]) -> dict[str, Path]:
    """Every declared repo that is actually checked out here. lab-commons is always in it."""
    found = {repo: repo_root(repo, paths) for repo in ('lab-commons', *paths)}
    return {repo: root for repo, root in found.items() if root is not None}


def ruff_config(root: Path) -> dict:
    """Ruff's RESOLVED config for *root*, taking its own precedence rules.

    A ``ruff.toml`` beside a ``pyproject.toml`` WINS -- verified against `ruff check --show-settings`,
    which prints the settings path it used. So a repo carrying both has one live config and one dead
    one, and reading ``[tool.ruff]`` unconditionally would report the dead one as current.
    """
    own = read_at_head(root, 'ruff.toml')
    if own is not None:
        return tomllib.loads(own)
    project_text = read_at_head(root, 'pyproject.toml')
    if project_text is None:
        msg = f'{root} declares no committed pyproject.toml at {head_sha(root)}, so its ruff config cannot be read'
        raise UnreadableTree(msg)
    return tomllib.loads(project_text).get('tool', {}).get('ruff', {})


#: EVERY SPELLING RUFF ACCEPTS FOR EACH WAIVER KIND, as a table rather than four `.get` chains.
#:
#: THE AXIS THIS TABLE EXISTS FOR IS SPELLING, and the reader it replaced was blind to it. A census
#: reading only ``lint.ignore`` measures the one spelling the four repos happen to use today: ruff
#: also honours ``lint.extend-ignore`` and the DEPRECATED top-level ``ignore``, so a consumer moving
#: an entry to either would empty the census's reading without changing one thing ruff does. A
#: control parametrized over REPOS cannot see that; only one parametrized over SPELLINGS can, which
#: is why the planted control in `test_a_waiver_wider_than_an_ignore_is_declared.py` drives THIS
#: table and not the four checkouts.
#:
#: MEASURED 2026-09-18: every ``extend-`` and every deprecated top-level spelling reads EMPTY in all
#: four repos, so unioning them moves no live number today. That is exactly when a blindness is cheap
#: to close, and it is why this lands as a reader change with no recorded value changing.
WAIVER_SPELLINGS: Final[dict[str, tuple[tuple[str, ...], ...]]] = {
    'select': (('lint', 'select'), ('lint', 'extend-select'), ('select',), ('extend-select',)),
    'ignore': (('lint', 'ignore'), ('lint', 'extend-ignore'), ('ignore',), ('extend-ignore',)),
    'exclude': (
        ('exclude',),
        ('extend-exclude',),
        ('lint', 'exclude'),
        ('lint', 'extend-exclude'),
        ('format', 'exclude'),
        ('format', 'extend-exclude'),
    ),
    'per-file-ignores': (
        ('lint', 'per-file-ignores'),
        ('lint', 'extend-per-file-ignores'),
        ('per-file-ignores',),
        ('extend-per-file-ignores',),
    ),
}


def _dig(config: dict, path: tuple[str, ...]) -> object:
    """*config* walked down *path*, or ``None`` the moment a level is missing or is not a table."""
    node: object = config
    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


def waiver_entries(config: dict, kind: str) -> frozenset[str]:
    """Every entry of *kind* in *config*, across ALL of ruff's spellings for it. PURE.

    A ``per-file-ignores`` entry is flattened to ``'<glob>::<code>'`` so both kinds compare as one
    sort of thing -- a set of strings each naming ONE waiver, which is what a named set has to be to
    be one. A glob carrying three codes is three rows, so dropping one of them moves the ratchet.
    """
    if kind not in WAIVER_SPELLINGS:
        msg = f'{kind!r} is not a declared waiver kind; the table names {sorted(WAIVER_SPELLINGS)}'
        raise CensusError(msg)
    out: set[str] = set()
    for path in WAIVER_SPELLINGS[kind]:
        value = _dig(config, path)
        if isinstance(value, dict):
            out |= {f'{glob}::{code}' for glob, codes in value.items() for code in codes}
        elif isinstance(value, list):
            out |= {str(entry) for entry in value}
        elif value is not None:
            msg = f'{".".join(path)} holds a {type(value).__name__}, which is neither a list nor a table of waivers'
            raise CensusError(msg)
    return frozenset(out)


def ruff_select(root: Path) -> frozenset[str]:
    return waiver_entries(ruff_config(root), 'select')


def ruff_ignore(root: Path) -> frozenset[str]:
    return waiver_entries(ruff_config(root), 'ignore')


def ruff_excludes(root: Path) -> frozenset[str]:
    """The paths ruff never opens in *root* -- the widest waiver a config can write.

    AN EXCLUDE IS NOT AN IGNORE AND IS STRICTLY STRONGER: an ignore drops ONE named code everywhere,
    an exclude drops ALL 58 selectors over a whole subtree and names no code at all. Nothing in this
    family read one until 2026-09-18.
    """
    return waiver_entries(ruff_config(root), 'exclude')


def ruff_per_file_waivers(root: Path) -> frozenset[str]:
    """``'<glob>::<code>'`` for every per-file waiver in *root*, across every spelling."""
    return waiver_entries(ruff_config(root), 'per-file-ignores')


def ruff_scalars(root: Path) -> dict[str, object]:
    """The knobs that are one value each, so two repos compare without a reader holding two files."""
    config = ruff_config(root)
    return {
        'line-length': config.get('line-length'),
        'target-version': config.get('target-version'),
        'unsafe-fixes': config.get('unsafe-fixes'),
        'quote-style': config.get('format', {}).get('quote-style'),
    }


_CODE = re.compile(r'\A([A-Z]+)([0-9]*)\Z')


def selector_covers(selector: str, code: str) -> bool:
    """Does ruff's *selector* enable *code*? LINTER first, digits second -- not a string prefix.

    The naive ``code.startswith(selector)`` is WRONG in a way that changes this census's headline
    number: ``E`` is pycodestyle and does not select ``ERA001``, ``F`` is Pyflakes and does not
    select ``FBT003``. Ruff resolves the alphabetic LINTER part exactly and only then matches the
    numeric part by prefix. Computing the counter-direction set the naive way inflated it from 8
    codes to 13, and all five extras belonged to other linters entirely.
    """
    want = _CODE.match(selector)
    have = _CODE.match(code)
    if want is None or have is None:
        return False
    return want[1] == have[1] and have[2].startswith(want[2])


def gitignore_patterns(root: Path) -> frozenset[str]:
    """Live patterns -- blanks and comments dropped, so a rewrapped comment is not a divergence."""
    return _live_lines(read_at_head(root, '.gitignore'))


_TARGET = re.compile('(?m)^([A-Za-z0-9_.-]+):(?!=)')


def make_targets(root: Path) -> frozenset[str]:
    """Every Makefile target except ``.PHONY``, which is a declaration ABOUT targets, not one."""
    text = read_at_head(root, 'Makefile')
    if text is None:
        msg = f'{root} declares no committed Makefile at {head_sha(root)}'
        raise UnreadableTree(msg)
    return frozenset(_TARGET.findall(text)) - {'.PHONY'}


_HOOK_ID = re.compile(r'(?m)^\s*-\s*id:\s*(\S+)')


def hook_ids(root: Path) -> frozenset[str]:
    """Hook ids DECLARED in ``.pre-commit-config.yaml``; empty when there is no such file.

    Commented-out hooks are dropped before the scan: all three consumers carry blocks of them, and a
    hook nobody runs is not a hook the repo declares.
    """
    config = root / '.pre-commit-config.yaml'
    if not config.is_file():
        return frozenset()
    lines = [line for line in config.read_text(encoding='utf-8').splitlines() if not line.strip().startswith('#')]
    return frozenset(_HOOK_ID.findall('\n'.join(lines)))


#: The names git actually invokes. A hooks DIRECTORY is shared by every worktree of a checkout,
#: which is why this reports and never repairs -- the reason `lab_commons.dev.hook_install` gives.
_GIT_HOOKS: Final = ('pre-commit', 'pre-push', 'commit-msg', 'prepare-commit-msg', 'post-checkout')


def installed_hook_names(root: Path) -> frozenset[str]:
    """Which of git's hook files are PRESENT -- the half a configuration cannot answer for itself.

    THE ONE READER THAT STAYS ON THE FILESYSTEM, and it is a decision rather than an omission. Every
    other reader here moved to :func:`read_at_head` on 2026-09-18 because a DECLARATION is a committed
    fact. An installed hook is not a declaration: it is a fact about THIS BOX, it is never committed
    anywhere, and reading it at HEAD would answer nothing at all. The rule is that the tree a reader
    consults must match the kind of fact it is about, not that one tree is always right.

    A worktree's ``.git`` is a FILE pointing at the parent checkout's git dir, and the hooks it runs
    are that checkout's. Resolving it is not a detail: reading ``<worktree>/.git/hooks`` as a
    directory reports every worktree in the family as having zero hooks, which is the opposite of
    what the motronics lane measured.
    """
    marker = root / '.git'
    if marker.is_dir():
        hooks_dir = marker / 'hooks'
    elif marker.is_file():
        gitdir = Path(marker.read_text(encoding='utf-8').split(':', 1)[1].strip())
        common = gitdir.parent.parent if gitdir.parent.name == 'worktrees' else gitdir
        hooks_dir = common / 'hooks'
    else:
        return frozenset()
    return frozenset(name for name in _GIT_HOOKS if (hooks_dir / name).is_file())


def dev_pages(root: Path) -> frozenset[str]:
    """Committed Markdown filenames under ``docs-src/dev/``. An absent tree reads empty, never raises."""
    return names_at_head(root, 'docs-src/dev', '.md')


def _live_lines(text: str | None) -> frozenset[str]:
    """Meaningful lines of a COMMITTED file's text; an uncommitted or absent file reads empty."""
    if text is None:
        return frozenset()
    kept = (line.strip() for line in text.splitlines())
    return frozenset(line for line in kept if line and not line.startswith('#'))
