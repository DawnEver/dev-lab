"""A render-golden fixture in code: pyproject, role bindings, deltas -- representative, not any real repo's."""

from __future__ import annotations

from dev_lab.dev.famconfig import Delta

#: The fixture's ``pyproject.toml``: its ``[tool.dev_lab.ci]`` declarations.
PYPROJECT = """\
# A Gitea repo whose family binds every role to CI: it renders the trusted review and the merge.
[project]
name = "gitea"

[tool.dev_lab.ci."review.yml"]
"""
#: The executor kind each role binds, as :data:`~dev_lab.dev.roles.ROLES_ENV` carries them.
ROLES = {'merge': 'ci', 'promote': 'ci', 'prune': 'ci', 'review': 'ci', 'tests': 'ci'}

DELTAS = {
    '.gitignore': Delta(repo='gitea', added=('/data/',), dropped={}, ceiling=1),
}
