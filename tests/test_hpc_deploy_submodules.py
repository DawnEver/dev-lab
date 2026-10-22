"""A SERVED CHECKOUT CARRIES ITS COMPONENTS: the deploy's clone and update initialise its submodules.

A product consumes its engines by path from ``components/<name>`` (:mod:`dev_lab.dev.components`),
so a served checkout without its submodules builds a venv that cannot resolve them. Driven over REAL
local repositories: an engine, and a product mounting it, both reached by ``file://`` urls.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from _forge_fake import git_out, run_git

from dev_lab.dev.hpchost.spec import Deployment, Repo, checkout_of
from dev_lab.dev.hpchost.steps import Step, Tools, update

_ALLOW_FILE = ('-c', 'protocol.file.allow=always')


def _commit(repo: Path, message: str) -> None:
    run_git(repo, '-c', 'user.name=t', '-c', 'user.email=t@t', *_ALLOW_FILE, 'commit', '-q', '-m', message)


def _product(tmp_path: Path) -> tuple[Path, Path]:
    engine = tmp_path / 'engine'
    engine.mkdir()
    run_git(engine, 'init', '-q', '-b', 'main')
    (engine / 'core.py').write_text('X = 1\n', encoding='utf-8')
    run_git(engine, 'add', 'core.py')
    _commit(engine, 'one')
    product = tmp_path / 'product'
    product.mkdir()
    run_git(product, 'init', '-q', '-b', 'main')
    run_git(product, *_ALLOW_FILE, 'submodule', 'add', '-q', engine.as_uri(), 'components/numerics-lab')
    _commit(product, 'mount')
    return engine, product


def test_a_fresh_clone_and_an_update_both_check_out_the_pinned_component(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv('GIT_CONFIG_COUNT', '1')
    monkeypatch.setenv('GIT_CONFIG_KEY_0', 'protocol.file.allow')
    monkeypatch.setenv('GIT_CONFIG_VALUE_0', 'always')
    engine, product = _product(tmp_path)
    repo = Repo('product', product.as_uri(), 'main')
    spec = Deployment('h', 'src', '3.13', (repo,))
    home = tmp_path / 'home'
    step = Step(Tools(), dry=False)

    assert update(step, spec, home, repo) == 0
    mounted = checkout_of(spec, home, repo) / 'components' / 'numerics-lab'
    assert (mounted / 'core.py').read_text(encoding='utf-8') == 'X = 1\n', 'the clone carries its component'

    (engine / 'core.py').write_text('X = 2\n', encoding='utf-8')
    run_git(engine, 'add', 'core.py')
    _commit(engine, 'two')
    inner = product / 'components' / 'numerics-lab'
    run_git(inner, 'pull', '-q', 'origin', 'main')
    run_git(product, 'add', 'components/numerics-lab')
    _commit(product, 'bump')

    assert update(step, spec, home, repo) == 0
    assert git_out(mounted, 'rev-parse', 'HEAD') == git_out(engine, 'rev-parse', 'HEAD'), 'the update moves the pin'
