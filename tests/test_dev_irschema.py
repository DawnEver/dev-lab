"""The IR schema door (docs-src/dev/ir-schema.md): generate, check, migrate, consumers and the --changed reach."""

from __future__ import annotations

import importlib
import json
import shutil
import sys
from pathlib import Path

import lab_commons.launch as _door
import pytest

from dev_lab.dev.ircheck import load
from dev_lab.dev.irmigrate import migrate
from dev_lab.dev.irschema import changed_reach, main, stale_refusal

GIT = shutil.which('git') or 'git'
FIXTURE = Path(__file__).parent / 'data' / 'ir_schema' / 'repo'
CONSUMER = 'from sample_pkg._ir_samples import Sample\n'
MIGRATIONS = """
def _to_1(name, value):
    if name == 'widgets.Widget':
        value = dict(value)
        value['mass'] = value.pop('weight')
    return value


MIGRATIONS = {0: _to_1}
"""


def _git(root: Path, *args: str) -> None:
    _door.run([GIT, '-C', str(root), *args], check=True, capture_output=True, text=True, encoding='utf-8', timeout=60)


def _purge() -> None:
    for name in [n for n in sys.modules if n == 'sample_pkg' or n.startswith('sample_pkg.')]:
        del sys.modules[name]


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = Path(shutil.copytree(FIXTURE, tmp_path / 'repo'))
    package = root / 'src' / 'sample_pkg'
    package.mkdir(parents=True)
    (package / '__init__.py').write_text('', encoding='utf-8')
    (package / 'ir_migrations.py').write_text(MIGRATIONS, encoding='utf-8')
    (package / 'uses_sample.py').write_text(CONSUMER, encoding='utf-8')
    (package / 'uses_nothing.py').write_text('VALUE = 1\n', encoding='utf-8')
    _git(root, 'init', '-q')
    _git(root, 'add', '.')
    _git(root, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '-m', 'base')
    monkeypatch.syspath_prepend(str(root / 'src'))
    _purge()
    yield root
    _purge()


def _edit(root: Path, relative: str, old: str, new: str) -> None:
    path = root / relative
    text = path.read_text(encoding='utf-8')
    assert old in text, old
    path.write_text(text.replace(old, new, 1), encoding='utf-8')


def test_check_refuses_a_missing_generated_file_by_name_until_generate_runs(repo: Path) -> None:
    refused = stale_refusal(repo)
    assert refused is not None
    assert '_ir_widgets.py is missing -- python -m dev_lab.dev.irschema generate' in refused
    assert main(['--root', str(repo), 'check']) == 1
    assert main(['--root', str(repo), 'generate']) == 0
    assert stale_refusal(repo) is None
    _edit(repo, 'ir/widgets.toml', 'doc = "One manufactured widget."', 'doc = "x"')
    _edit(repo, 'pyproject.toml', 'version = "1.0.0"', 'version = "1.0.1"')
    assert 'predates its schema' in stale_refusal(repo)


def test_generate_refuses_a_bump_below_the_change_class(repo: Path) -> None:
    _edit(repo, 'ir/widgets.toml', '[record.Widget.field.mass]\ntype = "float"\nquantity = "mass"\n', '')
    _edit(repo, 'pyproject.toml', 'version = "1.0.0"', 'version = "1.1.0"')
    assert main(['--root', str(repo), 'generate']) == 1
    assert 'the change is MAJOR' in stale_refusal(repo)


def test_a_repo_without_an_ir_is_silent(tmp_path: Path) -> None:
    (tmp_path / 'pyproject.toml').write_text('[project]\nname = "x"\n', encoding='utf-8')
    assert stale_refusal(tmp_path) is None
    assert changed_reach(tmp_path, ['pyproject.toml']) == ['pyproject.toml']


def test_migrate_chains_the_registered_steps_and_rewrites_at_the_current_version(repo: Path) -> None:
    assert main(['--root', str(repo), 'generate']) == 0
    stored = repo / 'w.json'
    value = {'ambient_pressure': 1.0, 'finish': 'raw', 'id': 'w-1', 'seal_pressure': 2.0, 'weight': 0.5}
    stored.write_text(json.dumps({'record': 'widgets.Widget', 'schema_version': '0.3.0', 'value': value}), 'utf-8')
    assert main(['--root', str(repo), 'migrate', str(stored)]) == 0
    rewritten = json.loads(stored.read_bytes())
    assert rewritten['schema_version'] == '1.0.0'
    assert rewritten['value']['mass'] == 0.5
    widgets = importlib.import_module('sample_pkg._ir_widgets')
    assert widgets.Widget.load(stored).mass == 0.5


def test_migrate_refuses_a_missing_step_by_name(repo: Path) -> None:
    assert main(['--root', str(repo), 'generate']) == 0
    _edit(repo, 'pyproject.toml', 'version = "1.0.0"', 'version = "2.0.0"')
    assert main(['--root', str(repo), 'generate']) == 0
    stored = repo / 'w.json'
    stored.write_text(json.dumps({'record': 'widgets.Widget', 'schema_version': '1.0.0', 'value': {}}), 'utf-8')
    refused = migrate(load(repo), stored)
    assert refused.startswith('IR-NO-MIGRATION')
    assert 'add MIGRATIONS[1] to sample_pkg.ir_migrations' in refused


def test_a_minor_change_reaches_only_the_consumers_of_its_records(repo: Path) -> None:
    _edit(
        repo,
        'ir/samples.toml',
        '[record.Batch]',
        '[record.Sample.field.note]\ntype = "str"\noptional = true\n\n[record.Batch]',
    )
    _edit(repo, 'pyproject.toml', 'version = "1.0.0"', 'version = "1.1.0"')
    reach = changed_reach(repo, ['ir/samples.toml', 'pyproject.toml'])
    assert reach == ['ir/samples.toml', 'src/sample_pkg/uses_sample.py']


def test_a_major_change_reaches_everything(repo: Path) -> None:
    _edit(repo, 'ir/samples.toml', 'shape = ["n", 3]', 'shape = ["n", 2]')
    _edit(repo, 'pyproject.toml', 'version = "1.0.0"', 'version = "2.0.0"')
    assert 'pyproject.toml' in changed_reach(repo, ['ir/samples.toml', 'pyproject.toml'])


def test_a_patch_change_reaches_nothing_of_its_own(repo: Path) -> None:
    _edit(repo, 'ir/samples.toml', 'doc = "A measured trace taken from one widget."', 'doc = "A trace."')
    _edit(repo, 'pyproject.toml', 'version = "1.0.0"', 'version = "1.0.1"')
    assert changed_reach(repo, ['ir/samples.toml', 'pyproject.toml']) == ['ir/samples.toml']
