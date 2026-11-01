"""Workflows are TOML rendered to bytes: this repo's files ARE the render, and a hand edit is refused.

Nothing here parses YAML -- the comparison is between rendered bytes and file bytes.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from dev_lab.dev.ciworkflows import (
    AI_LAB_REF_VAR,
    RENDER_COMMAND,
    STAMP,
    USE_STEPS,
    ai_lab_ref,
    drift,
    expand,
    main,
    merge,
    pin_drift,
    render,
    workflows,
    write,
)

_ROOT = Path(__file__).resolve().parents[1]


def test_this_repo_s_workflows_are_exactly_their_render() -> None:
    assert set(workflows(_ROOT)) == {'ci.yml', 'review-claims.yml'}, 'a floor: an empty table drifts from nothing'
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
    assert set(ci['on']) == {'push', 'pull_request', 'workflow_dispatch'}
    assert 'pull_request_target' not in render(ci), "a fork's code would run with this repository's secrets"
    assert ci['jobs']['review']['if'] == "${{ github.event_name == 'pull_request' }}"


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
        'merge-ready': {'contents': 'read', 'statuses': 'write', 'pull-requests': 'read'},
        'promote': {'contents': 'write', 'statuses': 'write', 'pull-requests': 'write'},
    }


def test_the_matrix_is_the_command_s_output_and_merge_ready_runs_last_in_the_same_workflow(tmp_path: Path) -> None:
    ci = _base_ci(tmp_path)
    jobs = ci['jobs']
    assert jobs['part']['strategy']['matrix'] == '${{ fromJSON(needs.parts.outputs.matrix) }}'
    assert jobs['parts']['outputs'] == {'matrix': '${{ steps.matrix.outputs.matrix }}'}
    (computed,) = [step for step in jobs['parts']['steps'] if step.get('id') == 'matrix']
    event = '--event ${{ github.event_name }}'
    assert f'dev_lab.dev.jobparts matrix --runners hosted {event}' in computed['run'], 'the rows follow the event'
    assert 'dev_lab.dev.jobparts produce ${{ matrix.part }}' in jobs['part']['steps'][-1]['run']
    assert f'dev_lab.dev.jobparts absent "$HEAD_SHA" {event}' in jobs['absent-parts']['steps'][-1]['run']
    assert jobs['absent-parts']['if'].startswith('${{ always()')
    assert set(jobs['merge-ready']['needs']) == {'security', 'review'}, 'the parts gate promote, never the merge'
    assert jobs['merge-ready']['if'].startswith('${{ always()')
    assert 'forge merge ready --pr' in jobs['merge-ready']['steps'][-1]['run']
    assert 'forge review run --pr' in jobs['review']['steps'][-1]['run']
    assert 'workflow_run' not in ci['on'], 'no cross-workflow trigger'


def test_the_review_job_runs_the_method_from_an_environment_that_carries_it(tmp_path: Path) -> None:
    """lab-commons #11, dev-lab #3: the repo's own .venv has no ai_lab, so the review never ran on GitHub."""
    steps = {step.get('name'): step for step in _base_ci(tmp_path)['jobs']['review']['steps']}
    install, review = steps['Install the review method']['run'], steps['tests/review']['run']
    assert 'uv pip install --python "$RUNNER_TEMP/ai-lab/bin/python" "ai_lab @ git+' in install
    assert '--runtime "ai_lab.python=$RUNNER_TEMP/ai-lab/bin/python"' in review
    assert '$GITHUB_WORKSPACE/.venv' not in review, "the repo's own environment does not carry the method"


def test_the_review_method_is_pinned_to_the_commit_dev_lab_declares() -> None:
    """dev-lab #5 (2026-10-31) installed whatever ai-lab's default branch was that minute: a pin, never a float."""
    assert re.fullmatch(r'[0-9a-f]{40}', ai_lab_ref()), ai_lab_ref()


def test_the_review_key_reaches_the_method_through_its_own_store_never_argv(tmp_path: Path) -> None:
    """The review key reaches ai-lab through its credential store, on stdin, never argv or the environment.

    ai-lab reads keys from the git credential store ONLY: dev-lab #5's reviewers were all `unsupported` with
    ANTHROPIC_API_KEY set. The job stores it (memory cache, stdin) for the review task.
    """
    steps = {step.get('name'): step for step in _base_ci(tmp_path)['jobs']['review']['steps']}
    login = steps['Store the review key']
    assert login['env'] == {'ANTHROPIC_API_KEY': '${{ secrets.ANTHROPIC_API_KEY }}'}
    assert "credential.helper 'cache" in login['run'], 'in memory, never a file on the runner'
    assert '-m ai_lab.auth login anthropic --task pr-review' in login['run']
    assert '| "$RUNNER_TEMP/ai-lab/bin/python"' in login['run'], 'the key travels on stdin'
    assert 'if [ -n "$ANTHROPIC_API_KEY" ]' in login['run'], 'a fork PR has no secret: the review holds the head'
    names = list(steps)
    assert names.index('Install the review method') < names.index('Store the review key') < names.index('tests/review')


def test_a_push_to_integration_runs_every_part_then_promote_fast_forwards_main_by_the_one_decision(
    tmp_path: Path,
) -> None:
    """ONE FLOW (D83): GitHub promotes by the SAME `integrate promote` Gitea runs, once every part settled."""
    ci = _base_ci(tmp_path)
    assert ci['on']['push'] == {'branches': ['integrate/main']}, 'main moves only by promote, never by a push run'
    promote = ci['jobs']['promote']
    assert promote['needs'] == ['absent-parts']
    assert promote['if'] == "${{ github.event_name == 'push' && github.ref == 'refs/heads/integrate/main' }}"
    (step,) = [one for one in promote['steps'] if 'integrate promote' in one.get('run', '')]
    assert 'python -m dev_lab.dev.integrate promote "$HEAD_SHA"' in step['run']
    assert 'git push origin main' in step['run']


def test_after_promote_the_push_job_sweeps_every_branch_integration_now_contains(tmp_path: Path) -> None:
    """LANDED-BRANCHES-SWEPT (ruling 2026-10-29): the sweep runs after promote, even when promote failed."""
    steps = _base_ci(tmp_path)['jobs']['promote']['steps']
    runs = [one.get('run', '') for one in steps]
    swept = next(i for i, run in enumerate(runs) if 'dev_lab.dev.branchprune sweep' in run)
    assert swept > next(i for i, run in enumerate(runs) if 'integrate promote' in run)
    assert steps[swept]['if'] == '${{ !cancelled() }}'


def test_a_shared_step_list_is_declared_once_and_expanded_in_every_job(tmp_path: Path) -> None:
    ci = _base_ci(tmp_path)
    setups = [job['steps'][:3] for job in ci['jobs'].values()]
    assert all(steps == setups[0] for steps in setups)
    assert setups[0][0]['with'] == {'ref': '${{ env.HEAD_SHA }}', 'fetch-depth': 0}
    assert '_steps' not in workflows(tmp_path)
    shared = {'a': [{'run': 'x'}]}
    assert expand({'jobs': {'j': {'steps': [{USE_STEPS: 'a'}, {'run': 'z'}]}}}, shared) == {
        'jobs': {'j': {'steps': [{'run': 'x'}, {'run': 'z'}]}}
    }


def test_a_repo_that_declares_nothing_renders_nothing(tmp_path: Path) -> None:
    (tmp_path / 'pyproject.toml').write_text('', encoding='utf-8')
    assert workflows(tmp_path) == {}
    assert write(tmp_path) == []


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


def test_a_hosted_part_renders_its_own_push_only_job_and_only_its_setup_step_sees_the_secret(
    tmp_path: Path, monkeypatch
) -> None:
    planted = 'sk-planted-value-never-rendered'
    monkeypatch.setenv('MODEL_KEY', planted)
    (tmp_path / 'pyproject.toml').write_text(_HOSTED, encoding='utf-8')
    ci = workflows(tmp_path)['ci.yml']
    job = ci['jobs']['part-live']
    assert job['runs-on'] == 'ubuntu-latest'
    assert job['if'] == "${{ github.event_name != 'pull_request' }}"
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


def test_the_ai_lab_ref_is_declared_once_and_the_install_reads_it(tmp_path: Path) -> None:
    """Round 1 F-581fef0aab0b: one declared value, rendered as the job's env; the install names no sha itself."""
    review = _base_ci(tmp_path)['jobs']['review']
    step = next(s for s in review['steps'] if s.get('name') == 'Install the review method')
    assert step['env'] == {AI_LAB_REF_VAR: ai_lab_ref()}
    assert f'/ai-lab.git@${AI_LAB_REF_VAR}"' in step['run']
    assert ai_lab_ref() not in step['run']


def test_the_pin_check_names_a_stale_ref_and_the_bump() -> None:
    """PLANTED control: the declared ref at ai-lab's head is no drift."""
    assert pin_drift(ai_lab_ref(), ai_lab_ref()) is None
    stale = pin_drift(ai_lab_ref(), 'f' * 40)
    assert ai_lab_ref()[:12] in stale
    assert 'f' * 12 in stale
    assert AI_LAB_REF_VAR in stale


def test_the_pin_verb_reads_ai_labs_head_through_its_seam(capsys) -> None:
    assert main(['pin'], head=ai_lab_ref) == 0
    assert main(['pin'], head=lambda: 'f' * 40) == 1
    assert 'f' * 12 in capsys.readouterr().out


def _gitea_review(tmp_path: Path) -> dict[str, Any]:
    (tmp_path / 'pyproject.toml').write_text('[tool.dev_lab.ci."review.yml"]\n', encoding='utf-8')
    return workflows(tmp_path)['review.yml']


def test_a_gitea_workflow_renders_under_dot_gitea_and_its_forge_key_is_not_rendered(tmp_path: Path, capsys) -> None:
    """Gitea runs ``.gitea/workflows`` (and ignores ``.github/workflows`` once it exists): the forge key places it.

    PLANTED CONTROL: a hand edit of the Gitea render, and a hand-written Gitea workflow, are refused like GitHub's.
    """
    review = _gitea_review(tmp_path)
    assert 'forge' not in review, 'a placement key, never a workflow key'
    (path,) = write(tmp_path)
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
    """
    review = _gitea_review(tmp_path)
    assert set(review['on']) == {'pull_request'}
    assert 'pull_request_target' not in render(review)
    job = review['jobs']['review']
    assert job['runs-on'] == 'review'
    assert not [step for step in job['steps'] if 'uses' in step]
    assert 'uv sync' not in render(review)
    (tmp_path / 'hub').mkdir()
    hub = _base_ci(tmp_path / 'hub')['jobs']['review']
    assert job['steps'][-1] == hub['steps'][-1], 'the review step is one source'
    install = next(s for s in job['steps'] if s.get('name') == 'Install the review method')
    assert install == next(s for s in hub['steps'] if s.get('name') == 'Install the review method')
    assert '"GITHUB_TOKEN": "${{ github.token }}"' in render(review), 'the job token posts: the forge is its creator'


def test_the_gitea_review_reaches_its_forge_on_the_runner_s_loopback_instance(tmp_path: Path) -> None:
    """``github.server_url`` is Gitea's ROOT_URL (refused from the host); the runner's instance is the address.

    act_runner sets ``ACTIONS_RUNTIME_URL`` to its registered instance + ``/api/actions_pipeline/``.
    """
    text = render(_gitea_review(tmp_path))
    assert '${ACTIONS_RUNTIME_URL%/api/actions_pipeline/}' in text
    assert 'GIT_CONFIG_GLOBAL' in text, "the job token never lands in the host user's global git config"
