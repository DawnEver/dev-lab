"""The family rows NO repo can drop: a pytest plugin that installing dev-lab switches on.

THE ONE EXCEPTION TO THIS PACKAGE'S SHAPE, and it is a user ruling (2026-11-07), not a convenience:
NO-CJK-IN-TRACKED-SOURCE is enforced in every family repo from ONE place, with no per-repo copy and
no opt-out. Every other body in :mod:`dev_lab.dev.famtests` is parametrized by a consumer file that
names its repo's facts; this rule has none left to name -- the corpus is the repo's tracked files,
the exemptions are :data:`dev_lab.dev.cjk.EXEMPT_PREFIXES`, and the declared set is DATA in the repo's
own manifest (``[tool.dev_lab.cjk] declared``, :func:`declared_cjk`; added for D26, 2026-11-17, when
memory and tasks lost their exemption) -- so a consumer file could only be a copy, or a place to forget it.

HOW IT REACHES A REPO. dev-lab registers :mod:`dev_lab.pytest_family` under pytest's ``pytest11``
entry point, so any pytest session in an environment where dev-lab is installed loads it, and that
shim calls :func:`append_rows` at collection. When the session's rootdir
is a git toplevel it appends one item per row in :func:`rows`; a session rooted anywhere else (a
pytester tree, an unpacked sdist) has no tracked corpus and gets none. :data:`dev_lab.dev.rules.ALWAYS_ON`
is the registry's half: an adoption may neither list these rules nor declare them absent.

A DECLARED CHECKOUT ALSO GETS THE TREE CHECKS (:mod:`dev_lab.dev.famtests.treechecks`, user ruling D42,
2026-11-17): the famtests bodies whose every argument the checkout answers, each where its population exists.

ONE ``git grep`` FINDS THE CANDIDATES (coordinator ruling 2026-11-07): a per-file Python read took
331 s over acme-consumer's 22k files. The PCRE class is built from :data:`dev_lab.dev.cjk.CJK_RANGES` and
the exclusions from :data:`dev_lab.dev.cjk.EXEMPT_PREFIXES`; ``-I`` skips binaries. The translation
exemption and orphan check run in Python on the short list, and only hit files are re-read to name
line and column. The floor: ``git ls-files`` lists at least one file.
"""

from __future__ import annotations

import shutil
import subprocess
import tomllib
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Final

import pytest
from lab_commons.hpc.testcells import TestCell
from lab_commons.launch import run
from lab_commons.outcomes import Cell, Reason, Status

from dev_lab.dev import cjk, frozen, remretired
from dev_lab.dev.family import declared_table, is_member
from dev_lab.dev.famtests import hiddenintake, modulealarm, treechecks
from dev_lab.dev.rules import ALWAYS_ON, tracked_files

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

__all__ = [
    'append_rows',
    'assert_required_collected',
    'candidates',
    'check_no_cjk',
    'cjk_pattern',
    'declared_cjk',
    'exclude_pathspecs',
    'required_ids',
    'resource_nodes',
    'rows',
    'run_checks',
]

_GIT_TIMEOUT_S: Final = 60
_GIT: Final = shutil.which('git') or 'git'


def cjk_pattern(ranges: tuple[tuple[int, int], ...] = cjk.CJK_RANGES) -> str:
    """A PCRE character class over *ranges* -- DERIVED from :data:`dev_lab.dev.cjk.CJK_RANGES`, never copied."""
    return '(*UTF)[' + ''.join(f'\\x{{{lo:04x}}}-\\x{{{hi:04x}}}' for lo, hi in ranges) + ']'


def exclude_pathspecs(prefixes: tuple[str, ...] = cjk.EXEMPT_PREFIXES) -> tuple[str, ...]:
    """Git pathspecs excluding *prefixes* with :func:`dev_lab.dev.cjk.exempted`'s semantics.

    A leading ``/`` anchors at the root; any other prefix matches as a segment at any depth.
    """
    specs: list[str] = []
    for prefix in prefixes:
        body = prefix.strip('/')
        specs.append(f':(exclude,glob){body}/**' if prefix.startswith('/') else f':(exclude,glob)**/{body}/**')
    return tuple(specs)


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return run([_GIT, *args], cwd=root, capture_output=True, check=False, timeout=_GIT_TIMEOUT_S)


def candidates(root: Path) -> tuple[str, ...]:
    """Tracked, text, non-exempt files under *root* holding a CJK character: ONE ``git grep``.

    ``-I`` skips binaries, which is the scanner's "undecodable is not read". Raises when git fails.
    """
    out = _git(
        root, '-c', 'core.quotepath=off', 'grep', '-I', '-l', '-z', '-P', cjk_pattern(), '--', '.', *exclude_pathspecs()
    )
    if out.returncode not in (0, 1):  # 1 means no match
        msg = f'git grep failed in {root}: {out.stderr.decode("utf-8", "replace").strip()}'
        raise AssertionError(msg)
    return tuple(sorted(name for name in out.stdout.decode('utf-8').split('\0') if name))


def declared_cjk(root: Path) -> tuple[str, ...]:
    """The repo's migration ledger: ``[tool.dev_lab.cjk] declared`` in *root*'s ``pyproject.toml``.

    Repo-relative POSIX paths still carrying CJK; the set may only shrink (:func:`dev_lab.dev.cjk.ratchet`
    refuses a declared file with none left). No manifest or no table is the empty set. A value that is
    not a list of strings is refused by name rather than read as empty, which would hide every entry.
    """
    try:
        text = (root / 'pyproject.toml').read_text(encoding='utf-8')
    except OSError:
        return ()
    entries = declared_table(tomllib.loads(text), 'cjk', {}).get('declared', [])
    if not isinstance(entries, list) or not all(isinstance(entry, str) for entry in entries):
        msg = f'[tool.dev_lab.cjk] declared must be a list of repo-relative paths, not {entries!r}'
        raise AssertionError(msg)
    return tuple(entries)


def check_no_cjk(root: Path) -> None:
    """Raise unless no tracked, non-exempt file under *root* carries CJK and no translation is orphaned."""
    tracked = tracked_files(root)  # raises rather than answering empty
    problems = list(cjk.orphaned_translations(tracked))
    if not tracked:
        problems.append('git ls-files listed no file, so a clean result would mean nothing')
    hits = [name for name in candidates(root) if not cjk.translation_exempted(name, tracked)]
    scan = cjk.scan_files([root / name for name in hits], exempt_prefixes=cjk.EXEMPT_PREFIXES, root=root)
    problems.extend(cjk.ratchet(scan.occurrences, declared_cjk(root)))
    if problems:
        raise AssertionError('\n  '.join(('NO-CJK-IN-TRACKED-SOURCE:', *problems)))


#: Rule ID -> the check this plugin runs for it over the repo root.
_LAYOUT_RULE: Final = 'MODULE-SIZE-ALARM'
_CHECKS: Final[dict[str, Callable[[Path], None]]] = {
    'NO-CJK-IN-TRACKED-SOURCE': check_no_cjk,
    remretired.RULE_ID: remretired.check,
    hiddenintake.RULE_ID: hiddenintake.check,
    _LAYOUT_RULE: modulealarm.check,
}


def rows() -> dict[str, Callable[[Path], None]]:
    """Rule ID -> check, for every ``always_on`` registry row (:data:`dev_lab.dev.rules.ALWAYS_ON`).

    Which rules are always on is the registry's data; this module owns only the checks. A row with no
    check here raises KeyError rather than being skipped.
    """
    return {rule: _CHECKS[rule] for rule in sorted(ALWAYS_ON)}


def _declared_checkout(root: Path) -> bool:
    """A family CHECKOUT: a manifest declaring membership AND a ``.git`` at the root.

    A declared tree with no ``.git`` (a test's temp project, an unpacked sdist) has no tracked corpus and is
    not judged; a declared checkout whose ``.git`` exists but cannot be read is refused loudly.
    """
    return is_member(root) and (root / '.git').exists()


def _declares_layout(root: Path) -> bool:
    """Opt-in: a ``[tool.dev_lab.layout]`` table, or a manifest too broken to say, enables the layout check."""
    try:
        data = tomllib.loads((root / 'pyproject.toml').read_text(encoding='utf-8'))
    except OSError:
        return False
    except ValueError:
        return True
    return declared_table(data, 'layout') is not None


def _applicable(root: Path) -> dict[str, Callable[[Path], None]]:
    checks = rows()
    if _declared_checkout(root):
        if _declares_layout(root):
            checks[_LAYOUT_RULE] = _CHECKS[_LAYOUT_RULE]
        if frozen.declared(root):
            checks[frozen.RULE_ID] = frozen.check
        checks.update(treechecks.applicable(root))
    return checks


def _identity(rule: str) -> str:
    return f'::family::{rule}'


def _catalog_ids(root: Path) -> tuple[str, ...]:
    return tuple(_identity(rule) for rule in _applicable(root)) if _declared_checkout(root) else ()


def required_ids(root: Path) -> tuple[str, ...]:
    """Exact required identities after fresh family Git-root proof; no claim for other inputs."""
    if not _declared_checkout(root):
        return ()
    if _toplevel(root) != root.resolve():
        refused = _git_refusal('the declared family root is not the readable git toplevel')
        raise refused
    return _catalog_ids(root)


def assert_required_collected(root: Path, ids: Sequence[str]) -> None:
    """Reject a family collection whose plugin did not actually supply every required item."""
    if missing := set(required_ids(root)) - set(ids):
        message = (
            f'required family checks missing from collection: {sorted(missing)}; '
            'enable the installed dev_lab_family pytest plugin (remove plugin-disable flags or '
            'PYTEST_DISABLE_PLUGIN_AUTOLOAD), then recollect before producing a complete part'
        )
        raise ValueError(message)


def resource_nodes(root: Path, ids: Sequence[str]) -> list[str]:
    """Identity projection, not qualification; collectors must separately prove their complete manifest."""
    required = set(_catalog_ids(root))
    return [node for node in ids if node not in required]


def run_checks(root: Path) -> dict[str, TestCell]:
    """Execute the same checks for non-pytest family producers, retaining their individual evidence."""
    if not _declared_checkout(root):
        return {}
    cells = {}
    for rule, check in _applicable(root).items():
        try:
            check(root)
        except (AssertionError, OSError, ValueError, RuntimeError) as exc:
            cells[_identity(rule)] = TestCell(Cell(Status.REJECTED, reason=Reason('assertion', str(exc))))
        else:
            cells[_identity(rule)] = TestCell(Cell(Status.OK))
    return cells


class FamilyItem(pytest.Item):
    """One always-on row, run against the session's repo root."""

    def __init__(self, *, name: str, parent: pytest.Session, check: Callable[[Path], None], root: Path) -> None:
        super().__init__(name=name, parent=parent, nodeid='::' + name)
        self._check = check
        self._root = root

    def runtest(self) -> None:
        self._check(self._root)

    def reportinfo(self) -> tuple[Path, None, str]:
        return self._root, None, f'family row {self.name}'


def _git_refusal(reason: str) -> ValueError:
    return ValueError(
        f'git identity of the declared family checkout cannot be established: {reason}; '
        'repair git checkout/access, then recollect before producing complete qualification'
    )


def _toplevel(root: Path) -> Path | None:
    try:
        out = _git(root, 'rev-parse', '--show-toplevel')
    except (OSError, subprocess.TimeoutExpired) as exc:
        if _declared_checkout(root):
            refused = _git_refusal(f'{type(exc).__name__}: {exc}')
            raise refused from exc
        return None
    if out.returncode != 0:
        if _declared_checkout(root):
            refused = _git_refusal(f'exit {out.returncode}: {out.stderr.decode("utf-8", "replace").strip()}')
            raise refused
        return None
    try:
        text = out.stdout.decode('utf-8').strip()
        top = Path(text).resolve() if text else None
    except (UnicodeError, OSError, ValueError) as exc:
        if _declared_checkout(root):
            refused = _git_refusal(str(exc))
            raise refused from exc
        return None
    if top is None and _declared_checkout(root):
        refused = _git_refusal('git returned an empty toplevel')
        raise refused
    return top


def _unreadable_root(_root: Path, *, reason: str) -> None:
    raise ValueError(reason)


def append_rows(session: pytest.Session, config: pytest.Config, items: list[pytest.Item]) -> None:
    """Append one item per row when the session is rooted at a git toplevel.

    Called at collection by :mod:`dev_lab.pytest_family`, the ``pytest11`` entry point.
    A declared family with unreadable Git retains failed runtime items, never an empty guard set.
    """
    root = Path(config.rootpath).resolve()
    if _declared_checkout(root):
        try:
            required_ids(root)
        except ValueError as exc:
            checks = dict.fromkeys(_applicable(root), partial(_unreadable_root, reason=str(exc)))
        else:
            checks = _applicable(root)
    else:
        if _toplevel(root) != root:
            return
        checks = _applicable(root)
    items.extend(
        FamilyItem.from_parent(session, name=_identity(rule).removeprefix('::'), check=check, root=root)
        for rule, check in checks.items()
    )
