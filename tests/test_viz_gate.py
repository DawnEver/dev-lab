"""``lab_commons.viz`` — the OPT-IN gate, and the constraint that makes each adapter an equal peer.

THREE PROPERTIES, AND ALL THREE DECAY SILENTLY. That importing ``lab_commons`` never pulls the tier
in (the same discipline that keeps ``lab_commons.dev`` and ``lab_commons.em`` optional); that the
vocabulary module reaches no plotting library at all, so a producer may depend on it on a box where
none is installed; and that each adapter imports EXACTLY the library its own extra names -- not the
other's, and not one that happens to be installed on the box reading this.

ASSERTED AGAINST THE REAL ARTEFACTS, not a restatement of them: a fresh interpreter for the first,
the parsed ``pyproject.toml`` and the actual import statements for the rest. Read from the SOURCE
rather than by importing, because a module that imported cleanly today would import cleanly tomorrow
off a dependency another layer happened to install -- and the question is what this layer DECLARES.
"""

import ast
import subprocess
import sys
from importlib.metadata import PackageNotFoundError
from importlib.metadata import files as distribution_files
from pathlib import Path

from lab_commons import viz
from lab_commons.file_io import read_toml

REPO_ROOT = Path(__file__).resolve().parents[1]
VIZ_ROOT = REPO_ROOT / 'src' / 'lab_commons' / 'viz'

#: The extra that gates each adapter, and the ONE distribution that adapter may import beyond the
#: base runtime set. NAMED, so an extra renamed in ``pyproject.toml`` reds here rather than being
#: discovered by a consumer whose install stopped delivering an import. ``_bokeh_names.py`` is in
#: the map rather than in the floor below because it is the OTHER half of the bokeh gate: a module
#: holding bokeh's spellings for the vocabulary must be covered by the extra that carries bokeh, or
#: the tables could reach a library the extra does not install and nothing here would notice.
#:
#: THE FOUR ADAPTER MODULES ARE TWO PAIRS, and each pair is one adapter: ``mpl.py``/``bokeh.py``
#: hold the CANVAS half (the figure, its style, its lifecycle) and ``*_frame.py`` the FRAME half
#: (one coordinate system and every draw verb). Both halves of a pair name the same extra, because
#: a frame without its canvas is not a tier a consumer can install. ``_bokeh_glyphs.py`` is the
#: third bokeh module and is here for ``_bokeh_names.py``'s reason: it is machinery of that adapter
#: -- the four verbs that build DATA rather than calling a glyph -- so it must be covered by the
#: extra that carries bokeh, not merely by the package. ``mpl_frame_3d.py`` is a FOURTH module of
#: the matplotlib adapter rather than a third entry for one of the two pairs: the 3D frame is a
#: protocol of its own (see :data:`PROTOCOLS`), it draws with ``mpl_toolkits.mplot3d`` -- which
#: ships with matplotlib and so names no dependency of its own -- and no bokeh counterpart exists to
#: keep in step with it.
BACKENDS: dict[str, str] = {
    'mpl.py': 'matplotlib',
    'mpl_frame.py': 'matplotlib',
    'mpl_frame_3d.py': 'matplotlib',
    'bokeh.py': 'bokeh',
    'bokeh_frame.py': 'bokeh',
    '_bokeh_glyphs.py': 'bokeh',
    '_bokeh_names.py': 'bokeh',
}

#: WHAT EACH DISTRIBUTION ACTUALLY PROVIDES, where that is more than the module it is named after —
#: MEASURED from the installed distribution's own file list rather than assumed, because the check
#: below is about DISTRIBUTIONS and it reads IMPORT NAMES. ``mpl_toolkits`` is the one entry here: it
#: is a second top-level module inside the matplotlib wheel (``mplot3d`` and the two toolkit
#: packages live under it), which is what makes the 3D frame's ``import mpl_toolkits.mplot3d.art3d``
#: a matplotlib import and NOT a dependency of its own — the property that lets this tier draw 3D
#: while its ``viz-mpl`` extra still names one distribution.
_PROVIDED: dict[str, frozenset[str]] = {'matplotlib': frozenset({'matplotlib', 'mpl_toolkits'})}

#: The protocols and the default implementation of each, as
#: ``(protocol, the module that DECLARES it, the canvas verb that builds one, implementations)``:
#: the vocabulary's canvas and its two coordinate systems against every implementation there is,
#: which is the equality a peer relationship is. The three are separate contracts, so they are
#: separate checks -- a frame that lost a verb and a canvas that grew one are different defects and
#: neither hides the other.
#:
#: THE THIRD ROW NAMES TWO IMPLEMENTATIONS AND NOT THREE, and that is the peer relationship stated
#: exactly: no plotting library but matplotlib has a third axis, so ``BokehRenderer`` refuses
#: ``frame_3d`` at the canvas (there is no frame object to keep in step with) and the equality is
#: between the two frames that DO exist. The renderers' own verb sets are still checked against
#: ``Figure``, which is where ``frame_3d`` is declared -- so a canvas that dropped the verb reds
#: above rather than here.
PROTOCOLS: tuple[tuple[str, str, str, tuple[tuple[str, str], ...]], ...] = (
    (
        'Figure',
        '__init__.py',
        'frame',
        (('__init__.py', 'NullRenderer'), ('mpl.py', 'MplRenderer'), ('bokeh.py', 'BokehRenderer')),
    ),
    (
        'Frame',
        '__init__.py',
        'frame',
        (('__init__.py', 'NullFrame'), ('mpl_frame.py', 'MplFrame'), ('bokeh_frame.py', 'BokehFrame')),
    ),
    (
        'Frame3D',
        '_three_d.py',
        'frame_3d',
        (('_three_d.py', 'NullFrame3D'), ('mpl_frame_3d.py', 'MplFrame3D')),
    ),
)

#: THE VOCABULARY, which is more than one module now: the primitives and the protocols, plus the
#: placement rules they refer to and the 3D protocol with its own shape. NAMED, because the check
#: below is "this tier reaches no plotting library" and a module that joined the vocabulary without
#: joining this set would be outside it -- a guarantee that quietly stopped covering the half that
#: was most recently written.
VOCABULARY: tuple[str, ...] = ('__init__.py', '_placement.py', '_three_d.py')

#: A FLOOR under each protocol's verb count, BY NAME -- a protocol that declares (nearly) nothing is
#: not a tier. Floors rather than counts, so a verb ADDED to a protocol never reds here and only a
#: verb LOST does; the numbers are the declared sets as measured, less the room an honest tidy-up of
#: one verb needs. Writing them down rather than deriving them is what makes a protocol that quietly
#: shrank to one verb a red instead of a smaller number.
_VERB_FLOORS: dict[str, int] = {'Figure': 6, 'Frame': 20, 'Frame3D': 10}


def _declared_requirements() -> frozenset[str]:
    """Every distribution ``[project] dependencies`` names, by its bare (unversioned) name."""
    declared = read_toml(REPO_ROOT / 'pyproject.toml')['project']['dependencies']
    names = set()
    for requirement in declared:
        bare = requirement.split('[')[0].split('>')[0].split('<')[0].split('=')[0].split(';')[0]
        names.add(bare.strip().lower().replace('-', '_'))
    return frozenset(names)


def _imported_roots(source: Path) -> set[str]:
    """Every top-level module name *source* imports, at any depth."""
    tree = ast.parse(source.read_text(encoding='utf-8'))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split('.')[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split('.')[0])
    return roots


def _declared_verbs(source: Path, class_name: str) -> frozenset[str]:
    """Every PUBLIC method name declared directly in *class_name*'s body, read from the source.

    READ FROM THE SOURCE AND NOT OFF THE CLASS, which is the whole point of this file's method:
    ``isinstance`` against the Protocol asks "is every verb present" and answers it only for an
    object the box could IMPORT, while the count and the extras -- a verb one adapter grew and the
    other did not, a method neither declared -- need the DECLARATION. It also keeps this check
    runnable on a box where neither plotting library is installed, which is where a parity claim
    that quietly held for one backend would otherwise never be read.
    """
    tree = ast.parse(source.read_text(encoding='utf-8'))
    classes = [node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name]
    assert classes, f'{source} declares no class {class_name}'
    return frozenset(
        child.name
        for child in classes[0].body
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and not child.name.startswith('_')
    )


def _declared_keywords(source: Path, class_name: str, method: str) -> tuple[str, ...]:
    """The KEYWORD-ONLY parameter names of one method declaration, in the order it spells them.

    READ FROM THE SOURCE for the reason :func:`_declared_verbs` gives, and keyword-only because
    that is how this vocabulary states a configuration surface: ``frame(rect=..., sharex=...,
    sharey=...)`` has no positional spelling, so the names ARE the call sites' contract.
    """
    tree = ast.parse(source.read_text(encoding='utf-8'))
    classes = [node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name]
    assert classes, f'{source} declares no class {class_name}'
    methods = [child for child in classes[0].body if isinstance(child, ast.FunctionDef) and child.name == method]
    assert len(methods) == 1, f'{class_name} declares no single {method}'
    return tuple(argument.arg for argument in methods[0].args.kwonlyargs)


def _extras() -> dict[str, frozenset[str]]:
    """Each declared extra and the distributions it names, by bare name."""
    table = read_toml(REPO_ROOT / 'pyproject.toml')['project']['optional-dependencies']
    return {
        extra: frozenset(
            spec.split('[')[0].split('>')[0].split('<')[0].split('=')[0].split(';')[0].strip().lower().replace('-', '_')
            for spec in requirements
        )
        for extra, requirements in table.items()
    }


class TestTheVizOptIn:
    def test_importing_lab_commons_does_not_pull_the_viz_tier_or_a_plotting_library(self) -> None:
        """A solver batch must not acquire a plotting library by importing the package.

        A FRESH INTERPRETER, because ``sys.modules`` in this process already holds the adapters
        (these tests imported them) and asking it whether they were pulled in would answer yes
        whatever the real import graph said. ``-c`` inherits the environment, so the child resolves
        ``lab_commons`` exactly as the parent did.
        """
        probe = (
            'import sys, lab_commons; '
            'print("lab_commons.viz" in sys.modules, "matplotlib" in sys.modules, "bokeh" in sys.modules)'
        )
        result = subprocess.run(
            [sys.executable, '-c', probe],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            check=True,
        )
        assert result.stdout.strip() == 'False False False', 'importing lab_commons pulled the viz tier in'

    def test_the_vocabulary_module_reaches_no_plotting_library(self) -> None:
        """The contract half is usable on a box that has neither backend installed.

        EVERY module of the vocabulary, not just the package's own surface: the placement rules are
        the other half of what a producer depends on, and a plotting import that arrived there would
        be outside the file this check used to read.
        """
        allowed = _declared_requirements() | set(sys.stdlib_module_names) | {'lab_commons'}
        offenders = {
            name: sorted(_imported_roots(VIZ_ROOT / name) - allowed)
            for name in VOCABULARY
            if _imported_roots(VIZ_ROOT / name) - allowed
        }
        assert not offenders, f'the vocabulary imports a plotting library: {offenders}'

    def test_each_adapter_imports_only_the_library_its_own_extra_names(self) -> None:
        """THE EXTRA IS THE GATE, so it has to be the one whose library this module actually uses.

        Both halves are read: an adapter importing something outside stdlib, tier 1 and its own
        library is refused, and so is an adapter importing the OTHER backend -- a peer relationship
        where either adapter worked only when both extras were installed is not a peer relationship.
        The library's own distribution is read through :data:`_PROVIDED`, so a module matplotlib
        SHIPS (``mpl_toolkits``) counts as matplotlib and nothing else can slip in under that name.
        """
        base = _declared_requirements() | set(sys.stdlib_module_names) | {'lab_commons'}
        problems: dict[str, list[str]] = {}
        for filename, library in BACKENDS.items():
            allowed = base | _PROVIDED.get(library, frozenset({library}))
            offenders = sorted(_imported_roots(VIZ_ROOT / filename) - allowed)
            if offenders:
                problems[filename] = offenders
        assert not problems, f'an adapter reaches beyond its own extra: {problems}'

    def test_the_import_map_names_modules_their_distribution_really_provides(self) -> None:
        """THE DECLARATION MEASURED WHERE THE DISTRIBUTION IS INSTALLED, and silent where it is not.

        :data:`_PROVIDED` widens the allow-list for one module name, which is exactly the shape of a
        waiver: it is here so that ``mpl_toolkits`` counts as matplotlib, and it would go on saying
        that after a future matplotlib stopped shipping the toolkit. This arm reads the
        distribution's OWN file list, so the widening is a measurement where the extra is installed
        -- and on a box without it there is nothing to measure, which is why the absent case passes
        rather than skips: the extra is an opt-in and its absence is not a defect of this tier.
        """
        for distribution, modules in _PROVIDED.items():
            try:
                installed = distribution_files(distribution)
            except PackageNotFoundError:
                continue
            # THE TOP-LEVEL NAME OF EVERY FILE THE DISTRIBUTION INSTALLS, which is what an import
            # statement resolves against -- ``matplotlib/__init__.py`` and ``mpl_toolkits/...`` are
            # two roots of ONE distribution, and the ``.dist-info`` rows carry the same shape.
            roots = {path.parts[0] for path in installed or () if len(path.parts) > 1}
            assert modules <= roots, f'{distribution} does not provide {sorted(modules - roots)}'

    def test_the_two_extras_are_equal_peers(self) -> None:
        """Each backend is one extra, and neither pulls the other's library in."""
        declared = _extras()
        assert {'viz-mpl', 'viz-bokeh'} <= set(declared), f'the viz extras are not declared: {sorted(declared)}'
        assert declared['viz-mpl'] == {'matplotlib'}, 'the matplotlib extra names something else'
        assert declared['viz-bokeh'] == {'bokeh'}, 'the bokeh extra names something else'

    def test_every_implementation_declares_exactly_its_protocols_verbs(self) -> None:
        """THE NAMED SET, BOTH WAYS: an equality for EACH contract, not the coverage isinstance gives.

        ``isinstance`` answers "every protocol member is present" for the objects this box can
        import, and it is the weaker half: an adapter carrying a verb the others LACK passes it, and
        so does an adapter that grew a method the protocol never declared -- which is how a peer
        relationship quietly stops being one. The equality names which verb moved, and a verb added
        to either protocol reds here until ALL implementations of that contract carry it, on a box
        where neither plotting library is installed.

        THE TABLE SAYS WHICH MODULE DECLARES EACH PROTOCOL, because they are no longer all in the
        vocabulary module: the 3D frame's contract lives in ``_three_d.py`` beside the shape only it
        draws, and a check that read ``__init__.py`` would have convicted that move as a missing
        class rather than measured it.
        """
        for protocol, declaring, _, defaults in PROTOCOLS:
            declared = _declared_verbs(VIZ_ROOT / declaring, protocol)
            assert len(declared) >= len(defaults), f'a floor: {protocol} declares nothing is not a tier'
            assert len(declared) >= _VERB_FLOORS[protocol], (
                f'a floor: {len(declared)} verbs is not the {protocol} this tier ships'
            )
            for module, class_name in defaults:
                names = _declared_verbs(VIZ_ROOT / module, class_name)
                assert names == declared, (
                    f'{class_name} is missing {sorted(declared - names)} and adds {sorted(names - declared)}'
                )

    def test_the_canvas_verbs_take_the_same_keywords_everywhere(self) -> None:
        """``frame(...)`` AND ``frame_3d(...)`` ARE CALLED BY NAME, so their KEYWORDS are the contract.

        ``isinstance`` cannot see a spelling: a canvas that named ``share_x`` where the others name
        ``sharex`` satisfies every protocol and raises at the first producer that spells it the way
        the documentation does. The 3D verb takes a rect and nothing else -- a shared axis and a twin
        are relationships between two PLANE coordinate systems -- and this is where that asymmetry is
        a declared one rather than a drift.
        """
        for verb, expected in (('frame', {'rect', 'projection', 'sharex', 'sharey'}), ('frame_3d', {'rect'})):
            shared: tuple[str, ...] | None = None
            for module, class_name in (('__init__.py', 'Figure'), *PROTOCOLS[0][3]):
                keywords = _declared_keywords(VIZ_ROOT / module, class_name, verb)
                assert keywords, f'{class_name}.{verb} declares no keyword arguments'
                if shared is None:
                    shared = keywords
                    assert set(shared) == expected, f'{verb} is spelled {shared}, not {sorted(expected)}'
                assert keywords == shared, f'{class_name}.{verb} takes {keywords}, not {shared}'

    def test_no_plotting_library_is_a_runtime_dependency(self) -> None:
        """A consumer inherits every entry of the base list, so a backend may not be one."""
        base = _declared_requirements()
        assert not base & {'matplotlib', 'bokeh'}, 'a plotting library became an inherited dependency'

    def test_every_declared_name_resolves_in_a_fresh_interpreter(self) -> None:
        """``__all__`` is the contract, and this is the one reading that makes it checkable.

        A star import binds every declared name, so a declaration naming something the module does
        not define raises HERE -- in a fresh interpreter, from the published surface, rather than in
        a consumer's ``from lab_commons.viz import *``.
        """
        probe = (
            'from lab_commons.viz import *\n'
            'print(",".join(sorted(name for name in globals() if not name.startswith("_"))))'
        )
        result = subprocess.run(
            [sys.executable, '-c', probe],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            check=True,
        )
        bound = frozenset(result.stdout.strip().split(','))
        assert bound == frozenset(viz.__all__), 'the surface a star import delivers is not the declared one'

    def test_the_scan_has_a_floor(self) -> None:
        """A scan that read no file would pass every assertion above, vacuously.

        A NAMED SET AND NOT A COUNT, for the reason the two maps above give: the question is which
        files the checks above actually read, and a module added to this tier has to be named here
        before any of them covers it -- which is what happened when the bokeh translation tables
        left the adapter for a module of their own, again when each adapter's frame half left its
        canvas half, again when the placement rules left the vocabulary module, and again when the
        3D protocol and the one shape only it draws left for ``_three_d.py``.
        """
        sources = sorted(VIZ_ROOT.glob('*.py'))
        assert {source.name for source in sources} == {
            '__init__.py',
            '_bokeh_glyphs.py',
            '_bokeh_names.py',
            '_placement.py',
            '_three_d.py',
            'bokeh.py',
            'bokeh_frame.py',
            'mpl.py',
            'mpl_frame.py',
            'mpl_frame_3d.py',
        }
