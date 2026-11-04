"""P3 (user ruling 2026-11-02): Gitea merges, closes landed PRs and sweeps branches in its own CI, on the light runner.

The merge job runs the ONE decision (``forge merge ready``) and holds no logic of its own; the light jobs install
neither the review method nor its key, and a light door installs only the packages its verbs import.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

import pytest

from dev_lab.dev.ciworkflows import BASE_PATH, LIGHT, runner_labels, workflows, write
from dev_lab.dev.forgemerge import CI_MERGER

_GITEA = ('review.yml', 'promote.yml', CI_MERGER)


def _gitea(tmp_path: Path) -> dict[str, dict[str, Any]]:
    tables = ''.join(f'[tool.dev_lab.ci."{name}"]\n' for name in _GITEA)
    (tmp_path / 'pyproject.toml').write_text(tables, encoding='utf-8')
    return workflows(tmp_path)


def _merge_job(tmp_path: Path) -> dict[str, Any]:
    return _gitea(tmp_path)[CI_MERGER]['jobs']['merge']


def _runs(job: dict[str, Any]) -> list[str]:
    return [step.get('run', '') for step in job['steps']]


def test_the_merger_renders_for_gitea_and_never_runs_from_a_pr_head(tmp_path: Path) -> None:
    """A pull_request-family trigger runs the workflow the HEAD holds (Gitea 1.27), so a PR could merge itself.

    Triggers: the Review workflow completing, a schedule fallback (statuses fire no Gitea event), and dispatch.
    """
    found = _gitea(tmp_path)[CI_MERGER]
    assert set(found['on']) == {'workflow_run', 'schedule', 'workflow_dispatch'}
    assert found['on']['workflow_run'] == {'workflows': ['Review'], 'types': ['completed']}
    assert found['on']['workflow_run']['workflows'] == [_gitea(tmp_path)['review.yml']['name']]
    assert not [event for event in found['on'] if event.startswith('pull_request')]
    assert found['concurrency'] == {'group': 'merge', 'cancel-in-progress': False}, 'one merge job at a time'
    assert tmp_path / '.gitea' / 'workflows' / CI_MERGER in write(tmp_path)


def test_the_merge_job_runs_the_one_decision_then_closes_landed_prs_then_sweeps(tmp_path: Path) -> None:
    job = _merge_job(tmp_path)
    runs = _runs(job)
    merged = next(i for i, run in enumerate(runs) if 'dev_lab.dev.forge merge ready' in run)
    assert '--pr' not in runs[merged], 'every open PR into integration, judged by forgemerge.ready'
    closed = next(i for i, run in enumerate(runs) if 'dev_lab.dev.prlanded' in run)
    swept = next(i for i, run in enumerate(runs) if 'dev_lab.dev.branchprune sweep' in run)
    assert merged < closed < swept
    for index in (closed, swept):
        assert job['steps'][index]['if'] == '${{ !cancelled() }}', 'a merge refused still closes and sweeps'
    assert job['permissions'] == {'contents': 'write', 'pull-requests': 'write'}
    text = json.dumps(job)
    for door in ('forge serve', 'forgeserve', 'slurm', 'jobparts', 'ANTHROPIC'):
        assert door not in text, door


def test_the_merge_job_judges_on_the_integration_tip_s_door_from_the_mirror(tmp_path: Path) -> None:
    """The decision trial-merges, so it needs trees: the persistent blobless mirror, never a fresh full clone."""
    steps = _merge_job(tmp_path)['steps']
    names = [step.get('name') for step in steps]
    fetch = steps[names.index('Fetch the head')]
    door = steps[names.index('Install the review door')]
    assert names.index('Fetch the head') < names.index('Install the review door')
    assert '$HOME/mirrors/' in fetch['run']
    assert "refs/pull/${{ github.event.pull_request.number || '*' }}/head" in fetch['run']
    assert 'git checkout -q --detach "${HEAD_SHA:-origin/integrate/main}"' in fetch['run']
    assert 'HEAD_SHA' not in _gitea(tmp_path)[CI_MERGER].get('env', {}), 'no PR: the checkout is the tip'
    assert 'echo "INTEGRATION_SHA=$(git rev-parse origin/integrate/main)" >> "$GITHUB_ENV"' in fetch['run']
    assert 'env.INTEGRATION_SHA' in door['env']['DOOR_SHA']


def test_every_gitea_job_runs_on_a_declared_label_and_review_alone_on_review(tmp_path: Path) -> None:
    labels = runner_labels()
    assert {'review', LIGHT} <= set(labels)
    seen = {}
    for name, workflow in _gitea(tmp_path).items():
        for job, body in workflow['jobs'].items():
            assert body['runs-on'] in labels, f'{name} {job}: {body["runs-on"]} is no declared label'
            seen[name, job] = body['runs-on']
    assert seen == {('review.yml', 'review'): 'review', ('promote.yml', 'promote'): LIGHT, (CI_MERGER, 'merge'): LIGHT}


def test_no_light_job_installs_the_review_method_or_its_key(tmp_path: Path) -> None:
    """PLANTED CONTROL: the review job, on the review runner, does both."""
    jobs = [body for workflow in _gitea(tmp_path).values() for body in workflow['jobs'].values()]
    light = [body for body in jobs if body['runs-on'] == LIGHT]
    assert light
    for body in light:
        text = json.dumps(body)
        for held in ('ai-lab', 'ai_lab', 'ANTHROPIC_API_KEY', 'credential', 'forge review'):
            assert held not in text, held
    review = json.dumps(_gitea(tmp_path)['review.yml']['jobs']['review'])
    assert 'ai-lab' in review
    assert 'ANTHROPIC_API_KEY' in review


def _only(body: dict[str, Any]) -> set[str]:
    names = body.get('env', {}).get('DOOR_ONLY', '').split('|')
    return {re.sub(r'[-_.]+', '_', name).lower() for name in names if name}


def test_a_light_door_s_packages_are_every_import_its_verbs_make(tmp_path: Path) -> None:
    """DOOR_ONLY is MEASURED, not trusted: each module a step runs imports only the stdlib, dev_lab and DOOR_ONLY."""
    jobs = [body for workflow in _gitea(tmp_path).values() for body in workflow['jobs'].values()]
    narrowed = [body for body in jobs if _only(body)]
    assert narrowed, 'promote.yml installs only lab-commons beside the door'
    for body in narrowed:
        modules = sorted({m for run in _runs(body) for m in re.findall(r'-m (dev_lab\.dev\.\w+)', run)})
        assert modules
        probe = (  # what the VERBS import: the interpreter's startup (a host's sitecustomize) is not theirs
            'import importlib, json, sys\n'
            'started = set(sys.modules)\n'
            f'for m in {modules!r}: importlib.import_module(m)\n'
            'print(json.dumps(sorted({n.split(".")[0] for n in set(sys.modules) - started})))'
        )
        done = subprocess.run(
            [sys.executable, '-I', '-c', probe], capture_output=True, text=True, encoding='utf-8', check=True
        )
        imported = set(json.loads(done.stdout)) - set(sys.stdlib_module_names) - {'dev_lab'}
        assert {name for name in imported if not name.startswith('_')} <= _only(body), modules


@pytest.mark.parametrize(
    ('only', 'expected'),
    [
        ('lab-commons', ['lab-commons @ git+https://x/lab-commons.git@abc']),
        ('lab-commons|pint', ['lab-commons @ git+https://x/lab-commons.git@abc', 'pint==0.26.2']),
    ],
)
def test_the_light_door_installs_exactly_the_named_locked_lines(tmp_path: Path, only: str, expected: list[str]) -> None:
    """The filter reads the door commit's own lock export: a named package the lock lacks refuses the job."""
    run = next(step['run'] for step in _shared('door'))
    (line,) = [one for one in run.splitlines() if one.startswith('grep -E ')]
    bash = shutil.which('bash')
    assert bash, 'the door step is bash'
    export = 'lab-commons @ git+https://x/lab-commons.git@abc\nnumpy==2.5.4\npint==0.26.2\npintx==1\n'
    (tmp_path / 'review.txt').write_text(export, encoding='utf-8')
    env = {**os.environ, 'DOOR_ONLY': only, 'RUNNER_TEMP': tmp_path.as_posix()}
    subprocess.run([bash, '-c', line], env=env, check=True, cwd=tmp_path)
    assert (tmp_path / 'only.txt').read_text(encoding='utf-8').splitlines() == expected
    env['DOOR_ONLY'] = 'lab-commons|absent'
    assert subprocess.run([bash, '-c', line], env=env, check=False, cwd=tmp_path).returncode != 0


def _shared(name: str) -> list[dict[str, Any]]:
    return tomllib.loads(BASE_PATH.read_text(encoding='utf-8'))['_steps'][name]
