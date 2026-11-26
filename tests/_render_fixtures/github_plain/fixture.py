"""A render-golden fixture in code: pyproject, role bindings, deltas -- representative, not any real repo's."""

from __future__ import annotations

from dev_lab.dev.famconfig import Delta

#: The fixture's ``pyproject.toml``: its ``[tool.dev_lab.ci]`` declarations.
PYPROJECT = """\
# A GitHub repo that declares the base CI with no layer of its own.
[project]
name = "plain"

[tool.dev_lab.ci."ci.yml"]
"""
#: The executor kind each role binds, as :data:`~dev_lab.dev.roles.ROLES_ENV` carries them.
ROLES = {'merge': 'ci', 'promote': 'ci', 'prune': 'ci', 'review': 'ci', 'tests': 'ci'}

DELTAS = {
    '.gitignore': Delta(repo='plain', added=(), dropped={}, ceiling=0),
    '.gitattributes': Delta(repo='plain', added=(), dropped={}, ceiling=0),
}
