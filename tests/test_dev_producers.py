"""A repo's producer is declared ONCE and every contradiction is refused (user ruling 2026-11-16).

Each rule of :mod:`dev_lab.dev.producercheck` is planted with the one violation it must name, beside this repo's
own tree, which must stand clean -- so the guard is shown able to say no, and shown saying yes where it should.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

import pytest

from dev_lab.dev.ciworkflows import placed, render, repo_forge
from dev_lab.dev.producercheck import host_refusals, repo_refusals
from dev_lab.dev.producers import (
    ACTIONS,
    CI_WORKFLOW,
    HPC,
    UndeclaredProducer,
    optional_needs_from,
    optional_parts,
    producer_from,
    producible,
)

ROOT: Final = Path(__file__).resolve().parents[1]
OWN: Final = (ROOT / 'pyproject.toml').read_text(encoding='utf-8')
DECLARED: Final = f'producer = "{ACTIONS}"'


def _repo(tmp_path: Path, text: str, *, rendered: bool = True) -> Path:
    """A repo whose pyproject is *text*, its GitHub workflows rendered from it when *rendered*."""
    root = tmp_path / 'repo'
    root.mkdir(parents=True)
    (root / 'pyproject.toml').write_text(text, encoding='utf-8')
    if rendered:
        for name, (directory, workflow) in placed(text, str(root), 'github').items():
            (root / directory).mkdir(parents=True, exist_ok=True)
            (root / directory / name).write_text(render(workflow), encoding='utf-8')
    return root


def _as(producer: str, extra: str = '') -> str:
    assert DECLARED in OWN, 'this repo declares itself an Actions repo'
    return OWN.replace(DECLARED, f'producer = "{producer}"') + extra


def test_this_repo_holds_its_declaration() -> None:
    """dev-lab is an Actions repo: its ci.yml posts tests/base, and nothing contradicts it."""
    assert producer_from(OWN, 'dev-lab') == ACTIONS
    assert repo_refusals(ROOT, repo_forge(ROOT)) == []


def test_a_planted_clean_actions_repo_is_not_refused(tmp_path: Path) -> None:
    """PLANTED CONTROL for the refusals below: the same tree, rendered, is clean."""
    assert repo_refusals(_repo(tmp_path, OWN), 'github') == []


@pytest.mark.parametrize('text', ['[project]\nname = "x"\n', '[tool.dev_lab.protection]\nproducer = "box"\n'])
def test_an_undeclared_producer_is_refused_by_name(text: str) -> None:
    with pytest.raises(UndeclaredProducer, match=r'\[tool\.dev_lab\.protection\] producer'):
        producer_from(text, 'x')


def test_a_an_hpc_repo_holding_a_github_workflow_is_refused(tmp_path: Path) -> None:
    root = _repo(tmp_path, _as(HPC), rendered=False)
    assert repo_refusals(root, 'github') == []  # an HPC repo renders nothing for GitHub
    (root / '.github' / 'workflows').mkdir(parents=True)
    (root / '.github' / 'workflows' / 'stray.yml').write_text('{}\n', encoding='utf-8')
    assert [line for line in repo_refusals(root, 'github') if 'stray.yml' in line and 'never runs' in line]


def test_an_hpc_repo_renders_no_ci_and_nothing_for_github() -> None:
    assert not [name for name, (where, _) in placed(_as(HPC), 'x', 'github').items() if 'github' in where.as_posix()]
    assert CI_WORKFLOW in placed(OWN, 'x', 'github')


def test_b_an_actions_repo_without_its_rendered_ci_is_refused(tmp_path: Path) -> None:
    root = _repo(tmp_path, OWN)
    (root / '.github' / 'workflows' / CI_WORKFLOW).unlink()
    assert [line for line in repo_refusals(root, 'github') if CI_WORKFLOW in line and 'not rendered' in line]


def test_c_an_actions_repo_declaring_what_only_the_hpc_queue_reads_is_refused(tmp_path: Path) -> None:
    root = _repo(tmp_path, OWN + '\n[tool.lab_commons.schedule]\nprior_cost_h = 1.0\n')
    assert [line for line in repo_refusals(root, 'github') if 'tool.lab_commons.schedule' in line]


def test_d_a_serve_table_on_a_host_that_is_no_hpc_account_is_refused() -> None:
    assert host_refusals('ws.toml', {'serve': {'parts': 'needs-a-resource'}, 'dev': {}})
    assert host_refusals('ada.toml', {'serve': {}, 'deploy': {'host': 'h'}}) == []  # an HPC account may
    assert host_refusals('ws.toml', {'dev': {}}) == []


def test_e_a_required_part_no_producer_posts_is_refused(tmp_path: Path) -> None:
    root = _repo(tmp_path, OWN.replace('[tool.dev_lab.parts]\n', '[tool.dev_lab.parts]\nrequired = ["jmag"]\n', 1))
    assert [line for line in repo_refusals(root, 'github') if 'tests/jmag has no producer' in line]
    optional = '[tool.dev_lab.parts]\noptional_needs = ["jmag"]\nrequired = ["jmag"]\n'
    hpc = _repo(tmp_path / 'h', _as(HPC).replace('[tool.dev_lab.parts]\n', optional, 1), rendered=False)
    assert [line for line in repo_refusals(hpc, 'github') if 'tests/jmag has no producer' in line]


def test_an_optional_part_is_named_and_still_producible_where_offered() -> None:
    optional = optional_needs_from('[tool.dev_lab.parts]\noptional_needs = ["jmag", "windows"]\n')
    assert optional_parts(['base', 'jmag', 'jmag+windows', 'heavy', 'base@windows'], optional) == {
        'jmag',
        'jmag+windows',
    }
    assert producible(HPC, 'heavy', hosted=(), optional=optional)
    assert not producible(HPC, 'jmag', hosted=(), optional=optional)
    assert producible(ACTIONS, 'base@windows', hosted=(), optional=optional)
    assert not producible(ACTIONS, 'heavy', hosted=(), optional=optional)


@pytest.mark.parametrize('needs', [['gpu', 'vendor', 'ocr'], ['workstation']])
def test_e_parts_declared_not_required_are_accepted(tmp_path: Path, needs: list[str]) -> None:
    """User ruling 2026-11-16: these parts are declared not required, so no Actions producer is owed for them."""
    declared = f'[tool.dev_lab.parts]\noptional_needs = {needs!r}\n'.replace("'", '"')
    root = _repo(tmp_path, OWN.replace('[tool.dev_lab.parts]\n', declared, 1))
    assert repo_refusals(root, 'github') == []
    assert optional_parts(needs, optional_needs_from(declared)) == set(needs)
