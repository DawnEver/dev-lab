"""A DECLARED HOSTED PART'S OWN WORKFLOW JOB -- rendered from the matrix ``part`` job (:mod:`dev_lab.dev.jobparts`).

Each part ``[tool.dev_lab.parts] hosted`` declares (:mod:`dev_lab.dev.hostedparts`) gets a ``part-<name>`` job:
its ``setup`` command, then for a part naming tasks a key step piping each bundle to ai-lab's loader, before
the produce step, and a teardown forgetting the keys after it. The render names secrets, never holds a value.
"""

from __future__ import annotations

import json
import shlex
from typing import TYPE_CHECKING, Any, Final

from dev_lab.dev.jobparts import hosted_runner
from dev_lab.dev.taskkeys import loader, secret_name

if TYPE_CHECKING:
    from collections.abc import Mapping

    from dev_lab.dev.hostedparts import Hosted

__all__ = ['hosted_jobs']

#: The ``if`` of a secretless hosted part's job: every run that has a matrix, a pull request's included.
_ANY_RUN: Final = "${{ needs.parts.outputs.matrix != '' }}"

#: The ``if`` of a hosted part's job naming secrets: a FULL run's (the parts job's event is not the PR's set, as
#: macos, D84; a merge's smoke takes the PR's set, D48-1A), never one main already holds (an empty matrix).
_FULL_ONLY: Final = "${{ needs.parts.outputs.matrix != '' && needs.parts.outputs.event != 'pull_request' }}"

#: The ``if`` of a ``manual`` hosted part's job: a manual dispatch only, never the nightly (user ruling D66).
_DISPATCH_ONLY: Final = "${{ needs.parts.outputs.matrix != '' && needs.parts.outputs.event == 'workflow_dispatch' }}"


#: The hosted job's key store: ai-lab reads keys from the git credential store ONLY, so the job keeps an in-memory
#: one of its own under RUNNER_TEMP (F-83bc8b74b803). Its lifetime is the review's rule (ci_base.toml, 30 min):
#: no hosted part declares a timeout, and the one this repo hosts measured 483 s, so 1800 s covers a part with room.
_KEY_SOCKET: Final = '--socket=$RUNNER_TEMP/git-credential-cache/socket'
_MEMORY_STORE: Final = f'git config --global credential.helper "cache --timeout=1800 {_KEY_SOCKET}"'

#: The teardown that ends the store with the part, run on success AND failure (F-dc28c7ef66b4): the daemon would
#: otherwise hold the keys past the part until its timeout.
_FORGET_KEYS: Final = {
    'name': 'Forget the key bundles',
    'if': 'always()',
    'run': f'git credential-cache {_KEY_SOCKET} exit || true',
}


def hosted_jobs(workflow: dict[str, Any], declared: Mapping[str, Hosted]) -> dict[str, Any]:
    """*workflow* with one ``part-<name>`` job per *declared* part, cut from its matrix ``part`` job. PURE.

    The job is the ``part`` job at one part, on :func:`hosted_runner`: its ``setup`` command, then -- for a part
    naming tasks -- a push-only key step with the bundles in THAT step's environment only, before the produce
    step, and an ``always()`` step after it stopping their cache, so a part that fails forgets them as one that
    passes. A part naming no task runs on every event. ``absent-parts`` waits for it. A workflow without the
    ``part`` job, or nothing declared, is returned as is.
    """
    jobs = workflow.get('jobs', {})
    if not declared or 'part' not in jobs:
        return workflow
    template = json.dumps({key: value for key, value in jobs['part'].items() if key != 'strategy'})
    # The produce step by what it runs, never by place: the verify-log step follows it in the template.
    at = next(i for i, step in enumerate(jobs['part']['steps']) if 'produce ${{ matrix.part }}' in step.get('run', ''))
    added = {}
    for name, part in sorted(declared.items()):
        one = json.loads(template.replace('${{ matrix.part }}', name))
        before = [{'name': f'Set up tests/{name}', 'run': part.setup}] if part.setup else []
        after = []
        if part.tasks:
            loads = (
                f"""printf '%s' "${secret_name(task)}" | uv run --no-sync {shlex.join(loader('python', task))}"""
                for task in part.tasks
            )
            before.append(
                {
                    'name': f'Set up tests/{name} from its key bundles',
                    'run': ' && '.join((_MEMORY_STORE, *loads)),
                    'env': {secret: f'${{{{ secrets.{secret} }}}}' for secret in part.secrets},
                }
            )
            after.append(_FORGET_KEYS)
        steps = [*one['steps'][:at], *before, *one['steps'][at:], *after]
        added[f'part-{name}'] = {
            **one,
            'if': _DISPATCH_ONLY if part.manual else _FULL_ONLY if part.tasks else _ANY_RUN,
            'runs-on': hosted_runner(name),
            'steps': steps,
        }
    out = dict(jobs)
    if 'absent-parts' in out:
        needs = out['absent-parts'].get('needs', [])
        needs = [needs] if isinstance(needs, str) else list(needs)
        out['absent-parts'] = {**out['absent-parts'], 'needs': [*needs, *added]}
    return {**workflow, 'jobs': {**out, **added}}
