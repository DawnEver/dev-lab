"""The controls for :mod:`dev_lab.dev.famtests.alwayson` -- the family rows no repo can drop.

Planted, both directions, through a REAL pytest session over a REAL git repo: a tracked CJK file is
refused, a clean tree passes, and a session outside a git checkout gets no item at all. No CJK
character is written into this file; the planted one is built with :func:`chr` from the shared ranges.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from dev_lab import pytest_family
from dev_lab.dev import cjk, rules
from dev_lab.dev.famtests import alwayson

pytest_plugins = ['pytester']

_CHAR = chr(cjk.CJK_RANGES[2][0])
_ROOT = Path(__file__).resolve().parents[1]
_GIT = shutil.which('git') or 'git'


def _git_repo(root: Path, files: dict[str, str]) -> None:
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
    subprocess.run([_GIT, 'init', '-q'], cwd=root, check=True, timeout=60)
    subprocess.run([_GIT, 'add', '--', *files], cwd=root, check=True, timeout=60)


def _run(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, *args: str) -> pytest.RunResult:
    # Autoload off, so the plugin is the module under test rather than whatever dev-lab is installed.
    monkeypatch.setenv('PYTEST_DISABLE_PLUGIN_AUTOLOAD', '1')
    return pytester.runpytest_subprocess('-p', pytest_family.__name__, *args, '-q', '-rA', timeout=300)


def test_a_tracked_cjk_file_is_refused(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> None:
    """THE PLANTED CONTROL: a repo with no CJK test of its own still reds on a tracked CJK file."""
    _git_repo(pytester.path, {'dirty.md': f'ahead {_CHAR}\n', 'test_x.py': 'def test_x():\n    pass\n'})
    result = _run(pytester, monkeypatch)
    result.assert_outcomes(passed=2, failed=1)
    result.stdout.fnmatch_lines(['*NO-CJK-IN-TRACKED-SOURCE*', '*dirty.md*'])


def test_a_clean_tree_passes_and_exemptions_hold(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> None:
    """The other direction: exempt prefixes and a translation beside its source stay exempt."""
    _git_repo(
        pytester.path,
        {
            'clean.md': 'plain\n',
            'page.md': 'english\n',
            'page.zh.md': f'{_CHAR}\n',
            'attic/old.py': f'# {_CHAR}\n',
            'test_x.py': 'def test_x():\n    pass\n',
        },
    )
    _run(pytester, monkeypatch).assert_outcomes(passed=3)


def test_an_orphaned_translation_is_refused(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> None:
    _git_repo(pytester.path, {'lone.zh.md': f'{_CHAR}\n', 'test_x.py': 'def test_x():\n    pass\n'})
    result = _run(pytester, monkeypatch)
    result.assert_outcomes(passed=2, failed=1)
    result.stdout.fnmatch_lines(['*ORPHANED TRANSLATION*lone.zh.md*'])


def test_no_item_outside_a_git_checkout(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> None:
    """A session rooted outside any checkout (a pytester tree) has no tracked corpus to judge."""
    pytester.makepyfile(test_x='def test_x():\n    pass\n')
    _run(pytester, monkeypatch).assert_outcomes(passed=1)


def test_a_declared_tree_that_is_not_a_checkout_gets_no_family_items(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A nested run in a temp project declaring [tool.dev_lab.*] but holding no .git is not judged."""
    pytester.makefile('.toml', pyproject='[tool.dev_lab.parts]\noutput = "out/logs"\n')
    pytester.makepyfile(test_x='def test_x():\n    pass\n')
    result = _run(pytester, monkeypatch)
    result.assert_outcomes(passed=1)
    assert '::family::' not in result.stdout.str()


def test_a_declared_checkout_with_a_broken_git_still_fails_loudly(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The planted negative: a .git that exists but cannot be read keeps every family item, failed."""
    pytester.makefile('.toml', pyproject='[tool.dev_lab.parts]\noutput = "out/logs"\n')
    (pytester.path / '.git').write_text('gitdir: missing/nowhere\n', encoding='utf-8')
    pytester.makepyfile(test_x='def test_x():\n    pass\n')
    result = _run(pytester, monkeypatch)
    result.assert_outcomes(passed=1, failed=len(alwayson.rows()))
    result.stdout.fnmatch_lines(['*git identity*'])


def test_a_family_without_layout_policy_has_not_opted_into_the_layout_guard(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    _git_repo(
        pytester.path,
        {
            'pyproject.toml': '[tool.lab_commons.tests]\nresources = []\n',
            'test_x.py': 'def test_x():\n    pass\n',
        },
    )
    result = _run(pytester, monkeypatch)
    result.assert_outcomes(passed=3)
    assert 'MODULE-SIZE-ALARM' not in result.stdout.str()


@pytest.mark.parametrize(
    'policy',
    [
        'module_limit = 300\n',
        'module_unit = "code"\n',
        'module_unit = "code"\nmodule_limit = true\n',
        'module_unit = "guessed"\nmodule_limit = 300\n',
        'module_unit = "raw"\nmodule_limit = 0\n',
        'module_unit = "code"\nmodule_limit = 300\nignore_tests = true\n',
    ],
)
def test_a_malformed_layout_policy_is_a_failed_runtime_guard(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, policy: str
) -> None:
    _git_repo(
        pytester.path,
        {
            'pyproject.toml': '[tool.lab_commons.tests]\nresources = []\n[tool.dev_lab.layout]\n' + policy,
            'test_x.py': 'def test_x():\n    pass\n',
        },
    )
    result = _run(pytester, monkeypatch)
    result.assert_outcomes(passed=3, failed=1)
    result.stdout.fnmatch_lines(['*layout*'])


@pytest.mark.parametrize('directory', ['src', 'tests', 'scripts'])
def test_the_required_layout_guard_does_not_exempt_tests_or_scripts_from_directory_width(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, directory: str
) -> None:
    files = {
        'pyproject.toml': '[tool.lab_commons.tests]\nresources = []\n'
        '[tool.dev_lab.layout]\nmodule_unit = "code"\nmodule_limit = 300\n',
        'test_x.py': 'def test_x():\n    pass\n',
    }
    files.update({f'{directory}/subject_{number}.py': 'value = 1\n' for number in range(26)})
    _git_repo(pytester.path, files)
    result = _run(pytester, monkeypatch)
    # every other required row passes: a tests/ tree also brings the tree checks (D42)
    result.assert_outcomes(passed=len(alwayson.required_ids(pytester.path)), failed=1)
    result.stdout.fnmatch_lines(['*26*25*'])


@pytest.mark.parametrize(('unit', 'limit'), [('code', 300), ('raw', 600), ('raw', 799)])
def test_valid_explicit_policy_runs_the_required_guard_even_under_a_selected_invocation(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, unit: str, limit: int
) -> None:
    _git_repo(
        pytester.path,
        {
            'pyproject.toml': '[tool.lab_commons.tests]\nresources = []\n'
            f'[tool.dev_lab.layout]\nmodule_unit = "{unit}"\nmodule_limit = {limit}\n',
            'test_x.py': 'def test_x():\n    pass\n',
            'src/one/two/three/four/five/six/subject.py': 'value = 1\n',
        },
    )
    result = _run(pytester, monkeypatch, '-k', 'test_x')
    result.assert_outcomes(passed=4)
    result.stdout.fnmatch_lines(['*family*'])


def test_the_plugin_is_an_entry_point() -> None:
    """Installed is enforced: the plugin rides pytest's own entry-point autoload, not a consumer file."""
    project = tomllib.loads((_ROOT / 'pyproject.toml').read_text(encoding='utf-8'))
    assert project['project']['entry-points']['pytest11'] == {'dev_lab_family': pytest_family.__name__}


def test_an_always_on_rule_cannot_be_waived_or_copied() -> None:
    """No opt-out and no per-repo row: the family plugin is the one mechanism."""
    assert 'NO-CJK-IN-TRACKED-SOURCE' in rules.ALWAYS_ON
    with pytest.raises(ValueError, match='always on'):
        rules.Adoption(app_name='x', declared_absent=frozenset({'NO-CJK-IN-TRACKED-SOURCE'}))
    with pytest.raises(ValueError, match='always on'):
        rules.Adoption(app_name='x', mechanisms={'NO-CJK-IN-TRACKED-SOURCE': (rules.guard('tests/t.py'),)})
    assert 'NO-CJK-IN-TRACKED-SOURCE' not in rules.unadopted(rules.RULES, rules.Adoption(app_name='x'))


def test_the_git_grep_path_finds_a_planted_file_and_skips_exempt_and_binary(tmp_path: Path) -> None:
    """THE PLANTED CONTROL for the fast path: one ``git grep`` names the dirty file and nothing else."""
    _git_repo(
        tmp_path,
        {
            'dirty.py': f'x = 1  # {_CHAR}\n',
            'clean.md': 'plain\n',
            'attic/old.md': f'{_CHAR}\n',
            'deep/.claude/memory/m.md': f'{_CHAR}\n',
            'archived/a.md': f'{_CHAR}\n',
            'x/archived/b.md': f'{_CHAR}\n',
        },
    )
    (tmp_path / 'blob.bin').write_bytes(b'\x00' + _CHAR.encode())
    subprocess.run([_GIT, 'add', 'blob.bin'], cwd=tmp_path, check=True, timeout=60)
    assert alwayson.candidates(tmp_path) == ('deep/.claude/memory/m.md', 'dirty.py', 'x/archived/b.md')


def test_a_memory_file_with_cjk_is_refused_naming_both_doors_d26(tmp_path: Path) -> None:
    """D26: memory and tasks are English only; the refusal names translate-or-declare."""
    _git_repo(tmp_path, {'.claude/memory/m.md': f'{_CHAR}\n', 'attic/a.md': f'{_CHAR}\n'})
    with pytest.raises(AssertionError) as caught:
        alwayson.check_no_cjk(tmp_path)
    text = str(caught.value)
    assert '.claude/memory/m.md' in text
    assert 'attic/a.md' not in text, 'attic stays exempt'
    assert '(user, translated)' in text
    assert '[tool.dev_lab.cjk]' in text


def test_a_declared_file_passes_and_a_cleaned_declaration_is_refused(tmp_path: Path) -> None:
    """The named set is read from ``[tool.dev_lab.cjk] declared``, and it may only shrink."""
    manifest = '[tool.dev_lab.cjk]\ndeclared = [".claude/memory/m.md"]\n'
    _git_repo(tmp_path, {'.claude/memory/m.md': f'{_CHAR}\n', 'pyproject.toml': manifest})
    alwayson.check_no_cjk(tmp_path)
    (tmp_path / '.claude/memory/m.md').write_text('translated to English\n', encoding='utf-8')
    with pytest.raises(AssertionError, match='ORPHANED CJK declaration'):
        alwayson.check_no_cjk(tmp_path)


def test_a_malformed_declaration_is_refused_by_name(tmp_path: Path) -> None:
    _git_repo(tmp_path, {'pyproject.toml': '[tool.dev_lab.cjk]\ndeclared = "one.md"\n', 'a.md': 'x\n'})
    with pytest.raises(AssertionError, match=r'\[tool.dev_lab.cjk\] declared'):
        alwayson.check_no_cjk(tmp_path)


def test_a_zh_json_beside_its_json_passes_and_an_orphan_names_its_source(tmp_path: Path) -> None:
    _git_repo(tmp_path, {'ui.json': '{}\n', 'ui.zh.json': f'"{_CHAR}"\n'})
    alwayson.check_no_cjk(tmp_path)
    _git_repo(tmp_path, {'lone.zh.toml': f'a = "{_CHAR}"\n'})
    with pytest.raises(AssertionError, match=r"ORPHANED TRANSLATION 'lone.zh.toml'.*'lone.toml'"):
        alwayson.check_no_cjk(tmp_path)


def test_the_pattern_is_derived_from_the_shared_ranges() -> None:
    narrowed = ((0x4E00, 0x4E00),)
    assert alwayson.cjk_pattern(narrowed) == r'(*UTF)[\x{4e00}-\x{4e00}]'
    for lo, hi in cjk.CJK_RANGES:
        assert rf'\x{{{lo:04x}}}-\x{{{hi:04x}}}' in alwayson.cjk_pattern()


def test_the_always_on_set_is_registry_data_read_off_the_rule_rows() -> None:
    """Which rules are always on is a field on the registry row; the plugin runs exactly that set."""
    assert frozenset(rule.id for rule in rules.RULES if rule.always_on) == rules.ALWAYS_ON
    assert set(alwayson.rows()) == rules.ALWAYS_ON


def test_the_plugin_imports_nothing_from_dev_lab_at_load() -> None:
    """A ``pytest11`` plugin loads before pytest-cov measures; a module it imports goes unmeasured."""
    code = (
        'import sys, importlib; importlib.import_module("dev_lab.pytest_family"); '
        'print(sorted(m for m in sys.modules if m.startswith("dev_lab.") and m != "dev_lab.pytest_family"))'
    )
    out = subprocess.run([sys.executable, '-c', code], capture_output=True, check=True, timeout=120, encoding='utf-8')
    assert out.stdout.strip() == '[]'


def test_the_required_identity_catalog_matches_actual_collected_items(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    _git_repo(
        pytester.path,
        {
            'pyproject.toml': '[tool.lab_commons.tests]\nresources = []\n'
            '[tool.dev_lab.layout]\nmodule_unit = "code"\nmodule_limit = 300\n',
            'test_x.py': 'def test_x():\n    pass\n',
            'conftest.py': 'import json\nfrom pathlib import Path\n'
            'def pytest_collection_finish(session):\n'
            '    Path("collected.json").write_text(json.dumps([item.nodeid for item in session.items]))\n',
        },
    )
    result = _run(pytester, monkeypatch, '--collect-only')
    assert result.ret == 0
    actual = json.loads((pytester.path / 'collected.json').read_text(encoding='utf-8'))
    required = set(alwayson.required_ids(pytester.path))
    assert required == set(actual) - {'test_x.py::test_x'}
    assert len(required) == len(alwayson.rows()) + 1, 'the declared layout table opts MODULE-SIZE-ALARM in'
    alwayson.assert_required_collected(pytester.path, actual)


def test_outer_collection_proof_refuses_each_missing_identity_and_names_the_door(tmp_path: Path) -> None:
    _git_repo(
        tmp_path,
        {'pyproject.toml': '[tool.dev_lab.layout]\nmodule_unit = "raw"\nmodule_limit = 600\n'},
    )
    required = list(alwayson.required_ids(tmp_path))
    assert required
    for absent in required:
        partial = [node for node in required if node != absent]
        with pytest.raises(ValueError, match='required') as refused:
            alwayson.assert_required_collected(tmp_path, partial)
        assert absent in str(refused.value)
        assert 'plugin' in str(refused.value).lower()


def test_resource_projection_uses_exact_catalog_identity_and_preserves_business_order(tmp_path: Path) -> None:
    _git_repo(
        tmp_path,
        {'pyproject.toml': '[tool.dev_lab.layout]\nmodule_unit = "raw"\nmodule_limit = 600\n'},
    )
    required = list(alwayson.required_ids(tmp_path))
    assert required
    business = ['test_x.py::test_first', 'test_family.py::test_family_identity', 'test_x.py::test_first']
    carrying = [business[0], *required, *business[1:]]
    assert alwayson.resource_nodes(tmp_path, carrying) == business
    assert carrying == [business[0], *required, *business[1:]], 'projection must not mutate the complete manifest'


@pytest.mark.parametrize('git', [False, True])
def test_outer_proof_does_not_advertise_nonfamily_inputs_as_family_qualification(tmp_path: Path, *, git: bool) -> None:
    if git:
        _git_repo(tmp_path, {'README.md': 'An ordinary non-family repository.\n'})
    assert not alwayson.required_ids(tmp_path)
    alwayson.assert_required_collected(tmp_path, [])
    assert alwayson.resource_nodes(tmp_path, ['test_x.py::test_x']) == ['test_x.py::test_x']


@pytest.mark.parametrize('failure', ['timeout', 'io-error', 'git-error'])
@pytest.mark.parametrize('entry', ['catalog', 'proof'])
def test_known_family_git_read_failure_is_not_a_successful_collection_proof(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str, entry: str
) -> None:
    _git_repo(
        tmp_path,
        {'pyproject.toml': '[tool.dev_lab.layout]\nmodule_unit = "code"\nmodule_limit = 300\n'},
    )
    healthy = list(alwayson.required_ids(tmp_path))
    assert healthy

    def unavailable(*_args: object) -> subprocess.CompletedProcess[bytes]:
        if failure == 'timeout':
            command = 'git'
            raise subprocess.TimeoutExpired(command, 60)
        if failure == 'io-error':
            message = 'git cannot be started'
            raise OSError(message)
        return subprocess.CompletedProcess(['git'], 128, stdout=b'', stderr=b'git index cannot be read')

    monkeypatch.setattr(alwayson, '_git', unavailable)
    operation = alwayson.required_ids if entry == 'catalog' else alwayson.assert_required_collected
    arguments = (tmp_path,) if entry == 'catalog' else (tmp_path, healthy)
    with pytest.raises(ValueError, match='git') as refused:
        operation(*arguments)
    assert 'recollect' in str(refused.value).lower()


@pytest.mark.parametrize('failure', ['timeout', 'git-error'])
def test_known_family_git_read_failure_remains_visible_as_failed_runtime_items(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    _git_repo(
        pytester.path,
        {
            'pyproject.toml': '[tool.dev_lab.layout]\nmodule_unit = "code"\nmodule_limit = 300\n',
            'test_x.py': 'def test_x():\n    pass\n',
            'conftest.py': 'import subprocess\nfrom dev_lab.dev.famtests import alwayson\n'
            'def unavailable(*args):\n'
            + (
                '    raise subprocess.TimeoutExpired("git", 60)\n'
                if failure == 'timeout'
                else '    return subprocess.CompletedProcess(["git"], 128, stdout=b"", '
                'stderr=b"git index unreadable")\n'
            )
            + 'def pytest_configure(config):\n    alwayson._git = unavailable\n',
        },
    )
    result = _run(pytester, monkeypatch)
    result.assert_outcomes(passed=1, failed=len(alwayson.rows()) + 1)
    result.stdout.fnmatch_lines(['*git*recollect*'])
