"""WHO PERFORMS EACH FORGE ROLE is the family's binding, read by one mechanism (toolchain D73).

Every refusal is planted beside the clean case it must not fire on, so each guard is shown able to say no. The
family layer here is a PLANTED fixture -- its cluster, accounts and hosts are invented; dev-lab names none of ours.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import Any, Final

import pytest
from _ops_fixtures import git

from dev_lab.dev.ciworkflows import placed, render, role_jobs
from dev_lab.dev.reviewgate import PREPARE_WORKFLOW
from dev_lab.dev.rolecheck import CI_WORKFLOW, host_refusals, repo_refusals
from dev_lab.dev.roles import (
    CI,
    HOST,
    HPC,
    ROLES,
    ROLES_ENV,
    Executor,
    Roles,
    Unbound,
    accounts,
    optional_needs_from,
    optional_parts,
    producible,
    retired_placement,
    roles_at,
    roles_for,
)
from dev_lab.dev.roles import host_refusals as role_host_refusals
from dev_lab.ops.configcheck import check_roles

ROOT: Final = Path(__file__).resolve().parents[1]
OWN: Final = (ROOT / 'pyproject.toml').read_text(encoding='utf-8')

#: A planted family layer: one cluster, a verification and a research account, two ops hosts.
FAMILY: Final = """
[hpc.clusters.alpha]
hosts = ["login.alpha.example"]
slurm_accounts = { free = { billed = false } }

[[hpc.grant]]
user = "vera"
cluster = "alpha"
slurm_account = "free"
role = "verification"

[[hpc.grant]]
user = "rhea"
cluster = "alpha"
slurm_account = "free"
role = "research"

[roles.github]
tests = "ci"
review = { host = "judgehost" }
merge = "ci"
promote = "ci"
prune = "ci"

[roles.gitea]
tests = { hpc = "alpha", role = "verification" }
review = { host = "judgehost" }
merge = { hpc = "alpha", role = "verification" }
promote = { host = "promotehost" }
prune = { hpc = "alpha", role = "verification" }
"""
LAYER: Final = tomllib.loads(FAMILY)
#: Every role on CI but review, which the judge host performs: a planted GitHub repo.
GITHUB: Final = Roles.of_kinds(tests=CI, review=HOST, merge=CI, promote=CI, prune=CI)
#: No role on CI: a planted Gitea repo of the HPC.
GITEA: Final = Roles.of_kinds(tests=HPC, review=HOST, merge=HPC, promote=HOST, prune=HPC)
EVERY_CI: Final = Roles.of_kinds(**dict.fromkeys(ROLES, CI))
#: dev-lab's own layer placing the judge's prepare on GitHub.
PREPARE_LAYER: Final = '[tool.dev_lab.ci."review-prepare.yml"]\nforge = "github"\n'


def _layer(**changed: object) -> dict[str, Any]:
    layer = tomllib.loads(FAMILY)
    for forge, table in changed.items():
        layer['roles'][forge] = table
    return layer


# -- the reader ------------------------------------------------------------------------------------------------------


def test_each_forge_binds_its_roles_and_an_hpc_binding_resolves_through_its_grants() -> None:
    gitea = roles_for(LAYER, 'gitea', 'team/app')
    assert gitea.of('tests') == Executor(HPC, cluster='alpha', grant_role='verification')
    assert accounts(gitea.of('tests'), LAYER) == ('vera',)  # PLANTED CONTROL: rhea is research, never named
    assert gitea.of('promote') == Executor(HOST, host='promotehost')
    assert roles_for(LAYER, 'github', 'owner/lib').env() == GITHUB.env()


def test_a_repo_override_binds_one_repo_over_its_forge() -> None:
    layer = tomllib.loads(FAMILY + '\n[roles.repos."team/odd"]\ntests = "ci"\n')
    assert roles_for(layer, 'gitea', 'team/odd').kind('tests') == CI
    assert roles_for(layer, 'gitea', 'team/app').kind('tests') == HPC


def test_an_unbound_role_is_refused_naming_both_tables() -> None:
    layer = _layer(github={'tests': 'ci', 'review': 'ci', 'merge': 'ci', 'promote': 'ci'})
    with pytest.raises(Unbound, match=r'prune is unbound -- bind it in \[roles\.github\] or \[roles\.repos\."o/x"\]'):
        roles_for(layer, 'github', 'o/x')


def test_no_roles_table_is_refused_naming_the_table_to_add() -> None:
    with pytest.raises(Unbound, match=r'declares no \[roles\]: bind every role of gitea repos in \[roles\.gitea\]'):
        roles_for({}, 'gitea', 'team/app')


@pytest.mark.parametrize(
    ('role', 'value', 'match'),
    [
        ('promote', {'hpc': 'alpha', 'role': 'verification'}, r'promote is performed by \[.ci., .host.\] alone'),
        ('tests', {'host': 'judgehost'}, r'tests is performed by \[.ci., .hpc.\] alone'),
        ('tests', {'hpc': 'alpha', 'role': 'nobody'}, r'resolves to no account: declare a \[\[hpc\.grant\]\]'),
        ('tests', {'hpc': 'beta', 'role': 'verification'}, r'resolves to no account'),
        ('tests', 'actions', r'is no binding: write "ci"'),
        ('tests', {'host': ''}, r'is no binding'),
    ],
)
def test_a_binding_its_role_cannot_take_or_the_family_cannot_resolve_is_refused(
    role: str, value: object, match: str
) -> None:
    table = dict(LAYER['roles']['gitea'])
    table[role] = value
    with pytest.raises(Unbound, match=match):
        roles_for(_layer(gitea=table), 'gitea', 'team/app')


def test_an_unknown_role_is_refused() -> None:
    table = {**LAYER['roles']['github'], 'deploy': 'ci'}
    with pytest.raises(Unbound, match=r"unknown roles \['deploy'\]"):
        roles_for(_layer(github=table), 'github', 'o/x')


def test_a_ci_job_reads_the_kinds_its_render_carried(tmp_path: Path) -> None:
    assert roles_at(tmp_path, layer={}, env={ROLES_ENV: GITEA.env()}).env() == GITEA.env()


def test_no_layer_and_nothing_carried_is_refused_naming_the_family_table(tmp_path: Path) -> None:
    with pytest.raises(Unbound, match=r'no family layer on this machine and no DEV_LAB_ROLES carried'):
        roles_at(tmp_path, layer={}, env={})
    with pytest.raises(Unbound, match='re-render the workflows'):
        roles_at(tmp_path, layer={}, env={ROLES_ENV: json.dumps({'tests': 'ci'})})


def test_a_checkout_is_bound_by_its_origin(tmp_path: Path) -> None:
    git(tmp_path, 'init', '-q')
    git(tmp_path, 'remote', 'add', 'origin', 'https://forge.example/team/app.git')
    assert roles_at(tmp_path, layer=LAYER, env={}).env() == GITEA.env()  # a non-GitHub host is a Gitea forge


# -- the host duties and the hosts' lists (configcheck) ---------------------------------------------------------------


def test_a_host_binding_needs_a_host_file_carrying_the_duty() -> None:
    cards: dict[str, Any] = {'judgehost': {'ops': {'judge': {}}}, 'promotehost': {'ops': {'promote': {}}}}
    assert role_host_refusals(LAYER, cards) == []
    del cards['promotehost']['ops']['promote']
    assert role_host_refusals(LAYER, cards) == [
        '[roles.gitea] promote = { host = "promotehost" }: that host carries no [ops.promote]'
    ]
    lone = role_host_refusals(LAYER, {'promotehost': {'ops': {'promote': {}}}})
    assert lone[0].endswith('no host file declares that host')


def test_a_hosts_list_is_the_binding_or_refused(tmp_path: Path) -> None:
    family = tmp_path / 'family.toml'
    family.write_text(FAMILY, encoding='utf-8')
    judge = tmp_path / 'judgehost.toml'
    promote = tmp_path / 'promotehost.toml'
    judge.write_text('[ops.judge]\nrepos = ["https://forge.example/team/app"]\n', encoding='utf-8')
    promote.write_text('[ops]\nrepos = ["https://forge.example/team/app.git"]\n[ops.promote]\n', encoding='utf-8')
    assert check_roles(family, [judge, promote]) == []
    promote.write_text('[ops]\nrepos = ["https://github.com/owner/lib.git"]\n[ops.promote]\n', encoding='utf-8')
    assert check_roles(family, [judge, promote]) == [
        (
            'promotehost: [ops] repos lists https://github.com/owner/lib.git, whose promote the family binds to '
            '"ci": the binding is the source'
        )
    ]


# -- the retired placements --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ('text', 'key'),
    [
        ('[tool.dev_lab.protection]\nproducer = "hpc"\n', 'protection] producer'),
        ('[tool.dev_lab.review]\nwhere = "judge"\n', 'review] where'),
        ('[tool.dev_lab.ci."merge.yml"]\n', 'ci] merge.yml'),
    ],
)
def test_a_repo_declaring_a_placement_is_refused_with_its_migration(text: str, key: str) -> None:
    (found,) = retired_placement(text, 'x')
    assert f'[tool.dev_lab.{key} is retired' in found
    assert '[roles.' in found


def test_this_repo_declares_no_placement() -> None:
    """PLANTED CONTROL for the refusals above: dev-lab's own pyproject is clean."""
    assert retired_placement(OWN, 'dev-lab') == []


# -- the render -------------------------------------------------------------------------------------------------------


def test_a_repo_with_no_role_on_ci_renders_only_the_judges_prepare() -> None:
    """The judge reviews a bundle the forge's CI prepares: the one job a Gitea HPC repo still renders."""
    bare = OWN.replace(PREPARE_LAYER, '')
    assert set(placed(bare, 'x', 'gitea', GITEA)) == {PREPARE_WORKFLOW}
    no_judge = Roles.of_kinds(tests=HPC, review=HPC, merge=HPC, promote=HOST, prune=HPC)
    assert placed(bare, 'x', 'gitea', no_judge) == {}


def test_every_rendered_workflow_carries_the_kinds_its_job_reads() -> None:
    rendered = placed(OWN, 'x', 'github', GITHUB)
    assert CI_WORKFLOW in rendered
    assert {flow['env'][ROLES_ENV] for _, flow in rendered.values()} == {GITHUB.env()}


def test_the_judge_prepare_renders_only_where_review_is_bound_to_a_host() -> None:
    assert PREPARE_WORKFLOW in placed(OWN, 'x', 'github', GITHUB)
    bare = OWN.replace('[tool.dev_lab.ci."review-prepare.yml"]\nforge = "github"\n', '')
    assert PREPARE_WORKFLOW not in placed(bare, 'x', 'github', EVERY_CI)


def test_a_mix_of_executors_no_workflow_can_hold_is_refused() -> None:
    mixed = Roles.of_kinds(tests=HPC, review=HOST, merge=CI, promote=CI, prune=CI)
    with pytest.raises(ValueError, match=r'needs .*whose role \[.tests.\] is not on ci here'):
        placed(OWN, 'x', 'github', mixed)


def test_a_job_naming_no_role_is_refused() -> None:
    with pytest.raises(ValueError, match=r"job 'x' names role = None"):
        role_jobs({'jobs': {'x': {'steps': []}}}, GITHUB, 'w')


def test_a_step_renders_only_where_its_own_role_is_on_ci() -> None:
    job = {'role': 'promote', 'steps': [{'name': 'promote'}, {'name': 'sweep', 'role': 'prune'}]}
    roles = Roles.of_kinds(tests=CI, review=CI, merge=CI, promote=CI, prune=HPC)
    kept = role_jobs({'jobs': {'promote': job}}, roles, 'w')
    assert [step['name'] for step in kept['jobs']['promote']['steps']] == ['promote']
    assert 'role' not in kept['jobs']['promote']


# -- the repo checks (rolecheck) --------------------------------------------------------------------------------------


def _repo(tmp_path: Path, text: str, roles: Roles, *, rendered: bool = True) -> Path:
    root = tmp_path / 'repo'
    root.mkdir(parents=True)
    (root / 'pyproject.toml').write_text(text, encoding='utf-8')
    if rendered:
        for name, (directory, workflow) in placed(text, str(root), 'github', roles).items():
            (root / directory).mkdir(parents=True, exist_ok=True)
            (root / directory / name).write_text(render(workflow), encoding='utf-8')
    return root


def test_a_planted_clean_ci_repo_is_not_refused(tmp_path: Path) -> None:
    assert repo_refusals(_repo(tmp_path, OWN, GITHUB), 'github', GITHUB) == []


def test_a_workflow_nothing_renders_is_refused(tmp_path: Path) -> None:
    root = _repo(tmp_path, OWN, GITEA, rendered=False)
    assert repo_refusals(root, 'github', GITEA) == []
    (root / '.github' / 'workflows').mkdir(parents=True)
    (root / '.github' / 'workflows' / 'stray.yml').write_text('{}\n', encoding='utf-8')
    assert [line for line in repo_refusals(root, 'github', GITEA) if 'stray.yml' in line and 'nothing renders' in line]


def test_a_ci_repo_without_its_rendered_ci_is_refused(tmp_path: Path) -> None:
    root = _repo(tmp_path, OWN, GITHUB)
    (root / '.github' / 'workflows' / CI_WORKFLOW).unlink()
    assert [line for line in repo_refusals(root, 'github', GITHUB) if CI_WORKFLOW in line and 'not rendered' in line]


def test_a_ci_repo_declaring_what_only_the_hpc_queue_reads_is_refused(tmp_path: Path) -> None:
    root = _repo(tmp_path, OWN + '\n[tool.lab_commons.schedule]\nprior_cost_h = 1.0\n', GITHUB)
    assert [line for line in repo_refusals(root, 'github', GITHUB) if 'tool.lab_commons.schedule' in line]


def test_a_required_part_no_executor_posts_is_refused(tmp_path: Path) -> None:
    text = OWN.replace('[tool.dev_lab.parts]\n', '[tool.dev_lab.parts]\nrequired = ["jmag"]\n', 1)
    root = _repo(tmp_path, text, GITHUB)
    assert [line for line in repo_refusals(root, 'github', GITHUB) if 'tests/jmag has no producer' in line]


def test_a_retired_placement_is_one_of_the_repo_refusals(tmp_path: Path) -> None:
    root = _repo(tmp_path, OWN, GITHUB)
    assert repo_refusals(root, 'github', GITHUB) == []  # PLANTED CONTROL
    planted = OWN.replace('[tool.dev_lab.review]\n', '[tool.dev_lab.review]\nwhere = "judge"\n')
    (root / 'pyproject.toml').write_text(planted, encoding='utf-8')
    assert [line for line in repo_refusals(root, 'github', GITHUB) if 'review] where is retired' in line]


def test_a_serve_table_on_a_host_that_is_no_hpc_account_is_refused() -> None:
    assert host_refusals('ws.toml', {'serve': {'parts': 'needs-a-resource'}, 'dev': {}})
    assert host_refusals('ada.toml', {'serve': {}, 'deploy': {'host': 'h'}}) == []
    assert host_refusals('ws.toml', {'dev': {}}) == []


def test_an_optional_part_is_named_and_still_producible_where_offered() -> None:
    optional = optional_needs_from('[tool.dev_lab.parts]\noptional_needs = ["jmag", "windows"]\n')
    rows = ['base', 'jmag', 'jmag+windows', 'heavy', 'base@windows']
    assert optional_parts(rows, optional) == {'jmag', 'jmag+windows'}
    assert producible(HPC, 'heavy', hosted=(), optional=optional)
    assert not producible(HPC, 'jmag', hosted=(), optional=optional)
    assert producible(CI, 'base@windows', hosted=(), optional=optional)
    assert not producible(CI, 'heavy', hosted=(), optional=optional)
