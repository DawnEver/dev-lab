"""``lab_commons.dev`` — the OPT-IN gate, and the absence of a new dependency.

Two properties, and both are the kind that decay silently: that importing ``lab_commons`` never
pulls this subpackage in (the same discipline that keeps ``lab_commons.em`` optional), and that
nothing here needs a package the library did not already declare. Both are asserted against the
REAL artifacts -- a fresh interpreter for the first, the parsed ``pyproject.toml`` and the actual
import statements for the second -- rather than against a restatement of them.
"""

import ast
import subprocess
import sys
from pathlib import Path

from lab_commons.file_io import read_toml

REPO_ROOT = Path(__file__).resolve().parents[1]
DEV_ROOT = REPO_ROOT / 'src' / 'lab_commons' / 'dev'


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


class TestTheOptInGate:
    def test_importing_lab_commons_does_not_pull_the_dev_layer(self) -> None:
        """A runtime consumer must not acquire a development system by importing the package.

        A FRESH INTERPRETER, because ``sys.modules`` in this process already holds the subpackage
        (these tests imported it) and asking it whether it was pulled in would answer yes whatever
        the real import graph said. ``-c`` inherits the environment, so the child resolves
        ``lab_commons`` exactly as the parent did.
        """
        probe = 'import sys, lab_commons; print("lab_commons.dev" in sys.modules)'
        result = subprocess.run(
            [sys.executable, '-c', probe],
            capture_output=True,
            text=True,
            check=True,
        )
        assert result.stdout.strip() == 'False', 'importing lab_commons pulled lab_commons.dev in'

    def test_the_dev_extra_exists_and_names_the_tools_this_layer_drives(self) -> None:
        """The extra IS the gate, so it has to be the one whose contents this layer actually uses."""
        extras = read_toml(REPO_ROOT / 'pyproject.toml')['project']['optional-dependencies']
        assert 'dev' in extras
        named = {requirement.split('>')[0].split('=')[0].strip().lower() for requirement in extras['dev']}
        assert {'pytest', 'ruff'} <= named

    def test_no_dev_module_imports_anything_outside_stdlib_and_tier_one(self) -> None:
        """THE DEPENDENCY IS NOT ADDED, and the way to say so is to read the import statements.

        A ``pip install lab-commons`` must keep pulling exactly what it pulled before -- the
        library's own pyproject states that posture in its own words ("a consumer that wants only
        logging installs nothing heavier than this"). So every import this layer needs has to be
        stdlib, ``lab_commons`` itself, or something ``[project] dependencies`` already names.

        Read from the SOURCE rather than by importing, because a module that imported cleanly today
        would import cleanly tomorrow off a dependency another layer happened to install -- and the
        question is what this layer DECLARES, not what this box happens to have.
        """
        allowed = _declared_requirements() | set(sys.stdlib_module_names) | {'lab_commons'}
        offenders = {
            source.name: sorted(_imported_roots(source) - allowed)
            for source in sorted(DEV_ROOT.glob('*.py'))
            if _imported_roots(source) - allowed
        }
        assert not offenders, f'dev modules reach beyond stdlib + tier 1: {offenders}'

    def test_the_scan_has_a_floor(self) -> None:
        """A scan that read no file would pass every one of the assertions above, vacuously."""
        sources = sorted(DEV_ROOT.glob('*.py'))
        assert len(sources) >= 6
        assert {'content.py', 'verdict.py', 'boxlock.py', 'profile.py'} <= {source.name for source in sources}
