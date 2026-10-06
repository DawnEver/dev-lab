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
from pathlib import Path

from lab_commons import viz
from lab_commons.file_io import read_toml

REPO_ROOT = Path(__file__).resolve().parents[1]
VIZ_ROOT = REPO_ROOT / 'src' / 'lab_commons' / 'viz'

#: The extra that gates each adapter, and the ONE distribution that adapter may import beyond the
#: base runtime set. NAMED, so an extra renamed in ``pyproject.toml`` reds here rather than being
#: discovered by a consumer whose install stopped delivering an import.
BACKENDS: dict[str, str] = {'mpl.py': 'matplotlib', 'bokeh.py': 'bokeh'}


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
        """The contract half is usable on a box that has neither backend installed."""
        allowed = _declared_requirements() | set(sys.stdlib_module_names) | {'lab_commons'}
        offenders = sorted(_imported_roots(VIZ_ROOT / '__init__.py') - allowed)
        assert not offenders, f'the vocabulary imports a plotting library: {offenders}'

    def test_each_adapter_imports_only_the_library_its_own_extra_names(self) -> None:
        """THE EXTRA IS THE GATE, so it has to be the one whose library this module actually uses.

        Both halves are read: an adapter importing something outside stdlib, tier 1 and its own
        library is refused, and so is an adapter importing the OTHER backend -- a peer relationship
        where either adapter worked only when both extras were installed is not a peer relationship.
        """
        base = _declared_requirements() | set(sys.stdlib_module_names) | {'lab_commons'}
        problems: dict[str, list[str]] = {}
        for filename, library in BACKENDS.items():
            allowed = base | {library}
            offenders = sorted(_imported_roots(VIZ_ROOT / filename) - allowed)
            if offenders:
                problems[filename] = offenders
        assert not problems, f'an adapter reaches beyond its own extra: {problems}'

    def test_the_two_extras_are_equal_peers(self) -> None:
        """Each backend is one extra, and neither pulls the other's library in."""
        declared = _extras()
        assert {'viz-mpl', 'viz-bokeh'} <= set(declared), f'the viz extras are not declared: {sorted(declared)}'
        assert declared['viz-mpl'] == {'matplotlib'}, 'the matplotlib extra names something else'
        assert declared['viz-bokeh'] == {'bokeh'}, 'the bokeh extra names something else'

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
        """A scan that read no file would pass every assertion above, vacuously."""
        sources = sorted(VIZ_ROOT.glob('*.py'))
        assert {source.name for source in sources} == {'__init__.py', 'mpl.py', 'bokeh.py'}
