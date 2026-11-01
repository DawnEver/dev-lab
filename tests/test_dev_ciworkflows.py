"""Workflows are TOML rendered to bytes: this repo's files ARE the render, and a hand edit is refused.

Nothing here parses YAML -- the comparison is between rendered bytes and file bytes.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from dev_lab.dev.ciworkflows import (
    PINS,
    RENDER_COMMAND,
    STAMP,
    USE_STEPS,
    drift,
    expand,
    main,
    merge,
    pin_drift,
    pinned_ref,
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
        'merge-ready': {'contents': 'write', 'statuses': 'write', 'pull-requests': 'write', 'actions': 'write'},
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


def test_the_review_method_is_pinned_to_the_commit_dev_lab_declares() -> None:
    """dev-lab #5 (2026-10-31) installed whatever ai-lab's default branch was that minute: a pin, never a float."""
    for repo in PINS:
        assert re.fullmatch(r'[0-9a-f]{40}', pinned_ref(repo)), (repo, pinned_ref(repo))


def test_the_review_key_reaches_the_method_through_its_own_store_never_argv(tmp_path: Path) -> None:
    """The review key reaches ai-lab through its credential store, on stdin, never argv or the environment.

    ai-lab reads keys from the git credential store ONLY: dev-lab #5's reviewers were all `unsupported` with
    ANTHROPIC_API_KEY set. The job stores it (memory cache, stdin) for the review task.
    """
    steps = {step.get('name'): step for step in _base_ci(tmp_path)['jobs']['review']['steps']}
    login = steps['Store the review key']
    assert login['env'] == {'ANTHROPIC_API_KEY': '${{ secrets.ANTHROPIC_API_KEY }}'}
    helper = 'credential.helper "cache --timeout=1800 --socket=$RUNNER_TEMP/git-credential-cache/socket"'
    assert helper in login['run'], 'in memory, one review long, the job its own'
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
    assert promote['if'] == (
        "${{ (github.event_name == 'push' || github.event_name == 'workflow_dispatch') "
        "&& github.ref == 'refs/heads/integrate/main' }}"
    ), 'a merge the job token made is dispatched, never pushed: that run promotes too (dev-lab#15)'
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
    setups = [job['steps'][:3] for name, job in ci['jobs'].items() if name != 'review']
    assert ci['jobs']['review']['steps'][0] == setups[0][0], 'the review checks the head out as DATA, no setup'
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


_INSTALLS = {'ai-lab': 'Install the review method', 'dev-lab': 'Install the review door'}


def test_each_pinned_ref_is_declared_once_and_both_review_workflows_install_it(tmp_path: Path) -> None:
    """Round 1 F-581fef0aab0b, F-76c85dbc4b77: one declared value per repo, rendered as its install step's env.

    GitHub's ci.yml review and Gitea's review.yml run the very same install step.
    """
    (tmp_path / 'hub').mkdir()
    jobs = (_base_ci(tmp_path / 'hub')['jobs']['review'], _gitea_review(tmp_path)['jobs']['review'])
    for repo, name in _INSTALLS.items():
        var = PINS[repo][1]
        hub, tea = (next(s for s in job['steps'] if s.get('name') == name) for job in jobs)
        assert hub == tea, f'{name}: one source for both forges'
        assert hub['env'][var] == pinned_ref(repo)
        assert f'${{FAMILY_SOURCE}}{repo}.git' in hub['run'], 'installed from the declared family source'
        assert f'${var}' in hub['run']
        assert pinned_ref(repo) not in hub['run'], 'the step names no sha itself'


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


def test_the_pin_check_names_a_stale_ref_and_the_bump() -> None:
    """PLANTED control: the declared ref at its repo's head is no drift."""
    for repo, (_, var) in PINS.items():
        assert pin_drift(repo, pinned_ref(repo), pinned_ref(repo)) is None
        stale = pin_drift(repo, pinned_ref(repo), 'f' * 40)
        assert pinned_ref(repo)[:12] in stale
        assert 'f' * 12 in stale
        assert var in stale


def test_the_pin_verb_reads_each_repo_s_head_through_its_seam(capsys) -> None:
    assert main(['pin'], head=pinned_ref) == 0
    assert main(['pin'], head=lambda repo: 'f' * 40 if repo == 'dev-lab' else pinned_ref(repo)) == 1
    assert 'DEV_LAB_REF pins dev-lab' in capsys.readouterr().out


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
    TRIGGERED BY ``pull_request_target`` ALONE (dev-lab #30, user ruling 2026-11-01, option (b)): Gitea runs a
    ``pull_request`` workflow from the PR head, which could rewrite it to post success or print the key; the
    ``pull_request_target`` workflow is the BASE's. Safe only because the job runs no PR code
    (:func:`test_the_review_job_runs_no_code_the_pr_supplies`). PLANTED CONTROL: GitHub's ci.yml never takes it.
    """
    review = _gitea_review(tmp_path)
    assert set(review['on']) == {'pull_request_target'}
    assert review['on']['pull_request_target']['types'] == ['opened', 'synchronize', 'reopened'], "pull_request's"
    (tmp_path / 'ci').mkdir()
    assert 'pull_request_target' not in render(_base_ci(tmp_path / 'ci'))
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

    Measured 2026-11-01 on motronics #5397: with ``contents: read`` the job's ``tests/review`` POST was refused
    while ``GET /user`` answered. ``contents: write`` is the Code-write the route asks for. Not a ceiling: Gitea
    takes a pull_request workflow from the PR head, whose author already holds Code write (see ci_base.toml).
    """
    permissions = _gitea_review(tmp_path)['jobs']['review']['permissions']
    assert permissions['contents'] == 'write'
    assert 'statuses' not in permissions, 'a GitHub scope Gitea ignores reads as a grant it never makes'


def test_the_gitea_review_job_token_can_read_its_own_run(tmp_path: Path) -> None:
    """The job reads its own run for reviewgate: ``GET .../actions/runs/{id}``, Actions read on Gitea 1.27.

    Measured 2026-11-01 on motronics #5397 and wdg-lab #427 (runs 5, 6): with no ``actions`` scope the GET was
    refused right after the status POST that ``contents: write`` had unblocked.
    """
    assert _gitea_review(tmp_path)['jobs']['review']['permissions']['actions'] == 'read'


def test_every_workflow_that_installs_from_the_family_source_declares_it_once(tmp_path: Path) -> None:
    """ONE family source per workflow, declared in the env of every workflow whose steps read it.

    F-1f2d0da331a7, F-8d90b59c0336: no step falls back to a second source. An undeclared one renders
    ``git+ai-lab.git@...`` and the install fails; enumerating the renders, not naming the workflows, keeps a
    fourth from slipping past.
    """
    (tmp_path / 'pyproject.toml').write_text(
        '[tool.dev_lab.ci."ci.yml"]\n[tool.dev_lab.ci."review.yml"]\n[tool.dev_lab.ci."review-claims.yml"]\n',
        encoding='utf-8',
    )
    rendered = workflows(tmp_path)
    readers = {name for name, workflow in rendered.items() if '${FAMILY_SOURCE}' in render(workflow)}
    assert readers == {'ci.yml', 'review.yml', 'review-claims.yml'}
    for name in readers:
        assert rendered[name]['env'].get('FAMILY_SOURCE'), f'{name} reads FAMILY_SOURCE but declares none'
        assert 'FAMILY_SOURCE:-' not in render(rendered[name]), f'{name}: a second source'
    assert rendered['review.yml']['env']['FAMILY_SOURCE'] == 'https://github.com/DawnEver/'


def test_the_gitea_review_declares_one_permissions_block(tmp_path: Path) -> None:
    """F-a9d56327e726: a workflow-level ``contents: read`` above the job's ``contents: write`` is two grants."""
    assert 'permissions' not in _gitea_review(tmp_path)


def test_the_gitea_review_checks_out_only_the_root_files(tmp_path: Path) -> None:
    """The review reads the head through git and only ``pyproject.toml`` from the tree (``forgereview.load_review``).

    Measured 2026-11-01, motronics #5397: in the blobless clone a full ``git checkout`` lazily fetched every blob of
    the head tree -- a ``pack-objects`` on the 1.6 GB forge host running 10+ minutes at 314 MiB. A cone sparse
    checkout with no directories materialises the root files alone.
    """
    steps = _gitea_review(tmp_path)['jobs']['review']['steps']
    run = next(s for s in steps if s.get('name') == 'Fetch the head')['run']
    assert run.index('git sparse-checkout set') < run.index('git checkout')


def _full_adoption(tmp_path: Path) -> dict[str, Any]:
    (tmp_path / 'pyproject.toml').write_text(
        '[tool.dev_lab.ci."ci.yml"]\n[tool.dev_lab.ci."review.yml"]\n[tool.dev_lab.ci."review-claims.yml"]\n',
        encoding='utf-8',
    )
    return workflows(tmp_path)


def test_the_review_key_cache_is_the_job_s_own(tmp_path: Path) -> None:
    """Every helper set and every daemon stopped names a socket under RUNNER_TEMP, removed with the job.

    F-83bc8b74b803 (motronics #5397 round 2): the default credential-cache socket is per HOME, shared by every job
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
