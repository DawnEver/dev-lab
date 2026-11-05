"""Workflows are TOML rendered to bytes: this repo's files ARE the render, and a hand edit is refused.

Nothing here parses YAML -- the comparison is between rendered bytes and file bytes.
"""

from __future__ import annotations

import ast
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

import pytest

from dev_lab.dev import ciworkflows
from dev_lab.dev.ciworkflows import (
    BASE_PATH,
    BY_FORGE,
    NIGHTLY_CRON,
    PREPARE,
    RENDER_COMMAND,
    RUNNERS,
    SHARED,
    STAMP,
    USE_STEPS,
    base_names,
    drift,
    expand,
    main,
    merge,
    render,
    repo_forge,
    workflows,
    write,
)
from dev_lab.dev.forgedraft import READY_ONLY
from dev_lab.dev.forgereview_pointer import ARTIFACT, BUNDLE_FILE
from dev_lab.dev.jobparts import PULL_REQUEST_SYSTEMS, systems_for
from dev_lab.dev.reviewgate import PREPARE_WORKFLOW, REVIEW_EVENT

_ROOT = Path(__file__).resolve().parents[1]
_JUDGE_REVIEW = '[tool.dev_lab.review]\nwhere = "judge"\njudge_login = "judge"\n'

_GITHUB_BASE = {'ci.yml', 'merge-tick.yml', 'review-claims.yml'}
_GITEA_BASE = {'review.yml', 'merge.yml'}


def _hosted(root: Path, url: str = 'https://github.com/o/r.git') -> Path:
    """*root* as a git repo whose ``origin`` is *url*: the one fact a repo's forge is read from."""
    git = shutil.which('git')
    assert git is not None
    subprocess.run([git, 'init', '-q', str(root)], check=True)
    subprocess.run([git, '-C', str(root), 'remote', 'add', 'origin', url], check=True)
    return root


def test_this_repo_s_workflows_are_exactly_their_render() -> None:
    assert set(workflows(_ROOT)) == _GITHUB_BASE, 'a floor: an empty table drifts from nothing'
    assert drift(_ROOT) == []


def test_a_repo_opts_in_and_its_layer_merges_over_the_base(tmp_path: Path) -> None:
    (tmp_path / 'pyproject.toml').write_text(
        '[tool.dev_lab.ci."ci.yml".jobs.review.permissions]\nissues = "read"\n', encoding='utf-8'
    )
    ci = workflows(tmp_path)['ci.yml']
    assert ci['jobs']['review']['permissions'] == {
        'contents': 'read',
        'statuses': 'write',
        'pull-requests': 'write',
        'issues': 'read',
    }


def _base_ci(tmp_path: Path) -> dict[str, Any]:
    (tmp_path / 'pyproject.toml').write_text('[tool.dev_lab.ci."ci.yml"]\n', encoding='utf-8')
    return workflows(tmp_path)['ci.yml']


def test_the_lifecycle_runs_on_pull_request_and_never_on_pull_request_target(tmp_path: Path) -> None:
    ci = _base_ci(tmp_path)
    assert set(ci['on']) == {'push', 'pull_request', 'workflow_dispatch', 'schedule'}
    assert 'pull_request_target' not in render(ci), "a fork's code would run with this repository's secrets"
    assert ci['jobs']['review']['if'] == _guarded("${{ github.event_name == 'pull_request' }}")


def test_every_job_holds_least_permissions_and_the_workflow_only_reads(tmp_path: Path) -> None:
    ci = _base_ci(tmp_path)
    assert ci['permissions'] == {'contents': 'read'}
    granted = {name: job.get('permissions', {}) for name, job in ci['jobs'].items()}
    assert granted == {
        'parts': {},
        'part': {'contents': 'write', 'statuses': 'write'},
        'absent-parts': {'contents': 'read', 'statuses': 'write'},
        'security': {'contents': 'read', 'statuses': 'write', 'pull-requests': 'read'},
        'review': {'contents': 'read', 'statuses': 'write', 'pull-requests': 'write', 'issues': 'write'},
        'merge-ready': {'contents': 'write', 'statuses': 'write', 'pull-requests': 'write', 'actions': 'write'},
        'promote': {'contents': 'write', 'statuses': 'write', 'pull-requests': 'write'},
    }


def test_the_matrix_is_the_command_s_output_and_merge_ready_runs_last_in_the_same_workflow(tmp_path: Path) -> None:
    ci = _base_ci(tmp_path)
    jobs = ci['jobs']
    assert jobs['part']['strategy']['matrix'] == '${{ fromJSON(needs.parts.outputs.matrix) }}'
    assert jobs['parts']['outputs'] == {
        'matrix': '${{ steps.matrix.outputs.matrix }}',
        'event': '${{ env.PARTS_EVENT }}',
        'pending': '${{ steps.pending.outputs.pending }}',
    }
    (computed,) = [step for step in jobs['parts']['steps'] if step.get('id') == 'matrix']
    event = '--event "$PARTS_EVENT"'
    assert f'dev_lab.dev.jobparts matrix --runners hosted {event}' in computed['run'], 'the rows follow the event'
    assert 'dev_lab.dev.jobparts produce ${{ matrix.part }}' in jobs['part']['steps'][-1]['run']
    assert f'dev_lab.dev.jobparts absent "$HEAD_SHA" {event}' in jobs['absent-parts']['steps'][-1]['run']
    assert jobs['absent-parts']['if'].startswith(_guarded('${{ always()').removesuffix(') }}'))
    assert set(jobs['merge-ready']['needs']) == {'security', 'review', 'part', 'absent-parts'}, (
        'a merge waits on its parts'
    )
    assert jobs['merge-ready']['if'].startswith(_guarded('${{ always()').removesuffix(') }}'))
    ready, dispatch = jobs['merge-ready']['steps'][-2:]
    assert 'forge merge ready --pr' in ready['run']
    assert '"; merged") echo "merged=true" >> "$GITHUB_OUTPUT"' in ready['run']
    assert dispatch['if'] == "${{ steps.ready.outputs.merged == 'true' }}", 'only a merge it made is dispatched'
    assert 'gh workflow run ci.yml' in dispatch['run'], 'a job-token merge starts no workflow (dev-lab#15)'
    assert 'forge review run --pr' in jobs['review']['steps'][-1]['run']
    assert 'workflow_run' not in ci['on'], 'no cross-workflow trigger'


def test_the_review_job_runs_the_method_from_an_environment_that_carries_it(tmp_path: Path) -> None:
    """lab-commons #11, dev-lab #3: the repo's own .venv has no ai_lab, so the review never ran on GitHub."""
    steps = {step.get('name'): step for step in _base_ci(tmp_path)['jobs']['review']['steps']}
    install, review = steps['Install the review method']['run'], steps['tests/review']['run']
    assert 'uv" pip install --no-config --python "$RUNNER_TEMP/ai-lab/bin/python" "ai_lab @ git+' in install
    assert '--runtime "ai_lab.python=$RUNNER_TEMP/ai-lab/bin/python"' in review
    assert '$GITHUB_WORKSPACE/.venv' not in review, "the repo's own environment does not carry the method"
    assert 'uv run' not in review


def test_the_review_key_reaches_the_method_through_its_own_store_never_argv(tmp_path: Path) -> None:
    """The review key reaches ai-lab through its credential store, on stdin, never argv or the environment.

    ai-lab reads keys from the git credential store ONLY: dev-lab #5's reviewers were all `unsupported` with
    ANTHROPIC_API_KEY set. The job stores it (memory cache, stdin) for the review task.
    """
    steps = {step.get('name'): step for step in _base_ci(tmp_path)['jobs']['review']['steps']}
    login = steps['Store the review key']
    (key,) = login['env'].values()
    assert set(login['env']) == {'ANTHROPIC_API_KEY'}
    assert key.endswith("&& secrets.ANTHROPIC_API_KEY || '' }}"), (
        'a fork PR is withheld it (test_a_fork_pr_s_review_job_holds_secret_free)'
    )
    helper = 'credential.helper "cache --timeout=1800 --socket=$RUNNER_TEMP/git-credential-cache/socket"'
    assert helper in login['run'], 'in memory, one review long, the job its own'
    assert '-m ai_lab.auth login anthropic --task pr-review' in login['run']
    assert '| "$RUNNER_TEMP/ai-lab/bin/python"' in login['run'], 'the key travels on stdin'
    assert 'if [ -n "$ANTHROPIC_API_KEY" ]' in login['run'], 'a fork PR has no secret: the review holds the head'
    names = list(steps)
    assert names.index('Install the review method') < names.index('Store the review key') < names.index('tests/review')


def _parts_event(ci: dict[str, Any], event: str, *, smoke: bool | None = None) -> str:
    """The RENDERED PARTS_EVENT expression, evaluated for one trigger (``inputs.smoke`` is null off a dispatch).

    Actions' ``&&``/``||`` return an operand, as Python's ``and``/``or`` do, so the expression is parsed as one and
    walked: only names, literals, ``==``/``!=`` and ``and``/``or`` are understood, anything else refuses.
    """
    expression = ci['env']['PARTS_EVENT'].removeprefix('${{').removesuffix('}}')
    python = expression.replace('&&', ' and ').replace('||', ' or ')
    python = python.replace('github.event_name', 'event_name').replace('inputs.smoke', 'smoke')
    names: dict[str, str | bool | None] = {'event_name': event, 'smoke': smoke}

    def walk(node: ast.expr) -> str | bool | None:
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            return names[node.id]
        if isinstance(node, ast.BoolOp):
            value = walk(node.values[0])
            for operand in node.values[1:]:
                if isinstance(node.op, ast.And) != bool(value):
                    return value
                value = walk(operand)
            return value
        if isinstance(node, ast.Compare) and len(node.ops) == 1 and isinstance(node.ops[0], ast.Eq | ast.NotEq):
            equal = walk(node.left) == walk(node.comparators[0])
            return equal if isinstance(node.ops[0], ast.Eq) else not equal
        raise ValueError(ast.dump(node))  # a PARTS_EVENT node this reader does not understand

    return walk(ast.parse(python.strip(), mode='eval').body)


def test_a_merge_runs_only_the_pr_part_set_as_its_smoke_and_never_promotes(tmp_path: Path) -> None:
    """D48-1A: a push to integrate/main (a merge) re-runs the PR's set, no macos (D84), and promotes nothing.

    merge-ready's dispatch after a job-token merge is a merge too: it asks for the smoke run.
    """
    ci = _base_ci(tmp_path)
    assert ci['on']['push'] == {'branches': ['integrate/main']}, 'main moves only by promote, never by a push run'
    assert _parts_event(ci, 'push') == 'pull_request'
    assert _parts_event(ci, 'workflow_dispatch', smoke=True) == 'pull_request'
    steps = {step.get('id'): step for step in ci['jobs']['parts']['steps']}
    assert '--event "$PARTS_EVENT"' in steps['matrix']['run']
    assert '--event "$PARTS_EVENT"' in ci['jobs']['absent-parts']['steps'][-1]['run'], 'the SAME event absent reads'
    assert steps['pending']['if'] == (
        "${{ env.PARTS_EVENT != 'pull_request' && github.ref == 'refs/heads/integrate/main' }}"
    ), 'a smoke run never asks pending, so its pending output is empty'
    assert ci['jobs']['promote']['if'] == _guarded("${{ needs.parts.outputs.pending == 'true' }}"), (
        'empty is never true'
    )
    dispatch = ci['jobs']['merge-ready']['steps'][-1]['run']
    assert dispatch.endswith('--ref integrate/main -f smoke=true')


def test_the_nightly_schedule_runs_the_full_matrix_then_promotes_by_the_one_decision(tmp_path: Path) -> None:
    """D48-1A: once nightly, and on demand, integrate/main's tip runs every part on every OS, then promotes.

    `integrate promote` alone asks the parts at scope full (D83); the schedule's run is never a merge's smoke.
    """
    ci = _base_ci(tmp_path)
    assert ci['on']['schedule'] == [{'cron': NIGHTLY_CRON}]
    assert ci['on']['workflow_dispatch']['inputs']['smoke']['default'] is False, 'on demand is the full run'
    assert _parts_event(ci, 'schedule') == 'schedule'
    assert _parts_event(ci, 'workflow_dispatch', smoke=False) == 'workflow_dispatch'
    assert systems_for('schedule') == ('linux', 'macos', 'windows')
    assert systems_for(_parts_event(ci, 'push')) == PULL_REQUEST_SYSTEMS, 'PLANTED CONTROL: the smoke has no macos'
    assert "'smoke' || github.event_name" in ci['concurrency']['group'], 'a merge never cancels the nightly run'
    promote = ci['jobs']['promote']
    assert promote['needs'] == ['parts', 'absent-parts']
    (step,) = [one for one in promote['steps'] if 'integrate promote' in one.get('run', '')]
    assert 'python -m dev_lab.dev.integrate promote "$HEAD_SHA"' in step['run']
    assert 'git push origin main' in step['run']


def test_a_tip_main_already_holds_runs_no_part_no_absent_and_no_promote(tmp_path: Path) -> None:
    """D48-1A: `integrate pending` says false -> no matrix -> every later job is skipped by its `if`.

    PLANTED CONTROL: each job's condition names the empty matrix (or pending), so a dropped guard reds here.
    """
    ci = _base_ci(tmp_path)
    steps = {step.get('id'): step for step in ci['jobs']['parts']['steps']}
    assert 'dev_lab.dev.integrate pending "$HEAD_SHA" >> "$GITHUB_OUTPUT"' in steps['pending']['run']
    assert steps['matrix']['if'] == "${{ steps.pending.outputs.pending != 'false' }}"
    assert ci['jobs']['parts']['outputs']['pending'] == '${{ steps.pending.outputs.pending }}'
    assert ci['jobs']['part']['if'] == _guarded("${{ needs.parts.outputs.matrix != '' }}")
    assert "needs.parts.outputs.matrix != ''" in ci['jobs']['absent-parts']['if']
    assert 'pending' in ci['jobs']['promote']['if']


def test_after_promote_the_nightly_job_sweeps_every_branch_integration_now_contains(tmp_path: Path) -> None:
    """LANDED-BRANCHES-SWEPT (ruling 2026-10-29): the sweep runs after promote, even when promote failed."""
    steps = _base_ci(tmp_path)['jobs']['promote']['steps']
    runs = [one.get('run', '') for one in steps]
    swept = next(i for i, run in enumerate(runs) if 'dev_lab.dev.branchprune sweep' in run)
    assert swept > next(i for i, run in enumerate(runs) if 'integrate promote' in run)
    assert steps[swept]['if'] == '${{ !cancelled() }}'


def test_a_shared_step_list_is_declared_once_and_expanded_in_every_job(tmp_path: Path) -> None:
    ci = _base_ci(tmp_path)
    setups = [job['steps'][:3] for name, job in ci['jobs'].items() if name != 'review']
    assert ci['jobs']['review']['steps'][0] == setups[0][0], 'the review checks the head out as DATA, no setup'
    assert all(steps == setups[0] for steps in setups)
    assert setups[0][0]['with'] == {'ref': '${{ env.HEAD_SHA }}', 'fetch-depth': 0}
    assert '_steps' not in workflows(tmp_path)
    shared = {'a': [{'run': 'x'}]}
    assert expand({'jobs': {'j': {'steps': [{USE_STEPS: 'a'}, {'run': 'z'}]}}}, shared) == {
        'jobs': {'j': {'steps': [{'run': 'x'}, {'run': 'z'}]}}
    }


def test_the_base_of_each_forge_is_every_base_table_placed_on_it() -> None:
    assert base_names('github') == _GITHUB_BASE
    assert base_names('gitea') == _GITEA_BASE


@pytest.mark.parametrize(('forge', 'expected'), [('github', _GITHUB_BASE), ('gitea', _GITEA_BASE)])
def test_a_repo_that_declares_nothing_renders_its_forge_s_whole_base(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, forge: str, expected: set[str]
) -> None:
    """The base is never an opt-in a repo can forget: merge-tick and review-claims went undeployed that way."""
    monkeypatch.setattr(ciworkflows, 'repo_forge', lambda _root: forge)
    (tmp_path / 'pyproject.toml').write_text('', encoding='utf-8')
    assert set(workflows(tmp_path)) == expected
    assert {path.name for path in write(tmp_path)} == expected


def test_an_undeclared_github_ci_still_runs_the_nightly_schedule(tmp_path: Path) -> None:
    _hosted(tmp_path)
    (tmp_path / 'pyproject.toml').write_text('', encoding='utf-8')
    assert workflows(tmp_path)['ci.yml']['on']['schedule'] == [{'cron': NIGHTLY_CRON}]


def test_a_repo_missing_a_base_workflow_is_refused_naming_it(tmp_path: Path) -> None:
    """PLANTED CONTROL: a full render drifts from nothing; deleting one base file is named."""
    _hosted(tmp_path)
    (tmp_path / 'pyproject.toml').write_text('', encoding='utf-8')
    write(tmp_path)
    assert drift(tmp_path) == []
    (tmp_path / '.github' / 'workflows' / 'merge-tick.yml').unlink()
    assert [line for line in drift(tmp_path) if 'merge-tick.yml' in line and 'base workflow' in line]


@pytest.mark.parametrize(
    ('tables', 'forge'),
    [('[tool.dev_lab.ci."ci.yml"]\n', 'github'), ('[tool.dev_lab.ci."merge.yml"]\n', 'gitea')],
)
def test_with_no_origin_the_forge_is_the_one_the_declared_tables_are_placed_on(
    tmp_path: Path, tables: str, forge: str
) -> None:
    (tmp_path / 'pyproject.toml').write_text(tables, encoding='utf-8')
    assert repo_forge(tmp_path) == forge


@pytest.mark.parametrize('tables', ['', '[tool.dev_lab.ci."ci.yml"]\n[tool.dev_lab.ci."merge.yml"]\n'])
def test_with_no_origin_and_no_single_declared_forge_the_render_is_refused_naming_the_remedy(
    tmp_path: Path, tables: str
) -> None:
    (tmp_path / 'pyproject.toml').write_text(tables, encoding='utf-8')
    with pytest.raises(ValueError, match='add the `origin` remote'):
        workflows(tmp_path)


@pytest.mark.parametrize(
    ('url', 'forge'),
    [('https://github.com/o/r.git', 'github'), ('https://gitea.example.org/o/r.git', 'gitea')],
)
def test_a_repo_s_forge_is_read_from_its_origin(tmp_path: Path, url: str, forge: str) -> None:
    assert repo_forge(_hosted(tmp_path, url)) == forge


def test_a_hand_edit_and_a_hand_written_workflow_are_refused_naming_the_render(tmp_path: Path, capsys) -> None:
    """PLANTED CONTROL: render, then edit one byte and add an undeclared file -- both must be named."""
    (tmp_path / 'pyproject.toml').write_text('[tool.dev_lab.ci."ci.yml"]\n', encoding='utf-8')
    write(tmp_path)
    assert main(['check', '--root', str(tmp_path)]) == 0
    path = tmp_path / '.github' / 'workflows' / 'ci.yml'
    path.write_text(path.read_text(encoding='utf-8').replace('"CI"', '"Ci"'), encoding='utf-8')
    (path.parent / 'extra.yml').write_text('name: x\n', encoding='utf-8')
    assert main(['check', '--root', str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert 'ci.yml: differs' in out
    assert 'extra.yml: a workflow no' in out
    assert RENDER_COMMAND in out


def test_the_render_is_a_stamp_then_json() -> None:
    text = render({'name': 'x', 'on': {'push': {}}})
    assert text.startswith(f'{STAMP}\n{{\n')
    assert text.endswith('}\n')


def test_merge_replaces_a_non_table_and_merges_a_table() -> None:
    assert merge({'a': {'b': 1, 'c': [1]}}, {'a': {'c': [2]}}) == {'a': {'b': 1, 'c': [2]}}


_HOSTED = """
[tool.lab_commons.tests]
resources = ["live"]

[tool.dev_lab.parts]
hosted = { live = { secrets = ["MODEL_KEY"], setup = "login --from-file -" } }

[tool.dev_lab.ci."ci.yml"]
"""


def test_a_hosted_part_renders_its_own_full_run_only_job_and_only_its_setup_step_sees_the_secret(
    tmp_path: Path, monkeypatch
) -> None:
    planted = 'sk-planted-value-never-rendered'
    monkeypatch.setenv('MODEL_KEY', planted)
    (tmp_path / 'pyproject.toml').write_text(_HOSTED, encoding='utf-8')
    ci = workflows(tmp_path)['ci.yml']
    job = ci['jobs']['part-live']
    assert job['runs-on'] == 'ubuntu-latest'
    assert job['if'] == _guarded(
        "${{ needs.parts.outputs.matrix != '' && needs.parts.outputs.event != 'pull_request' }}"
    )
    assert job['name'] == 'tests/live'
    carrying = [step for step in job['steps'] if 'env' in step]
    assert len(carrying) == 1
    setup = carrying[0]
    assert setup['env'] == {'MODEL_KEY': '${{ secrets.MODEL_KEY }}'}
    assert setup['run'] == r"""printf '%s=%s\n' MODEL_KEY "$MODEL_KEY" | { login --from-file -; }"""
    assert job['steps'][-1]['run'].endswith('jobparts produce live')
    assert 'part-live' in ci['jobs']['absent-parts']['needs'], 'absent waits for it'
    others = {name: render({'j': body}) for name, body in ci['jobs'].items() if name not in {'part-live', 'review'}}
    assert all('MODEL_KEY' not in text for text in others.values()), 'no other job carries the secret'
    assert planted not in render(ci), 'the render never prints a secret value'
    (tmp_path / 'pyproject.toml').write_text('[tool.dev_lab.ci."ci.yml"]\n', encoding='utf-8')
    assert not [name for name in workflows(tmp_path)['ci.yml']['jobs'] if name.startswith('part-')], (
        'PLANTED CONTROL: nothing declared, no hosted job'
    )


def _unguarded(step: dict[str, Any]) -> dict[str, Any]:
    """*step* without the guard Gitea's review job adds (the settle step's skip): the shared step itself."""
    return {key: value for key, value in step.items() if key != 'if'}


def _method_steps(tmp_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    (tmp_path / 'hub').mkdir()
    jobs = (_base_ci(tmp_path / 'hub')['jobs']['review'], _gitea_review(tmp_path)['jobs']['review'])
    hub, tea = (next(s for s in job['steps'] if s.get('name') == 'Install the review method') for job in jobs)
    return hub, _unguarded(tea)


def test_the_review_method_is_the_ai_lab_the_door_s_dev_lab_lock_pins(tmp_path: Path) -> None:
    """dev-lab is the code that calls the review method, so ITS lock names the ai-lab that runs -- no second pin.

    The door cloned that dev-lab at the trusted DOOR_SHA's locked revision; the method reads ai-lab from there.
    """
    hub, tea = _method_steps(tmp_path)
    assert hub == tea, 'one source for both forges'
    assert 'env' not in hub or not any(re.fullmatch(r'[0-9a-f]{40}', v) for v in hub['env'].values())
    assert '< "$RUNNER_TEMP/dev-lab/uv.lock"' in hub['run']
    assert '"ai_lab @ git+${FAMILY_SOURCE}ai-lab.git@$AI_LAB_REV"' in hub['run']
    assert not re.search(r'[0-9a-f]{40}', hub['run']), 'the step names no sha itself'


def test_the_method_reads_the_locked_git_ai_lab_and_refuses_any_other_source(tmp_path: Path) -> None:
    """The snippet resolves a git-sourced ai-lab; a missing or non-git ai-lab refuses, printing nothing."""
    run = _method_steps(tmp_path)[0]['run']
    lock = '[[package]]\nname = "{name}"\nsource = {source}\n'
    git = lock.format(name='ai-lab', source='{ git = "https://github.com/DawnEver/ai-lab.git#' + 'c' * 40 + '" }')
    assert _locked_ref(run, git).stdout.strip() == 'c' * 40
    for refused in (
        lock.format(name='ai-lab', source='{ registry = "https://pypi.org/simple" }'),
        lock.format(name='ai-lab', source='{ editable = "." }'),
        lock.format(name='dev-lab', source='{ git = "https://github.com/DawnEver/dev-lab.git#' + 'c' * 40 + '" }'),
    ):
        done = _locked_ref(run, refused)
        assert done.returncode != 0, refused
        assert not done.stdout.strip(), refused


def test_every_job_installing_the_method_installs_the_door_first(tmp_path: Path) -> None:
    """The method reads the door's dev-lab lock, so a job without the door before it has no ai-lab to install."""
    names = [n for n in tomllib.loads(BASE_PATH.read_text(encoding='utf-8')) if n not in {SHARED, RUNNERS, PREPARE}]
    tables = ''.join(f'[tool.dev_lab.ci."{n}"]\n' for n in names)
    _hosted(tmp_path)
    (tmp_path / 'pyproject.toml').write_text(_JUDGE_REVIEW + tables, encoding='utf-8')
    all_jobs = [(f'{w}:{j}', job) for w, flow in workflows(tmp_path).items() for j, job in flow['jobs'].items()]
    users = 0
    for name, job in all_jobs:
        steps = [s.get('name') for s in job['steps']]
        if 'Install the review method' in steps:
            users += 1
            assert 'Install the review door' in steps, name
            assert steps.index('Install the review door') < steps.index('Install the review method'), name
    assert users >= 2, 'PLANTED CONTROL: the review and the claims jobs install the method'


def test_ai_lab_ref_is_gone_everywhere() -> None:
    """The retired second pin survives nowhere tracked: the lock is the one source."""
    root = Path(__file__).resolve().parents[1]
    hits = subprocess.run(
        [shutil.which('git') or 'git', 'grep', '-l', 'AI_LAB' + '_REF'],
        cwd=root,
        capture_output=True,
        text=True,
        encoding='utf-8',
        check=False,
    ).stdout.split()
    assert hits == []


def test_the_review_group_stays_out_of_the_door_and_every_consumer() -> None:
    """ai-lab is a NON-DEFAULT group: dev-lab's lock pins it, yet the door's export and a consumer install skip it."""
    root = Path(__file__).resolve().parents[1]
    project = tomllib.loads((root / 'pyproject.toml').read_text(encoding='utf-8'))
    assert any(d.startswith('ai-lab') for d in project['dependency-groups']['review'])
    assert 'review' not in project.get('tool', {}).get('uv', {}).get('default-groups', ['dev'])
    assert not any('ai-lab' in d for d in project['project']['dependencies']), 'a group never reaches a consumer'
    exported = subprocess.run(
        [
            shutil.which('uv') or 'uv',
            'export',
            '--no-config',
            '--project',
            str(root),
            '--frozen',
            '--no-hashes',
            '--no-header',
            '--no-annotate',
            '--no-emit-project',
        ],
        capture_output=True,
        text=True,
        encoding='utf-8',
        check=True,
    ).stdout
    assert 'ai-lab' not in exported, "the door's export excludes the group"
    assert 'ai_lab' not in exported


def test_the_review_job_runs_no_code_the_pr_supplies(tmp_path: Path) -> None:
    """F-76c85dbc4b77: the job holds the review key and a write token, so the PR head is DATA only.

    No install resolves from the checkout (its uv.lock / project), nothing is synced from it, and the door runs
    isolated so a PR-planted ``dev_lab/`` in the cwd cannot shadow it. PLANTED CONTROL: the old install step reds.
    """
    (tmp_path / 'hub').mkdir()
    for workflow in (_base_ci(tmp_path / 'hub'), _gitea_review(tmp_path)):
        assert not _from_the_checkout(workflow['jobs']['review']['steps']), render(workflow)
        review = next(s for s in workflow['jobs']['review']['steps'] if s.get('name') == 'tests/review')
        assert '"$REVIEW_PYTHON" -I -m dev_lab' in review['run']
    old = {
        'name': 'Install the review door',
        'run': (
            'uv export --frozen --no-hashes --no-header --no-annotate --no-emit-project --all-extras | grep -E '
            '\'^(dev-lab|lab-commons) @ \' > "$RUNNER_TEMP/review.txt"'
        ),
    }
    assert _from_the_checkout([old]) == ['Install the review door'], 'PLANTED CONTROL: the PR-lock install'
    assert _from_the_checkout([{'run': 'uv sync --frozen --all-extras'}]) == [None]
    quoted = {'run': '"$RUNNER_TEMP/review/bin/uv" export --frozen > "$RUNNER_TEMP/review.txt"'}
    assert _from_the_checkout([quoted]) == [None], 'PLANTED CONTROL: the quoted-binary form (F-040fa46aa691)'


def test_no_uv_call_in_the_review_job_reads_the_checkouts_config(tmp_path: Path) -> None:
    """F-963500c5db57: a PR's uv.toml / [tool.uv.pip] must not name the index the review's packages come from.

    PLANTED CONTROL: a uv pip install without --no-config is what the scan refuses.
    """
    (tmp_path / 'hub').mkdir()
    for workflow in (_base_ci(tmp_path / 'hub'), _gitea_review(tmp_path)):
        assert not _reads_uv_config(workflow['jobs']['review']['steps']), render(workflow)
    planted = {'name': 'p', 'run': '"$RUNNER_TEMP/review/bin/uv" pip install --python x -r y'}
    assert _reads_uv_config([planted]) == ['p'], 'PLANTED CONTROL'
    for bypass in (
        'uv pip install x && uv pip install y --no-config',  # the flag on a sibling command
        'uv --quiet pip install x',  # a global flag before the verb
        'uv venv x',  # a verb outside a fixed list
    ):
        assert _reads_uv_config([{'name': 'b', 'run': bypass}]) == ['b'], f'PLANTED CONTROL: {bypass}'
    assert not _reads_uv_config([{'name': 'ok', 'run': 'uv pip install \\\n  --no-config x'}]), 'a continuation'


def _reads_uv_config(steps: list[dict[str, Any]]) -> list[str | None]:
    """Each step with a uv command -- any verb, any global flag, any spelling of the binary -- lacking --no-config."""
    return [
        step.get('name')
        for step in steps
        if any(_UV.search(cmd) and '--no-config' not in cmd for cmd in _commands(step.get('run', '')))
    ]


def _from_the_checkout(steps: list[dict[str, Any]]) -> list[str | None]:
    """Each step resolving or running code from the PR checkout: a uv verb without ``--project`` elsewhere."""
    verbs = re.compile(r'\buv"?\s+(sync|run|export|lock)\b(?![^\n]*--project "\$RUNNER_TEMP)')
    return [step.get('name') for step in steps if verbs.search(step.get('run', ''))]


def test_no_credential_outlives_the_step_that_uses_it(tmp_path: Path) -> None:
    """F-00bc79a46330: no forge token in any git config file; the key's cache is stopped by the step reading it.

    PLANTED CONTROL: the old global extraHeader line is what the scan refuses.
    """
    (tmp_path / 'hub').mkdir()
    for workflow in (_base_ci(tmp_path / 'hub'), _gitea_review(tmp_path)):
        text = render(workflow)
        assert not _config_held_token(text), text
        steps = workflow['jobs']['review']['steps']
        for step in steps:
            if 'FAMILY_READ_TOKEN' in step.get('run', '') and step.get('name') != _HAND_OVER:
                assert 'GIT_CONFIG_VALUE_0=' in step['run'], f'{step.get("name")}: process-scoped, never config'
                # GitHub's git server takes only Basic (x-access-token:<token>); a `token` scheme prompts and dies
                # (dev-lab #17's own review, 2026-11-01: "could not read Username").
                assert 'Authorization: basic $(' in step['run'], step.get('name')
        review = next(s for s in steps if s.get('name') == 'tests/review')
        # F-5fd2611e79ea: the token files die with the step, whatever the door did (a self-hosted runner reuses temp).
        assert review['run'].startswith(
            "trap 'git credential-cache --socket=$RUNNER_TEMP/git-credential-cache/socket exit; "
            """rm -rf "$RUNNER_TEMP/forge-secrets"' EXIT"""
        )
        # F-ca1dda52c2ef: the door carries the lazy-blob header itself, read from the hand-over file.
        assert 'GIT_CONFIG' not in review['run'], 'the review step derives no header in shell'
        assert '--git-token-file "$RUNNER_TEMP/forge-secrets/read"' in review['run']
        assert '--api-token-file "$RUNNER_TEMP/forge-secrets/api"' in review['run']
    planted = 'git config --global http."$FORGE_URL/".extraHeader "Authorization: token ${FAMILY_READ_TOKEN}"'
    assert _config_held_token(planted), 'PLANTED CONTROL'


_HAND_OVER = 'Hand the forge tokens to the door'
_FORGE_TOKENS = {'GITHUB_TOKEN', 'FAMILY_READ_TOKEN'}


def _token_envs(workflow: dict[str, Any]) -> list[str]:
    """Where a forge token is env of the review job outside the hand-over step: workflow, job or step level."""
    job = workflow['jobs']['review']
    found = [f'workflow {k}' for k in workflow.get('env', {}) if k in _FORGE_TOKENS]
    found += [f'job {k}' for k in job.get('env', {}) if k in _FORGE_TOKENS]
    steps, names = job['steps'], [step.get('name') for step in job['steps']]
    after = steps[names.index(_HAND_OVER) + 1 :] if _HAND_OVER in names else steps
    return found + [f'{step.get("name")} {k}' for step in after for k in step.get('env', {}) if k in _FORGE_TOKENS]


def test_no_forge_token_is_env_of_the_review_or_anything_after_the_hand_over(tmp_path: Path) -> None:
    """F-d61706393b50: /proc/<pid>/environ keeps an unset variable, so the review's tokens reach it by file only.

    Steps BEFORE the hand-over (the installs) keep their own process-scoped token. PLANTED CONTROL: the job token
    at workflow level, as ci.yml had it, is what the scan refuses.
    """
    (tmp_path / 'hub').mkdir()
    for workflow in (_base_ci(tmp_path / 'hub'), _gitea_review(tmp_path)):
        assert not _token_envs(workflow), _token_envs(workflow)
        names = [s.get('name') for s in workflow['jobs']['review']['steps']]
        assert names.index(_HAND_OVER) == names.index('tests/review') - 1
        review = workflow['jobs']['review']['steps'][names.index('tests/review')]
        for word in (*_FORGE_TOKENS, 'GIT_CONFIG'):
            assert word not in review['run'], word
            assert word not in str(review.get('env', {})), word
        hand = workflow['jobs']['review']['steps'][names.index(_HAND_OVER)]
        assert hand['run'].startswith('umask 077'), 'the token files are private'
    planted = {**_base_ci(tmp_path / 'hub'), 'env': {'GITHUB_TOKEN': '${{ github.token }}'}}
    assert _token_envs(planted) == ['workflow GITHUB_TOKEN'], 'PLANTED CONTROL'


def _config_held_token(text: str) -> bool:
    return re.search(r'git config [^\n]*extraHeader', text, flags=re.IGNORECASE) is not None


def _door_steps(tmp_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    (tmp_path / 'hub').mkdir()
    jobs = (_base_ci(tmp_path / 'hub')['jobs']['review'], _gitea_review(tmp_path)['jobs']['review'])
    hub, tea = (next(s for s in job['steps'] if s.get('name') == 'Install the review door') for job in jobs)
    return hub, _unguarded(tea)


def test_the_door_is_the_dev_lab_the_base_s_lock_pins(tmp_path: Path) -> None:
    """dev-lab #18: the door has ONE source, the consumer's uv.lock, read at the BASE sha -- never the PR head's.

    The job runs the base's workflow, so a lock read at the head would let a PR choose the door that judges it.
    """
    hub, tea = _door_steps(tmp_path)
    assert hub == tea, 'one source for both forges'
    assert hub['env']['DOOR_SHA'] == '${{ github.event.pull_request.base.sha || env.INTEGRATION_SHA }}'
    assert 'DEV_LAB_REF' not in hub['env'], 'no second, hand-bumped pin beside the lock'
    assert 'show "$DOOR_SHA:uv.lock"' in hub['run']
    assert 'HEAD_SHA' not in hub['run'], 'PLANTED CONTROL: the head lock is never read'


def _locked_ref(run: str, lock: str) -> subprocess.CompletedProcess[str]:
    (code,) = re.findall(r"python3 -I -c '([^']*)'", run)
    return subprocess.run(
        [sys.executable, '-I', '-c', code, 'b' * 40],
        input=lock,
        capture_output=True,
        text=True,
        encoding='utf-8',
        check=False,
    )


def test_the_door_reads_the_locked_git_revision_and_refuses_any_other_source(tmp_path: Path) -> None:
    """A consumer's lock names a git revision; dev-lab's own (editable) is its base; anything else refuses."""
    run = _door_steps(tmp_path)[0]['run']
    lock = '[[package]]\nname = "{name}"\nsource = {source}\n'
    git = lock.format(name='dev-lab', source='{ git = "https://github.com/DawnEver/dev-lab.git#' + 'a' * 40 + '" }')
    assert _locked_ref(run, git).stdout.strip() == 'a' * 40
    own = lock.format(name='dev-lab', source='{ editable = "." }')
    assert _locked_ref(run, own).stdout.strip() == 'b' * 40, 'dev-lab reviews itself with its base'
    for refused in (
        lock.format(name='dev-lab', source='{ registry = "https://pypi.org/simple" }'),
        lock.format(name='other', source='{ editable = "." }'),
    ):
        done = _locked_ref(run, refused)
        assert done.returncode != 0, refused
        assert not done.stdout.strip(), refused


def _gitea_review(tmp_path: Path) -> dict[str, Any]:
    (tmp_path / 'pyproject.toml').write_text('[tool.dev_lab.ci."review.yml"]\n', encoding='utf-8')
    return workflows(tmp_path)['review.yml']


def test_a_gitea_workflow_renders_under_dot_gitea_and_its_forge_key_is_not_rendered(
    tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Gitea runs ``.gitea/workflows`` (and ignores ``.github/workflows`` once it exists): the forge key places it.

    PLANTED CONTROL: a hand edit of the Gitea render, and a hand-written Gitea workflow, are refused like GitHub's.
    """
    monkeypatch.setattr(ciworkflows, 'repo_forge', lambda _root: 'gitea')
    review = _gitea_review(tmp_path)
    assert 'forge' not in review, 'a placement key, never a workflow key'
    written = {path.name: path for path in write(tmp_path)}
    assert set(written) == _GITEA_BASE
    path = written['review.yml']
    assert path == tmp_path / '.gitea' / 'workflows' / 'review.yml'
    assert not (tmp_path / '.github').exists()
    assert drift(tmp_path) == []
    path.write_text(path.read_text(encoding='utf-8').replace('"review"', '"ubuntu-latest"'), encoding='utf-8')
    (path.parent / 'extra.yml').write_text('name: x\n', encoding='utf-8')
    assert main(['check', '--root', str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert 'review.yml: differs' in out
    assert 'extra.yml: a workflow no' in out


def test_the_gitea_review_job_is_lean_on_the_review_runner_and_runs_github_s_review_step(tmp_path: Path) -> None:
    """ONE review step: the Gitea job runs the very step GitHub's ci.yml review job runs, on the ``review`` runner.

    Lean: no ``uses`` action (a host-mode runner behind an ACL fetches none), no ``uv sync`` of the repo's deps.
    TRIGGERED BY ``pull_request_target`` ALONE (dev-lab #30, user ruling 2026-11-01, option (b)): Gitea runs a
    ``pull_request`` workflow from the PR head, which could rewrite it to post success or print the key; the
    ``pull_request_target`` workflow is the BASE's. Safe only because the job acts on nothing the head declares:
    the diff is data, the review declaration is the base's (``forgereview_declared.review_at``, F-46e412ee799d) and the
    tools
    are pinned by SHA (:func:`test_the_review_job_runs_no_code_the_pr_supplies`).
    PLANTED CONTROL: GitHub's ci.yml never takes it.
    """
    review = _gitea_review(tmp_path)
    assert set(review['on']) == {'pull_request_target'}
    assert review['on']['pull_request_target']['types'] == [
        'opened',
        'synchronize',
        'reopened',
        'ready_for_review',
        'edited',
    ]
    (tmp_path / 'gh').mkdir()
    github = _base_ci(tmp_path / 'gh')
    assert 'ready_for_review' in github['on']['pull_request']['types'], 'D52/D53: marking ready reviews a draft'
    (tmp_path / 'ci').mkdir()
    assert 'pull_request_target' not in render(_base_ci(tmp_path / 'ci'))
    job = review['jobs']['review']
    assert job['runs-on'] == 'review'
    assert not [step for step in job['steps'] if 'uses' in step]
    assert 'uv sync' not in render(review)
    (tmp_path / 'hub').mkdir()
    hub = _base_ci(tmp_path / 'hub')['jobs']['review']
    assert _unguarded(job['steps'][-1]) == hub['steps'][-1], 'the review step is one source'
    install = _unguarded(next(s for s in job['steps'] if s.get('name') == 'Install the review method'))
    assert install == next(s for s in hub['steps'] if s.get('name') == 'Install the review method')
    assert '"GITHUB_TOKEN": "${{ github.token }}"' in render(review), 'the job token posts: the forge is its creator'


def test_the_gitea_review_reaches_its_forge_on_the_runner_s_loopback_instance(tmp_path: Path) -> None:
    """``github.server_url`` is Gitea's ROOT_URL (refused from the host); the runner's instance is the address.

    act_runner sets ``ACTIONS_RUNTIME_URL`` to its registered instance + ``/api/actions_pipeline/``.
    """
    text = render(_gitea_review(tmp_path))
    assert '${ACTIONS_RUNTIME_URL%/api/actions_pipeline/}' in text
    assert 'GIT_CONFIG_GLOBAL' in text, "the job token never lands in the host user's global git config"


def test_no_python_in_the_review_job_imports_from_the_checkout(tmp_path: Path) -> None:
    """F-7b2f4bd210de: `python -m` puts the cwd -- the PR's checkout -- first on sys.path, so a planted module runs.

    Every interpreter the review job starts is isolated (`-I`) or runs in a step that left the checkout first.
    PLANTED CONTROL: the key store as it was, `-m ai_lab.auth` from the checkout.
    """
    (tmp_path / 'hub').mkdir()
    for workflow in (_base_ci(tmp_path / 'hub'), _gitea_review(tmp_path)):
        assert not _imports_from_the_checkout(workflow['jobs']['review']['steps']), render(workflow)
    planted = {'name': 'k', 'run': 'printf x | "$RUNNER_TEMP/ai-lab/bin/python" -m ai_lab.auth login anthropic'}
    assert _imports_from_the_checkout([planted]) == ['k'], 'PLANTED CONTROL'
    for bypass in (
        'cd "$RUNNER_TEMP"\ncd "$GITHUB_WORKSPACE" && python -m x',  # a cd prefix excuses nothing
        'python -u -m x',  # a flag between the binary and -m
        'python -c "import x"',  # -c puts the cwd on sys.path too
    ):
        assert _imports_from_the_checkout([{'name': 'b', 'run': bypass}]) == ['b'], f'PLANTED CONTROL: {bypass}'


def _imports_from_the_checkout(steps: list[dict[str, Any]]) -> list[str | None]:
    """Each step starting a python that is not isolated: no step is excused, every command is judged on its own."""
    return [
        step.get('name')
        for step in steps
        if any(_PYTHON.search(cmd) and not _ISOLATED.search(cmd) for cmd in _commands(step.get('run', '')))
    ]


_UV = re.compile(r'^"?[^\s"]*\buv"?(?=\s)')  # the program a command runs, by its first word
_PYTHON = re.compile(r'^"?[^\s"]*\bpython[0-9.]*"?(?=\s)')
_ISOLATED = re.compile(r'python[0-9.]*"?(?:\s+-(?!m\b|c\b)\S+)*\s+-I\b')


def _commands(run: str) -> list[str]:
    """A step's shell text as single commands: continuations joined, split on newlines and operators."""
    return [part.strip() for part in re.split(r'\n|&&|\|\||;|\|', run.replace('\\\n', ' ')) if part.strip()]


def test_the_gitea_review_job_token_can_post_its_commit_status(tmp_path: Path) -> None:
    """Gitea has no ``statuses`` scope: ``POST /statuses/{sha}`` is ``reqRepoWriter(unit.TypeCode)`` (1.27).

    Measured 2026-11-01 on consumer #5397: with ``contents: read`` the job's ``tests/review`` POST was refused
    while ``GET /user`` answered. ``contents: write`` is the Code-write the route asks for. Not a ceiling: Gitea
    takes a pull_request workflow from the PR head, whose author already holds Code write (see ci_base.toml).
    """
    permissions = _gitea_review(tmp_path)['jobs']['review']['permissions']
    assert permissions['contents'] == 'write'
    assert 'statuses' not in permissions, 'a GitHub scope Gitea ignores reads as a grant it never makes'


def test_the_gitea_review_job_token_can_read_its_own_run(tmp_path: Path) -> None:
    """The job reads its own run for reviewgate: ``GET .../actions/runs/{id}``, Actions read on Gitea 1.27.

    Measured 2026-11-01 on consumer #5397 and consumer-b #427 (runs 5, 6): with no ``actions`` scope the GET was
    refused right after the status POST that ``contents: write`` had unblocked.
    """
    assert _gitea_review(tmp_path)['jobs']['review']['permissions']['actions'] == 'read'


def test_every_workflow_that_installs_from_the_family_source_declares_it_once(tmp_path: Path) -> None:
    """ONE family source per workflow, declared in the env of every workflow whose steps read it.

    F-1f2d0da331a7, F-8d90b59c0336: no step falls back to a second source. An undeclared one renders
    ``git+ai-lab.git@...`` and the install fails; enumerating the renders, not naming the workflows, keeps a
    fourth from slipping past.
    """
    _hosted(tmp_path)
    (tmp_path / 'pyproject.toml').write_text(
        '[tool.dev_lab.ci."ci.yml"]\n[tool.dev_lab.ci."review.yml"]\n[tool.dev_lab.ci."review-claims.yml"]\n',
        encoding='utf-8',
    )
    rendered = workflows(tmp_path)
    readers = {name for name, workflow in rendered.items() if '${FAMILY_SOURCE}' in render(workflow)}
    assert readers == {'ci.yml', 'merge-tick.yml', 'review.yml', 'review-claims.yml'}  # merge-tick: GitHub's base
    for name in readers:
        assert rendered[name]['env'].get('FAMILY_SOURCE'), f'{name} reads FAMILY_SOURCE but declares none'
        assert 'FAMILY_SOURCE:-' not in render(rendered[name]), f'{name}: a second source'
    assert rendered['review.yml']['env']['FAMILY_SOURCE'] == 'https://github.com/DawnEver/'


def test_the_gitea_review_declares_one_permissions_block(tmp_path: Path) -> None:
    """F-a9d56327e726: a workflow-level ``contents: read`` above the job's ``contents: write`` is two grants."""
    assert 'permissions' not in _gitea_review(tmp_path)


def test_the_gitea_review_checks_out_only_the_root_files(tmp_path: Path) -> None:
    """The review reads the head through git and only ``pyproject.toml`` from the tree.

    (``forgereview_declared.load_review``).

    Measured 2026-11-01, consumer #5397: in the blobless clone a full ``git checkout`` lazily fetched every blob of
    the head tree -- a ``pack-objects`` on the 1.6 GB forge host running 10+ minutes at 314 MiB. A cone sparse
    checkout with no directories materialises the root files alone.
    """
    steps = _gitea_review(tmp_path)['jobs']['review']['steps']
    run = next(s for s in steps if s.get('name') == 'Fetch the head')['run']
    assert run.index('git sparse-checkout set') < run.index('git checkout')


def _full_adoption(tmp_path: Path) -> dict[str, Any]:
    _hosted(tmp_path)
    (tmp_path / 'pyproject.toml').write_text(
        '[tool.dev_lab.ci."ci.yml"]\n[tool.dev_lab.ci."review.yml"]\n[tool.dev_lab.ci."review-claims.yml"]\n',
        encoding='utf-8',
    )
    return workflows(tmp_path)


def test_the_review_key_cache_is_the_job_s_own(tmp_path: Path) -> None:
    """Every helper set and every daemon stopped names a socket under RUNNER_TEMP, removed with the job.

    F-83bc8b74b803 (consumer #5397 round 2): the default credential-cache socket is per HOME, shared by every job
    on a persistent runner, and a SIGKILLed job never runs its EXIT trap -- the key then waits for the next job.
    """
    socket = '--socket=$RUNNER_TEMP/git-credential-cache/socket'
    for name, workflow in _full_adoption(tmp_path).items():
        text = render(workflow)
        assert text.count('credential.helper') == text.count(f'cache --timeout=1800 {socket}'), f'{name}: shared'
        assert text.count('git credential-cache') == text.count(f'git credential-cache {socket} exit'), name


def test_the_gitea_job_refuses_to_run_without_its_forge(tmp_path: Path) -> None:
    """F-ccbbe815af51: with ACTIONS_RUNTIME_URL unset FORGE_URL was empty and the clone read ``/<repo>.git``.

    The lean steps are Gitea-only and use FORGE_URL alone; the first one fails loudly when it cannot derive it.
    """
    lean = _gitea_review(tmp_path)['jobs']['review']['steps']
    reach = next(s for s in lean if s.get('name') == "Reach the forge on the runner's instance")['run']
    assert 'ACTIONS_RUNTIME_URL' in reach
    assert 'exit 1' in reach
    fetch = next(s for s in lean if s.get('name') == 'Fetch the head')['run']
    assert 'FORGE_URL:-' not in fetch


def _expression(text: str, event: dict[str, Any]) -> bool:
    """A ``(term || term ...)`` workflow guard over *event*, each term ``!name`` or ``name == name``."""
    names = {'github': {'repository': 'o/r', 'event': event}}

    def value(dotted: str) -> object:
        found: object = names
        for part in dotted.strip().split('.'):
            found = found.get(part) if isinstance(found, dict) else None
        return found

    def term(one: str) -> bool:
        if one.startswith('!'):
            return not value(one[1:])
        left, equals, right = one.partition(' == ')
        assert equals, f'{one!r}: outside the guard grammar this test reads'
        return value(left) == value(right)

    return any(term(one.strip()) for one in text.strip().removeprefix('(').removesuffix(')').split(' || '))


def test_a_fork_pr_s_review_job_holds_secret_free(tmp_path: Path) -> None:
    """F-dd353e505b47 (dev-lab #38): under Gitea's pull_request_target a fork PR's run is handed the secrets.

    Every secret the rendered review.yml reads is guarded by the PR's head repo being this one: a fork stores no
    review key (the job then holds the head, NEEDS_MAINTAINER) and hands out no FAMILY_READ_TOKEN.
    PLANTED CONTROL: a same-repo PR, and an event with no PR (review-claims' issue_comment), get them.
    """
    text = render(_gitea_review(tmp_path))
    secrets = [one for one in re.findall(r'\$\{\{ (.*?) \}\}', text) if 'secrets.' in one]
    named = {found.group(1) for one in secrets if (found := re.search(r'secrets\.(\w+)', one))}
    assert named >= {'ANTHROPIC_API_KEY', 'FAMILY_READ_TOKEN'}
    fork = {'pull_request': {'head': {'repo': {'full_name': 'fork/r'}}}}
    same = {'pull_request': {'head': {'repo': {'full_name': 'o/r'}}}}
    for one in secrets:
        guard, _, rest = one.rpartition(' && ')
        assert rest.endswith(" || ''"), f'{one}: a withheld secret is the empty string'
        assert not _expression(guard, fork), f'{one}: a fork PR is handed it'
        assert _expression(guard, same), f'{one}: a same-repo PR is not'
        assert _expression(guard, {}), f'{one}: an event with no PR is not'


def _fetch_the_head(tmp_path: Path) -> dict[str, Any]:
    steps = _gitea_review(tmp_path)['jobs']['review']['steps']
    return next(s for s in steps if s.get('name') == 'Fetch the head')


def test_the_review_job_fetches_from_a_per_repository_mirror(tmp_path: Path) -> None:
    """D53(b): a whole-history clone per job was most of the runner's 557 MiB peak (consumer, 1.6 GB host).

    The job updates a persistent bare mirror under the runner's HOME, one per repository, under a kernel lock
    (released when a killed job dies), and its checkout borrows the mirror's objects; no whole clone from the forge.
    """
    run = _fetch_the_head(tmp_path)['run']
    assert 'MIRROR="$HOME/mirrors/${{ github.repository }}.git"' in run
    assert 'flock' in run
    assert '--shared' in run
    assert 'clone -q --no-tags --filter=blob:none --no-checkout "$FORGE_URL/' not in run.replace('--bare ', '')
    assert run.index('flock') < run.index('--shared') < run.index('git checkout')


def test_no_credential_or_pr_influence_persists_in_the_mirror(tmp_path: Path) -> None:
    """The header lives only in the step's GIT_CONFIG_* env; nothing written to a config carries it.

    No hook runs (an empty template and ``core.hooksPath=/dev/null``), and the mirror stores only the forge's
    branches -- the PR head is fetched into the disposable checkout, never into the shared mirror.
    PLANTED CONTROL: a ``git config`` write of the header is caught by the same scan.
    """
    run = _fetch_the_head(tmp_path)['run']

    def writes_header(text: str) -> list[str]:
        return [
            line
            for line in text.splitlines()
            if 'git' in line and 'config' in line.split('#')[0] and 'extraHeader' in line and 'GIT_CONFIG_' not in line
        ]

    assert writes_header(run) == []
    assert writes_header(run + '\ngit -C "$MIRROR" config http.extraHeader "$H"') != []
    assert 'core.hooksPath /dev/null' in run
    assert '--template=' in run
    mirror_fetches = [line for line in run.splitlines() if '-C "$MIRROR" fetch' in line]
    assert mirror_fetches
    assert all('refs/pull' not in line for line in mirror_fetches)


def test_gitea_renders_no_promoter_because_the_host_s_ops_promote_role_owns_gitea_promotion(tmp_path: Path) -> None:
    """ONE PROMOTER PER REPO: on Gitea, `dev_lab.ops` `[ops.promote]` (a timer on the forge host) promotes the trunk.

    A rendered nightly workflow would be a SECOND promoter racing its pushes to main, and would push main on a repo
    whose host deliberately does not promote it. GitHub keeps its promote job inside ci.yml.
    PLANTED CONTROL: the GitHub base still promotes.
    """
    assert base_names('gitea') == {'review.yml', 'merge.yml'}
    gitea = _hosted(tmp_path / 'gitea', 'https://gitea.example/o/r.git')
    for name, workflow in workflows(gitea).items():
        assert 'integrate promote' not in render(workflow), name
    assert 'promote' in _base_ci(tmp_path)['jobs'], 'PLANTED CONTROL: GitHub promotes inside ci.yml'


def test_a_judge_repo_renders_the_prepare_workflow_the_judge_trusts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``where = "judge"`` renders the BASE's prepare workflow under the ONE name the judge reads its runs by.

    ``pull_request_target`` alone (:data:`~dev_lab.dev.reviewgate.REVIEW_EVENT`): the base's definition runs, so a PR
    can neither alter it nor start it as its own. It holds no review method and no key.
    PLANTED CONTROL: a serve repo -- declared or by default -- renders no such workflow.
    """
    monkeypatch.setattr(ciworkflows, 'repo_forge', lambda _root: 'gitea')
    (tmp_path / 'pyproject.toml').write_text(_JUDGE_REVIEW, encoding='utf-8')
    prepare = workflows(tmp_path)[PREPARE_WORKFLOW]
    assert set(prepare['on']) == {REVIEW_EVENT}
    (job,) = prepare['jobs'].values()
    text = render(prepare)
    assert '-I -m dev_lab.dev.forge review prepare --pr ${{ github.event.pull_request.number }}' in text
    assert 'ANTHROPIC_API_KEY' not in text
    assert 'Install the review method' not in text
    assert job['runs-on'] in tomllib.loads(BASE_PATH.read_text(encoding='utf-8'))[RUNNERS]
    assert {path.relative_to(tmp_path).as_posix() for path in write(tmp_path)} == {
        f'.gitea/workflows/{name}' for name in {PREPARE_WORKFLOW, *_GITEA_BASE}
    }
    assert drift(tmp_path) == []
    for serve in ('', '[tool.dev_lab.review]\nwhere = "serve"\n'):
        (tmp_path / 'pyproject.toml').write_text(serve, encoding='utf-8')
        assert PREPARE_WORKFLOW not in workflows(tmp_path)


def test_a_github_judge_repo_renders_the_same_prepare_for_github(tmp_path: Path) -> None:
    """``forge = "github"`` renders the prepare to ``.github/workflows``, under the same name, event and job.

    GitHub hands a ``run`` step no runtime token, so ``actions/upload-artifact`` attaches the file ``prepare`` leaves
    to the run, under the very name the judge reads (:data:`~dev_lab.dev.forgereview_pointer.ARTIFACT`). Read-only,
    no credential kept by the checkout, a fork PR not prepared (no fork run names its PR), no method and no key.
    PLANTED CONTROL: none of Gitea's part -- the host runner's reach and mirror -- reaches GitHub's render.
    """
    layer = f'\n[tool.dev_lab.ci."{PREPARE_WORKFLOW}"]\nforge = "github"\n'
    (tmp_path / 'pyproject.toml').write_text(_JUDGE_REVIEW + layer, encoding='utf-8')
    prepare = workflows(tmp_path)[PREPARE_WORKFLOW]
    assert set(prepare['on']) == {REVIEW_EVENT}
    assert BY_FORGE not in prepare
    (job,) = prepare['jobs'].values()
    assert job['permissions'] == {'contents': 'read', 'pull-requests': 'read'}
    assert job['if'] == _guarded('${{ github.event.pull_request.head.repo.full_name == github.repository }}')
    names = [step.get('name') for step in job['steps']]
    assert "Reach the forge on the runner's instance" not in names
    assert 'Fetch the head' not in names
    checkout, upload = job['steps'][0], job['steps'][-1]
    assert checkout['with']['persist-credentials'] is False
    assert names.index('Install the review door') < names.index('Prepare the review bundle') < len(names) - 1
    assert upload['uses'].startswith('actions/upload-artifact@')
    assert upload['with']['name'] == ARTIFACT
    assert upload['with']['path'] == f'${{{{ runner.temp }}}}/{ARTIFACT}/{BUNDLE_FILE}'
    text = render(prepare)
    assert 'ANTHROPIC_API_KEY' not in text
    assert 'Install the review method' not in text
    written = {path.relative_to(tmp_path).as_posix() for path in write(tmp_path)}
    assert written == {f'.github/workflows/{name}' for name in (*_GITHUB_BASE, PREPARE_WORKFLOW)}
    assert drift(tmp_path) == []


def test_a_pr_with_no_code_is_settled_before_any_clone_or_install(tmp_path: Path) -> None:
    """Consumer #5514 (2026-11-03): six memory-only pushes paid six mirror clones and venv installs, 100-150 s each.

    The step after reaching the forge runs :mod:`dev_lab.dev.reviewcode` (fetched alone, at the door's locked
    dev-lab commit) on a bare interpreter; when it settles the head, every later step is skipped.
    PLANTED CONTROL: a later step without the guard would still clone.
    """
    steps = _gitea_review(tmp_path)['jobs']['review']['steps']
    names = [step.get('name') for step in steps]
    first = names.index('Settle a PR with no code to review')
    assert names[:first] == ["Reach the forge on the runner's instance"]
    settle = steps[first]
    assert 'src/dev_lab/dev/reviewcode.py' in settle['run']
    assert 'python3 -I' in settle['run']
    for text in ('git clone', 'pip install', 'git fetch'):
        assert text not in settle['run'], text
    skip = f"${{{{ steps.{settle['id']}.outputs.settled != 'true' }}}}"
    assert [step.get('if') for step in steps[first + 1 :]] == [skip] * len(steps[first + 1 :])
    assert settle['env']['PR_NUMBER'] == '${{ github.event.pull_request.number }}'


def test_a_use_steps_guard_reaches_every_step_it_expands_to() -> None:
    shared = {'two': [{'run': 'a'}, {'run': 'b', 'if': '${{ always() }}'}]}
    job = {'jobs': {'j': {'steps': [{'use-steps': 'two', 'if': '${{ x }}'}]}}}
    assert expand(job, shared)['jobs']['j']['steps'] == [
        {'run': 'a', 'if': '${{ x }}'},
        {'run': 'b', 'if': '${{ (x) && (always()) }}'},
    ]


def test_the_mirror_follows_the_forge_when_it_moves_hosts(tmp_path: Path) -> None:
    """2026-11-03: after the forge moved hosts every job failed reading the mirror's first-clone origin URL."""
    run = _fetch_the_head(tmp_path)['run']
    assert run.index('git -C "$MIRROR" remote set-url origin "$REPO"') < run.index('git -C "$MIRROR" fetch')


def test_a_part_posted_after_merge_ready_ran_re_judges_every_open_pr(tmp_path: Path) -> None:
    """A part settling after ci.yml's merge-ready ran (a workstation or HPC part) re-judges the PR, no human.

    GitHub runs ``status`` and ``schedule`` from the DEFAULT branch's file, never a PR head's. PLANTED CONTROL:
    merge-ready's own decision, and a pending part, start nothing (no loop, no judging a claim).
    """
    (tmp_path / 'pyproject.toml').write_text(
        '[tool.dev_lab.ci."ci.yml"]\n[tool.dev_lab.ci."merge-tick.yml"]\n', encoding='utf-8'
    )
    tick = workflows(tmp_path)['merge-tick.yml']
    assert {'status', 'schedule', 'workflow_dispatch'} <= set(tick['on'])
    assert not {'pull_request', 'pull_request_target'} & set(tick['on']), 'a merging token never runs a PR head'
    job = tick['jobs']['merge-tick']
    gate = job['if']
    assert "startsWith(github.event.context, 'tests/')" in gate
    assert "github.event.context != 'tests/merge-ready'" in gate
    assert "github.event.state != 'pending'" in gate
    ready, dispatch = job['steps'][-2:]
    assert 'forge merge ready)' in ready['run'], 'no --pr: every open PR into integration'
    assert '*"; merged"*) echo "merged=true" >> "$GITHUB_OUTPUT"' in ready['run']
    assert dispatch['if'] == "${{ steps.ready.outputs.merged == 'true' }}"
    assert 'gh workflow run ci.yml' in dispatch['run']
    assert '-f smoke=true' in dispatch['run']
    assert job['permissions'] == {
        'contents': 'write',
        'statuses': 'write',
        'pull-requests': 'write',
        'actions': 'write',
    }


def _guard_holds(text: str, event: dict[str, Any]) -> bool:
    """The draft guard's grammar -- ``!``, ``&&``, ``||``, ``!=``, ``startsWith`` (case-blind), dotted names -- read."""

    def value(dotted: str) -> object:
        found: object = {'github': {'event': event}}
        for part in dotted.split('.'):
            found = found.get(part) if isinstance(found, dict) else None
        return found

    def starts(text: object, prefix: str) -> bool:
        return isinstance(text, str) and text.upper().startswith(prefix.upper())

    python = re.sub(r'github(\.[\w-]+)+', lambda m: f'value({m.group(0)!r})', text)
    python = python.replace('!=', ' NE ').replace('!', ' not ').replace(' NE ', ' != ')
    python = python.replace('||', ' or ').replace('&&', ' and ').replace('startsWith', 'starts')
    calls = {'value': value, 'starts': starts}

    def read(node: ast.expr) -> object:
        if isinstance(node, ast.BoolOp):
            values = [bool(read(one)) for one in node.values]
            return all(values) if isinstance(node.op, ast.And) else any(values)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            return not read(node.operand)
        if isinstance(node, ast.Compare) and isinstance(node.ops[0], ast.NotEq):
            return read(node.left) != read(node.comparators[0])
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            return calls[node.func.id](*(read(arg) for arg in node.args))
        assert isinstance(node, ast.Constant), ast.dump(node)
        return node.value

    return bool(read(ast.parse(python.strip(), mode='eval').body))


def _bare(expression: str) -> str:
    return expression.strip().removeprefix('${{').removesuffix('}}').strip()


def _guarded(expression: str) -> str:
    """A PR-started job's *expression* as rendered: AND-ed after the draft guard."""
    return f'${{{{ ({READY_ONLY}) && ({_bare(expression)}) }}}}'


@pytest.mark.parametrize('forge', ['github', 'gitea'])
def test_a_draft_pr_runs_no_job_on_either_forge_and_a_ready_one_runs_every_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, forge: str
) -> None:
    """A DRAFT RUNS NOTHING (user ruling 2026-11-05): every job of every PR-triggered workflow is guarded.

    The draft is the one :func:`~dev_lab.dev._forge_records.pull_of` reads (GitHub's ``draft``, Gitea's
    ``WIP:``/``[WIP]`` title); Gitea marks ready by a title edit, so ``edited`` runs only when the title LEFT a draft.
    PLANTED CONTROL: a ready PR, ``ready_for_review``, leaving a draft and an event with no PR all run; a job's own
    condition survives the AND; a workflow no PR starts carries no guard.
    """
    monkeypatch.setattr(ciworkflows, 'repo_forge', lambda _root: forge)
    (tmp_path / 'pyproject.toml').write_text(_JUDGE_REVIEW, encoding='utf-8')
    rendered = workflows(tmp_path)
    events = {'pull_request', 'pull_request_target'}
    triggered = {name: w for name, w in rendered.items() if events & set(w['on'])}
    assert PREPARE_WORKFLOW in triggered
    for name, workflow in triggered.items():
        (trigger,) = events & set(workflow['on'])
        assert 'ready_for_review' in workflow['on'][trigger]['types'], f'{name}: marking ready starts everything'
        for job_name, job in workflow['jobs'].items():
            assert _bare(job['if']).startswith(f'({READY_ONLY})'), f'{name} {job_name}: a draft runs it'
    if forge == 'gitea':
        for name in ('review.yml', PREPARE_WORKFLOW):
            assert 'edited' in rendered[name]['on']['pull_request_target']['types'], f'{name}: Gitea readies by title'
    else:
        assert _bare(rendered['ci.yml']['jobs']['review']['if']).endswith("(github.event_name == 'pull_request')")
    assert all(READY_ONLY not in render(w) for name, w in rendered.items() if name not in triggered)
    assert _guard_holds(READY_ONLY, {'action': 'opened', 'pull_request': {'draft': False, 'title': 'feat: x'}})
    assert _guard_holds(READY_ONLY, {'action': 'ready_for_review', 'pull_request': {'draft': False, 'title': 'x'}})
    assert _guard_holds(READY_ONLY, {})
    left = {'action': 'edited', 'pull_request': {'title': 'x'}, 'changes': {'title': {'from': 'WIP: x'}}}
    assert _guard_holds(READY_ONLY, left)
    assert not _guard_holds(READY_ONLY, {'action': 'synchronize', 'pull_request': {'draft': True, 'title': 'x'}})
    for title in ('WIP: x', 'wip: x', '[WIP] x'):
        assert not _guard_holds(READY_ONLY, {'action': 'opened', 'pull_request': {'title': title}}), title
    assert not _guard_holds(READY_ONLY, {'action': 'edited', 'pull_request': {'title': 'x'}, 'changes': {}})
