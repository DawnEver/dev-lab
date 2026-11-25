"""THE ROLES BINDING HOLDS: every fact of a repo that would contradict the family's binding of its roles is refused.

D73 (:mod:`dev_lab.dev.roles`). :func:`repo_refusals` reads a repo's working tree under the family's binding:

* a retired placement the repo still declares (:func:`~dev_lab.dev.roles.retired_placement`);
* a workflow file on the repo's forge that nothing renders is refused: the family binds its role to another
  executor, so the forge's CI never runs it (a repo with no role on ``ci`` holds no workflow at all);
* ``tests`` bound to ``ci`` renders :data:`CI_WORKFLOW`, its ``jobparts produce`` posting ``tests/base``, and the
  file stands on disk -- unless it declares ``[tool.dev_lab.integrator] merge_checks``, the Actions checks its merge
  waits on instead (a config-only repo);
* ``tests`` on ``actions`` declares nothing only the serving hosts' queue reads (:data:`HPC_ONLY`): no host would
  ever read it -- ``[tool.lab_commons.hpc]`` is NOT among them: it says how a cluster BUILDS the repo, which dev-lab
  declares for the tooling it ships;
* every required part (``base`` and ``[tool.dev_lab.parts] required``) is one the ``tests`` executor's kind posts
  (:func:`~dev_lab.dev.roles.producible`), and none needs an ``optional_needs`` resource.

:func:`host_refusals` reads a host card: a ``[serve]`` table belongs only to an HPC account (``[deploy]``) -- a
workstation never serves a merge's parts.
"""

from __future__ import annotations

import json
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

from lab_commons.compute.serves import SERVE_TABLE
from lab_commons.hpc.needsets import BASE

from dev_lab.dev.ciworkflows import placed
from dev_lab.dev.ciworkflowshape import WORKFLOW_DIRS
from dev_lab.dev.family import declared_table
from dev_lab.dev.hostedparts import hosted_parts
from dev_lab.dev.roles import CI, TESTS, Roles, Unbound, optional_needs_from, producible, retired_placement, roles_at

__all__ = ['CI_WORKFLOW', 'HPC_ONLY', 'POSTS_BASE', 'host_refusals', 'repo_refusals']

#: The workflow whose ``jobparts produce`` posts ``tests/base``: rendered where ``tests`` is on ``actions``.
CI_WORKFLOW: Final = 'ci.yml'

#: What a rendered ``ci.yml`` runs to post its parts, ``tests/base`` among them (:mod:`dev_lab.dev.jobparts`).
POSTS_BASE: Final = 'dev_lab.dev.jobparts produce'

#: Declarations only an HPC executor's queue reads (``tool`` path -> why): ``tests`` bound to ``ci`` carrying one is
#: refused.
HPC_ONLY: Final = {
    ('lab_commons', 'schedule'): 'the HPC queue ranks by it (dev_lab.dev.forgeschedule)',
    ('dev_lab', 'parts', 'refs'): 'the HPC queue filters the refs a part is offered on by it (dev_lab.dev.partrefs)',
}


def _declares(data: Mapping[str, Any], path: tuple[str, ...]) -> bool:
    node: Any = data.get('tool', {})
    for key in path:
        if not isinstance(node, Mapping) or key not in node:
            return False
        node = node[key]
    return True


def _unrendered(root: Path, text: str, origin: str, forge: str, roles: Roles) -> list[str]:
    rendered = placed(text, origin, forge, roles)
    directory = root / WORKFLOW_DIRS[forge]
    found = sorted(p for p in directory.iterdir() if p.suffix in {'.yml', '.yaml'}) if directory.is_dir() else []
    return [
        f'{path}: nothing renders it -- the family binds its role to another executor (dev_lab.dev.roles), so {forge} '
        'Actions never runs it; python -m dev_lab.dev.ciworkflows render removes it'
        for path in found
        if path.name not in rendered
    ]


def _ci_refusals(root: Path, text: str, origin: str, forge: str, roles: Roles) -> list[str]:
    if declared_table(tomllib.loads(text), 'integrator', {}).get('merge_checks'):
        return []  # its merge waits on its declared Actions checks, never on tests/base (user ruling 2026-11-12)
    rendered = placed(text, origin, forge, roles)
    if CI_WORKFLOW not in rendered:
        return [f'{origin}: tests bound to "{CI}" but no {CI_WORKFLOW} renders on {forge}: nothing posts tests/base']
    directory, workflow = rendered[CI_WORKFLOW]
    found = []
    if POSTS_BASE not in json.dumps(workflow):
        found.append(f'{origin}: the rendered {CI_WORKFLOW} never runs `{POSTS_BASE}`: nothing posts tests/base')
    if not (root / directory / CI_WORKFLOW).is_file():
        found.append(f'{root / directory / CI_WORKFLOW}: not rendered -- python -m dev_lab.dev.ciworkflows render')
    return found


def _required_refusals(text: str, origin: str, tests: str) -> list[str]:
    parts = declared_table(tomllib.loads(text), 'parts', {})
    required = {BASE, *parts.get('required', [])}
    optional = optional_needs_from(text)
    hosted = set(hosted_parts(text))
    return [
        f'{origin}: the required part tests/{part} has no producer with tests bound to "{tests}"'
        + (' (CI posts base and hosted parts)' if tests == CI else ' (it needs an optional_needs resource)')
        for part in sorted(required)
        if not producible(tests, part, hosted=hosted, optional=optional)
    ]


def repo_refusals(root: Path, forge: str, roles: Roles | None = None) -> list[str]:
    """Every fact of *root*'s working tree contradicting its roles; *forge* is where it is hosted.

    *roles* default to the family's binding for the checkout (:func:`~dev_lab.dev.roles.roles_at`).
    """
    origin = str(root / 'pyproject.toml')
    text = (root / 'pyproject.toml').read_text(encoding='utf-8')
    found = retired_placement(text, origin)
    try:
        roles = roles_at(root) if roles is None else roles
    except Unbound as unbound:
        return [*found, str(unbound)]
    tests = roles.kind(TESTS)
    found += _unrendered(root, text, origin, forge, roles)
    if tests == CI:
        found += _ci_refusals(root, text, origin, forge, roles)
        data = tomllib.loads(text)
        found += [
            f'{origin}: tests bound to "{CI}" yet it declares [tool.{".".join(path)}], which only {why}'
            for path, why in HPC_ONLY.items()
            if _declares(data, path)
        ]
    return found + _required_refusals(text, origin, tests)


def host_refusals(name: str, card: Mapping[str, Any]) -> list[str]:
    """Why host card *name* contradicts the 2026-11-16 ruling: a ``[serve]`` table on a host that is no HPC account."""
    if SERVE_TABLE in card and 'deploy' not in card:
        why = "a workstation never serves a merge's parts (user ruling 2026-11-16); delete the table"
        return [f'{name}: [{SERVE_TABLE}] on a host that is no HPC account -- {why}']
    return []
