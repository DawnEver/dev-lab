"""WHAT A SYNC LEAVES BEHIND: can the repo still run its OWN VERDICT after that command?

:mod:`lab_commons.dev.installdoor` asks whether a command delivers the declared BUILD of a floating
requirement, and :mod:`lab_commons.dev.doorcensus` asks whether a repo's door set was ever looked
at. Both are about ONE distribution's version. Neither can see the other half of what a sync does,
and that half is the one that took a working box apart -- the census says so in its own docstring
and names this ratchet as ABSENT rather than implying it covers it.

THE INCIDENT, MEASURED 2026-09-18 in the motronics ``feat/optimi-lab`` worktree. ``dep_sync --sync``
with NO ``--extra`` SUCCEEDED and took the environment from **113 distributions to 30**: pytest,
ruff, pre-commit, motronics_native, optimi_lab and wdg-lab among the 83 removed, and the warning
printed AFTER the prune. Restoring took two passes, because ``--extra all`` in that repo does NOT
include ``img-to-cad``. That command classifies ``RESOLVES`` under ``installdoor`` and it is RIGHT:
the kit build it delivered was the declared one. The environment it delivered could not run a test.

WHY THIS IS WORSE THAN A WRONG BUILD, and it is the reason the question is worth its own module: a
repo with no pytest cannot produce ANY verdict, so the failure reads as a BROKEN TREE rather than a
broken ENVIRONMENT and the reader is sent to debug the wrong thing. A stale build at least runs.

**AN EXTRAS NAME IS NOT A FACT ABOUT THE COMMAND, IT IS A FACT ABOUT THE MANIFEST.** That is what
made the incident expensive: ``all`` is a name a reader assumes means everything, and in motronics
it means ``motronics[euclid,maxwell,pareto,femm,gui,native]`` -- no ``dev`` and no ``img-to-cad``.
So every answer here is a JOIN of a command's selection with a repo's ``[project.optional-
dependencies]``, and a selection naming an extra the manifest does not declare is REFUSED rather
than scored as empty. ``[project.optional-dependencies]`` is DECLINED as a family base in
`_famconfig_pyproject_rows.PYPROJECT_DECLINED` -- it is the dependency graph and per-repo -- and
that decline is the constraint this module is built inside, not an obstacle to it: nothing here
proposes a shared value, it reads each repo's own table and asks one portable question of it.

THE MEASURED SEMANTICS every branch below is a row of. Nothing here installs, syncs or prunes, and
nothing here may -- re-running the defect under study is how a working box is destroyed:

=================================================  ===========================================
command                                            population
=================================================  ===========================================
``uv sync`` (no ``--extra``)                       base dependencies + project. 113 -> 30.
``uv sync --extra pareto --extra dev``             base + those two. MEASURED 2026-09-15 in
                                                   ``dep_sync``: removed cadquery-ocp, wdg-lab.
``uv run <anything>`` without ``--no-sync``        the implicit sync, carrying NO extras
``uv run --no-sync`` / ``uv sync --inexact``       unchanged -- not a population door
``uv pip install`` / ``pip install``               ADDS; pip has no prune verb
=================================================  ===========================================

``--no-dev`` IS NOT ABOUT A ``dev`` EXTRA and the spelling invites exactly that misreading: it
suppresses ``[dependency-groups]``, which NO repo in this family declares. All four put pytest and
ruff in an EXTRA, so the dev tooling arrives only under ``--extra dev`` and ``--no-dev`` changes
nothing. The day a repo adopts ``[dependency-groups]`` this module answers :attr:`Scope.UNMEASURED`
rather than a confident wrong answer, because it does not model the group axis.

WHAT THIS CANNOT SEE, stated so a green is not over-read:

* WHETHER A TEST IMPORTS A PRUNED DISTRIBUTION. The verdict set is derived from the MANIFEST -- the
  runner and the plugins its own pytest configuration names. A test module importing ``cv2`` from an
  extra outside ``all`` still errors at collection, and no reading of a manifest can say so. That is
  why ``img-to-cad``'s absence scores :attr:`Scope.COMPLETE` here: the RUNNER survives.
* WHAT A COMMAND DID ON A BOX. Same refusal as ``installdoor``: TEXT and declared config only.
* A SELECTION BUILT AT RUNTIME. A shell variable or a Python-composed argv is UNMEASURED, and the
  caller declares the selection with the file and line that pins it.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from enum import Enum
from typing import Final

__all__ = [
    'NON_PRUNING_FLAGS',
    'PLUGIN_TRIGGERS',
    'PRUNING_VERBS',
    'RUNNER',
    'Scope',
    'Selection',
    'UnknownExtraError',
    'canon',
    'declares_groups',
    'extras',
    'scope',
    'selection',
    'stranded',
    'survivors',
    'verdict_set',
]

#: The ``uv`` verbs that make the environment MATCH a resolution, dropping whatever is not in it.
#: ``run`` is here for the same reason it is in ``installdoor.LOCK_CONSUMING``: its implicit sync is
#: a full sync, and it carries no ``--extra``, so a bare ``uv run`` after an ``--extra`` sync undoes
#: the step before it. That is the shape the shared CI workflow's ``--no-sync`` exists to refuse.
PRUNING_VERBS: Final = frozenset({'run', 'sync'})

#: Flags under which a pruning verb stops moving the population. ``--inexact`` is uv's own "leave
#: extraneous packages alone"; ``--no-sync`` skips the implicit sync entirely. ``--frozen`` is
#: deliberately NOT here: it pins WHICH resolution is used and still makes the environment match it.
NON_PRUNING_FLAGS: Final = frozenset({'--inexact', '--no-sync'})

#: The distribution that runs every verdict in this family. Not derived -- it is the premise: a tree
#: with no pytest cannot report PASS, FAIL or INCONCLUSIVE, so its absence is not a degraded verdict
#: but the absence of the instrument.
RUNNER: Final = 'pytest'

#: A pytest CONFIGURATION token and the distribution it silently requires. This is the half a reader
#: forgets: pytest exits 4 -- USAGE ERROR, no verdict -- on an unrecognised option, so an ``addopts``
#: naming ``-n auto`` makes ``pytest-xdist`` as load-bearing as pytest itself. Keyed by the token as
#: it appears in the manifest, because that is where the requirement is DECLARED.
PLUGIN_TRIGGERS: Final[dict[str, str]] = {
    '--cov': 'pytest-cov',
    '--dist': 'pytest-xdist',
    '-n': 'pytest-xdist',
    'timeout': 'pytest-timeout',
}

#: The linter every ``verify`` runs tree-wide before it will promote a verdict.
_LINTER: Final = 'ruff'

#: The kit itself: the family's one verify entry point is ``python -m lab_commons.dev.verify``, so a
#: repo that DECLARES lab-commons anywhere cannot produce a verdict without it. A repo that does not
#: declare it is either the kit or does not run it, and neither is this rule's subject.
_KIT: Final = 'lab-commons'

#: The leading run of a PEP 508 spec that is the distribution name: ``pkg[extra] @ git+...`` and
#: ``pkg>=1; sys_platform == 'win32'`` both answer ``pkg``.
_NAME: Final = re.compile(r'^\s*(?P<name>[A-Za-z0-9._-]+)')

#: The ``uv run`` flags that CONSUME the token after them, so a value is never read as the child
#: program. Declared as data because the alternative -- "the first bare token wins" -- reads
#: ``uv run --python 3.12 pytest`` as running ``3.12``.
_VALUE_FLAGS: Final = frozenset({'--directory', '--extra', '--group', '--project', '--python', '--with', '-p'})

#: How a spec names extras of the distribution it references: ``motronics[euclid,maxwell]``.
_EXTRAS_OF: Final = re.compile(r'^\s*[A-Za-z0-9._-]+\s*\[(?P<extras>[^\]]*)\]')


class UnknownExtraError(ValueError):
    """A command selects an extra the manifest does not declare, so what it would install is unreadable.

    REFUSED RATHER THAN SCORED AS EMPTY, and this is the incident's own shape pointed at the other
    repo: ``--extra all`` is correct in motronics and names nothing in lab-commons. Treating an
    unknown name as "no extra" would answer the question as if the flag had not been typed.
    """


class Scope(Enum):
    """What a command leaves the repo able to do. Four values, because two of them are not failures.

    :attr:`INERT` is a command that moves no population -- there is nothing for it to strand.
    :attr:`UNMEASURED` is an honest blind spot: the selection or the manifest is outside what TEXT
    can settle, and a guessed measurement is worse than a named gap.
    """

    COMPLETE = 'complete'
    STRANDS = 'strands'
    INERT = 'inert'
    UNMEASURED = 'unmeasured'


@dataclass(frozen=True, slots=True)
class Selection:
    """WHICH EXTRAS a command asks for, separated from what those extras MEAN.

    The split is the module's whole premise: this half is readable from the command, and it is worth
    nothing until it is joined to a manifest. *unresolved* carries the tokens that name an extra
    nothing in the text can settle -- a shell variable, a matrix input -- so a caller can tell "no
    extras" from "extras this reader could not read".
    """

    prunes: bool
    extras: frozenset[str] = frozenset()
    all_extras: bool = False
    unresolved: tuple[str, ...] = ()


def canon(name: str) -> str:
    """The PEP 503 normalised distribution name: case-folded, with runs of ``-_.`` as one ``-``.

    ``img-to-cad`` and ``img_to_cad`` are one extra and ``motronics_native`` and
    ``motronics-native`` are one distribution; a reader comparing raw spellings scores either pair
    as two things and reports a strand that is not there.
    """
    return re.sub(r'[-_.]+', '-', name.strip()).lower()


def _spec_name(spec: str) -> str | None:
    match = _NAME.match(spec)
    return canon(match['name']) if match else None


def _spec_extras(spec: str) -> tuple[str, ...]:
    match = _EXTRAS_OF.match(spec)
    return tuple(canon(part) for part in match['extras'].split(',') if part.strip()) if match else ()


def _manifest(text: str) -> dict:
    return tomllib.loads(text).get('project', {})


def declares_groups(text: str) -> bool:
    """Answer whether the manifest declares ``[dependency-groups]``, the axis this module does NOT model.

    Asked rather than assumed absent. No repo in the family declares one today, and a reader that
    silently ignored the table would answer confidently about a population it could not see.
    """
    return bool(tomllib.loads(text).get('dependency-groups'))


def extras(text: str) -> dict[str, frozenset[str]]:
    """Every declared extra of this manifest, as normalised distribution names, SELF-REFERENCES EXPANDED.

    ``all = ["motronics[euclid,maxwell,pareto,femm,gui,native]"]`` is the shape that hid the
    incident: read literally the extra contains one distribution -- the project -- and what it
    actually installs is six other extras that a reader has to go and look up. Expanded here, once,
    so no caller has to know the trick. A reference to a FOREIGN distribution's extras
    (``lab-commons[dev]``) contributes that distribution and stops: what its own extras pull in is
    its manifest's business and is not in this text.

    Raises:
        UnknownExtraError: a self-reference names an extra this manifest does not declare.

    """
    project = _manifest(text)
    raw = {canon(name): tuple(specs) for name, specs in project.get('optional-dependencies', {}).items()}
    me = canon(project.get('name', ''))
    return {name: frozenset(_expand(name, raw, me, set())) for name in raw}


def _expand(name: str, raw: dict[str, tuple[str, ...]], me: str, seen: set[str]) -> set[str]:
    """The distributions *name* installs, following self-references. *seen* makes a cycle finite."""
    if name in seen:
        return set()
    if name not in raw:
        msg = f'extra {name!r} is not declared in this manifest; it declares {sorted(raw)}'
        raise UnknownExtraError(msg)
    seen = seen | {name}
    out: set[str] = set()
    for spec in raw[name]:
        dist = _spec_name(spec)
        if dist is None:
            continue
        if dist == me and me:
            for inner in _spec_extras(spec):
                out |= _expand(inner, raw, me, seen)
        else:
            out.add(dist)
    return out


def _base(text: str) -> frozenset[str]:
    """The project itself plus every required dependency -- what survives a sync selecting nothing."""
    project = _manifest(text)
    names = {canon(project['name'])} if project.get('name') else set()
    names |= {dist for spec in project.get('dependencies', ()) if (dist := _spec_name(spec))}
    return frozenset(names)


def _marked(text: str) -> frozenset[str]:
    """Every distribution supplied ONLY by specs carrying an environment marker, in any table here.

    A marked spec installs on some platforms and not others, so its presence is not a property of
    the manifest. Nothing in any verdict set is marked today; if one ever is, :func:`scope` answers
    UNMEASURED rather than reading a Windows-only requirement as universally present.
    """
    project = _manifest(text)
    supplied: dict[str, bool] = {}
    for spec in [*project.get('dependencies', ()), *_all_optional(project)]:
        dist = _spec_name(spec)
        if dist is not None:
            supplied[dist] = supplied.get(dist, True) and ';' in spec
    return frozenset(dist for dist, only_marked in supplied.items() if only_marked)


def _all_optional(project: dict) -> list[str]:
    return [spec for specs in project.get('optional-dependencies', {}).values() for spec in specs]


def verdict_set(text: str) -> frozenset[str]:
    """The distributions this repo cannot report ANY verdict without, DERIVED from its own manifest.

    Four rules, and each is a fact the manifest states rather than a name somebody typed:

    * :data:`RUNNER` -- no pytest, no verdict of any kind.
    * every plugin this repo's own ``[tool.pytest.ini_options]`` NAMES. pytest exits 4 on an
      unrecognised option, so motronics' ``-n auto`` and ``timeout = 300`` make xdist and timeout
      load-bearing, and the two repos whose ``addopts`` carry ``--cov`` require pytest-cov.
    * ``ruff`` -- ``verify`` runs ``ruff format --check`` tree-wide before it promotes anything.
    * ``lab-commons`` when the manifest declares it, because the family's one verify entry point
      lives there. The kit itself does not declare itself and is not its own subject.
    """
    table = tomllib.loads(text)
    ini = table.get('tool', {}).get('pytest', {}).get('ini_options', {})
    addopts = ini.get('addopts', '')
    haystack = f'{addopts if isinstance(addopts, str) else " ".join(addopts)} {" ".join(ini)}'
    tokens = set(haystack.split())
    plugins = {dist for token, dist in PLUGIN_TRIGGERS.items() if token in tokens or f'{token}=' in haystack}
    needed = {RUNNER, _LINTER} | plugins
    declared = _base(text) | {dist for members in extras(text).values() for dist in members}
    if _KIT in declared and canon(_manifest(text).get('name', '')) != _KIT:
        needed.add(_KIT)
    return frozenset(needed)


def selection(argv: list[str]) -> Selection:
    """WHICH EXTRAS this command asks for, and whether it prunes at all. Pure over its argument.

    Pure so that a planted control drives THIS function rather than a second implementation that
    would agree with it by construction -- the same argument ``installdoor.classify`` makes.
    """
    if not argv or argv[0].lower().removesuffix('.exe') != 'uv':
        return Selection(prunes=False)
    rest = argv[1:]
    verb = next((token for token in rest if not token.startswith('-')), '')
    if verb not in PRUNING_VERBS or NON_PRUNING_FLAGS & set(rest):
        return Selection(prunes=False)
    return _select(rest if verb == 'sync' else _uv_own(rest[rest.index(verb) + 1 :]))


def _uv_own(after_run: list[str]) -> list[str]:
    """``uv run``'s OWN flags: everything before the CHILD program token.

    Without the cut, ``uv run pytest --extra x`` would read as a selection uv never saw -- those
    tokens belong to the child. A flag from :data:`_VALUE_FLAGS` consumes the token after it, which
    is what stops ``uv run --python 3.12 pytest`` mistaking the version for the program.
    """
    own: list[str] = []
    skip = False
    for token in after_run:
        if skip:
            own.append(token)
            skip = False
            continue
        if not token.startswith('-'):
            break
        own.append(token)
        skip = token in _VALUE_FLAGS
    return own


def _select(tokens: list[str]) -> Selection:
    picked: set[str] = set()
    unresolved: list[str] = []
    for index, word in enumerate(tokens):
        if word == '--extra' and index + 1 < len(tokens):
            value = tokens[index + 1]
        elif word.startswith('--extra='):
            value = word.split('=', 1)[1]
        else:
            continue
        # A `$VAR`, a `${{ inputs.x }}` or a glob is a selection composed somewhere else. NAMED
        # rather than dropped: "no extras" and "extras this reader could not read" have opposite
        # remedies, and scoring the second as the first is how a blind spot reads as a measurement.
        if re.search(r'[$*{}]', value):
            unresolved.append(value)
        else:
            picked.add(canon(value))
    return Selection(
        prunes=True,
        extras=frozenset(picked),
        all_extras='--all-extras' in tokens,
        unresolved=tuple(unresolved),
    )


def survivors(chosen: Selection, text: str) -> frozenset[str]:
    """The distributions left installed by a selection that prunes: base, project, and the extras named.

    Raises:
        UnknownExtraError: the selection names an extra this manifest does not declare -- the
            ``--extra all`` hazard read against the wrong repo.

    """
    declared = extras(text)
    if chosen.all_extras:
        return _base(text) | frozenset(dist for members in declared.values() for dist in members)
    unknown = sorted(chosen.extras - set(declared))
    if unknown:
        msg = f'selection names {unknown} which this manifest does not declare; it declares {sorted(declared)}'
        raise UnknownExtraError(msg)
    return _base(text) | frozenset(dist for name in chosen.extras for dist in declared[name])


def stranded(chosen: Selection, text: str) -> tuple[str, ...]:
    """Every verdict-critical distribution this selection would REMOVE, sorted. Empty is the good answer."""
    return tuple(sorted(verdict_set(text) - survivors(chosen, text)))


def scope(chosen: Selection, text: str) -> Scope:
    """THE READER. Would this command leave the repo able to run its own verdict?

    Raises:
        UnknownExtraError: from :func:`survivors` -- an extras name the manifest does not declare.

    """
    if not chosen.prunes:
        return Scope.INERT
    if chosen.unresolved or declares_groups(text):
        return Scope.UNMEASURED
    left = stranded(chosen, text)
    if _marked(text) & verdict_set(text):
        return Scope.UNMEASURED
    return Scope.STRANDS if left else Scope.COMPLETE
