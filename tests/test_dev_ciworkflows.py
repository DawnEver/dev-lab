"""Workflows are TOML rendered to bytes: this repo's files ARE the render, and a hand edit is refused.

Nothing here parses YAML -- the comparison is between rendered bytes and file bytes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from dev_lab.dev.ciworkflows import (
    RENDER_COMMAND,
    STAMP,
    USE_STEPS,
    drift,
    expand,
    main,
    merge,
    render,
    workflows,
    write,
)

_ROOT = Path(__file__).resolve().parents[1]


def test_this_repo_s_workflows_are_exactly_their_render() -> None:
    assert set(workflows(_ROOT)) == {'ci.yml'}, 'a floor: an empty table drifts from nothing'
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
        'promote': {'contents': 'write', 'statuses': 'write'},
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
