"""ENV-IS-READ-ONCE: every environment read is the declared entry's, on the pending ledger, or refused.

Each reader carries planted controls (the shapes it must convict and the similar shapes it must pass); the ledger is
judged on both sides (an unrecorded read reds, a pending path with no read left reds); strict mode drops the test
exemption; and the pre-push half refuses a pending list that GREW since the merge-base.
"""

from __future__ import annotations

import shutil
import subprocess
from typing import TYPE_CHECKING

import pytest

from dev_lab.dev import envreads
from dev_lab.dev.envreads import EnvPolicy

if TYPE_CHECKING:
    from pathlib import Path

_GIT = shutil.which('git') or 'git'


def _write(root: Path, rel: str, text: str = '') -> None:
    (root / rel).parent.mkdir(parents=True, exist_ok=True)
    (root / rel).write_text(text, encoding='utf-8')


def _git(root: Path, *args: str) -> str:
    done = subprocess.run([_GIT, '-C', str(root), *args], check=True, capture_output=True, text=True)
    return done.stdout.strip()


def _repo(root: Path) -> None:
    _git(root, 'init', '-q', '-b', 'main')
    _git(root, 'config', 'user.email', 'test@example.invalid')
    _git(root, 'config', 'user.name', 'test')
    _git(root, 'config', 'commit.gpgsign', 'false')


def _commit(root: Path, message: str) -> str:
    _git(root, 'add', '-A')
    _git(root, '-c', 'core.hooksPath=/dev/null', 'commit', '-q', '-m', message)
    return _git(root, 'rev-parse', 'HEAD')


def _manifest(entry: tuple[str, ...] = (), pending: tuple[str, ...] = (), *, strict: bool = False) -> str:
    def listed(paths: tuple[str, ...]) -> str:
        return '[' + ', '.join(f'"{p}"' for p in paths) + ']'

    flag = 'true' if strict else 'false'
    return f'[tool.dev_lab.env]\nentry = {listed(entry)}\npending = {listed(pending)}\nstrict = {flag}\n'


# -- the Python reader ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    'source',
    [
        "import os\nx = os.environ['HOME']\n",
        "import os\nx = os.environ.get('HOME')\n",
        "import os\nx = os.getenv('HOME')\n",
        "import os\nos.putenv('A', '1')\n",
        "import os\nos.environ['A'] = '1'\n",
        'import os\nchild = dict(os.environ)\n',
        "import os\nx = os.environb[b'HOME']\n",
        "import os as _os\nx = _os.environ.get('HOME')\n",
        "from os import environ\nx = environ['HOME']\n",
        "from os import getenv as read\nx = read('HOME')\n",
        "def f():\n    import os\n    return os.getenv('A')\n",
    ],
)
def test_a_planted_python_read_is_convicted(source: str) -> None:
    """PLANTED CONTROL: each spelling of an environment read through ``os`` is one finding."""
    assert envreads.python_reads(source) != ()


@pytest.mark.parametrize(
    'source',
    [
        "env = {'A': '1'}\nsubprocess.run(['x'], env=env)\n",
        "x = self.environ['A']\n",
        "x = config.getenv('A')\n",
        '"""os.environ is named in prose only."""\n',
        "import os\nx = os.path.join('a', 'b')\n",
    ],
)
def test_a_python_look_alike_passes(source: str) -> None:
    """An explicit child env, another object's ``environ``/``getenv``, prose and other ``os`` calls are not reads."""
    assert envreads.python_reads(source) == ()


def test_the_python_reader_names_each_line() -> None:
    source = "import os\na = os.getenv('A')\nb = 1\nc = os.environ['C']\n"
    assert envreads.python_reads(source) == (2, 4)


# -- the Rust reader -----------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    'source',
    [
        'let x = std::env::var("HOME");\n',
        'let x = env::var_os("HOME");\n',
        'for (k, v) in std::env::vars() {}\n',
        'unsafe { env::set_var("A", "1") };\n',
        'env::remove_var("A");\n',
    ],
)
def test_a_planted_rust_read_is_convicted(source: str) -> None:
    """PLANTED CONTROL: each runtime ``std::env`` read or write is one finding."""
    assert envreads.rust_reads(source) != ()


@pytest.mark.parametrize(
    'source',
    ['// std::env::var("HOME") in a comment\n', '/// env::var documented\n', 'let dir = env::current_dir();\n'],
)
def test_a_rust_look_alike_passes(source: str) -> None:
    assert envreads.rust_reads(source) == ()


# -- the declaration -----------------------------------------------------------------------------------------------


def test_an_undeclared_table_is_the_empty_policy_and_a_malformed_one_is_refused(tmp_path: Path) -> None:
    assert envreads.declared_env(tmp_path) == EnvPolicy()
    _write(tmp_path, 'pyproject.toml', '[project]\nname = "x"\n')
    assert envreads.declared_env(tmp_path) == EnvPolicy()
    _write(tmp_path, 'pyproject.toml', '[tool.dev_lab.env]\nentry = "src/a.py"\n')
    with pytest.raises(ValueError, match='entry'):
        envreads.declared_env(tmp_path)
    _write(tmp_path, 'pyproject.toml', '[tool.dev_lab.env]\npending = [1]\n')
    with pytest.raises(ValueError, match='pending'):
        envreads.declared_env(tmp_path)
    _write(tmp_path, 'pyproject.toml', '[tool.dev_lab.env]\nstrict = "yes"\n')
    with pytest.raises(ValueError, match='strict'):
        envreads.declared_env(tmp_path)
    _write(tmp_path, 'pyproject.toml', '[tool.dev_lab.env]\nlegacy = []\n')
    with pytest.raises(ValueError, match='legacy'):
        envreads.declared_env(tmp_path)
    _write(tmp_path, 'pyproject.toml', _manifest(('src/e.py',), ('src/p.py',), strict=True))
    assert envreads.declared_env(tmp_path) == EnvPolicy(('src/e.py',), ('src/p.py',), strict=True)


# -- the ledger, both sides ----------------------------------------------------------------------------------------

_READ = "import os\nx = os.getenv('A')\n"
_CLEAN = 'x = 1\n'


def _problems(root: Path, policy: EnvPolicy, files: dict[str, str]) -> list[str]:
    for rel, text in files.items():
        _write(root, rel, text)
    return envreads.problems(root, policy, files)


def test_an_unrecorded_read_is_refused_naming_its_line_and_the_door(tmp_path: Path) -> None:
    found = _problems(tmp_path, EnvPolicy(), {'src/pkg/a.py': _READ})
    assert len(found) == 1
    assert 'src/pkg/a.py:2' in found[0]
    assert envreads.RULE_ID in found[0]


def test_the_entry_and_a_pending_path_may_read(tmp_path: Path) -> None:
    policy = EnvPolicy(entry=('src/pkg/host.py',), pending=('src/pkg/old.py',))
    assert _problems(tmp_path, policy, {'src/pkg/host.py': _READ, 'src/pkg/old.py': _READ}) == []


def test_a_pending_path_with_no_read_left_is_stale(tmp_path: Path) -> None:
    """The other side of the ratchet: a migrated file leaves the ledger in the same change."""
    found = _problems(tmp_path, EnvPolicy(pending=('src/pkg/old.py',)), {'src/pkg/old.py': _CLEAN})
    assert len(found) == 1
    assert 'stale' in found[0]
    found = _problems(tmp_path, EnvPolicy(pending=('src/pkg/gone.py',)), {})
    assert len(found) == 1
    assert 'stale' in found[0]


def test_an_entry_that_is_not_a_file_is_a_declaration_that_lies(tmp_path: Path) -> None:
    found = _problems(tmp_path, EnvPolicy(entry=('src/pkg/host.py',)), {})
    assert len(found) == 1
    assert 'entry' in found[0]


def test_a_path_both_entry_and_pending_is_refused(tmp_path: Path) -> None:
    found = _problems(tmp_path, EnvPolicy(entry=('src/a.py',), pending=('src/a.py',)), {'src/a.py': _READ})
    assert any('both' in problem for problem in found)


@pytest.mark.parametrize(
    'rel', ['tests/test_a.py', 'tests/conftest.py', 'pkg/tests/helpers.py', 'conftest.py', 'test_x.py', 'src/a_test.py']
)
def test_a_test_file_is_exempt_only_outside_strict_mode(tmp_path: Path, rel: str) -> None:
    """C-class reads become pytest options: strict mode (opt-in) refuses them like any other."""
    assert _problems(tmp_path, EnvPolicy(), {rel: _READ}) == []
    assert len(_problems(tmp_path, EnvPolicy(strict=True), {rel: _READ})) == 1


def test_a_rust_read_is_refused_and_other_suffixes_are_not_read(tmp_path: Path) -> None:
    files = {'rust/crates/a/src/lib.rs': 'fn f() { std::env::var("A"); }\n', 'docs/x.md': 'os.getenv("A")\n'}
    found = _problems(tmp_path, EnvPolicy(), files)
    assert len(found) == 1
    assert 'lib.rs:1' in found[0]


def test_census_lists_every_unrecorded_reader_as_a_pending_block(tmp_path: Path) -> None:
    policy = EnvPolicy(entry=('src/host.py',))
    for rel in ('src/host.py', 'src/b.py', 'src/a.py', 'tests/test_x.py'):
        _write(tmp_path, rel, _READ)
    _write(tmp_path, 'src/clean.py', _CLEAN)
    files = ('src/host.py', 'src/b.py', 'src/a.py', 'tests/test_x.py', 'src/clean.py')
    assert envreads.census(tmp_path, policy, files) == ('src/a.py', 'src/b.py')


# -- the always-on family check ------------------------------------------------------------------------------------


def test_the_check_applies_where_a_source_tree_exists(tmp_path: Path) -> None:
    """PLANTED CONTROL: a checkout with no source tree has no population; each source tree brings the check."""
    assert not envreads.applies(tmp_path)
    for tree in envreads.SOURCE_TREES:
        (tmp_path / tree).mkdir()
        assert envreads.applies(tmp_path)
        (tmp_path / tree).rmdir()


def test_check_reads_the_tracked_tree_with_a_floor(tmp_path: Path) -> None:
    _repo(tmp_path)
    _write(tmp_path, 'pyproject.toml', _manifest())
    _write(tmp_path, 'README.md', 'x\n')
    _commit(tmp_path, 'init')
    with pytest.raises(AssertionError, match='EMPTY'):
        envreads.check(tmp_path)
    _write(tmp_path, 'src/pkg/a.py', _READ)
    _git(tmp_path, 'add', '-A')
    with pytest.raises(AssertionError, match=r'ENV-IS-READ-ONCE.*src/pkg/a\.py:2'):
        envreads.check(tmp_path)
    _write(tmp_path, 'pyproject.toml', _manifest(pending=('src/pkg/a.py',)))
    envreads.check(tmp_path)


# -- the pre-push half: the pending list only shrinks --------------------------------------------------------------


def test_a_pending_list_that_grew_since_the_base_is_refused_and_a_shrink_passes(tmp_path: Path) -> None:
    _repo(tmp_path)
    _write(tmp_path, 'pyproject.toml', _manifest(pending=('src/a.py', 'src/b.py')))
    base = _commit(tmp_path, 'base')
    _write(tmp_path, 'pyproject.toml', _manifest(pending=('src/a.py',)))
    shrunk = _commit(tmp_path, 'shrink')
    assert envreads.range_problems(tmp_path, base, shrunk) == []
    _write(tmp_path, 'pyproject.toml', _manifest(pending=('src/a.py', 'src/c.py')))
    grown = _commit(tmp_path, 'grow')
    found = envreads.range_problems(tmp_path, base, grown)
    assert len(found) == 1
    assert 'src/c.py' in found[0]
    assert 'only shrinks' in found[0]


def test_a_base_with_no_table_lets_the_first_census_land(tmp_path: Path) -> None:
    """Adoption: the first declaration records the census; every later push may only shrink it."""
    _repo(tmp_path)
    _write(tmp_path, 'pyproject.toml', '[project]\nname = "x"\n')
    base = _commit(tmp_path, 'base')
    _write(tmp_path, 'pyproject.toml', _manifest(pending=('src/a.py',)))
    adopted = _commit(tmp_path, 'adopt')
    assert envreads.range_problems(tmp_path, base, adopted) == []


def test_the_cli_range_and_census(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _repo(tmp_path)
    _write(tmp_path, 'pyproject.toml', _manifest(pending=('src/a.py',)))
    _write(tmp_path, 'src/a.py', _READ)
    _write(tmp_path, 'src/b.py', _READ)
    base = _commit(tmp_path, 'base')
    assert envreads.main(['range', base, base], cwd=tmp_path) == 0
    assert envreads.main(['census'], cwd=tmp_path) == 0
    out = capsys.readouterr().out
    assert 'pending = [\n    "src/a.py",\n    "src/b.py",\n]' in out, 'the census is the whole list, pasteable'
    assert envreads.main(['check'], cwd=tmp_path) == 1
    assert envreads.main(['--bogus'], cwd=tmp_path) == envreads.USAGE


# -- class C: an environment read that decides whether a test runs ------------------------------------------------


_OS_PYTEST = 'import os\nimport pytest\n'


@pytest.mark.parametrize(
    'body',
    [
        "@pytest.mark.skipif(not os.getenv('LIVE'), reason='x')\ndef test_a(): ...\n",
        "LIVE = os.environ.get('LIVE') == '1'\npytestmark = pytest.mark.skipif(not LIVE, reason='x')\n",
        "def test_a():\n    if not os.environ.get('FEMM_DIR'):\n        pytest.skip('x')\n",
        "def test_a():\n    if 'LIVE' in os.environ:\n        run()\n    else:\n        pytest.skip('x')\n",
        "@pytest.mark.xfail(condition=os.getenv('X') is None, reason='x')\ndef test_a(): ...\n",
        "def mark():\n    return pytest.mark.skipif(True, reason='x') if os.getenv('L') != '1' else None\n",
        "from os import environ\nif environ.get('LIVE') != '1':\n    pytest.skip('x', allow_module_level=True)\n",
    ],
)
def test_a_planted_test_switch_is_convicted(body: str) -> None:
    """PLANTED CONTROL: a read deciding a skip or an xfail -- directly or through a name it binds -- is a switch."""
    assert envreads.python_switches(_OS_PYTEST + body) != ()


@pytest.mark.parametrize(
    'body',
    [
        "from pathlib import Path\ntmp = os.environ['TMP']\nout = Path(tmp) / 'x'\n",
        "import subprocess\nenv = {**os.environ, 'A': '1'}\nsubprocess.run(['x'], env=env)\n",
        "@pytest.mark.skipif(sys.platform != 'win32', reason=os.environ.get('W', 'x'))\ndef test_a(): ...\n",
        "from pathlib import Path\nif path := os.environ.get('FAKE_OUT'):\n    Path(path).write_text('x')\n",
        "TMP = os.environ['TMP']\n@pytest.mark.skipif(sys.platform != 'win32', reason='x')\ndef test_a(): ...\n",
        "done = run(['x'], env={**os.environ, 'A': '1'})\nif done.returncode:\n    pytest.xfail('x')\n",
    ],
)
def test_a_read_deciding_no_skip_is_not_a_switch(body: str) -> None:
    """A fact, a child env (its RESULT deciding an xfail), a skip REASON, a fake's input, another condition pass."""
    assert envreads.python_switches(_OS_PYTEST + body) == ()


_SWITCH = "import os\nimport pytest\nif not os.getenv('LIVE'):\n    pytest.skip('x', allow_module_level=True)\n"
_FACT = "import os\nTMP = os.environ['TMP']\n"


@pytest.mark.parametrize('rel', ['tests/test_a.py', 'tests/conftest.py', 'conftest.py'])
@pytest.mark.parametrize('strict', [False, True])
def test_a_test_switch_is_refused_in_every_mode_naming_its_door(tmp_path: Path, rel: str, *, strict: bool) -> None:
    """Class C has no test exemption: the refusal names the line and the door, once (never also as a plain read)."""
    found = _problems(tmp_path, EnvPolicy(strict=strict), {rel: _SWITCH})
    assert len(found) == 1
    assert f'{rel}:3' in found[0]
    assert 'pytest option' in found[0]
    assert 'resource need' in found[0]


def test_a_switch_in_src_is_not_judged_as_a_test_switch(tmp_path: Path) -> None:
    """Outside test code the read is an ordinary one (class A there): one finding, the general one."""
    found = _problems(tmp_path, EnvPolicy(), {'src/pkg/a.py': _SWITCH})
    assert len(found) == 1
    assert 'pytest option' not in found[0]


def test_an_entry_cannot_launder_a_test_switch_but_the_pending_ledger_records_it(tmp_path: Path) -> None:
    files = {'tests/conftest.py': _SWITCH}
    assert len(_problems(tmp_path, EnvPolicy(entry=('tests/conftest.py',), strict=True), files)) == 1
    assert _problems(tmp_path, EnvPolicy(pending=('tests/conftest.py',)), files) == []
    assert _problems(tmp_path, EnvPolicy(pending=('tests/conftest.py',), strict=True), files) == []


def test_a_test_fact_is_allowed_only_when_declared(tmp_path: Path) -> None:
    """PLANTED CONTROL, strict: an OS-set temp dir read in test code reds undeclared, passes as entry or pending."""
    files = {'tests/conftest.py': _FACT}
    found = _problems(tmp_path, EnvPolicy(strict=True), files)
    assert len(found) == 1
    assert 'tests/conftest.py:2' in found[0]
    assert 'pytest option' not in found[0], 'a fact is not a switch: its door is the declaration'
    assert _problems(tmp_path, EnvPolicy(entry=('tests/conftest.py',), strict=True), files) == []
    assert _problems(tmp_path, EnvPolicy(pending=('tests/conftest.py',), strict=True), files) == []


def test_a_pending_test_switch_is_not_stale_and_the_census_records_it(tmp_path: Path) -> None:
    """Outside strict mode a test file is judged for switches only: on the ledger it is a live read, not stale."""
    assert _problems(tmp_path, EnvPolicy(pending=('tests/test_a.py',)), {'tests/test_a.py': _SWITCH}) == []
    _write(tmp_path, 'tests/test_b.py', _FACT)
    _write(tmp_path, 'tests/test_a.py', _SWITCH)
    files = ('tests/test_a.py', 'tests/test_b.py')
    assert envreads.census(tmp_path, EnvPolicy(), files) == ('tests/test_a.py',)
