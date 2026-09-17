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
    'compose',
    'dev_pages',
    'gitignore_patterns',
    'hook_ids',
    'installed_hook_names',
    'make_targets',
    'reachable_repos',
    'repo_root',
    'ruff_config',
    'ruff_ignore',
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


class CensusError(ValueError):
    """A row the census refuses to hold: a bad side, a caption for a reason, a key in two hands."""


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
    own = root / 'ruff.toml'
    if own.is_file():
        return tomllib.loads(own.read_text(encoding='utf-8'))
    project = tomllib.loads((root / 'pyproject.toml').read_text(encoding='utf-8'))
    return project.get('tool', {}).get('ruff', {})


def ruff_select(root: Path) -> frozenset[str]:
    return frozenset(ruff_config(root).get('lint', {}).get('select', ()))


def ruff_ignore(root: Path) -> frozenset[str]:
    return frozenset(ruff_config(root).get('lint', {}).get('ignore', ()))


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
    return _live_lines(root / '.gitignore')


_TARGET = re.compile('(?m)^([A-Za-z0-9_.-]+):(?!=)')


def make_targets(root: Path) -> frozenset[str]:
    """Every Makefile target except ``.PHONY``, which is a declaration ABOUT targets, not one."""
    text = (root / 'Makefile').read_text(encoding='utf-8')
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
    """Markdown filenames under ``docs-src/dev/``. An absent tree reads empty rather than raising."""
    tree = root / 'docs-src' / 'dev'
    return frozenset(p.name for p in tree.glob('*.md')) if tree.is_dir() else frozenset()


def _live_lines(path: Path) -> frozenset[str]:
    if not path.is_file():
        return frozenset()
    kept = (line.strip() for line in path.read_text(encoding='utf-8').splitlines())
    return frozenset(line for line in kept if line and not line.startswith('#'))
